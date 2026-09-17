"""Past-only weekday demand bootstrap and shared depot delivery paths."""

import zlib
from dataclasses import replace
from datetime import timedelta

import numpy as np

from app.config import (
    ASSUMED_DELAYS, BASELINE_DAYS, DISPLAY_DAYS, INTERNAL_DAYS,
    MAX_STOCK_AGE_HOURS, MIN_DELIVERY_OBSERVATIONS, MIN_OBSERVATIONS,
    PATH_COUNT, PLANNING_QUANTILE, WEEKDAY_SHRINKAGE,
)
from app.schemas import Scenario, Snapshot, validate_assumptions
from app.services.simulator import Paths


def _rng(seed: int, entity: str, stream: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([seed, zlib.crc32(entity.encode()), stream]))


def generate_paths(snapshot: Snapshot, scenario: Scenario, sku_id: str, *, count: int = PATH_COUNT) -> Paths:
    """Generate paired paths; scenario edits preserve all underlying random draws."""
    if sku_id not in {item.sku_id for item in snapshot.products}:
        raise ValueError(f"unknown SKU {sku_id}")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise ValueError("path count must be a positive integer")
    if scenario.snapshot_id != snapshot.id or scenario.as_of != snapshot.as_of:
        raise ValueError("scenario and snapshot must share an ID and as_of time")
    validate_assumptions(snapshot, scenario.assumptions)
    facility_ids = tuple(sorted(item.id for item in snapshot.facilities))
    demand = np.zeros((count, len(facility_ids), INTERNAL_DAYS), dtype=np.int64)
    evidence: dict[str, dict] = {}
    as_of = scenario.as_of
    first_date = as_of.date() - timedelta(days=BASELINE_DAYS)
    history_by_facility: dict[str, list] = {facility_id: [] for facility_id in facility_ids}
    for row in snapshot.history:
        if row.sku_id == sku_id and first_date <= row.date < as_of.date():
            history_by_facility[row.facility_id].append(row)
    for index, facility_id in enumerate(facility_ids):
        rows = sorted(history_by_facility[facility_id], key=lambda row: row.date)
        known = [row for row in rows if row.requested_units is not None]
        batches = [batch for batch in snapshot.batches if batch.facility_id == facility_id and batch.sku_id == sku_id]
        flags: list[str] = []
        if len(known) < MIN_OBSERVATIONS:
            flags.append("insufficient_demand_evidence")
        mean = float(np.mean([row.requested_units for row in known])) if known else 0.0
        if known and mean == 0:
            flags.append("no_observed_demand")
        if not batches:
            flags.append("missing_stock_observation")
        age_hours = max(((as_of - batch.observed_at).total_seconds() / 3600 for batch in batches), default=None)
        if age_hours is not None and age_hours > MAX_STOCK_AGE_HOURS:
            flags.append("stale_stock")
        usable_units = sum(batch.usable_units for batch in batches if batch.expires_on >= as_of.date())
        evidence[facility_id] = {
            "known_demand_days": len(known), "baseline_window_days": BASELINE_DAYS,
            "mean_daily_requested_units": round(mean, 3), "stock_age_hours": age_hours,
            "current_usable_units": usable_units, "flags": flags,
            "is_eligible": not flags,
        }
        if len(known) < MIN_OBSERVATIONS or mean <= 0:
            continue  # Masked as unknown in every output; never reported as zero risk.
        weekday_means = np.array([
            (sum(row.requested_units for row in known if row.date.weekday() == weekday) + WEEKDAY_SHRINKAGE * mean)
            / (sum(row.date.weekday() == weekday for row in known) + WEEKDAY_SHRINKAGE)
            for weekday in range(7)
        ])
        residuals = np.array([row.requested_units / weekday_means[row.date.weekday()] for row in known])
        daily_means = np.array([weekday_means[(as_of.date() + timedelta(days=day)).weekday()] for day in range(INTERNAL_DAYS)])
        samples = _rng(scenario.seed, facility_id + ":" + sku_id, 1).choice(residuals, size=(count, INTERNAL_DAYS))
        values = samples * daily_means
        for override in scenario.assumptions.demand_overrides:
            if override.facility_id == facility_id and override.sku_id == sku_id:
                end_day = INTERNAL_DAYS - 1 if override.end_day == DISPLAY_DAYS - 1 else override.end_day
                values[:, override.start_day:end_day + 1] *= override.multiplier
        demand[:, index, :] = np.maximum(0, np.rint(values)).astype(np.int64)

    assumptions = [
        "Demand residuals are sampled independently; multi-day demand correlation is not modelled.",
        "Scenario demand changes ending on day 13 continue through reserve-check day 20.",
        "Pointwise inventory P10–P90 bands summarize these model paths; real-world coverage is unvalidated.",
        "Configured routes and travel durations are simulated; proximity does not create demand.",
    ]
    depot_lateness: dict[str, np.ndarray] = {}
    for depot in sorted(snapshot.depots, key=lambda item: item.id):
        delays = [max(0, (item.actual_date - item.promised_date).days) for item in snapshot.deliveries if item.depot_id == depot.id and item.actual_date < as_of.date()]
        if len(delays) < MIN_DELIVERY_OBSERVATIONS:
            delays = snapshot.assumed_delay_days or list(ASSUMED_DELAYS)
            assumptions.append(f"{depot.name}: fewer than five completed deliveries; assumed delay days {delays} with equal frequency.")
        depot_lateness[depot.id] = _rng(scenario.seed, depot.id, 2).choice(delays, size=count).astype(np.int64)
    extra_delays = {item.depot_id: item.extra_days for item in scenario.assumptions.depot_delays}
    shipment_arrivals = {
        shipment.id: np.maximum(shipment.current_eta_day, shipment.promised_arrival_day + depot_lateness[shipment.depot_id]) + extra_delays.get(shipment.depot_id, 0)
        for shipment in snapshot.shipments if shipment.sku_id == sku_id and shipment.status == "PENDING"
    }
    return Paths(sku_id, facility_ids, demand, shipment_arrivals, depot_lateness, evidence, tuple(assumptions), tuple(scenario.assumptions.closed_route_ids))


def planning_paths(paths: Paths) -> Paths:
    """Marginal P80 stress case, not a joint 80% probability guarantee."""
    return replace(
        paths,
        demand=np.quantile(paths.demand, PLANNING_QUANTILE, axis=0, method="higher")[None, :, :].astype(np.int64),
        shipment_arrivals={key: np.array([int(np.quantile(value, PLANNING_QUANTILE, method="higher"))]) for key, value in paths.shipment_arrivals.items()},
        depot_lateness={key: np.array([int(np.quantile(value, PLANNING_QUANTILE, method="higher"))]) for key, value in paths.depot_lateness.items()},
    )


def subset_paths(paths: Paths, facility_ids: set[str]) -> Paths:
    indices = [index for index, item in enumerate(paths.facility_ids) if item in facility_ids]
    return replace(paths, facility_ids=tuple(paths.facility_ids[index] for index in indices), demand=paths.demand[:, indices, :])


run = generate_paths
