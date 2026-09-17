"""
ShelfWatch Domino Impact Service
================================
Paired counterfactual experiments: measures systemic vulnerability by
simulating extra delays at shared supply depots and measuring secondary facility fallout.
Implements Section 7 of docs/IMPLEMENTATION_PLAN.md.
"""
from dataclasses import replace
from typing import Dict, List, Any
import numpy as np

from app.schemas import Scenario, Snapshot
from app.services.forecast import generate_paths
from app.services.simulator import Paths, simulate


def compute_depot_impact(
    snapshot: Snapshot,
    scenario: Scenario,
    sku_id: str,
    *,
    extra_days: int = 7,
    horizon: int = 7
) -> List[Dict[str, Any]]:
    """
    For each depot:
    1. Runs baseline scenario (without additional disruption).
    2. Simulates counterfactual run where all shipments from this depot are delayed by extra_days.
    3. Calculates additional affected facilities and additional unmet units over horizon (default 7 days).
    4. Ranks depots by additional unmet units DESC, then facility count DESC.
    """
    if not 1 <= horizon <= 14 or extra_days < 0:
        raise ValueError("impact requires a 1–14 day horizon and non-negative extra delay")
    # 1. Baseline simulation
    base_paths = generate_paths(snapshot, scenario, sku_id)
    base_sim = simulate(snapshot, base_paths)
    included = np.array([base_paths.evidence[facility_id]["is_eligible"]
                         for facility_id in base_paths.facility_ids])
    excluded = [facility_id for facility_id, valid in zip(base_paths.facility_ids, included) if not valid]
    base_unmet = base_sim.unmet[:, :, :horizon].copy()
    base_unmet[:, ~included, :] = 0

    # Facilities that had any unmet demand in baseline on each path: (path, facility) bool
    base_fac_has_unmet = (base_unmet.sum(axis=2) > 0)
    base_total_unmet_per_path = base_unmet.sum(axis=(1, 2))

    facility_ids = base_paths.facility_ids
    depot_dict = {d.id: d for d in snapshot.depots}

    results = []

    # 2. Counterfactual test for each depot
    for depot_id, depot in depot_dict.items():
        # Check if depot supplies any shipments for this SKU
        depot_shipments = [
            s for s in snapshot.shipments
            if s.depot_id == depot_id and s.sku_id == sku_id and s.status == "PENDING"
        ]
        if not depot_shipments:
            results.append({
                "depot_id": depot_id,
                "depot_name": depot.name,
                "additional_affected_facilities_mean": 0.0,
                "additional_affected_facilities_p10": 0.0,
                "additional_affected_facilities_p50": 0.0,
                "additional_affected_facilities_p90": 0.0,
                "additional_unmet_units_mean": 0.0,
                "additional_unmet_units_p10": 0.0,
                "additional_unmet_units_p50": 0.0,
                "additional_unmet_units_p90": 0.0,
                "newly_affected_facility_ids": [],
                "tested_extra_days": extra_days,
                "horizon_days": horizon,
                "excluded_facility_ids": excluded,
                "modeled_facility_count": int(included.sum()),
            })
            continue

        # Perturb the paired arrivals directly. The extra experiment is not a
        # user scenario edit, and may extend beyond its 14-day slider limit.
        shipment_ids = {shipment.id for shipment in depot_shipments}
        disrupted_paths = replace(base_paths, shipment_arrivals={
            shipment_id: arrivals + (extra_days if shipment_id in shipment_ids else 0)
            for shipment_id, arrivals in base_paths.shipment_arrivals.items()
        })
        disrupted_sim = simulate(snapshot, disrupted_paths)
        disrupted_unmet = disrupted_sim.unmet[:, :, :horizon].copy()
        disrupted_unmet[:, ~included, :] = 0

        # Facilities with unmet demand in disrupted run
        disrupted_fac_has_unmet = (disrupted_unmet.sum(axis=2) > 0)  # (path, facility)

        # Newly affected facilities: has unmet in disrupted BUT NOT in baseline
        newly_affected_mask = disrupted_fac_has_unmet & (~base_fac_has_unmet)  # (path, facility)
        additional_fac_count_per_path = newly_affected_mask.sum(axis=1)  # (path,)

        # Additional unmet units
        disrupted_total_unmet_per_path = disrupted_unmet.sum(axis=(1, 2))
        additional_unmet_units_per_path = np.maximum(0, disrupted_total_unmet_per_path - base_total_unmet_per_path)

        # Include every facility newly affected on at least one paired path.
        fac_appearance_freq = newly_affected_mask.mean(axis=0)
        affected_fac_ids = [
            facility_ids[i] for i in range(len(facility_ids)) if fac_appearance_freq[i] > 0
        ]

        mean_fac_count = round(float(additional_fac_count_per_path.mean()), 2)
        p10_fac_count = round(float(np.quantile(additional_fac_count_per_path, 0.10)), 1)
        p50_fac_count = round(float(np.quantile(additional_fac_count_per_path, 0.50)), 1)
        p90_fac_count = round(float(np.quantile(additional_fac_count_per_path, 0.90)), 1)

        mean_unmet = round(float(additional_unmet_units_per_path.mean()), 1)
        p10_unmet = round(float(np.quantile(additional_unmet_units_per_path, 0.10)), 1)
        p50_unmet = round(float(np.quantile(additional_unmet_units_per_path, 0.50)), 1)
        p90_unmet = round(float(np.quantile(additional_unmet_units_per_path, 0.90)), 1)

        results.append({
            "depot_id": depot_id,
            "depot_name": depot.name,
            "additional_affected_facilities_mean": mean_fac_count,
            "additional_affected_facilities_p10": p10_fac_count,
            "additional_affected_facilities_p50": p50_fac_count,
            "additional_affected_facilities_p90": p90_fac_count,
            "additional_unmet_units_mean": mean_unmet,
            "additional_unmet_units_p10": p10_unmet,
            "additional_unmet_units_p50": p50_unmet,
            "additional_unmet_units_p90": p90_unmet,
            "newly_affected_facility_ids": affected_fac_ids,
            "tested_extra_days": extra_days,
            "horizon_days": horizon,
            "excluded_facility_ids": excluded,
            "modeled_facility_count": int(included.sum()),
        })

    # Rank by mean additional unmet units DESC, then additional facilities DESC, then depot ID ASC
    results.sort(key=lambda r: (-r["additional_unmet_units_mean"], -r["additional_affected_facilities_mean"], r["depot_id"]))
    return results
