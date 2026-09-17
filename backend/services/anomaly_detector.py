"""
ShelfWatch Anomaly Detection Service
====================================
Detects abnormal consumption velocity and stockout acceleration using
NIST dual-sided CUSUM control charts and baseline z-scores.
Follows CONTRACTS.md and CONVENTIONS.md standards.
"""
import math
import logging
import sqlite3
import numpy as np
from typing import List, Dict, Optional, Tuple

from config import (
    ANOMALY_WINDOW,
    ANOMALY_Z_THRESHOLD,
    CUSUM_DRIFT,
    CUSUM_THRESHOLD,
    RISK_THRESHOLD_AT_RISK,
    RISK_THRESHOLD_CRITICAL,
)
from models.enums import RiskLevel

logger = logging.getLogger("shelfwatch.anomaly_detector")


# ── Private Helpers ──────────────────────────────────────────────────────────
def _sigmoid(x: float) -> float:
    """Logistic sigmoid activation clamped to prevent overflow."""
    return 1.0 / (1.0 + math.exp(-max(min(x, 15.0), -15.0)))


def _compute_facility_drug_anomaly(
    history_rows: List[sqlite3.Row],
    target_day: int
) -> Optional[Dict]:
    """
    Computes consumption velocity, dual-sided CUSUM, z-score,
    and composite local risk score for a single (facility, drug) time series.
    """
    if not history_rows:
        return None

    facility_id = history_rows[0]["facility_id"]
    drug_id = history_rows[0]["drug_id"]

    # Sort rows chronologically
    sorted_rows = sorted(history_rows, key=lambda r: r["day"])
    # Filter up to target_day
    active_rows = [r for r in sorted_rows if r["day"] <= target_day]
    if not active_rows:
        return None

    current_row = active_rows[-1]
    current_day = current_row["day"]
    current_stock = float(current_row["stock_on_hand"])
    today_consumed = float(current_row["consumed_today"])

    consumptions = np.array([float(r["consumed_today"]) for r in active_rows])

    # 1. Historical Baseline (30 days prior to active window)
    baseline_window = 30
    if len(consumptions) >= 7:
        baseline_slice = consumptions[-min(len(consumptions), baseline_window):]
        mu = float(np.mean(baseline_slice))
        sigma = float(np.std(baseline_slice))
        if sigma < 0.1:
            sigma = max(0.1, mu * 0.1)
    else:
        mu = max(float(np.mean(consumptions)), 1.0)
        sigma = max(float(np.std(consumptions)), mu * 0.1)

    # 2. Rolling Consumption Velocity (7-day window)
    recent_slice = consumptions[-min(len(consumptions), ANOMALY_WINDOW):]
    rolling_velocity = float(np.mean(recent_slice))

    # Velocity z-score vs baseline
    z_score = round((rolling_velocity - mu) / sigma, 2)

    # 3. NIST Dual-Sided CUSUM Calculation over available history
    # C+ detects consumption spikes (demand surge)
    # C- detects consumption drops (facility abandonment / data failure)
    k = CUSUM_DRIFT * sigma  # Allowable slack parameter
    h = CUSUM_THRESHOLD * sigma  # Decision threshold

    cusum_pos = 0.0
    cusum_neg = 0.0

    for x in consumptions:
        cusum_pos = max(0.0, cusum_pos + (x - mu) - k)
        cusum_neg = max(0.0, cusum_neg + (mu - k) - x)

    # Normalize CUSUM statistics by sigma for standardized comparison
    cusum_upper = round(cusum_pos / sigma, 2)
    cusum_lower = round(cusum_neg / sigma, 2)

    # 4. Days of Stock Remaining (runway)
    effective_daily_demand = max(rolling_velocity, today_consumed, 0.5)
    days_of_stock = round(max(0.0, current_stock / effective_daily_demand), 1)

    # 5. Determine Flag Reasons
    flag_reasons = []
    if current_stock <= 0.0:
        flag_reasons.append("stockout_detected")
    elif days_of_stock < 3.0:
        flag_reasons.append("critical_stock_depletion")
    elif days_of_stock < 7.0:
        flag_reasons.append("low_stock_runway")

    if z_score >= ANOMALY_Z_THRESHOLD:
        flag_reasons.append("consumption_velocity_spike")
    if cusum_upper >= CUSUM_THRESHOLD:
        flag_reasons.append("cusum_demand_shift_detected")
    if cusum_lower >= CUSUM_THRESHOLD:
        flag_reasons.append("consumption_rate_collapse")

    # 6. Composite Local Risk Score (0.0 to 1.0)
    # Sigmoid weighted combination of z-score, cusum_upper, and runway deficit
    if current_stock <= 0.0:
        local_risk_score = 1.0
        risk_level = RiskLevel.STOCKOUT.value
    else:
        # Runway factor: higher when days_of_stock is low
        runway_urgency = 10.0 / max(days_of_stock, 0.5)
        raw_score = (
            0.30 * max(0.0, z_score)
            + 0.30 * (cusum_upper / max(CUSUM_THRESHOLD, 1.0))
            + 0.40 * runway_urgency
            - 2.2  # centering intercept
        )
        local_risk_score = round(max(0.0, min(1.0, _sigmoid(raw_score))), 3)

        # Classify risk tier
        if local_risk_score >= RISK_THRESHOLD_CRITICAL or days_of_stock < 3.0:
            risk_level = RiskLevel.CRITICAL.value
        elif local_risk_score >= RISK_THRESHOLD_AT_RISK or days_of_stock < 7.0 or z_score >= ANOMALY_Z_THRESHOLD:
            risk_level = RiskLevel.AT_RISK.value
        else:
            risk_level = RiskLevel.STABLE.value

    return {
        "facility_id": facility_id,
        "drug_id": drug_id,
        "local_risk_score": local_risk_score,
        "risk_level": risk_level,
        "z_score": z_score,
        "cusum_upper": cusum_upper,
        "cusum_lower": cusum_lower,
        "days_of_stock": days_of_stock,
        "flag_reasons": flag_reasons,
        "detected_at": current_day,
    }


