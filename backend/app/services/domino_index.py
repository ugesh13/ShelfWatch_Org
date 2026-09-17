"""
ShelfWatch Domino Index Calculator ⭐ D1
========================================
For every facility, answers: "If this facility stocks out completely,
how many other facilities cascade into crisis within 7 days?"

This is STRUCTURAL pre-crisis intelligence — computed from graph topology
and dependency relationships, NOT from live anomaly scores (avoids circular
dependency). A high Domino Index means a facility is structurally dangerous
even when its shelves are FULL.

Uses clean-room graph simulation: set facility F stock to 0 while all others
keep current stock, run graph diffusion forward 7 days, count cascades.
"""
import logging
import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.config import (
    DOMINO_SIMULATION_DAYS,
    DOMINO_NEIGHBOUR_RADIUS_KM,
    DOMINO_RISK_TRANSFER_RATE,
    RISK_THRESHOLD_AT_RISK,
    SCENARIO_SEED,
)
from app.schemas import Assumptions, Scenario, Snapshot
from app.services.forecast import generate_paths

logger = logging.getLogger("shelfwatch.domino_index")


# ── Private Helpers ──────────────────────────────────────────────────────────
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate distance in km using Haversine formula."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _build_graph(snapshot: Snapshot, closed_route_ids=()) -> Dict:
    """
    Builds an adjacency graph from snapshot routes and facility positions.
    Returns graph metadata including adjacency list, distances, and weights.
    """
    facility_coords: Dict[str, Tuple[float, float]] = {}
    for fac in snapshot.facilities:
        facility_coords[fac.id] = (fac.lat, fac.lon)

    # Adjacency list: facility_id -> [(neighbour_id, distance_km, weight)]
    adjacency: Dict[str, List[Tuple[str, float, float]]] = defaultdict(list)

    # From explicit routes
    for route in snapshot.routes:
        if route.kind == "TRANSFER" and route.enabled and route.id not in closed_route_ids:
            dist = route.distance_km
            weight = 1.0 / max(dist, 1.0)
            adjacency[route.from_id].append((route.to_id, dist, weight))
            adjacency[route.to_id].append((route.from_id, dist, weight))

    # From supply routes (facilities sharing same depot are indirectly connected)
    depot_facilities: Dict[str, List[str]] = defaultdict(list)
    for fac in snapshot.facilities:
        depot_facilities[fac.depot_id].append(fac.id)

    for depot_id, facs in depot_facilities.items():
        for i, f1 in enumerate(facs):
            for f2 in facs[i + 1:]:
                if f1 in facility_coords and f2 in facility_coords:
                    dist = _haversine_km(*facility_coords[f1], *facility_coords[f2])
                    if dist < DOMINO_NEIGHBOUR_RADIUS_KM:
                        # Weaker connection than explicit transfer routes
                        weight = 0.5 / max(dist, 1.0)
                        if f2 not in [n[0] for n in adjacency.get(f1, [])]:
                            adjacency[f1].append((f2, dist, weight))
                            adjacency[f2].append((f1, dist, weight))

    for facility_id, neighbors in adjacency.items():
        unique = {}
        for neighbor, distance, weight in neighbors:
            if neighbor not in unique or distance < unique[neighbor][0]:
                unique[neighbor] = (distance, weight)
        adjacency[facility_id] = [(neighbor, *values) for neighbor, values in sorted(unique.items())]
    return {
        "adjacency": adjacency,
        "coords": facility_coords,
        "depot_facilities": depot_facilities,
    }


def _compute_slack(snapshot: Snapshot, facility_id: str, sku_id: str) -> float:
    """
    Compute the stock slack margin for a facility.
    slack = days_of_stock / 14, clamped to [0, 1].
    Higher slack = more buffer.
    """
    # Get current stock from batches
    stock = sum(
        b.usable_units for b in snapshot.batches
        if b.facility_id == facility_id and b.sku_id == sku_id
        and b.expires_on >= snapshot.as_of.date()
    )

    # Estimate daily consumption from recent history
    fac_history = sorted(
        [h for h in snapshot.history
         if h.facility_id == facility_id and h.sku_id == sku_id
         and h.date < snapshot.as_of.date() and h.requested_units is not None],
        key=lambda h: h.date,
    )

    if len(fac_history) < 7:
        return 0.5  # unknown → assume moderate

    recent = fac_history[-7:]
    avg_daily = sum(h.requested_units for h in recent) / len(recent)
    days_of_stock = stock / max(avg_daily, 0.5)

    return min(1.0, max(0.0, days_of_stock / 14.0))


