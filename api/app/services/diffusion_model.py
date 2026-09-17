"""
ShelfWatch SIS Contagion Diffusion Model ⭐ D3
===============================================
Models shortage spread as epidemiological contagion across the facility graph.

SIS-inspired model with severity levels (NOT SIR):
- S (Stable): risk < 0.4, healthy, not infectious
- I₁ (At-Risk): 0.4 ≤ risk < 0.7, spreads at rate β₁
- I₂ (Critical): risk ≥ 0.7, spreads at HIGHER rate β₂ > β₁
- Recovery: ONLY when actual replenishment arrives (no passive decay)

Key difference from naive SIR: there is NO passive γ decay. Recovery happens
ONLY via actual restocking events. This prevents the model from falsely
showing risk declining when no intervention occurred.
"""
import logging
import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.config import (
    DIFFUSION_DAYS_FORWARD,
    DIFFUSION_BETA_AT_RISK,
    DIFFUSION_BETA_CRITICAL,
    DIFFUSION_RECOVERY_GAMMA,
    RISK_THRESHOLD_AT_RISK,
    RISK_THRESHOLD_CRITICAL,
    SCENARIO_SEED,
)
from app.schemas import Assumptions, Scenario, Snapshot
from app.services.forecast import generate_paths, planning_paths
from app.services.simulator import simulate

logger = logging.getLogger("shelfwatch.diffusion")


# ── Private Helpers ──────────────────────────────────────────────────────────
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _classify_state(risk: float) -> str:
    """Classify facility state from risk score."""
    if risk >= RISK_THRESHOLD_CRITICAL:
        return "CRITICAL"
    if risk >= RISK_THRESHOLD_AT_RISK:
        return "AT_RISK"
    return "STABLE"


def _build_edges(snapshot: Snapshot, closed_route_ids=()) -> List[Dict]:
    """Build directed edges with distance and referral weight."""
    edges: List[Dict] = []
    facility_coords = {fac.id: (fac.lat, fac.lon) for fac in snapshot.facilities}

    for route in snapshot.routes:
        if route.kind == "TRANSFER" and route.enabled and route.id not in closed_route_ids:
            dist = route.distance_km
            # Referral weight: inversely proportional to distance
            referral_weight = 1.0 / max(dist, 1.0)
            edges.append({
                "from_id": route.from_id,
                "to_id": route.to_id,
                "distance_km": dist,
                "referral_weight": referral_weight,
            })
            # Add reverse edge (bidirectional influence)
            edges.append({
                "from_id": route.to_id,
                "to_id": route.from_id,
                "distance_km": dist,
                "referral_weight": referral_weight * 0.5,  # weaker reverse
            })

    # Add supply-route proximity edges (facilities sharing a depot)
    depot_facilities: Dict[str, List[str]] = defaultdict(list)
    for fac in snapshot.facilities:
        depot_facilities[fac.depot_id].append(fac.id)

    for depot_id, facs in depot_facilities.items():
        for i, f1 in enumerate(facs):
            for f2 in facs[i + 1:]:
                if f1 in facility_coords and f2 in facility_coords:
                    dist = _haversine_km(*facility_coords[f1], *facility_coords[f2])
                    if dist < 40.0:
                        weight = 0.3 / max(dist, 1.0)
                        edges.append({"from_id": f1, "to_id": f2,
                                      "distance_km": dist, "referral_weight": weight})
                        edges.append({"from_id": f2, "to_id": f1,
                                      "distance_km": dist, "referral_weight": weight})

    # A pair's influence must not be multiplied by duplicate/reciprocal routes.
    unique = {}
    for edge in edges:
        key = (edge["from_id"], edge["to_id"])
        if key not in unique or edge["referral_weight"] > unique[key]["referral_weight"]:
            unique[key] = edge
    return list(unique.values())


def _compute_slack(snapshot: Snapshot, facility_id: str, sku_id: str) -> float:
    """
    Compute stock slack margin.
    slack = days_of_stock / 14, clamped to [0, 1].
    """
    stock = sum(
        b.usable_units for b in snapshot.batches
        if b.facility_id == facility_id and b.sku_id == sku_id
        and b.expires_on >= snapshot.as_of.date()
    )

    fac_history = sorted(
        [h for h in snapshot.history
         if h.facility_id == facility_id and h.sku_id == sku_id
         and h.date < snapshot.as_of.date() and h.requested_units is not None],
        key=lambda h: h.date,
    )

    if len(fac_history) < 7:
        return 0.5

    recent = fac_history[-7:]
    avg_daily = sum(h.requested_units for h in recent) / len(recent)
    days_of_stock = stock / max(avg_daily, 0.5)

    return min(1.0, max(0.0, days_of_stock / 14.0))


