"""
ShelfWatch Constrained Greedy Transfer Planner
==============================================
Donor-safe redistribution optimization with reserve constraints,
batch FEFO allocation, and multi-policy comparison.
Implements Section 8 of docs/IMPLEMENTATION_PLAN.md.
"""
from datetime import timedelta
from functools import cache
from math import ceil
from typing import Dict, List, Optional, Tuple
from uuid import NAMESPACE_URL, uuid5
import numpy as np

from app.config import ALGORITHM_VERSION, DISPLAY_DAYS, INTERNAL_DAYS, RESERVE_DAYS
from app.schemas import (
    BatchAllocation,
    Plan,
    PlanMetrics,
    RecommendationItem,
    Scenario,
    Snapshot,
    Transfer,
)
from app.services.forecast import planning_paths as make_planning_paths, subset_paths
from app.services.simulator import Paths, simulate


def _build_planning_paths(paths: Paths) -> Tuple[Paths, np.ndarray, np.ndarray]:
    """
    Constructs a single deterministic planning stress-case path from P80 demand and delays.
    Returns (planning_paths, planning_demand_2d, reserve_2d).
    """
    # 1. P80 demand across paths: shape (facility, day)
    if paths.days < INTERNAL_DAYS:
        raise ValueError("planning requires all 21 days for the forward reserve checks")
    planning_paths = make_planning_paths(paths)
    planning_demand_2d = planning_paths.demand[0]
    single_demand = planning_demand_2d[np.newaxis, :, :]  # (1, facility, day)

    # 2. P80 shipment arrival days
    single_shipments = {}
    for ship_id, arr_arr in paths.shipment_arrivals.items():
        arr_val = int(planning_paths.shipment_arrivals[ship_id][0])
        single_shipments[ship_id] = np.array([arr_val], dtype=np.int64)

    # 3. P80 depot lateness
    single_lateness = {}
    for dep_id, lat_arr in paths.depot_lateness.items():
        lat_val = int(planning_paths.depot_lateness[dep_id][0])
        single_lateness[dep_id] = np.array([lat_val], dtype=np.int64)

    planning_paths = Paths(
        sku_id=paths.sku_id,
        facility_ids=paths.facility_ids,
        demand=single_demand,
        shipment_arrivals=single_shipments,
        depot_lateness=single_lateness,
        evidence=paths.evidence,
        assumptions=paths.assumptions,
        closed_route_ids=paths.closed_route_ids,
    )

    # 4. Donor 7-day reserve after each day t (days t+1 to t+7)
    # Shape: (facility, DISPLAY_DAYS)
    facility_count, total_days = planning_demand_2d.shape
    reserve_2d = np.zeros((facility_count, DISPLAY_DAYS), dtype=np.int64)
    for fac_idx in range(facility_count):
        for day in range(DISPLAY_DAYS):
            end_day = min(day + RESERVE_DAYS + 1, total_days)
            reserve_2d[fac_idx, day] = planning_demand_2d[fac_idx, day + 1:end_day].sum()

    return planning_paths, planning_demand_2d, reserve_2d


def _check_donor_reserve(
    snapshot: Snapshot,
    planning_paths: Paths,
    reserve_2d: np.ndarray,
    donor_fac_id: str,
    tentative_transfers: List[Transfer]
) -> Tuple[bool, int, int]:
    """
    Simulates the planning stress-case with tentative_transfers and checks whether
    the donor's closing stock remains >= reserve on every day 0..DISPLAY_DAYS-1.
    Returns (is_valid, min_closing_stock, reserve_at_min_day).
    """
    donor_transfers = [item for item in tentative_transfers if item.from_facility_id == donor_fac_id]
    donor_facilities = {donor_fac_id, *(item.to_facility_id for item in donor_transfers)}
    donor_paths = subset_paths(planning_paths, donor_facilities)
    try:
        sim = simulate(snapshot, donor_paths, donor_transfers)
    except ValueError:
        return False, 0, 0

    donor_idx = planning_paths.facility_ids.index(donor_fac_id)
    donor_closing = sim.closing[0, donor_paths.facility_ids.index(donor_fac_id), :DISPLAY_DAYS]
    donor_reserves = reserve_2d[donor_idx, :DISPLAY_DAYS]

    deficit = donor_closing - donor_reserves
    min_day = int(np.argmin(deficit))
    min_stock = int(donor_closing[min_day])
    reserve_at_min = int(donor_reserves[min_day])

    is_valid = bool((deficit >= 0).all())
    return is_valid, min_stock, reserve_at_min


