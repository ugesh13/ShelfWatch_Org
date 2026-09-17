"""
ShelfWatch API Endpoints Integration Test Suite
===============================================
Tests all FastAPI REST endpoints, status codes, payload envelopes,
error handling, and revision concurrency checks.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["data"]["status"] == "ok"
    assert data["data"]["schema_version"] == "1.0"
    assert data["data"]["algorithm_version"] == "inventory-1.1"


def test_list_fixtures_endpoint():
    res = client.get("/api/demo/fixtures")
    assert res.status_code == 200
    fixtures = res.json()["data"]
    assert len(fixtures) >= 10
    fixture_ids = {f["id"] for f in fixtures}
    assert "shared_depot_delay" in fixture_ids
    assert "verified_delay" in fixture_ids
    assert "verified_normal" in fixture_ids


def test_scenario_lifecycle_and_patch():
    # 1. Create Scenario
    create_res = client.post("/api/scenarios", json={"fixture_id": "verified_delay", "seed": 42})
    assert create_res.status_code == 201
    scen = create_res.json()["data"]
    scen_id = scen["id"]
    assert scen["revision"] == 1

    # 2. Get Scenario
    get_res = client.get(f"/api/scenarios/{scen_id}")
    assert get_res.status_code == 200
    details = get_res.json()["data"]
    assert details["scenario"]["id"] == scen_id
    assert len(details["snapshot"]["facilities"]) == 3

    # 3. Patch Scenario (advance revision)
    patch_res = client.patch(
        f"/api/scenarios/{scen_id}",
        json={
            "expected_revision": 1,
            "demand_overrides": [{"facility_id": "F-A", "sku_id": "AMX500_CAP", "multiplier": 1.5}],
            "depot_delays": [{"depot_id": "DEPOT-N", "extra_days": 8}],
            "closed_route_ids": [],
        }
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()["data"]
    assert patched["revision"] == 2

    # 4. Stale patch should return 409 Conflict
    stale_res = client.patch(
        f"/api/scenarios/{scen_id}",
        json={
            "expected_revision": 1,
            "demand_overrides": [],
            "depot_delays": [],
            "closed_route_ids": [],
        }
    )
    assert stale_res.status_code == 409


def test_simulation_and_facility_detail_endpoints():
    # Create scenario
    scen_res = client.post("/api/scenarios", json={"fixture_id": "verified_delay", "seed": 42})
    scen_id = scen_res.json()["data"]["id"]

    # Run simulation
    run_res = client.post(f"/api/scenarios/{scen_id}/run", json={"sku_id": "AMX500_CAP", "expected_revision": 1})
    assert run_res.status_code == 200
    run_data = run_res.json()["data"]
    assert run_data["metrics"]["expected_unmet_units"] == 140.0
    assert len(run_data["facilities"]) == 3

    # Facility detail
    fac_res = client.get(f"/api/scenarios/{scen_id}/facilities/F-A?sku_id=AMX500_CAP")
    assert fac_res.status_code == 200
    fac_data = fac_res.json()["data"]
    assert fac_data["facility_id"] == "F-A"
    assert "explanation" in fac_data
    assert "stock_trajectory" in fac_data
    assert len(fac_data["history"]) > 0


def test_domino_impact_endpoint():
    scen_res = client.post("/api/scenarios", json={"fixture_id": "verified_normal", "seed": 42})
    scen_id = scen_res.json()["data"]["id"]

    impact_res = client.post(f"/api/scenarios/{scen_id}/impact", json={"sku_id": "AMX500_CAP", "expected_revision": 1})
    assert impact_res.status_code == 200
    results = impact_res.json()["data"]
    assert len(results) == 2
    depot_n = next(r for r in results if r["depot_id"] == "DEPOT-N")
    assert depot_n["additional_affected_facilities_mean"] == 2.0
    assert depot_n["additional_unmet_units_mean"] == 100.0


def test_plans_and_review_workflow():
    scen_res = client.post("/api/scenarios", json={"fixture_id": "verified_delay", "seed": 42})
    scen_id = scen_res.json()["data"]["id"]

    # Generate plan
    plan_res = client.post(f"/api/scenarios/{scen_id}/plans?policy=shelfwatch", json={"sku_id": "AMX500_CAP", "expected_revision": 1})
    assert plan_res.status_code == 200
    data = plan_res.json()["data"]
    selected = data["selected_plan"]
    assert selected["metrics"]["expected_unmet_units"] == 0.0
    plan_id = selected["id"]

    # Get Plan
    get_plan_res = client.get(f"/api/plans/{plan_id}")
    assert get_plan_res.status_code == 200
    assert get_plan_res.json()["data"]["status"] == "DRAFT"

    # Review (Approve)
    review_res = client.post(f"/api/plans/{plan_id}/review", json={"expected_revision": 1, "action": "APPROVE", "reason": "Verified safe transfer"})
    assert review_res.status_code == 200
    assert review_res.json()["data"]["status"] == "APPROVED"
