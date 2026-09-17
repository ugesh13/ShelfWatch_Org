"""
ShelfWatch Shortage Fingerprinting Service ⭐ D2
=================================================
Classifies the TYPE of shortage by analysing consumption signature patterns.
Rule-based classifier (fully transparent, no ML) with 4 archetypes:
- DEMAND_SURGE: Sudden spike in consumption, normal supply
- SUPPLY_DISRUPTION: Normal consumption, stock dropping from missed replenishment
- PANIC_HOARDING: Abnormally large single-day orders at one facility, neighbours normal
- CHRONIC_EROSION: Slow steady depletion over weeks, no single spike
"""
import logging
import math
from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np

from app.config import (
    SPIKE_RATIO_DEMAND_SURGE,
    SPIKE_RATIO_HOARDING,
    SUPPLY_GAP_MULTIPLIER,
    CHRONIC_EROSION_SLOPE,
    CHRONIC_EROSION_WINDOW,
    NEIGHBOR_Z_NORMAL,
    FINGERPRINT_WINDOW,
    ANOMALY_WINDOW,
)
from app.schemas import Snapshot

logger = logging.getLogger("shelfwatch.fingerprinter")

# Shortage type constants
DEMAND_SURGE = "DEMAND_SURGE"
SUPPLY_DISRUPTION = "SUPPLY_DISRUPTION"
PANIC_HOARDING = "PANIC_HOARDING"
CHRONIC_EROSION = "CHRONIC_EROSION"
MIXED = "MIXED"

# Recommended interventions per type
INTERVENTIONS = {
    DEMAND_SURGE: "Emergency redistribution from surplus facilities + expedite next scheduled procurement",
    SUPPLY_DISRUPTION: "Expedite overdue supply order + reroute from alternate warehouse/depot",
    PANIC_HOARDING: "Review request and order records for an isolated demand spike; consumption alone cannot establish hoarding",
    CHRONIC_EROSION: "Systemic budget review + increase reorder quantity and review safety stock levels",
    MIXED: "Combined intervention: investigate multiple contributing factors before acting",
}


# ── Private Helpers ──────────────────────────────────────────────────────────
def _extract_facility_series(
    snapshot: Snapshot, facility_id: str, sku_id: str
) -> List[dict]:
    """Extract and sort history rows for a facility/sku pair."""
    rows = [
        {
            "date": row.date,
            "fulfilled_units": row.fulfilled_units,
            "requested_units": row.requested_units,
            "received_units": row.received_units,
            "closing_units": row.closing_units,
        }
        for row in snapshot.history
        if row.facility_id == facility_id and row.sku_id == sku_id
        and row.date < snapshot.as_of.date() and row.requested_units is not None
    ]
    rows.sort(key=lambda r: r["date"])
    return rows


def _compute_feature_vector(
    rows: List[dict],
    neighbour_z_scores: List[float],
) -> Dict[str, float]:
    """
    Compute the 5-feature vector for shortage classification:
    1. spike_ratio — recent velocity / baseline mean
    2. supply_gap_days — days since last replenishment
    3. max_single_day_ratio — largest single-day consumption / baseline
    4. trend_slope — linear regression slope of closing stock
    5. neighbor_z_mean — mean z-score of neighbours
    """
    consumptions = np.array([r["requested_units"] for r in rows], dtype=float)
    received = np.array([r["received_units"] for r in rows], dtype=float)
    closing = np.array([r["closing_units"] for r in rows], dtype=float)

    # Baseline: first 60% of history, recent: last FINGERPRINT_WINDOW days
    split = max(len(consumptions) - FINGERPRINT_WINDOW, int(len(consumptions) * 0.6))
    baseline = consumptions[:split]
    recent = consumptions[-min(FINGERPRINT_WINDOW, len(consumptions)):]

    baseline_mean = max(float(np.mean(baseline)), 0.5) if len(baseline) > 0 else 1.0
    baseline_std = max(float(np.std(baseline)), 0.1) if len(baseline) > 0 else 1.0

    # 1. Spike ratio
    recent_mean = float(np.mean(recent)) if len(recent) > 0 else 0.0
    spike_ratio = round(recent_mean / baseline_mean, 2)

    # 2. Supply gap days (days since last non-zero replenishment)
    last_receipt_indices = np.where(received > 0)[0]
    if len(last_receipt_indices) > 0:
        supply_gap_days = (rows[-1]["date"] - rows[int(last_receipt_indices[-1])]["date"]).days + 1
    else:
        supply_gap_days = len(received)

    # Expected replenishment cycle (from receipt pattern)
    if len(last_receipt_indices) >= 2:
        diffs = [(rows[int(right)]["date"] - rows[int(left)]["date"]).days
                 for left, right in zip(last_receipt_indices[:-1], last_receipt_indices[1:])]
        expected_cycle = float(np.median(diffs))
    else:
        expected_cycle = 7.0  # default

    # 3. Max single-day ratio
    max_single_day = float(np.max(recent)) if len(recent) > 0 else 0.0
    max_single_day_ratio = round(max_single_day / baseline_mean, 2)

    # 4. Trend slope (linear regression on closing stock, last CHRONIC_EROSION_WINDOW days)
    trend_window = min(CHRONIC_EROSION_WINDOW, len(closing))
    if trend_window >= CHRONIC_EROSION_WINDOW:
        trend_data = closing[-trend_window:]
        x = np.arange(len(trend_data))
        if np.std(trend_data) > 0:
            slope = float(np.polyfit(x, trend_data, 1)[0])
        else:
            slope = 0.0
        # Normalize by baseline mean
        trend_slope = round(slope / max(baseline_mean, 1.0), 3)
    else:
        trend_slope = 0.0

    # 5. Neighbour z-score mean
    neighbor_z_mean = round(float(np.mean(neighbour_z_scores)), 2) if neighbour_z_scores else 0.0

    return {
        "spike_ratio": spike_ratio,
        "supply_gap_days": supply_gap_days,
        "expected_cycle": expected_cycle,
        "max_single_day_ratio": max_single_day_ratio,
        "trend_slope": trend_slope,
        "neighbor_z_mean": neighbor_z_mean,
    }