def _check_donor_harm_on_paths(
    snapshot: Snapshot,
    paths: Paths,
    baseline_unmet: np.ndarray,
    donor_fac_id: str,
    tentative_transfers: List[Transfer]
) -> int:
    """
    Checks if tentative_transfers causes additional unmet units at the donor on any sampled path.
    Returns count of paths with donor harm.
    """
    donor_transfers = [item for item in tentative_transfers if item.from_facility_id == donor_fac_id]
    donor_facilities = {donor_fac_id, *(item.to_facility_id for item in donor_transfers)}
    donor_paths = subset_paths(paths, donor_facilities)
    try:
        sim = simulate(snapshot, donor_paths, donor_transfers)
    except ValueError:
        return paths.count

    donor_idx = paths.facility_ids.index(donor_fac_id)
    # Cumulative unmet units through horizon
    donor_unmet = sim.unmet[:, donor_paths.facility_ids.index(donor_fac_id), :DISPLAY_DAYS].sum(axis=1)
    base_donor_unmet = baseline_unmet[:, donor_idx, :DISPLAY_DAYS].sum(axis=1)

    harm_paths = int((donor_unmet > base_donor_unmet).sum())
    return harm_paths


def _recipient_shortfall(snapshot: Snapshot, paths: Paths, recipient_id: str, transfers: List[Transfer]) -> int:
    """Evaluate only transfers into this recipient; other ledgers cannot affect it.

    Donor feasibility still checks every committed outgoing transfer separately.
    Donors and recipients are disjoint, so there is no forwarding dependency.
    """
    incoming = [transfer for transfer in transfers if transfer.to_facility_id == recipient_id]
    relevant = {recipient_id, *(transfer.from_facility_id for transfer in incoming)}
    recipient_paths = subset_paths(paths, relevant)
    result = simulate(snapshot, recipient_paths, incoming)
    index = recipient_paths.facility_ids.index(recipient_id)
    return int(result.unmet[0, index, :DISPLAY_DAYS].sum())