def _simulate_cascade(
    graph: Dict,
    snapshot: Snapshot,
    knocked_out_facility: str,
    sku_id: str,
    days: int = DOMINO_SIMULATION_DAYS,
    slack_by_facility: dict[str, float] | None = None,
) -> int:
    """
    Clean-room cascade simulation:
    1. Set knocked_out_facility stock to 0
    2. All other facilities keep their current slack
    3. Propagate risk via graph edges for `days` steps
    4. Count how many facilities transition to At-Risk or Critical

    No live anomaly scores used — this is STRUCTURAL analysis only.
    """
    adjacency = graph["adjacency"]
    slack_by_facility = slack_by_facility if slack_by_facility is not None else {
        facility.id: _compute_slack(snapshot, facility.id, sku_id) for facility in snapshot.facilities
    }
    facility_ids = list(slack_by_facility)

    # Initialize risk: knocked-out facility = 1.0, all others = baseline slack
    risk: Dict[str, float] = {}
    slack: Dict[str, float] = {}

    for fid in facility_ids:
        if fid == knocked_out_facility:
            risk[fid] = 1.0
            slack[fid] = 0.0
        else:
            s = slack_by_facility[fid]
            slack[fid] = s
            risk[fid] = max(0.0, 0.1 * (1.0 - s))  # slight base risk from low slack

    # Run graph diffusion for `days` steps
    for day in range(days):
        new_risk = dict(risk)
        for fid in facility_ids:
            if fid == knocked_out_facility:
                continue

            infection_pressure = 0.0
            for neighbour_id, distance, weight in adjacency.get(fid, []):
                if risk.get(neighbour_id, 0) > 0.3:
                    # Risk propagation weighted by distance and slack
                    infection_pressure += (
                        DOMINO_RISK_TRANSFER_RATE
                        * risk[neighbour_id]
                        * weight
                        * (1.0 - slack[fid])
                    )

            new_risk[fid] = min(1.0, risk[fid] + infection_pressure)
        risk = new_risk

    # Count facilities that transitioned to "at-risk" (risk > 0.4)
    cascaded = sum(
        1 for fid in facility_ids
        if fid != knocked_out_facility and risk[fid] >= RISK_THRESHOLD_AT_RISK
    )

    return cascaded


def _compute_betweenness(graph: Dict, facility_ids: List[str]) -> Dict[str, float]:
    """Normalized weighted Brandes centrality, including tied shortest paths."""
    from heapq import heappop, heappush

    nodes = set(facility_ids)
    centrality = dict.fromkeys(facility_ids, 0.0)
    for source in facility_ids:
        predecessors = {node: [] for node in facility_ids}
        counts = dict.fromkeys(facility_ids, 0.0)
        counts[source] = 1.0
        distances = dict.fromkeys(facility_ids, math.inf)
        distances[source] = 0.0
        queue, stack, settled = [(0.0, source)], [], set()
        while queue:
            distance, node = heappop(queue)
            if node in settled:
                continue
            settled.add(node)
            stack.append(node)
            for neighbor, edge_distance, _ in graph["adjacency"].get(node, []):
                if neighbor not in nodes:
                    continue
                candidate = distance + max(edge_distance, 0.001)
                if candidate < distances[neighbor] - 1e-9:
                    distances[neighbor] = candidate
                    counts[neighbor] = counts[node]
                    predecessors[neighbor] = [node]
                    heappush(queue, (candidate, neighbor))
                elif math.isclose(candidate, distances[neighbor], abs_tol=1e-9):
                    counts[neighbor] += counts[node]
                    predecessors[neighbor].append(node)
        dependency = dict.fromkeys(facility_ids, 0.0)
        while stack:
            node = stack.pop()
            for predecessor in predecessors[node]:
                dependency[predecessor] += counts[predecessor] / counts[node] * (1 + dependency[node])
            if node != source:
                centrality[node] += dependency[node]
    denominator = (len(nodes) - 1) * (len(nodes) - 2)
    return {node: round(value / denominator, 3) if denominator > 0 else 0.0
            for node, value in centrality.items()}


def _compute_isolation(
    graph: Dict, facility_id: str, facility_ids: List[str]
) -> float:
    """
    Isolation score: inverse of number of alternative sources within radius.
    High = few alternatives nearby.
    """
    coords = graph["coords"]
    if facility_id not in coords:
        return 1.0

    lat, lon = coords[facility_id]
    alternatives = 0
    for fid in facility_ids:
        if fid != facility_id and fid in coords:
            dist = _haversine_km(lat, lon, *coords[fid])
            if dist < DOMINO_NEIGHBOUR_RADIUS_KM:
                alternatives += 1

    if alternatives == 0:
        return 1.0
    return round(1.0 / (1.0 + alternatives), 3)


