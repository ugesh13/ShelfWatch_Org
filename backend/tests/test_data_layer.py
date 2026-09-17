"""
ShelfWatch Phase 1 Data Layer Tests
===================================
Comprehensive unit tests for snapshot generator, fixture integrity,
network coordinates, and scenario repository.
"""
import pytest
from app.data.generator import (
    FIXTURES,
    generate_snapshot,
    fixture_assumptions,
)
from app.database import Repository
from app.schemas import ScenarioCreate, ScenarioPatch


def test_fixtures_catalog_completeness():
    """Verify all 10 demonstration fixtures exist with valid metadata."""
    assert len(FIXTURES) >= 10
    fixture_ids = [f["id"] for f in FIXTURES]
    assert "verified_delay" in fixture_ids
    assert "shared_depot_delay" in fixture_ids
    assert "demand_increase" in fixture_ids
    assert "no_safe_donors" in fixture_ids


def test_verified_delay_snapshot_structure():
    """Verify Section 12 verified_delay fixture has exact canonical structure."""
    snap = generate_snapshot("verified_delay")
    assert snap.id == "SNAP-VERIFIED"
    assert len(snap.facilities) == 3
    assert len(snap.depots) == 2
    assert len(snap.products) >= 1

    # Check facility IDs match Section 12 spec
    fac_ids = {f.id for f in snap.facilities}
    assert fac_ids == {"F-A", "F-B", "F-C"}

    # Check coastal coordinates
    for fac in snap.facilities:
        assert 12.0 <= fac.lat <= 15.0
        assert 74.0 <= fac.lon <= 76.0

    # Check inventory ledger history
    assert len(snap.history) > 0
    for h in snap.history:
        assert h.closing_units >= 0
        assert h.fulfilled_units >= 0


def test_shared_depot_snapshot_18_facilities():
    """Verify shared_depot_delay fixture contains 18 district facilities."""
    snap = generate_snapshot("shared_depot_delay")
    assert len(snap.facilities) == 18
    assert len(snap.depots) == 2

    # Check routes exist for both supply and transfer
    supply_routes = [r for r in snap.routes if r.kind == "SUPPLY"]
    transfer_routes = [r for r in snap.routes if r.kind == "TRANSFER"]
    assert len(supply_routes) >= 18
    assert len(transfer_routes) >= 10


def test_repository_lifecycle_and_revisions():
    """Verify Repository scenario creation, revision increment, and conflict protection."""
    repo = Repository()

    # 1. Create scenario
    req = ScenarioCreate(fixture_id="verified_delay", seed=42, horizon_days=14)
    scenario = repo.create_scenario(req)
    assert scenario.fixture_id == "verified_delay"
    assert scenario.revision == 1

    # 2. Patch scenario with correct revision
    patch = ScenarioPatch(
        expected_revision=1,
        demand_overrides=[{"facility_id": "F-A", "sku_id": "AMX500_CAP", "multiplier": 1.5}],
    )
    updated = repo.patch_scenario(scenario.id, patch)
    assert updated.revision == 2
    assert len(updated.assumptions.demand_overrides) == 1

    # 3. Patch with stale revision should raise ValueError (concurrency guard)
    stale_patch = ScenarioPatch(
        expected_revision=1,
        demand_overrides=[],
    )
    with pytest.raises(ValueError, match="revision conflict"):
        repo.patch_scenario(scenario.id, stale_patch)