def _classify_shortage(features: Dict[str, float]) -> tuple:
    """
    Rule-based decision tree classifier.
    Returns (shortage_type, confidence).

    Decision logic (from implementation plan):
    - IF spike_ratio > 2.5 AND supply_gap < 1.5x → DEMAND_SURGE
    - IF spike_ratio < 1.5 AND supply_gap > 1.5x → SUPPLY_DISRUPTION
    - IF max_single_day > 3x AND neighbor_z_mean < 1.5 → PANIC_HOARDING
    - IF trend_slope < -threshold over 21d → CHRONIC_EROSION
    - ELSE → MIXED
    """
    spike = features["spike_ratio"]
    supply_gap = features["supply_gap_days"]
    expected_cycle = features["expected_cycle"]
    max_day = features["max_single_day_ratio"]
    trend = features["trend_slope"]
    neighbor_z = features["neighbor_z_mean"]

    is_supply_on_time = supply_gap < expected_cycle * SUPPLY_GAP_MULTIPLIER
    is_supply_overdue = supply_gap >= expected_cycle * SUPPLY_GAP_MULTIPLIER

    scores = {
        DEMAND_SURGE: 0.0,
        SUPPLY_DISRUPTION: 0.0,
        PANIC_HOARDING: 0.0,
        CHRONIC_EROSION: 0.0,
    }

    # Rule 1: DEMAND_SURGE — high consumption spike, supply on schedule
    if spike >= SPIKE_RATIO_DEMAND_SURGE and is_supply_on_time:
        scores[DEMAND_SURGE] = 0.7 + min(0.3, (spike - SPIKE_RATIO_DEMAND_SURGE) * 0.15)
    elif spike >= 1.8 and is_supply_on_time:
        scores[DEMAND_SURGE] = 0.4 + (spike - 1.8) * 0.2

    # Rule 2: SUPPLY_DISRUPTION — normal consumption, supply failed
    if spike < 1.5 and is_supply_overdue:
        gap_severity = supply_gap / max(expected_cycle, 1.0)
        scores[SUPPLY_DISRUPTION] = 0.6 + min(0.4, (gap_severity - 1.5) * 0.2)
    elif is_supply_overdue:
        scores[SUPPLY_DISRUPTION] = max(scores[SUPPLY_DISRUPTION], 0.3)

    # Rule 3: PANIC_HOARDING — extreme single-day, neighbours normal
    if max_day >= SPIKE_RATIO_HOARDING and spike < 1.5 and neighbor_z < NEIGHBOR_Z_NORMAL:
        scores[PANIC_HOARDING] = 0.65 + min(0.35, (max_day - SPIKE_RATIO_HOARDING) * 0.1)
    # If both facility AND neighbours are spiking → DEMAND_SURGE, not hoarding
    if max_day >= SPIKE_RATIO_HOARDING and neighbor_z >= NEIGHBOR_Z_NORMAL:
        scores[DEMAND_SURGE] = max(scores[DEMAND_SURGE], 0.6)

    # Rule 4: CHRONIC_EROSION — slow steady depletion
    if trend < CHRONIC_EROSION_SLOPE:
        scores[CHRONIC_EROSION] = 0.6 + min(0.4, abs(trend - CHRONIC_EROSION_SLOPE) * 0.5)
    elif trend < -0.1:
        scores[CHRONIC_EROSION] = 0.3

    # Pick the highest-scoring type
    best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_type]

    if best_score < 0.3:
        return MIXED, round(best_score, 2)

    # Check if multiple types have high scores → MIXED
    high_scores = [t for t, s in scores.items() if s > 0.5 and t != best_type]
    if high_scores and best_score - scores[high_scores[0]] < 0.15:
        return MIXED, round(best_score * 0.7, 2)

    return best_type, round(min(best_score, 1.0), 2)