# ── Public API ───────────────────────────────────────────────────────────────
def run(
    snapshot: Snapshot,
    sku_id: str = "AMX500_CAP",
    *,
    scenario: Scenario | None = None,
) -> List[Dict]:
    """
    Main entry point. For every facility, computes:
    - Domino Index (cascade count)
    - Betweenness centrality
    - Isolation score
    - Dependency fan-out
    - Vulnerability rank
    - Risk narrative

    Returns list of DominoResult matching CONTRACTS.md.
    """
    logger.info(f"Computing Domino Index for SKU {sku_id}...")

    scenario = scenario or Scenario(
        id="DOMINO", snapshot_id=snapshot.id, fixture_id=None,
        name="Heuristic structural experiment", as_of=snapshot.as_of,
        seed=SCENARIO_SEED, assumptions=Assumptions(),
    )
    paths = generate_paths(snapshot, scenario, sku_id, count=1)
    graph = _build_graph(snapshot, paths.closed_route_ids)
    adjacency = graph["adjacency"]
    facility_ids = [fac.id for fac in snapshot.facilities]
    facility_names = {fac.id: fac.name for fac in snapshot.facilities}
    facility_types = {fac.id: fac.type for fac in snapshot.facilities}

    # Compute betweenness centrality
    betweenness = _compute_betweenness(graph, facility_ids)
    slack_by_facility = {}
    for facility_id, evidence in paths.evidence.items():
        if evidence["is_eligible"]:
            multiplier = next((override.multiplier for override in scenario.assumptions.demand_overrides
                               if override.facility_id == facility_id and override.sku_id == sku_id
                               and override.start_day == 0), 1.0)
            demand = evidence["mean_daily_requested_units"] * multiplier
            slack_by_facility[facility_id] = min(1.0, evidence["current_usable_units"] / (14 * demand)) if demand > 0 else 1.0

    results: List[Dict] = []
    for fac_id in facility_ids:
        # Cascade simulation (clean-room)
        domino_index = (_simulate_cascade(graph, snapshot, fac_id, sku_id, slack_by_facility=slack_by_facility)
                        if fac_id in slack_by_facility else None)

        # Dependency fan-out (direct neighbours)
        fan_out = len(adjacency.get(fac_id, []))

        # Isolation score
        isolation = _compute_isolation(graph, fac_id, facility_ids)

        # Risk narrative
        fac_name = facility_names[fac_id]
        fac_type = facility_types[fac_id]
        type_label = {"DH": "District Hospital", "CHC": "Community Health Centre",
                      "PHC": "Primary Health Centre", "SC": "Sub-Centre"}.get(fac_type, fac_type)

        if domino_index is None:
            severity = "unknown structural risk"
        elif domino_index >= 5:
            severity = "critical network hub"
        elif domino_index >= 3:
            severity = "significant dependency node"
        elif domino_index >= 1:
            severity = "moderate structural risk"
        else:
            severity = "low structural risk"

        narrative = (
            f"{fac_name} ({type_label}) is a {severity}. "
            f"Stockout here would cascade to {domino_index} dependent "
            f"{'facility' if domino_index == 1 else 'facilities'} within "
            f"{DOMINO_SIMULATION_DAYS} days"
        )

        if domino_index is None:
            narrative = f"{fac_name}: cascade estimate unavailable because stock or demand evidence is missing or stale."
        else:
            narrative = (f"Hypothetical stockout at {fac_name}: {domino_index} other facilities cross "
                         f"the graph-model threshold within {DOMINO_SIMULATION_DAYS} days. "
                         "This unvalidated experiment assumes influence along transfer links and shared-depot proximity.")

        results.append({
            "facility_id": fac_id,
            "domino_index": domino_index,
            "betweenness_centrality": betweenness.get(fac_id, 0.0),
            "isolation_score": isolation,
            "dependency_fan_out": fan_out,
            "vulnerability_rank": 0,  # Filled below after sorting
            "risk_narrative": narrative,
            "model_kind": "heuristic_graph",
        })

    # Assign vulnerability ranks (1 = most vulnerable)
    results.sort(key=lambda r: (
        r["domino_index"] is None,
        -(r["domino_index"] or 0),
        -r["betweenness_centrality"],
        -r["isolation_score"],
        r["facility_id"],
    ))
    for rank, result in enumerate(results, 1):
        result["vulnerability_rank"] = rank

    logger.info(f"Domino Index complete. Top facility: {results[0]['facility_id']} "
                f"(index={results[0]['domino_index']})" if results else "No facilities.")
    return results


def run_for_facility(
    snapshot: Snapshot,
    facility_id: str,
    sku_id: str = "AMX500_CAP",
) -> Optional[Dict]:
    """Single-facility Domino Index lookup."""
    all_results = run(snapshot, sku_id)
    for result in all_results:
        if result["facility_id"] == facility_id:
            return result
    return None