def build_plan(
    snapshot: Snapshot,
    scenario: Scenario,
    paths: Paths,
    policy: str = "shelfwatch"
) -> Plan:
    """
    Generates a donor-safe redistribution plan for a specific SKU.
    Supports policies: 'shelfwatch', 'nearest_donor', 'no_action'.
    """
    facility_ids = paths.facility_ids
    as_of_date = snapshot.as_of.date()
    sku_id = paths.sku_id
    if policy not in {"shelfwatch", "nearest_donor", "no_action"}:
        raise ValueError(f"unknown planning policy {policy}")
    identity = f"{ALGORITHM_VERSION}:{scenario.id}:{scenario.revision}:{sku_id}:{policy}"
    plan_id = f"PLAN-{uuid5(NAMESPACE_URL, identity).hex}"
    excluded = [facility_id for facility_id in facility_ids
                if not paths.evidence.get(facility_id, {}).get("is_eligible", True)]
    notes = ["Donor checks cover the complete plan and sampled paths, not a real-world safety guarantee."]
    if excluded:
        notes.append(f"Insufficient or stale evidence: excluded from planning and regional metrics: {', '.join(excluded)}.")

    # Baseline no-action simulation on sampled paths
    base_sim = simulate(snapshot, paths, [])
    base_metrics = base_sim.metrics(DISPLAY_DAYS)

    if policy == "no_action":
        return Plan(
            id=plan_id,
            scenario_id=scenario.id,
            scenario_revision=scenario.revision,
            sku_id=sku_id,
            policy="no_action",
            status="DRAFT",
            transfers=[],
            recommendations=[],
            metrics=PlanMetrics(
                expected_unmet_units=base_metrics["expected_unmet_units"],
                expected_facility_days=base_metrics["expected_facility_days"],
                expected_expiry_units=base_metrics["expected_expiry_units"],
                expected_additional_donor_unmet=0.0,
                transfer_units=0,
                transfer_distance=0.0,
                unmet_units_avoided=0.0,
            ),
            residual_deficit=ceil(base_metrics["expected_unmet_units"]),
            constraint_checks={"conservation_holds": True, "donor_reserves_respected": True, "zero_donor_harm_paths": True},
            notes=notes,
            excluded_facility_ids=excluded,
            modeled_facility_count=len(facility_ids) - len(excluded),
        )

    # 1. Build planning stress case (P80)
    planning_paths, planning_demand, reserve_2d = _build_planning_paths(paths)
    plan_sim = simulate(snapshot, planning_paths, [])
    plan_unmet = plan_sim.unmet[0, :, :DISPLAY_DAYS]  # (facility, day)

    # 2. Identify and rank recipients
    # A recipient has planning unmet units in the first 14 days
    recipients = []
    for idx, fac_id in enumerate(facility_ids):
        if fac_id in excluded:
            continue
        unmet_days = np.where(plan_unmet[idx] > 0)[0]
        if len(unmet_days) > 0:
            first_day = int(unmet_days[0])
            total_unmet = int(plan_unmet[idx].sum())
            recipients.append((fac_id, first_day, total_unmet))

    # Sort recipients: earliest shortfall day ASC, highest unmet DESC, fac_id ASC
    recipients.sort(key=lambda r: (r[1], -r[2], r[0]))

    # Map candidate routes and donor batches
    routes = {r.id: r for r in snapshot.routes if r.enabled and r.id not in paths.closed_route_ids and r.kind == "TRANSFER"}
    product = next(item for item in snapshot.products if item.sku_id == sku_id)
    if product.storage_class != "ROOM_TEMPERATURE":
        routes = {}
        notes.append("This SKU requires unsupported storage handling; no transfers proposed.")
    batches_by_fac: Dict[str, list] = {}
    for b in snapshot.batches:
        if b.sku_id == sku_id and b.expires_on >= as_of_date:
            batches_by_fac.setdefault(b.facility_id, []).append(b)

    # Track committed batch allocations across all transfers
    committed_batch: Dict[str, int] = {}
    committed_donor_transfers: List[Transfer] = []
    recommendation_items: List[RecommendationItem] = []

    # 3. Greedy allocation loop across recipients
    recipient_queue = list(recipients)
    while recipient_queue:
        to_fac_id, first_day, total_unmet = recipient_queue.pop(0)
        # Incoming eligible transfer routes
        incoming_routes = [r for r in routes.values() if r.to_id == to_fac_id]
        if not incoming_routes:
            continue

        # Donors cannot be recipients (disjoint sets)
        recipient_fac_ids = {r[0] for r in recipients}
        candidate_options = []

        for route in incoming_routes:
            from_fac_id = route.from_id
            if from_fac_id in recipient_fac_ids:
                continue  # Disjoint donor/recipient requirement

            # Check donor eligibility flags from paths evidence
            ev = paths.evidence.get(from_fac_id, {})
            if not ev.get("is_eligible", True):
                continue

            # Donor batches eligible for this route (expires >= arrival date)
            arrival_date = as_of_date + timedelta(days=route.transit_days)
            donor_batches = [
                b for b in batches_by_fac.get(from_fac_id, [])
                if b.expires_on >= arrival_date and (b.usable_units - committed_batch.get(b.batch_id, 0)) > 0
            ]
            if not donor_batches:
                continue

            # Sort donor batches FEFO
            donor_batches.sort(key=lambda b: (b.expires_on, b.batch_id))
            available_donor_units = sum(b.usable_units - committed_batch.get(b.batch_id, 0) for b in donor_batches)
            if available_donor_units <= 0:
                continue

            # Binary search for maximum permissible donation under reserve & harm constraints
            # Both searches revisit quantities within this unchanged route/commitment context.
            @cache
            def _test_donation(qty: int) -> Tuple[bool, Optional[Transfer], int, int]:
                if qty <= 0:
                    return True, None, 0, 0
                allocs = []
                rem = qty
                for b in donor_batches:
                    avail = b.usable_units - committed_batch.get(b.batch_id, 0)
                    alloc_qty = min(rem, avail)
                    if alloc_qty > 0:
                        allocs.append(BatchAllocation(batch_id=b.batch_id, quantity_units=alloc_qty))
                        rem -= alloc_qty
                    if rem <= 0:
                        break
                t = Transfer(
                    id=f"TR-{len(committed_donor_transfers) + 1:03d}",
                    from_facility_id=from_fac_id,
                    to_facility_id=to_fac_id,
                    sku_id=sku_id,
                    quantity_units=qty,
                    route_id=route.id,
                    dispatch_day=0,
                    arrival_day=route.transit_days,
                    batch_allocations=allocs,
                )
                test_list = committed_donor_transfers + [t]
                res_ok, min_s, res_at_min = _check_donor_reserve(snapshot, planning_paths, reserve_2d, from_fac_id, test_list)
                if not res_ok:
                    return False, None, min_s, res_at_min

                harm = _check_donor_harm_on_paths(snapshot, paths, base_sim.unmet, from_fac_id, test_list)
                if harm > 0:
                    return False, None, min_s, res_at_min

                return True, t, min_s, res_at_min

            # Binary search upper bound
            low, high = 1, available_donor_units
            best_max_qty = 0
            best_t = None
            best_min_s, best_res_at_min = 0, 0

            while low <= high:
                mid = (low + high) // 2
                ok, t, min_s, res_at_min = _test_donation(mid)
                if ok:
                    best_max_qty = mid
                    best_t = t
                    best_min_s = min_s
                    best_res_at_min = res_at_min
                    low = mid + 1
                else:
                    high = mid - 1

            if best_max_qty <= 0 or not best_t:
                continue

            # Calculate unmet units reduction on planning stress case
            rec_idx = planning_paths.facility_ids.index(to_fac_id)
            unmet_before = plan_unmet[rec_idx].sum()
            unmet_after = _recipient_shortfall(snapshot, planning_paths, to_fac_id, committed_donor_transfers + [best_t])
            reduction = int(unmet_before - unmet_after)

            if reduction <= 0:
                continue

            # Find smallest integer quantity that achieves maximum reduction
            q_low, q_high = 1, best_max_qty
            min_useful_qty = best_max_qty
            min_useful_t = best_t
            useful_min_s, useful_res_at_min = best_min_s, best_res_at_min

            while q_low <= q_high:
                q_mid = (q_low + q_high) // 2
                ok, t_mid, ms, ram = _test_donation(q_mid)
                if ok and t_mid:
                    mid_unmet = _recipient_shortfall(snapshot, planning_paths, to_fac_id, committed_donor_transfers + [t_mid])
                    mid_reduction = int(unmet_before - mid_unmet)
                    if mid_reduction == reduction:
                        min_useful_qty = q_mid
                        min_useful_t = t_mid
                        useful_min_s = ms
                        useful_res_at_min = ram
                        q_high = q_mid - 1
                    else:
                        q_low = q_mid + 1
                else:
                    q_low = q_mid + 1

            candidate_options.append({
                "route": route,
                "transfer": min_useful_t,
                "quantity": min_useful_qty,
                "reduction": reduction,
                "arrival_day": route.transit_days,
                "distance_km": route.distance_km,
                "donor_min_stock": useful_min_s,
                "donor_reserve": useful_res_at_min,
                "from_fac_id": from_fac_id,
            })

        if not candidate_options:
            continue

        # Rank candidates according to chosen policy
        if policy == "shelfwatch":
            # greatest reduction DESC, earlier arrival ASC, shorter distance ASC, donor ID ASC
            candidate_options.sort(key=lambda c: (-c["reduction"], c["arrival_day"], c["distance_km"], c["from_fac_id"]))
        elif policy == "nearest_donor":
            # shortest distance ASC, greatest reduction DESC, earlier arrival ASC, donor ID ASC
            candidate_options.sort(key=lambda c: (c["distance_km"], -c["reduction"], c["arrival_day"], c["from_fac_id"]))

        chosen = candidate_options[0]
        chosen_t = chosen["transfer"]

        # Commit transfer
        committed_donor_transfers.append(chosen_t)
        for alloc in chosen_t.batch_allocations:
            committed_batch[alloc.batch_id] = committed_batch.get(alloc.batch_id, 0) + alloc.quantity_units

        # Update planning unmet for recipient
        updated_sim = simulate(snapshot, planning_paths, committed_donor_transfers)
        plan_unmet = updated_sim.unmet[0, :, :DISPLAY_DAYS]

        rec_item = RecommendationItem(
            id=f"REC-{len(recommendation_items) + 1:03d}",
            from_facility_id=chosen_t.from_facility_id,
            to_facility_id=chosen_t.to_facility_id,
            sku_id=sku_id,
            quantity_units=chosen_t.quantity_units,
            route_id=chosen_t.route_id,
            dispatch_day=0,
            arrival_day=chosen_t.arrival_day,
            batch_allocations=chosen_t.batch_allocations,
            planning_unmet_units_avoided=chosen["reduction"],
            donor_minimum_planning_stock=chosen["donor_min_stock"],
            donor_reserve_at_minimum_day=chosen["donor_reserve"],
            sampled_donor_harm_paths=0,
            status="DRAFT",
        )
        recommendation_items.append(rec_item)
        # The recipient may need several donors. Preserve all commitments and
        # re-evaluate remaining candidates until none can reduce its shortfall.
        if plan_unmet[planning_paths.facility_ids.index(to_fac_id)].sum() > 0:
            recipient_queue.insert(0, (to_fac_id, first_day, total_unmet))

    # 4. Final multi-path evaluation of the committed plan
    final_sim = simulate(snapshot, paths, committed_donor_transfers)
    final_metrics = final_sim.metrics(DISPLAY_DAYS)
    total_transferred = sum(t.quantity_units for t in committed_donor_transfers)
    route_dict = {r.id: r for r in snapshot.routes}
    total_dist = round(sum(route_dict[t.route_id].distance_km for t in committed_donor_transfers), 1)
    unmet_avoided = round(float(base_metrics["expected_unmet_units"] - final_metrics["expected_unmet_units"]), 3)

    # Check additional donor unmet
    donor_ids = sorted({item.from_facility_id for item in committed_donor_transfers})
    donor_fac_indices = [facility_ids.index(facility_id) for facility_id in donor_ids]
    if donor_fac_indices:
        donor_final_unmet = final_sim.unmet[:, donor_fac_indices, :DISPLAY_DAYS].sum(axis=(1, 2)).mean()
        donor_base_unmet = base_sim.unmet[:, donor_fac_indices, :DISPLAY_DAYS].sum(axis=(1, 2)).mean()
        add_donor_unmet = round(float(max(0.0, donor_final_unmet - donor_base_unmet)), 3)
    else:
        add_donor_unmet = 0.0

    reserves_respected = True
    zero_harm_paths = True
    for donor_id in donor_ids:
        valid, minimum_stock, reserve = _check_donor_reserve(
            snapshot, planning_paths, reserve_2d, donor_id, committed_donor_transfers
        )
        harm_paths = _check_donor_harm_on_paths(
            snapshot, paths, base_sim.unmet, donor_id, committed_donor_transfers
        )
        reserves_respected = reserves_respected and valid
        zero_harm_paths = zero_harm_paths and harm_paths == 0
        for item in recommendation_items:
            if item.from_facility_id == donor_id:
                item.donor_minimum_planning_stock = minimum_stock
                item.donor_reserve_at_minimum_day = reserve
                item.sampled_donor_harm_paths = harm_paths
    if not reserves_respected or not zero_harm_paths:
        raise AssertionError("final plan failed its donor constraints")
    if final_metrics["expected_unmet_units"] > 0:
        notes.append("Residual unmet demand remains; additional replenishment is required.")
    return Plan(
        id=plan_id,
        scenario_id=scenario.id,
        scenario_revision=scenario.revision,
        sku_id=sku_id,
        policy=policy,
        status="DRAFT",
        transfers=committed_donor_transfers,
        recommendations=recommendation_items,
        metrics=PlanMetrics(
            expected_unmet_units=final_metrics["expected_unmet_units"],
            expected_facility_days=final_metrics["expected_facility_days"],
            expected_expiry_units=final_metrics["expected_expiry_units"],
            expected_additional_donor_unmet=add_donor_unmet,
            transfer_units=total_transferred,
            transfer_distance=total_dist,
            unmet_units_avoided=unmet_avoided,
        ),
        residual_deficit=ceil(final_metrics["expected_unmet_units"]),
        constraint_checks={
            "conservation_holds": True,
            "donor_reserves_respected": reserves_respected,
            "zero_donor_harm_paths": zero_harm_paths,
        },
        notes=notes,
        excluded_facility_ids=excluded,
        modeled_facility_count=len(facility_ids) - len(excluded),
    )


def compare_policies(
    snapshot: Snapshot,
    scenario: Scenario,
    paths: Paths
) -> Dict[str, Plan]:
    """Runs all three policies (no_action, nearest_donor, shelfwatch) on identical paths."""
    no_action_plan = build_plan(snapshot, scenario, paths, policy="no_action")
    nearest_donor_plan = build_plan(snapshot, scenario, paths, policy="nearest_donor")
    shelfwatch_plan = build_plan(snapshot, scenario, paths, policy="shelfwatch")
    return {
        "no_action": no_action_plan,
        "nearest_donor": nearest_donor_plan,
        "shelfwatch": shelfwatch_plan,
    }
