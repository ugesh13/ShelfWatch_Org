"""
ShelfWatch Section 12 Verified Numerical Demo Test Suite
========================================================
Validates all deterministic accounting, conservation, donor protection,
and Domino counterfactual experiments specified in Section 12 of docs/IMPLEMENTATION_PLAN.md.
"""
import pytest
import numpy as np

from app.data.generator import generate_snapshot, fixture_assumptions
from app.schemas import Assumptions, DemandOverride, DepotDelay, Scenario, Transfer, BatchAllocation
from app.services.forecast import generate_paths
from app.services.impact import compute_depot_impact
from app.services.planner import build_plan
from app.services.simulator import simulate, validate_transfers


def test_verified_delay_baseline():
    """
    Inputs:
      - Facility A: 60 opening, 20 daily, 240 arrival on day 8 from Depot North
      - Facility B: 500 opening, 25 daily, 250 arrival on day 5 from Depot South
      - Facility C: 120 opening, 20 daily, 240 arrival on day 8 from Depot North
    Expected No Action:
      - A unmet = 100 units
      - C unmet = 40 units
      - B unmet = 0 units
      - Total unmet = 140 units, 7 facility-days
    """
    snap = generate_snapshot("verified_delay")
    assumptions = fixture_assumptions("verified_delay")
    scenario = Scenario(
        id="SCEN-TEST-1",
        name="Verified Delay Test",
        fixture_id="verified_delay",
        snapshot_id=snap.id,
        as_of=snap.as_of,
        seed=42,
        assumptions=assumptions,
    )
    paths = generate_paths(snap, scenario, "AMX500_CAP", count=1)
    sim = simulate(snap, paths)

    metrics = sim.metrics(14)
    assert metrics["expected_unmet_units"] == 140.0
    assert metrics["expected_facility_days"] == 7.0

    idx_a = paths.facility_ids.index("F-A")
    idx_b = paths.facility_ids.index("F-B")
    idx_c = paths.facility_ids.index("F-C")

    assert sim.unmet[0, idx_a, :14].sum() == 100
    assert sim.unmet[0, idx_b, :14].sum() == 0
    assert sim.unmet[0, idx_c, :14].sum() == 40


def test_verified_shelfwatch_plan():
    """
    Expected ShelfWatch Plan:
      - Transfer 100 units from B to A (day 1 arrival)
      - Transfer 40 units from B to C (day 1 arrival)
      - Post-plan unmet units across all facilities = 0
      - B minimum daily closing stock = 235 (above 175 reserve)
    """
    snap = generate_snapshot("verified_delay")
    assumptions = fixture_assumptions("verified_delay")
    scenario = Scenario(
        id="SCEN-TEST-2",
        name="Verified Plan Test",
        fixture_id="verified_delay",
        snapshot_id=snap.id,
        as_of=snap.as_of,
        seed=42,
        assumptions=assumptions,
    )
    paths = generate_paths(snap, scenario, "AMX500_CAP", count=1)
    plan = build_plan(snap, scenario, paths, policy="shelfwatch")

    assert len(plan.transfers) == 2
    t_a = next(t for t in plan.transfers if t.to_facility_id == "F-A")
    t_c = next(t for t in plan.transfers if t.to_facility_id == "F-C")

    assert t_a.from_facility_id == "F-B"
    assert t_a.quantity_units == 100
    assert t_c.from_facility_id == "F-B"
    assert t_c.quantity_units == 40

    assert plan.metrics.expected_unmet_units == 0.0
    assert plan.metrics.expected_facility_days == 0.0
    assert plan.metrics.transfer_units == 140

    # Simulate plan and check B's closing stock curve
    sim = simulate(snap, paths, plan.transfers)
    idx_b = paths.facility_ids.index("F-B")
    b_closing = sim.closing[0, idx_b, :14]

    # Day 4 closing stock before day 5 delivery must be exactly 235
    assert b_closing[4] == 235
    # Every day closing stock must be >= 175
    assert (b_closing >= 175).all()