# ── Public API ───────────────────────────────────────────────────────────────
def run(
    snapshot: Snapshot,
    anomalies: List[Dict],
    sku_id: str = "AMX500_CAP",
) -> List[Dict]:
    """
    Main entry point. Classifies shortage TYPE for every facility
    flagged by the anomaly detector.

    Returns list of FingerprintResult matching CONTRACTS.md.
    """
    logger.info(f"Running shortage fingerprinting for SKU {sku_id}...")

    # Pre-compute z-scores per facility from anomaly results
    facility_z_scores: Dict[str, float] = {}
    for anomaly in anomalies:
        if anomaly["z_score"] is not None:
            facility_z_scores[anomaly["facility_id"]] = anomaly["z_score"]

    # Build facility coordinate lookup for neighbour detection
    facility_coords: Dict[str, tuple] = {}
    for fac in snapshot.facilities:
        facility_coords[fac.id] = (fac.lat, fac.lon)

    # Build adjacency from routes
    neighbours: Dict[str, List[str]] = defaultdict(list)
    for route in snapshot.routes:
        if route.kind == "TRANSFER" and route.enabled:
            neighbours[route.from_id].append(route.to_id)
            neighbours[route.to_id].append(route.from_id)
        elif route.kind == "SUPPLY":
            # Facilities sharing same depot are weak neighbours
            pass

    # Also add proximity-based neighbours (same depot or within routes)
    for fac in snapshot.facilities:
        for other in snapshot.facilities:
            if fac.id != other.id and other.id not in neighbours.get(fac.id, []):
                # Use Haversine approximation
                dlat = (fac.lat - other.lat) * 111.0
                dlon = (fac.lon - other.lon) * 111.0 * math.cos(math.radians(fac.lat))
                dist = math.sqrt(dlat ** 2 + dlon ** 2)
                if dist < 25.0:
                    neighbours[fac.id].append(other.id)

    # Filter to flagged facilities only (risk_level != STABLE)
    flagged = [a for a in anomalies if a["risk_level"] not in ("STABLE", "UNKNOWN")]

    results: List[Dict] = []
    for anomaly in flagged:
        facility_id = anomaly["facility_id"]
        rows = _extract_facility_series(snapshot, facility_id, sku_id)
        if len(rows) < 7:
            continue

        # Gather neighbour z-scores
        neighbour_ids = set(neighbours.get(facility_id, []))
        neighbour_z = [
            facility_z_scores[nid]
            for nid in neighbour_ids
            if nid in facility_z_scores
        ]

        features = _compute_feature_vector(rows, neighbour_z)
        shortage_type, confidence = _classify_shortage(features)

        results.append({
            "facility_id": facility_id,
            "drug_id": sku_id,
            "shortage_type": shortage_type,
            "confidence": confidence,
            "rule_score": confidence,
            "confidence_kind": "heuristic_not_probability",
            "signature": {
                "spike_ratio": features["spike_ratio"],
                "supply_gap_days": features["supply_gap_days"],
                "max_single_day_ratio": features["max_single_day_ratio"],
                "trend_slope": features["trend_slope"],
                "neighbor_z_mean": features["neighbor_z_mean"],
            },
            "recommended_intervention": INTERVENTIONS[shortage_type],
        })

    logger.info(f"Fingerprinting complete. Classified {len(results)} shortage events.")
    return results


def run_for_facility(
    snapshot: Snapshot,
    anomalies: List[Dict],
    facility_id: str,
    sku_id: str = "AMX500_CAP",
) -> Optional[Dict]:
    """Single-facility fingerprinting."""
    return next((result for result in run(snapshot, anomalies, sku_id)
                 if result["facility_id"] == facility_id), None)
