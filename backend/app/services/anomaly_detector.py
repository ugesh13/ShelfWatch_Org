"""Historical demand anomaly signals; heuristic scores are not probabilities."""

import math
from datetime import timedelta

import numpy as np

from app.config import (
    ANOMALY_WINDOW, ANOMALY_Z_THRESHOLD, CUSUM_DRIFT, CUSUM_THRESHOLD,
    RISK_THRESHOLD_AT_RISK, RISK_THRESHOLD_CRITICAL, SCENARIO_SEED,
)
from app.schemas import Assumptions, Scenario, Snapshot
from app.services.forecast import generate_paths


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(value, 15.0), -15.0)))


def run(snapshot: Snapshot, sku_id: str = "AMX500_CAP", *, scenario: Scenario | None = None) -> list[dict]:
    """Use requested demand and current usable batches, preserving missing data."""
    scenario = scenario or Scenario(
        id="ANALYTICS", snapshot_id=snapshot.id, fixture_id=None,
        name="Historical analytics", as_of=snapshot.as_of,
        seed=SCENARIO_SEED, assumptions=Assumptions(),
    )
    paths = generate_paths(snapshot, scenario, sku_id, count=1)
    recent_start = snapshot.as_of.date() - timedelta(days=ANOMALY_WINDOW)
    baseline_start = recent_start - timedelta(days=30)
    results = []
    for facility_id in paths.facility_ids:
        evidence = paths.evidence[facility_id]
        rows = sorted(
            [row for row in snapshot.history if row.facility_id == facility_id
             and row.sku_id == sku_id and baseline_start <= row.date < snapshot.as_of.date()],
            key=lambda row: row.date,
        )
        baseline = [row.requested_units for row in rows
                    if row.date < recent_start and row.requested_units is not None]
        recent = [row.requested_units for row in rows
                  if row.date >= recent_start and row.requested_units is not None]
        flags = list(evidence["flags"])
        if not baseline or not recent:
            flags.append("insufficient_recent_demand")
        if flags:
            results.append({
                "facility_id": facility_id, "drug_id": sku_id,
                "local_risk_score": None, "risk_level": "UNKNOWN",
                "z_score": None, "cusum_upper": None, "cusum_lower": None,
                "days_of_stock": None, "flag_reasons": flags, "detected_at": 0,
                "score_kind": "heuristic_not_probability",
            })
            continue

        mean = float(np.mean(baseline))
        sigma = max(float(np.std(baseline)), mean * 0.1, 0.1)
        velocity = float(np.mean(recent))
        z_score = round((velocity - mean) / (sigma / math.sqrt(len(recent))), 2)
        positive = negative = 0.0
        for requested in recent:
            positive = max(0.0, positive + requested - mean - CUSUM_DRIFT * sigma)
            negative = max(0.0, negative + mean - requested - CUSUM_DRIFT * sigma)
        upper, lower = round(positive / sigma, 2), round(negative / sigma, 2)

        multiplier = next(
            (override.multiplier for override in scenario.assumptions.demand_overrides
             if override.facility_id == facility_id and override.sku_id == sku_id
             and override.start_day == 0), 1.0,
        )
        daily_demand = max(velocity, recent[-1]) * multiplier
        stock = evidence["current_usable_units"]
        days_of_stock = round(stock / daily_demand, 1) if daily_demand > 0 else None
        stockout = stock == 0 and evidence["mean_daily_requested_units"] > 0
        reasons = []
        if stockout:
            reasons.append("stockout_detected")
        elif days_of_stock is not None and days_of_stock < 3:
            reasons.append("critical_stock_depletion")
        elif days_of_stock is not None and days_of_stock < 7:
            reasons.append("low_stock_runway")
        if z_score >= ANOMALY_Z_THRESHOLD:
            reasons.append("consumption_velocity_spike")
        if upper >= CUSUM_THRESHOLD:
            reasons.append("cusum_demand_shift_detected")
        if lower >= CUSUM_THRESHOLD:
            reasons.append("consumption_rate_collapse")
        if multiplier != 1:
            reasons.append("scenario_demand_override")
        if any(shipment.facility_id == facility_id and shipment.sku_id == sku_id
               and shipment.status == "PENDING" and shipment.promised_arrival_day < 0
               for shipment in snapshot.shipments):
            reasons.append("replenishment_overdue")
        runway_urgency = 10 / max(days_of_stock, 0.5) if days_of_stock is not None else 0
        score = 1.0 if stockout else round(_sigmoid(
            0.3 * max(0, z_score) + 0.3 * upper / CUSUM_THRESHOLD + 0.4 * runway_urgency - 2.2
        ), 3)
        if stockout:
            level = "STOCKOUT"
        elif score >= RISK_THRESHOLD_CRITICAL or (days_of_stock is not None and days_of_stock < 3):
            level = "CRITICAL"
        elif score >= RISK_THRESHOLD_AT_RISK or (days_of_stock is not None and days_of_stock < 7) or z_score >= ANOMALY_Z_THRESHOLD:
            level = "AT_RISK"
        else:
            level = "STABLE"
        results.append({
            "facility_id": facility_id, "drug_id": sku_id,
            "local_risk_score": score, "risk_level": level,
            "z_score": z_score, "cusum_upper": upper, "cusum_lower": lower,
            "days_of_stock": days_of_stock, "flag_reasons": reasons, "detected_at": 0,
            "score_kind": "heuristic_not_probability",
        })
    return results


def run_for_facility(snapshot: Snapshot, facility_id: str, sku_id: str = "AMX500_CAP") -> dict | None:
    return next((item for item in run(snapshot, sku_id) if item["facility_id"] == facility_id), None)
