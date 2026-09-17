"""Independent accounting and exhaustive allocation checks for the audit."""
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from app.data.generator import fixture_assumptions, generate_snapshot
from app.schemas import BatchAllocation, DemandOverride, Scenario, Transfer
from app.services.forecast import generate_paths
from app.services.explanations import compute_facility_explanations
from app.services.planner import build_plan
from app.services.simulator import simulate


def context():
    snapshot = generate_snapshot("verified_delay")
    scenario = Scenario(
        id="SCEN-BOUNDARY", name="Boundary checks", snapshot_id=snapshot.id,
        fixture_id="verified_delay", as_of=snapshot.as_of, seed=42,
        assumptions=fixture_assumptions("verified_delay"),
    )
    return snapshot, scenario


def test_fefo_uses_earliest_expiry_before_later_stock():
    snapshot, scenario = context()
    original = next(batch for batch in snapshot.batches if batch.facility_id == "F-A")
    early = original.model_copy(update={"batch_id": "EARLY", "usable_units": 7,
                                        "expires_on": snapshot.as_of.date()})
    later = original.model_copy(update={"batch_id": "LATER", "usable_units": 5,
                                        "expires_on": snapshot.as_of.date() + timedelta(days=3)})
    snapshot.batches = [batch for batch in snapshot.batches if batch.facility_id != "F-A"] + [later, early]
    snapshot.shipments = []
    paths = generate_paths(snapshot, scenario, "AMX500_CAP", count=1)
    demand = np.zeros_like(paths.demand)
    index = paths.facility_ids.index("F-A")
    demand[0, index, :2] = [8, 5]
    result = simulate(snapshot, replace(paths, demand=demand), trace=True)
    served = [(item["batch_id"], item["units_by_path"]) for item in result.batch_trace
              if item["event"] == "fulfilled" and item["facility_id"] == "F-A" and item["day"] == 0]
    assert served == [("EARLY", [7]), ("LATER", [1])]
    assert result.fulfilled[0, index, :2].tolist() == [8, 4]
    assert result.unmet[0, index, :2].tolist() == [0, 1]
    assert result.expired[:, index, :].sum() == 0
    result.assert_conservation()


def test_stock_and_receipts_are_usable_on_expiry_date_only():
    snapshot, scenario = context()
    batch = next(item for item in snapshot.batches if item.facility_id == "F-A")
    batch.usable_units = 5
    batch.expires_on = snapshot.as_of.date()
    shipment = next(item for item in snapshot.shipments if item.facility_id == "F-A")
    shipment.quantity_units = 6
    shipment.expires_on = snapshot.as_of.date()
    paths = generate_paths(snapshot, scenario, "AMX500_CAP", count=1)
    demand = np.zeros_like(paths.demand)
    index = paths.facility_ids.index("F-A")
    demand[0, index, :2] = 8
    arrivals = {**paths.shipment_arrivals, shipment.id: np.array([0], dtype=np.int64)}
    result = simulate(snapshot, replace(paths, demand=demand, shipment_arrivals=arrivals))
    assert result.receipts[0, index, 0] == 6
    assert result.fulfilled[0, index, :2].tolist() == [8, 0]
    assert result.expired[0, index, 1] == 3
    assert result.unmet[0, index, :2].tolist() == [0, 8]
    result.assert_conservation()


@pytest.mark.parametrize("multiplier,arrival_day", [(1, 1), (2, 1), (1, 5), (2, 5)])
def test_planner_quantity_matches_exhaustive_feasible_search(multiplier, arrival_day):
    snapshot, scenario = context()
    scenario.assumptions.closed_route_ids = ["B_TO_C"]
    scenario.assumptions.demand_overrides = [DemandOverride(
        facility_id="F-A", sku_id="AMX500_CAP", multiplier=multiplier)]
    next(route for route in snapshot.routes if route.id == "B_TO_A").transit_days = arrival_day
    paths = generate_paths(snapshot, scenario, "AMX500_CAP", count=1)
    baseline = simulate(snapshot, paths)
    donor = paths.facility_ids.index("F-B")
    recipient = paths.facility_ids.index("F-A")
    reserve = np.array([paths.demand[0, donor, day + 1:day + 8].sum() for day in range(14)])
    stock = next(batch for batch in snapshot.batches if batch.facility_id == "F-B")
    best_benefit, minimum_quantity = 0, 0
    for quantity in range(1, stock.usable_units + 1):
        transfer = Transfer(
            id="ENUMERATED", from_facility_id="F-B", to_facility_id="F-A",
            sku_id=paths.sku_id, quantity_units=quantity, route_id="B_TO_A", arrival_day=arrival_day,
            batch_allocations=[BatchAllocation(batch_id=stock.batch_id, quantity_units=quantity)],
        )
        result = simulate(snapshot, paths, [transfer])
        if (result.closing[0, donor, :14] < reserve).any():
            continue
        if result.unmet[0, donor, :14].sum() > baseline.unmet[0, donor, :14].sum():
            continue
        benefit = int(baseline.unmet[0, recipient, :14].sum() - result.unmet[0, recipient, :14].sum())
        if benefit > best_benefit:
            best_benefit, minimum_quantity = benefit, quantity
    plan = build_plan(snapshot, scenario, paths)
    assert sum(item.quantity_units for item in plan.transfers) == minimum_quantity
    assert sum(item.planning_unmet_units_avoided for item in plan.recommendations) == best_benefit


def test_forecast_ignores_future_demand_and_delivery_records():
    snapshot, scenario = context()
    before = generate_paths(snapshot, scenario, "AMX500_CAP", count=30)
    row = snapshot.history[0].model_copy(update={
        "date": snapshot.as_of.date() + timedelta(days=1), "requested_units": 999_999,
    })
    delivery = snapshot.deliveries[0].model_copy(update={
        "actual_date": snapshot.as_of.date() + timedelta(days=100),
    })
    snapshot.history.append(row)
    snapshot.deliveries.append(delivery)
    after = generate_paths(snapshot, scenario, "AMX500_CAP", count=30)
    assert np.array_equal(before.demand, after.demand)
    assert all(np.array_equal(values, after.shipment_arrivals[key])
               for key, values in before.shipment_arrivals.items())


def test_receipt_beyond_last_simulated_day_is_not_promised_as_usable():
    snapshot, scenario = context()
    paths = generate_paths(snapshot, scenario, "AMX500_CAP", count=1)
    shipment = next(item for item in snapshot.shipments if item.facility_id == "F-A")
    paths = replace(paths, shipment_arrivals={**paths.shipment_arrivals,
                                              shipment.id: np.array([paths.days], dtype=np.int64)})
    result = simulate(snapshot, paths)
    explanation = compute_facility_explanations(snapshot, scenario, paths, result, "F-A")
    assert any(factor["code"] == "receipt_not_usable" for factor in explanation["all_factors"])
    assert not any(factor["code"] == "projected_delivery_delay" for factor in explanation["all_factors"])