def _estimate_replenishment_days(
    snapshot: Snapshot, facility_id: str, sku_id: str
) -> List[int]:
    """
    Estimate which future days a facility might receive replenishment,
    based on pending shipments.
    """
    replenishment_days: List[int] = []
    for shipment in snapshot.shipments:
        if (shipment.facility_id == facility_id
                and shipment.sku_id == sku_id
                and shipment.status == "PENDING"):
            replenishment_days.append(shipment.current_eta_day)
    return replenishment_days


# ── Public API ───────────────────────────────────────────────────────────────
def run(
    snapshot: Snapshot,
    anomalies: List[Dict],
    sku_id: str = "AMX500_CAP",
    days_forward: int = DIFFUSION_DAYS_FORWARD,
    *,
    scenario: Scenario | None = None,
) -> Dict:
    """
    Main entry point. Runs SIS-style contagion diffusion forward from
    current anomaly states.

    Returns DiffusionResult matching CONTRACTS.md:
    {
        "simulation_days": int,
        "timeline": [{"day": int, "facilities_stable": int, ...}],
        "facility_projections": {facility_id: {...}}
    }
    """
    logger.info(f"Running SIS diffusion for SKU {sku_id}, {days_forward} days forward...")

    if not isinstance(days_forward, int) or not 0 <= days_forward <= DIFFUSION_DAYS_FORWARD:
        raise ValueError("diffusion horizon must be between 0 and 14 days")
    scenario = scenario or Scenario(
        id="DIFFUSION", snapshot_id=snapshot.id, fixture_id=None,
        name="Heuristic graph scenario", as_of=snapshot.as_of,
        seed=SCENARIO_SEED, assumptions=Assumptions(),
    )
    paths = generate_paths(snapshot, scenario, sku_id)
    stress_paths = planning_paths(paths)
    inventory = simulate(snapshot, stress_paths)
    facility_ids = [fid for fid in paths.facility_ids if paths.evidence[fid]["is_eligible"]]
    unknown_ids = [fid for fid in paths.facility_ids if fid not in facility_ids]
    edges = _build_edges(snapshot, paths.closed_route_ids)

    # Build edge index: to_id -> [(from_id, distance, weight)]
    incoming_edges: Dict[str, List[Tuple[str, float, float]]] = defaultdict(list)
    for edge in edges:
        incoming_edges[edge["to_id"]].append(
            (edge["from_id"], edge["distance_km"], edge["referral_weight"])
        )

    # Initialize risk from anomaly results
    risk: Dict[str, float] = {}
    for fid in facility_ids:
        risk[fid] = 0.0

    for anomaly in anomalies:
        if anomaly["facility_id"] in risk and anomaly["local_risk_score"] is not None:
            floor = {"AT_RISK": RISK_THRESHOLD_AT_RISK, "CRITICAL": RISK_THRESHOLD_CRITICAL, "STOCKOUT": 1.0}.get(anomaly["risk_level"], 0)
            risk[anomaly["facility_id"]] = max(anomaly["local_risk_score"], floor)

    # Compute slack margins
    slack: Dict[str, float] = {}
    for fid in facility_ids:
        slack[fid] = _compute_slack(snapshot, fid, sku_id)

    # Estimate replenishment schedules
    replenishment: Dict[str, List[int]] = {}
    for fid in facility_ids:
        index = paths.facility_ids.index(fid)
        replenishment[fid] = np.flatnonzero(inventory.receipts[0, index] > 0).tolist()

    # Track projections
    timeline: List[Dict] = []
    risk_trajectories: Dict[str, List[float]] = {fid: [] for fid in facility_ids}
    day_entered_at_risk: Dict[str, Optional[int]] = {fid: None for fid in facility_ids}
    day_entered_critical: Dict[str, Optional[int]] = {fid: None for fid in facility_ids}

    # Set initial entry markers from current state
    for fid in facility_ids:
        if risk[fid] >= RISK_THRESHOLD_CRITICAL:
            day_entered_critical[fid] = 0
            day_entered_at_risk[fid] = 0
        elif risk[fid] >= RISK_THRESHOLD_AT_RISK:
            day_entered_at_risk[fid] = 0

    # SIS Diffusion loop
    for day in range(days_forward + 1):
        # Record current state
        for fid in facility_ids:
            risk_trajectories[fid].append(round(risk[fid], 3))

        stable_count = sum(1 for fid in facility_ids
                          if risk[fid] < RISK_THRESHOLD_AT_RISK)
        at_risk_count = sum(1 for fid in facility_ids
                           if RISK_THRESHOLD_AT_RISK <= risk[fid] < RISK_THRESHOLD_CRITICAL)
        critical_count = sum(1 for fid in facility_ids
                            if risk[fid] >= RISK_THRESHOLD_CRITICAL)
        regional_risk = round(sum(risk.values()) / len(facility_ids), 3) if facility_ids else None

        timeline.append({
            "day": day,
            "facilities_stable": stable_count,
            "facilities_at_risk": at_risk_count,
            "facilities_critical": critical_count,
            "regional_risk_score": regional_risk,
            "facilities_unknown": len(unknown_ids),
        })
        if day == days_forward:
            break

        # Compute new risk values
        new_risk: Dict[str, float] = {}
        for fid in facility_ids:
            # Infection pressure from neighbours
            infection_pressure = 0.0
            for from_id, distance, weight in incoming_edges.get(fid, []):
                if from_id not in risk:
                    continue
                neighbour_risk = risk[from_id]
                if neighbour_risk < RISK_THRESHOLD_AT_RISK:
                    continue

                # β depends on severity level of the infecting facility
                if neighbour_risk >= RISK_THRESHOLD_CRITICAL:
                    beta = DIFFUSION_BETA_CRITICAL
                else:
                    beta = DIFFUSION_BETA_AT_RISK

                # Infection pressure formula from implementation plan
                infection_pressure += (
                    beta
                    * (neighbour_risk / max(distance, 1.0))
                    * weight
                    * (1.0 - slack[fid])
                )

            # Recovery: ONLY when actual replenishment arrives
            recovery = 0.0
            if day in replenishment.get(fid, []):
                index = paths.facility_ids.index(fid)
                reserve_demand = max(1, int(stress_paths.demand[0, index, day:day + 7].sum()))
                recovery = DIFFUSION_RECOVERY_GAMMA * min(1, inventory.receipts[0, index, day] / reserve_demand)

            # Update risk
            new_risk[fid] = min(1.0, max(0.0, risk[fid] + infection_pressure - recovery))
            index = paths.facility_ids.index(fid)
            daily_demand = float(stress_paths.demand[0, index, day])
            stock = int(inventory.closing[0, index, day])
            slack[fid] = min(1.0, stock / (14 * daily_demand)) if daily_demand > 0 else 1.0
            if inventory.unmet[0, index, day] > 0:
                new_risk[fid] = 1.0

        risk = new_risk

        # Track state transitions
        for fid in facility_ids:
            if (risk[fid] >= RISK_THRESHOLD_AT_RISK
                    and day_entered_at_risk[fid] is None):
                day_entered_at_risk[fid] = day + 1
            if (risk[fid] >= RISK_THRESHOLD_CRITICAL
                    and day_entered_critical[fid] is None):
                day_entered_critical[fid] = day + 1

    # Build facility projections
    facility_projections: Dict[str, Dict] = {}
    for fid in facility_ids:
        facility_projections[fid] = {
            "day_entered_at_risk": day_entered_at_risk[fid],
            "day_entered_critical": day_entered_critical[fid],
            "risk_trajectory": risk_trajectories[fid],
        }
    for fid in unknown_ids:
        facility_projections[fid] = {
            "day_entered_at_risk": None, "day_entered_critical": None,
            "risk_trajectory": [None] * (days_forward + 1),
        }

    result = {
        "simulation_days": days_forward,
        "timeline": timeline,
        "facility_projections": facility_projections,
        "model_kind": "heuristic_graph",
        "assumptions": [
            "Graph pressure is a hypothetical mechanism, not measured patient movement or a calibrated probability.",
            "Receipts and stock depletion follow the scenario's P80 inventory stress case.",
        ],
    }

    logger.info(
        f"Diffusion complete. Day {days_forward}: "
        f"{timeline[-1]['facilities_at_risk']} at-risk, "
        f"{timeline[-1]['facilities_critical']} critical."
    )
    return result