# ── Public API ───────────────────────────────────────────────────────────────
def run(db_connection: sqlite3.Connection, target_day: int = 89) -> List[Dict]:
    """
    Main entry point for anomaly detection.
    Scans all facility and drug pairs across stock_history up to target_day.
    Returns list of AnomalyResult dictionaries matching CONTRACTS.md.
    """
    logger.info(f"Running anomaly detection up to day {target_day}...")
    cursor = db_connection.cursor()

    cursor.execute(
        """
        SELECT facility_id, drug_id, day, consumed_today, replenished_today, stock_on_hand
        FROM stock_history
        WHERE day <= ?
        ORDER BY facility_id, drug_id, day ASC;
        """,
        (target_day,),
    )
    rows = cursor.fetchall()

    # Group rows by (facility_id, drug_id)
    grouped: Dict[Tuple[str, str], List[sqlite3.Row]] = {}
    for r in rows:
        key = (r["facility_id"], r["drug_id"])
        grouped.setdefault(key, []).append(r)

    results = []
    for (fac_id, drug_id), group_rows in grouped.items():
        anomaly = _compute_facility_drug_anomaly(group_rows, target_day)
        if anomaly:
            results.append(anomaly)

    logger.info(f"Anomaly detection complete. Analyzed {len(results)} facility-drug series.")
    return results


def run_for_facility(
    db_connection: sqlite3.Connection,
    facility_id: str,
    target_day: int = 89
) -> List[Dict]:
    """Runs anomaly detection for all drugs in a single facility."""
    cursor = db_connection.cursor()
    cursor.execute(
        """
        SELECT facility_id, drug_id, day, consumed_today, replenished_today, stock_on_hand
        FROM stock_history
        WHERE facility_id = ? AND day <= ?
        ORDER BY drug_id, day ASC;
        """,
        (facility_id, target_day),
    )
    rows = cursor.fetchall()

    grouped: Dict[str, List[sqlite3.Row]] = {}
    for r in rows:
        grouped.setdefault(r["drug_id"], []).append(r)

    results = []
    for drug_id, group_rows in grouped.items():
        anomaly = _compute_facility_drug_anomaly(group_rows, target_day)
        if anomaly:
            results.append(anomaly)

    return results
