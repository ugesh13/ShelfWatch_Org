"""Regression cases for accounting, uncertainty, scenario isolation, and reviews."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.data.generator import fixture_assumptions, generate_snapshot
from app.database import Repository
from app.schemas import Assumptions, DepotDelay, ReviewRequest, Scenario, ScenarioCreate, ScenarioPatch
from app.services.anomaly_detector import run as detect_anomalies
from app.services.explanations import compute_facility_explanations
from app.services.forecast import generate_paths
from app.services.impact import compute_depot_impact
from app.services.planner import build_plan, compare_policies
from app.services.simulator import simulate
from app.services.diffusion_model import run as diffuse, run_what_if
from app.services.domino_index import _compute_betweenness


def make_scenario(snapshot, fixture_id="verified_delay", assumptions=None):
    return Scenario(
        id="SCEN-AUDIT", name="Audit regression", snapshot_id=snapshot.id,
        fixture_id=fixture_id, as_of=snapshot.as_of, seed=42,
        assumptions=assumptions if assumptions is not None else fixture_assumptions(fixture_id),
    )


@pytest.fixture
def audit_client(monkeypatch):
    import app.main as api_module

    repository = Repository()
    monkeypatch.setattr(api_module, "repo", repository)
    with TestClient(api_module.app, raise_server_exceptions=False) as client:
        yield client, repository


def test_impact_accepts_maximum_valid_scenario_delay():
    snapshot = generate_snapshot("verified_delay")
    scenario = make_scenario(snapshot, assumptions=Assumptions(
        depot_delays=[DepotDelay(depot_id="DEPOT-N", extra_days=14)]
    ))
    results = compute_depot_impact(snapshot, scenario, "AMX500_CAP")
    assert len(results) == 2
    assert scenario.assumptions.depot_delays[0].extra_days == 14


def test_planner_combines_multiple_donors_for_one_recipient():
    snapshot = generate_snapshot("verified_delay").model_copy(deep=True)
    next(batch for batch in snapshot.batches if batch.facility_id == "F-B").usable_units = 450
    next(batch for batch in snapshot.batches if batch.facility_id == "F-C").usable_units = 390
    next(facility for facility in snapshot.facilities if facility.id == "F-C").depot_id = "DEPOT-S"
    next(route for route in snapshot.routes if route.id == "SUP-F-C").from_id = "DEPOT-S"
    shipment = next(item for item in snapshot.shipments if item.facility_id == "F-C")
    shipment.depot_id = "DEPOT-S"
    shipment.promised_arrival_day = 5
    shipment.current_eta_day = 5
    shipment.quantity_units = 250
    template = next(route for route in snapshot.routes if route.id == "B_TO_A")
    snapshot.routes.append(template.model_copy(update={"id": "C_TO_A", "from_id": "F-C"}))
    assumptions = fixture_assumptions("verified_delay").model_dump()
    assumptions["demand_overrides"] = [{"facility_id": "F-A", "sku_id": "AMX500_CAP", "multiplier": 2.0}]
    scenario = make_scenario(snapshot, assumptions=Assumptions.model_validate(assumptions))
    paths = generate_paths(snapshot, scenario, "AMX500_CAP", count=1)
    plan = build_plan(snapshot, scenario, paths)
    assert {item.from_facility_id for item in plan.transfers} == {"F-B", "F-C"}
    assert plan.metrics.expected_unmet_units == 0
    assert plan.metrics.transfer_units == 260
    simulate(snapshot, paths, plan.transfers).assert_conservation()


def test_recommendation_reserve_describes_the_complete_plan():
    snapshot = generate_snapshot("verified_delay")
    scenario = make_scenario(snapshot)
    plan = build_plan(snapshot, scenario, generate_paths(snapshot, scenario, "AMX500_CAP", count=1))
    assert len(plan.recommendations) == 2
    assert all(item.donor_minimum_planning_stock == 235 for item in plan.recommendations)
    assert all(item.donor_reserve_at_minimum_day == 175 for item in plan.recommendations)


def test_no_action_residual_uses_the_displayed_horizon():
    snapshot = generate_snapshot("verified_delay")
    scenario = make_scenario(snapshot)
    paths = generate_paths(snapshot, scenario, "AMX500_CAP", count=1)
    plan = build_plan(snapshot, scenario, paths, policy="no_action")
    assert plan.residual_deficit == plan.metrics.expected_unmet_units == 140


def test_plan_ids_are_distinct_for_each_sku():
    snapshot = generate_snapshot("healthy_supply")
    scenario = make_scenario(snapshot, "healthy_supply")
    ids = [build_plan(snapshot, scenario, generate_paths(snapshot, scenario, sku, count=1),
                      policy="no_action").id for sku in ("AMX500_CAP", "PCM500_TAB")]
    assert len(set(ids)) == 2


def test_unknown_demand_is_not_reported_as_zero_probability():
    snapshot = generate_snapshot("incomplete_records")
    scenario = make_scenario(snapshot, "incomplete_records")
    paths = generate_paths(snapshot, scenario, "AMX500_CAP", count=5)
    detail = compute_facility_explanations(snapshot, scenario, paths, simulate(snapshot, paths), "F-01")
    assert detail["risk_state"] == "Unknown"
    assert detail["shortage_probability_14d"] is None
    assert detail["shortage_probability_7d"] is None
    assert detail["expected_unmet_units_14d"] is None


def test_shortfall_quantiles_never_interpolate_censored_paths():
    snapshot = generate_snapshot("verified_normal")
    scenario = make_scenario(snapshot, "verified_normal")
    paths = generate_paths(snapshot, scenario, "AMX500_CAP", count=10)
    demand = paths.demand.copy()
    index = paths.facility_ids.index("F-A")
    demand[:, index, :] = 0
    demand[:9, index, 1] = 100
    paths = replace(paths, demand=demand)
    detail = compute_facility_explanations(snapshot, scenario, paths, simulate(snapshot, paths), "F-A")
    assert detail["first_shortfall_day_p10"] == 1
    assert detail["first_shortfall_day_p50"] == 1
    assert detail["first_shortfall_day_p90"] is None


def test_anomaly_detector_uses_current_batches_not_yesterdays_stock():
    snapshot = generate_snapshot("verified_normal").model_copy(deep=True)
    next(batch for batch in snapshot.batches if batch.facility_id == "F-A").usable_units = 0
    result = next(item for item in detect_anomalies(snapshot) if item["facility_id"] == "F-A")
    assert result["risk_level"] == "STOCKOUT"
    assert result["days_of_stock"] == 0


@pytest.mark.parametrize("change", ["empty_paths", "duplicate_facilities", "unknown_facility", "fractional_arrival"])
def test_simulator_rejects_invalid_path_inputs(change):
    snapshot = generate_snapshot("verified_delay")
    scenario = make_scenario(snapshot)
    paths = generate_paths(snapshot, scenario, "AMX500_CAP", count=1)
    if change == "empty_paths":
        paths = replace(paths, demand=paths.demand[:0])
    elif change == "duplicate_facilities":
        paths = replace(paths, facility_ids=("F-A", "F-A", "F-C"))
    elif change == "unknown_facility":
        paths = replace(paths, facility_ids=("F-A", "F-B", "MISSING"))
    else:
        arrivals = dict(paths.shipment_arrivals)
        arrivals["SHIP-F-A"] = np.array([2.5])
        paths = replace(paths, shipment_arrivals=arrivals)
    with pytest.raises(ValueError):
        simulate(snapshot, paths)


@pytest.mark.parametrize("endpoint", ["run", "impact", "plans", "risk-scores", "fingerprints", "domino-index", "diffusion", "analytics"])
def test_unknown_sku_is_a_validation_error(audit_client, endpoint):
    client, _ = audit_client
    scenario = client.post("/api/scenarios", json={"fixture_id": "verified_delay"}).json()["data"]
    response = client.post(f"/api/scenarios/{scenario['id']}/{endpoint}",
                           json={"expected_revision": 1, "sku_id": "MISSING"})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("field,value", [
    ("demand_overrides", [{"facility_id": "MISSING", "sku_id": "AMX500_CAP", "multiplier": 2}]),
    ("depot_delays", [{"depot_id": "MISSING", "extra_days": 7}]),
    ("closed_route_ids", ["MISSING"]),
])
def test_unknown_assumption_targets_do_not_create_a_revision(audit_client, field, value):
    client, _ = audit_client
    scenario = client.post("/api/scenarios", json={"fixture_id": "verified_delay"}).json()["data"]
    response = client.patch(f"/api/scenarios/{scenario['id']}",
                            json={"expected_revision": 1, field: value})
    assert response.status_code == 422, response.text
    assert client.get(f"/api/scenarios/{scenario['id']}").json()["data"]["scenario"]["revision"] == 1


def test_explicit_empty_assumptions_override_fixture_defaults():
    repository = Repository()
    scenario = repository.create_scenario(ScenarioCreate(fixture_id="verified_delay", depot_delays=[]))
    assert scenario.assumptions.depot_delays == []


def test_repository_returns_immutable_revision_copies():
    repository = Repository()
    scenario = repository.create_scenario(ScenarioCreate(fixture_id="verified_delay"))
    returned = repository.get_scenario(scenario.id)
    returned.assumptions.depot_delays.clear()
    assert repository.get_scenario(scenario.id).assumptions.depot_delays
    snapshot = repository.get_snapshot(scenario.snapshot_id)
    snapshot.batches[0].usable_units = 0
    assert repository.get_snapshot(scenario.snapshot_id).batches[0].usable_units == 60


def test_plan_regeneration_preserves_review_and_recommendation_status(audit_client):
    client, _ = audit_client
    scenario = client.post("/api/scenarios", json={"fixture_id": "verified_delay"}).json()["data"]
    url = f"/api/scenarios/{scenario['id']}/plans"
    body = {"expected_revision": 1, "sku_id": "AMX500_CAP"}
    plan = client.post(url, json=body).json()["data"]["selected_plan"]
    approved = client.post(f"/api/plans/{plan['id']}/review", json={"expected_revision": 1, "action": "APPROVE"})
    assert approved.status_code == 200
    regenerated = client.post(url, json=body).json()["data"]["selected_plan"]
    assert regenerated["status"] == "APPROVED"
    assert all(item["status"] == "APPROVED" for item in regenerated["recommendations"])


def test_selecting_a_different_plan_leaves_only_one_approved_proposal():
    repository = Repository()
    scenario = repository.create_scenario(ScenarioCreate(fixture_id="verified_delay"))
    snapshot = repository.get_snapshot(scenario.snapshot_id)
    plans = compare_policies(snapshot, scenario, generate_paths(snapshot, scenario, "AMX500_CAP", count=1))
    for plan in plans.values():
        repository.save_plan(plan)
    request = ReviewRequest(expected_revision=1, action="APPROVE")
    repository.review_plan(plans["shelfwatch"].id, request)
    repository.review_plan(plans["nearest_donor"].id, request)
    assert repository.get_plan(plans["shelfwatch"].id).status == "DRAFT"
    assert repository.get_plan(plans["nearest_donor"].id).status == "APPROVED"


def test_scenarios_and_reviews_survive_repository_restart(tmp_path):
    database_path = tmp_path / "audit.db"
    repository = Repository(database_path)
    scenario = repository.create_scenario(ScenarioCreate(fixture_id="verified_delay"))
    snapshot = repository.get_snapshot(scenario.snapshot_id)
    plan = build_plan(snapshot, scenario, generate_paths(snapshot, scenario, "AMX500_CAP", count=1))
    repository.save_plan(plan)
    repository.review_plan(plan.id, ReviewRequest(expected_revision=1, action="APPROVE"))
    restored = Repository(database_path)
    assert restored.get_scenario(scenario.id) == scenario
    assert restored.get_plan(plan.id).status == "APPROVED"
    assert restored.get_snapshot(scenario.snapshot_id) == snapshot


def test_revision_compare_and_swap_is_atomic_across_connections(tmp_path):
    database_path = tmp_path / "concurrent.db"
    first = Repository(database_path)
    second = Repository(database_path)
    scenario = first.create_scenario(ScenarioCreate(fixture_id="verified_normal"))

    def patch(repository):
        try:
            return repository.patch_scenario(scenario.id, ScenarioPatch(expected_revision=1)).revision
        except ValueError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(patch, [first, second]))
    assert sorted(results, key=str) == [2, "conflict"]


def test_anomaly_detects_requested_demand_even_when_fulfillment_is_capped():
    snapshot = generate_snapshot("verified_normal").model_copy(deep=True)
    for row in snapshot.history:
        if row.facility_id == "F-A" and row.date >= snapshot.as_of.date() - timedelta(days=7):
            row.requested_units = 80
    result = next(item for item in detect_anomalies(snapshot) if item["facility_id"] == "F-A")
    assert result["z_score"] > 2
    assert "consumption_velocity_spike" in result["flag_reasons"]


def test_anomaly_reports_missing_demand_as_unknown():
    snapshot = generate_snapshot("incomplete_records")
    result = next(item for item in detect_anomalies(snapshot) if item["facility_id"] == "F-01")
    assert result["risk_level"] == "UNKNOWN"
    assert result["local_risk_score"] is None


def test_diffusion_timeline_includes_its_final_projection_day():
    snapshot = generate_snapshot("verified_normal")
    result = diffuse(snapshot, detect_anomalies(snapshot), days_forward=7)
    assert result["timeline"][-1]["day"] == 7
    assert len(result["timeline"]) == len(result["facility_projections"]["F-A"]["risk_trajectory"])


def test_diffusion_does_not_recover_from_a_closed_supply_route():
    snapshot = generate_snapshot("verified_normal")
    anomalies = detect_anomalies(snapshot)
    open_result = run_what_if(snapshot, anomalies, days_forward=7)
    closed_result = run_what_if(snapshot, anomalies, closed_routes=["SUP-F-A"], days_forward=7)
    assert closed_result["facility_projections"]["F-A"]["risk_trajectory"] != open_result["facility_projections"]["F-A"]["risk_trajectory"]


def test_diffusion_applies_extra_delivery_delay():
    snapshot = generate_snapshot("verified_normal")
    anomalies = detect_anomalies(snapshot)
    normal = run_what_if(snapshot, anomalies, days_forward=7)
    delayed = run_what_if(snapshot, anomalies, extra_delay_days=7, days_forward=7)
    assert delayed["facility_projections"]["F-A"]["risk_trajectory"] != normal["facility_projections"]["F-A"]["risk_trajectory"]


def test_betweenness_counts_all_equal_shortest_paths():
    graph = {"adjacency": {
        "A": [("B", 1, 1), ("D", 1, 1)],
        "B": [("A", 1, 1), ("C", 1, 1)],
        "C": [("B", 1, 1), ("D", 1, 1)],
        "D": [("A", 1, 1), ("C", 1, 1)],
    }}
    results = _compute_betweenness(graph, ["A", "B", "C", "D"])
    assert all(value == pytest.approx(1 / 6, abs=0.001) for value in results.values())


def test_review_is_idempotent_and_rejects_an_old_revision(audit_client):
    client, repository = audit_client
    scenario = client.post("/api/scenarios", json={"fixture_id": "verified_delay"}).json()["data"]
    plan = client.post(f"/api/scenarios/{scenario['id']}/plans", json={"expected_revision": 1}).json()["data"]["selected_plan"]
    url = f"/api/plans/{plan['id']}/review"
    for _ in range(2):
        assert client.post(url, json={"expected_revision": 1, "action": "APPROVE"}).status_code == 200
    assert len(repository.get_reviews(plan["id"])) == 1
    assert client.patch(f"/api/scenarios/{scenario['id']}", json={"expected_revision": 1}).status_code == 200
    assert client.post(url, json={"expected_revision": 1, "action": "APPROVE"}).status_code == 409
