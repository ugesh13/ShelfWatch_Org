"""Evidence and discrete uncertainty summaries from the inventory simulation."""

from datetime import timedelta

import numpy as np

from app.config import BASELINE_DAYS, DEMAND_ELEVATED_RATIO, DISPLAY_DAYS, HIGH_RISK_THRESHOLD, WATCH_THRESHOLD
from app.schemas import Scenario, Snapshot
from app.services.simulator import Paths, SimulationResult


def _shortfall_quantiles(unmet: np.ndarray) -> tuple[int | None, ...]:
    """Keep no-shortfall paths censored; never interpolate them into a date."""
    horizon = unmet.shape[1]
    has_shortfall = (unmet > 0).any(axis=1)
    first_days = np.where(has_shortfall, (unmet > 0).argmax(axis=1), horizon)
    values = np.quantile(first_days, [0.1, 0.5, 0.9], method="higher")
    return tuple(int(value) if value < horizon else None for value in values)


def _risk_state(probability: float) -> str:
    if probability >= HIGH_RISK_THRESHOLD:
        return "High risk"
    if probability >= WATCH_THRESHOLD:
        return "Watch"
    return "Lower risk"


def compute_facility_explanations(
    snapshot: Snapshot,
    scenario: Scenario,
    paths: Paths,
    sim_result: SimulationResult,
    facility_id: str,
) -> dict:
    """Report observations and explicit assumptions separately from predictions."""
    index = paths.facility_ids.index(facility_id)
    as_of = scenario.as_of
    sku_id = paths.sku_id
    evidence = paths.evidence.get(facility_id, {})
    flags = list(evidence.get("flags", []))
    is_known = not flags
    stock_known = not {"missing_stock_observation", "stale_stock"}.intersection(flags)
    current_stock = sum(
        batch.usable_units for batch in snapshot.batches
        if batch.facility_id == facility_id and batch.sku_id == sku_id
        and batch.expires_on >= as_of.date()
    ) if stock_known else None

    unmet = sim_result.unmet[:, index, :DISPLAY_DAYS]
    closing = sim_result.closing[:, index, :DISPLAY_DAYS]
    probability_7d = round(float((unmet[:, :7] > 0).any(axis=1).mean()), 3) if is_known else None
    probability_14d = round(float((unmet > 0).any(axis=1).mean()), 3) if is_known else None
    expected_unmet = round(float(unmet.sum(axis=1).mean()), 3) if is_known else None
    p10, p50, p90 = _shortfall_quantiles(unmet) if is_known else (None, None, None)

    risk_state = "Unknown"
    if is_known:
        risk_state = "Empty" if current_stock == 0 else _risk_state(probability_14d)

    daily_probability = [
        round(float((unmet[:, day] > 0).mean()), 3) if is_known else None
        for day in range(DISPLAY_DAYS)
    ]
    daily_stock = [
        int(np.quantile(closing[:, day], 0.5, method="higher")) if is_known else None
        for day in range(DISPLAY_DAYS)
    ]
    daily_states = [
        ("Unknown" if not is_known else
         "Empty" if daily_stock[day] == 0 and paths.demand[:, index, day].mean() > 0
         else _risk_state(daily_probability[day]))
        for day in range(DISPLAY_DAYS)
    ]

    factors = []

    def add(code: str, category: str, title: str, description: str, priority: int):
        factors.append({
            "code": code, "category": category, "title": title,
            "description": description, "priority": priority,
        })

    if flags:
        add("incomplete_evidence", "data", "Forecast unavailable",
            "Required evidence is missing or stale: " + ", ".join(flag.replace("_", " ") for flag in flags) + ".", 0)
    if is_known and current_stock == 0:
        add("zero_current_stock", "inventory", "Zero current stock",
            "No usable units are observed while positive demand is expected.", 1)
    elif p50 is not None and p50 < 7:
        add("imminent_shortfall", "inventory", f"Median first shortfall: day {p50}",
            f"Half of the sampled paths first experience unmet demand by day {p50}.", 2)

    shipments = [
        shipment for shipment in snapshot.shipments
        if shipment.facility_id == facility_id and shipment.sku_id == sku_id
        and shipment.status == "PENDING"
    ]
    routes = {route.id: route for route in snapshot.routes}
    usable_arrival_days = []
    for shipment in shipments:
        if shipment.promised_arrival_day < 0:
            add("replenishment_overdue", "supply",
                f"Shipment overdue by {-shipment.promised_arrival_day} days",
                f"{shipment.quantity_units} units were promised before the snapshot; the current reported ETA is day {shipment.current_eta_day}.", 3)
        route = routes[shipment.route_id]
        if not route.enabled or route.id in paths.closed_route_ids:
            add("supply_route_closed", "supply", "Supplier route unavailable",
                f"Route {route.id} blocks the pending {shipment.quantity_units}-unit receipt throughout this scenario.", 3)
            continue
        arrivals = paths.shipment_arrivals[shipment.id]
        expiry_day = (shipment.expires_on - as_of.date()).days
        eligible_arrivals = np.where(arrivals <= expiry_day, arrivals, paths.days + 1)
        median_arrival = int(np.quantile(eligible_arrivals, 0.5, method="higher"))
        if median_arrival < paths.days:
            usable_arrival_days.append(median_arrival)
            if median_arrival > max(0, shipment.promised_arrival_day):
                add("projected_delivery_delay", "supply", f"Projected receipt on day {median_arrival}",
                    f"The median modeled arrival of {shipment.quantity_units} units is day {median_arrival}, including the declared depot delay and sampled delivery history.", 5)
        else:
            add("receipt_not_usable", "supply", "Receipt unavailable in the forecast",
                f"Shipment {shipment.id} arrives beyond the forecast or after its batch expiry in at least half of the paths.", 5)

    first_date = as_of.date() - timedelta(days=BASELINE_DAYS)
    rows = sorted(
        [row for row in snapshot.history if row.facility_id == facility_id
         and row.sku_id == sku_id and first_date <= row.date < as_of.date()],
        key=lambda row: row.date,
    )
    if len(rows) == BASELINE_DAYS and all(row.requested_units is not None for row in rows):
        recent_mean = float(np.mean([row.requested_units for row in rows[-7:]]))
        prior_mean = float(np.mean([row.requested_units for row in rows[:-7]]))
        if prior_mean > 0 and recent_mean / prior_mean >= DEMAND_ELEVATED_RATIO:
            ratio = recent_mean / prior_mean
            add("demand_elevated", "demand", f"Observed demand elevated {ratio:.2f}x",
                f"Known requests averaged {recent_mean:.1f} units in the latest 7 days versus {prior_mean:.1f} in the preceding 21 days.", 4)
        if sum(row.fulfilled_units for row in rows) > sum(row.received_units for row in rows) and rows[-1].closing_units < rows[0].opening_units:
            add("persistent_imbalance", "inventory", "Receipts below fulfilled demand",
                "In the complete 28-day history, fulfilled demand exceeded receipts and stock declined; the underlying cause requires review.", 7)

    for override in scenario.assumptions.demand_overrides:
        if override.facility_id == facility_id and override.sku_id == sku_id and override.multiplier != 1:
            add("scenario_demand_change", "demand", f"Assumed demand: {override.multiplier:g}x",
                f"The what-if scenario multiplies demand on days {override.start_day}–{override.end_day}; this is an entered assumption.", 4)

    supplying_depots = {shipment.depot_id for shipment in shipments}
    for delay in scenario.assumptions.depot_delays:
        if delay.depot_id in supplying_depots and delay.extra_days > 0:
            other_facilities = {
                shipment.facility_id for shipment in snapshot.shipments
                if shipment.depot_id == delay.depot_id and shipment.sku_id == sku_id
                and shipment.status == "PENDING" and shipment.facility_id != facility_id
            }
            add("shared_depot_exposure", "network", f"Assumed supplier delay (+{delay.extra_days}d)",
                f"Pending receipts from {delay.depot_id} are delayed in this scenario; {len(other_facilities)} other facilities have pending receipts for this SKU from that depot.", 5)

    if p50 is not None and usable_arrival_days and p50 < min(usable_arrival_days):
        arrival = min(usable_arrival_days)
        add("insufficient_coverage", "inventory", "Shortfall before next modeled receipt",
            f"Median first shortfall is day {p50}; the earliest median usable receipt is day {arrival}.", 6)

    factors.sort(key=lambda factor: (factor["priority"], factor["code"]))
    return {
        "facility_id": facility_id, "sku_id": sku_id, "risk_state": risk_state,
        "shortage_probability_7d": probability_7d,
        "shortage_probability_14d": probability_14d,
        "expected_unmet_units_14d": expected_unmet,
        "first_shortfall_day_p10": p10, "first_shortfall_day_p50": p50, "first_shortfall_day_p90": p90,
        "current_usable_stock": current_stock,
        "daily_shortage_probability": daily_probability, "daily_stock_p50": daily_stock,
        "daily_risk_state": daily_states,
        "primary_factors": factors[:3], "all_factors": factors, "flags": flags,
    }


run = compute_facility_explanations