def run_what_if(
    snapshot: Snapshot,
    anomalies: List[Dict],
    sku_id: str = "AMX500_CAP",
    demand_shock_facility: Optional[str] = None,
    demand_multiplier: float = 1.0,
    extra_delay_days: int = 0,
    closed_routes: Optional[List[str]] = None,
    days_forward: int = DIFFUSION_DAYS_FORWARD,
) -> Dict:
    """
    What-if variant: allows injecting custom shock parameters
    and re-running the diffusion model.
    """
    assumptions = Assumptions(
        demand_overrides=(
            [{"facility_id": demand_shock_facility, "sku_id": sku_id, "multiplier": demand_multiplier}]
            if demand_shock_facility else []
        ),
        depot_delays=[{"depot_id": depot.id, "extra_days": extra_delay_days} for depot in snapshot.depots],
        closed_route_ids=closed_routes or [],
    )
    scenario = Scenario(
        id="WHAT-IF", snapshot_id=snapshot.id, fixture_id=None,
        name="Heuristic what-if", as_of=snapshot.as_of, seed=SCENARIO_SEED,
        assumptions=assumptions,
    )
    if demand_shock_facility:
        from app.services.anomaly_detector import run as detect_anomalies
        anomalies = detect_anomalies(snapshot, sku_id, scenario=scenario)
    return run(snapshot, anomalies, sku_id, days_forward, scenario=scenario)