def test_b_maximum_donation_and_201_failure():
    """
    The largest total donation B can make under this fixture's reserve constraints is 200 units:
    its day-4 closing stock becomes exactly 175.
    A donation of 201 leaves 174 and must fail the reserve constraint.
    """
    snap = generate_snapshot("verified_delay")
    assumptions = fixture_assumptions("verified_delay")
    scenario = Scenario(
        id="SCEN-TEST-3",
        name="Donation Limit Test",
        fixture_id="verified_delay",
        snapshot_id=snap.id,
        as_of=snap.as_of,
        seed=42,
        assumptions=assumptions,
    )
    paths = generate_paths(snap, scenario, "AMX500_CAP", count=1)

    # 200 unit donation
    t_200 = Transfer(
        id="T-200",
        from_facility_id="F-B",
        to_facility_id="F-A",
        sku_id="AMX500_CAP",
        quantity_units=200,
        route_id="B_TO_A",
        dispatch_day=0,
        arrival_day=1,
        batch_allocations=[BatchAllocation(batch_id="F-B-AMX-01", quantity_units=200)],
    )
    sim_200 = simulate(snap, paths, [t_200])
    idx_b = paths.facility_ids.index("F-B")
    # Day 4 closing stock is exactly 175
    assert sim_200.closing[0, idx_b, 4] == 175

    # 201 unit donation
    t_201 = Transfer(
        id="T-201",
        from_facility_id="F-B",
        to_facility_id="F-A",
        sku_id="AMX500_CAP",
        quantity_units=201,
        route_id="B_TO_A",
        dispatch_day=0,
        arrival_day=1,
        batch_allocations=[BatchAllocation(batch_id="F-B-AMX-01", quantity_units=201)],
    )
    sim_201 = simulate(snap, paths, [t_201])
    # Day 4 closing stock leaves 174 < 175 (fails reserve check)
    assert sim_201.closing[0, idx_b, 4] == 174


def test_stress_double_a_demand():
    """
    Double A's demand to 40 units/day:
    No action leaves 300 units unmet across A and C.
    B's donation limit is 200.
    Allocating 200 to earliest-shortfall recipient A leaves 100 units unmet.
    The plan must report the unresolved residual deficit.
    """
    snap = generate_snapshot("verified_delay")
    assumptions = Assumptions(
        depot_delays=[DepotDelay(depot_id="DEPOT-N", extra_days=6)],
        demand_overrides=[DemandOverride(facility_id="F-A", sku_id="AMX500_CAP", multiplier=2.0)],
    )
    scenario = Scenario(
        id="SCEN-TEST-4",
        name="Double Demand Test",
        fixture_id="verified_delay",
        snapshot_id=snap.id,
        as_of=snap.as_of,
        seed=42,
        assumptions=assumptions,
    )
    paths = generate_paths(snap, scenario, "AMX500_CAP", count=1)
    base_sim = simulate(snap, paths)
    assert base_sim.unmet[0, :, :14].sum() == 300

    plan = build_plan(snap, scenario, paths, policy="shelfwatch")
    assert plan.metrics.expected_unmet_units == 100.0
    assert plan.metrics.transfer_units == 200
    assert plan.residual_deficit == 100


def test_stress_close_b_to_a():
    """
    Close route B->A:
    B->C can still transfer 40 units.
    A retains 100 unmet units.
    Plan must not draw a fictional route to A.
    """
    snap = generate_snapshot("verified_delay")
    assumptions = Assumptions(
        depot_delays=[DepotDelay(depot_id="DEPOT-N", extra_days=6)],
        closed_route_ids=["B_TO_A"],
    )
    scenario = Scenario(
        id="SCEN-TEST-5",
        name="Closed Route Test",
        fixture_id="verified_delay",
        snapshot_id=snap.id,
        as_of=snap.as_of,
        seed=42,
        assumptions=assumptions,
    )
    paths = generate_paths(snap, scenario, "AMX500_CAP", count=1)
    plan = build_plan(snap, scenario, paths, policy="shelfwatch")

    assert len(plan.transfers) == 1
    assert plan.transfers[0].to_facility_id == "F-C"
    assert plan.transfers[0].quantity_units == 40
    assert plan.metrics.expected_unmet_units == 100.0


def test_domino_impact_experiment():
    """
    Domino demonstration from restored baseline:
    Add standard 7-day disruption to Depot North.
    Within first 7 days: A has 80 unmet, C has 20 unmet.
    Report 2 additional affected facilities and 100 additional unmet units.
    """
    snap = generate_snapshot("verified_normal")
    assumptions = fixture_assumptions("verified_normal")
    scenario = Scenario(
        id="SCEN-TEST-6",
        name="Domino Test",
        fixture_id="verified_normal",
        snapshot_id=snap.id,
        as_of=snap.as_of,
        seed=42,
        assumptions=assumptions,
    )
    results = compute_depot_impact(snap, scenario, "AMX500_CAP", extra_days=7, horizon=7)

    depot_n = next(r for r in results if r["depot_id"] == "DEPOT-N")
    assert depot_n["additional_affected_facilities_mean"] == 2.0
    assert depot_n["additional_unmet_units_mean"] == 100.0
    assert set(depot_n["newly_affected_facility_ids"]) == {"F-A", "F-C"}

    depot_s = next(r for r in results if r["depot_id"] == "DEPOT-S")
    assert depot_s["additional_affected_facilities_mean"] == 0.0
    assert depot_s["additional_unmet_units_mean"] == 0.0
