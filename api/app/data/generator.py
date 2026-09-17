"""Seeded fictional inventory records; forecast inputs contain no shock labels."""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app.config import HISTORY_DAYS, HISTORY_SEED, PRODUCTS
from app.schemas import Assumptions, Snapshot

AS_OF = datetime(2026, 9, 16, tzinfo=timezone.utc)

FIXTURES = [
    {"id": "shared_depot_delay", "name": "Shared depot delay", "description": "18 facilities; a delayed common supplier exposes local stock gaps.", "mode": "stochastic"},
    {"id": "healthy_supply", "name": "Healthy supply", "description": "Timely replenishment and healthy reserves.", "mode": "stochastic"},
    {"id": "demand_increase", "name": "Demand increase", "description": "One facility faces increased requested demand.", "mode": "stochastic"},
    {"id": "mixed_pressure", "name": "Mixed pressure", "description": "Demand increase coincides with a delayed depot.", "mode": "stochastic"},
    {"id": "no_safe_donors", "name": "No safe donors", "description": "Regional shortages exceed available donor reserves.", "mode": "stochastic"},
    {"id": "expiry_trap", "name": "Expiry trap", "description": "Apparent surplus includes batches expiring too soon.", "mode": "stochastic"},
    {"id": "closed_route", "name": "Closed transfer route", "description": "A useful directed transfer route is unavailable.", "mode": "stochastic"},
    {"id": "incomplete_records", "name": "Incomplete records", "description": "Stale stock and missing requested demand stay unknown.", "mode": "stochastic"},
    {"id": "verified_delay", "name": "Verified demo · delayed depot", "description": "Three-facility numerical fixture: 140 unmet units before intervention.", "mode": "deterministic"},
    {"id": "verified_normal", "name": "Verified demo · normal supply", "description": "Three-facility baseline for the paired Domino experiment.", "mode": "deterministic"},
]


def fixture_assumptions(fixture_id: str) -> Assumptions:
    data: dict = {}
    if fixture_id in {"shared_depot_delay", "mixed_pressure", "no_safe_donors", "expiry_trap", "closed_route", "incomplete_records"}:
        data["depot_delays"] = [{"depot_id": "DEPOT-N", "extra_days": 7}]
    if fixture_id == "verified_delay":
        data["depot_delays"] = [{"depot_id": "DEPOT-N", "extra_days": 6}]
    if fixture_id in {"demand_increase", "mixed_pressure"}:
        data["demand_overrides"] = [{"facility_id": "F-01", "sku_id": "AMX500_CAP", "multiplier": 2.0}]
    if fixture_id == "closed_route":
        data["closed_route_ids"] = ["T-F-10-F-01"]
    return Assumptions.model_validate(data)


def _depots() -> list[dict]:
    return [
        {"id": "DEPOT-N", "name": "North supply depot", "lat": 13.52, "lon": 74.79},
        {"id": "DEPOT-S", "name": "South supply depot", "lat": 13.16, "lon": 74.85},
    ]


def _deliveries(as_of: datetime, *, deterministic: bool) -> list[dict]:
    return [
        {"depot_id": depot_id, "promised_date": as_of.date() - timedelta(days=80 - index * 6),
         "actual_date": as_of.date() - timedelta(days=80 - index * 6) + timedelta(days=0 if deterministic else [0, 0, 1, 0, 2, 1, 0, 0, 1, 0][index])}
        for depot_id in ["DEPOT-N", "DEPOT-S"] for index in range(10)
    ]


def _history(facility_id: str, sku_id: str, daily: float, opening_target: int, rng: np.random.Generator, *, deterministic: bool, as_of: datetime = AS_OF) -> list[dict]:
    requested = []
    for index in range(HISTORY_DAYS):
        current_date = as_of.date() - timedelta(days=HISTORY_DAYS - index)
        weekday = [1.05, 1.03, 1.0, 1.0, 1.08, 0.92, 0.87][current_date.weekday()]
        value = daily if deterministic else daily * weekday * max(0.45, rng.normal(1, 0.12))
        requested.append(max(0, int(round(value))))
    stock = int(round(daily * 15))
    rows = []
    for index, demand in enumerate(requested):
        received = int(round(daily * 7)) if index % 7 == 0 else 0
        # Calibrate the final snapshot by choosing the final preceding-day receipt,
        # never by changing demand/fulfillment or clamping away an unmet request.
        if index == HISTORY_DAYS - 1:
            received = max(0, opening_target + demand - stock)
        fulfilled = min(demand, stock + received)
        closing = stock + received - fulfilled
        rows.append({"facility_id": facility_id, "sku_id": sku_id,
                     "date": as_of.date() - timedelta(days=HISTORY_DAYS - index),
                     "requested_units": demand, "fulfilled_units": fulfilled,
                     "opening_units": stock, "received_units": received,
                     "expired_units": 0, "closing_units": closing})
        stock = closing
    # Bring the ledger to the chosen snapshot with a documented final-day expiry
    # when the previous simulated inventory exceeds the target.
    if rows[-1]["closing_units"] > opening_target:
        adjustment = rows[-1]["closing_units"] - opening_target
        rows[-1]["expired_units"] += adjustment
        rows[-1]["closing_units"] = opening_target
    return rows


def verified_snapshot() -> Snapshot:
    rng = np.random.default_rng(HISTORY_SEED)
    facilities = [
        {"id": "F-A", "name": "Facility A · Riverbend", "type": "PHC", "lat": 13.43, "lon": 74.77, "depot_id": "DEPOT-N", "is_simulated": True},
        {"id": "F-B", "name": "Facility B · Hillview", "type": "CHC", "lat": 13.26, "lon": 74.84, "depot_id": "DEPOT-S", "is_simulated": True},
        {"id": "F-C", "name": "Facility C · Coastside", "type": "PHC", "lat": 13.36, "lon": 74.72, "depot_id": "DEPOT-N", "is_simulated": True},
    ]
    sku_id = "AMX500_CAP"
    batches, history, shipments, routes = [], [], [], []
    for facility, stock, daily, receipt, arrival in zip(facilities, [60, 500, 120], [20, 25, 20], [240, 250, 240], [2, 5, 2], strict=True):
        facility_id = facility["id"]
        batches.append({"batch_id": f"{facility_id}-AMX-01", "facility_id": facility_id, "sku_id": sku_id, "usable_units": stock, "expires_on": AS_OF.date() + timedelta(days=180), "observed_at": AS_OF - timedelta(hours=1)})
        history.extend(_history(facility_id, sku_id, daily, stock, rng, deterministic=True))
        route_id = f"SUP-{facility_id}"
        routes.append({"id": route_id, "from_id": facility["depot_id"], "to_id": facility_id, "kind": "SUPPLY", "distance_km": 12.0, "transit_days": 1, "enabled": True})
        shipments.append({"id": f"SHIP-{facility_id}", "depot_id": facility["depot_id"], "facility_id": facility_id, "sku_id": sku_id, "batch_id": f"IN-{facility_id}", "quantity_units": receipt, "promised_arrival_day": arrival, "current_eta_day": arrival, "expires_on": AS_OF.date() + timedelta(days=180), "status": "PENDING", "route_id": route_id})
    routes.extend([
        {"id": "B_TO_A", "from_id": "F-B", "to_id": "F-A", "kind": "TRANSFER", "distance_km": 24.0, "transit_days": 1, "enabled": True},
        {"id": "B_TO_C", "from_id": "F-B", "to_id": "F-C", "kind": "TRANSFER", "distance_km": 16.0, "transit_days": 1, "enabled": True},
    ])
    return Snapshot.model_validate({"id": "SNAP-VERIFIED", "as_of": AS_OF, "name": "Verified numerical fixture", "facilities": facilities, "depots": _depots(), "products": [PRODUCTS[0]], "batches": batches, "history": history, "shipments": shipments, "routes": routes, "deliveries": _deliveries(AS_OF, deterministic=True)})


def generate_snapshot(fixture_id: str = "shared_depot_delay", *, seed: int = HISTORY_SEED) -> Snapshot:
    if fixture_id not in {item["id"] for item in FIXTURES}:
        raise ValueError(f"unknown fixture {fixture_id}")
    if fixture_id.startswith("verified_"):
        return verified_snapshot()
    rng = np.random.default_rng(seed)
    names = ["Riverbend", "Palm Grove", "Northbank", "Mango Hill", "Cedar Point", "Estuary", "Orchard", "Lakeside", "Paddyfield", "Hillview", "Southgate", "Canal End", "Rainwood", "Coastside", "Banyan", "Seabreeze", "Stonebridge", "Garden Reach"]
    facilities, batches, history, shipments, routes = [], [], [], [], []
    daily_bases = [20, 36, 14, 24, 12]
    for index, name in enumerate(names):
        facility_id = f"F-{index + 1:02d}"
        depot_id = "DEPOT-N" if index < 9 else "DEPOT-S"
        facility_type = "DH" if index in (0, 9) else "CHC" if index % 4 == 0 else "PHC"
        facility = {"id": facility_id, "name": f"{name} {('District Centre' if facility_type == 'DH' else 'Health Centre')}", "type": facility_type,
                    "lat": round(13.17 + (index // 3) * 0.06 + rng.uniform(-0.012, 0.012), 5),
                    "lon": round(74.72 + (index % 3) * 0.064 + rng.uniform(-0.012, 0.012), 5),
                    "depot_id": depot_id, "is_simulated": True}
        facilities.append(facility)
        route_id = f"SUP-{facility_id}"
        routes.append({"id": route_id, "from_id": depot_id, "to_id": facility_id, "kind": "SUPPLY", "distance_km": round(float(rng.uniform(8, 38)), 1), "transit_days": 1, "enabled": True})
        for product_index, product in enumerate(PRODUCTS):
            sku_id = product["sku_id"]
            daily = daily_bases[product_index] * (1.3 if facility_type == "DH" else 1.0)
            cover = [3, 5, 6, 8, 4, 9, 6, 11, 5][index % 9] if index < 9 else [31, 25, 23, 27, 22, 30, 24, 26, 28][index % 9]
            if fixture_id == "healthy_supply":
                cover = 32
            if fixture_id == "no_safe_donors":
                cover = 3 if index < 9 else 6
            stock = int(round(daily * cover))
            expiry = AS_OF.date() + timedelta(days=120)
            if fixture_id == "expiry_trap" and index >= 9:
                expiry = AS_OF.date()  # usable today, never eligible for tomorrow's arrival
            observed = AS_OF - timedelta(hours=1)
            if fixture_id == "incomplete_records" and index in (1, 9):
                observed -= timedelta(days=3)
            batches.append({"batch_id": f"{facility_id}-{sku_id}-01", "facility_id": facility_id, "sku_id": sku_id, "usable_units": stock, "expires_on": expiry, "observed_at": observed})
            facility_history = _history(facility_id, sku_id, daily, stock, rng, deterministic=False)
            if fixture_id == "incomplete_records" and index in (0, 10):
                for row in facility_history[-20:]:
                    row["requested_units"] = None
            history.extend(facility_history)
            for cycle, arrival in enumerate([2 if index < 9 else 5, 12]):
                shipments.append({"id": f"SHIP-{facility_id}-{sku_id}-{cycle}", "depot_id": depot_id, "facility_id": facility_id, "sku_id": sku_id,
                                  "batch_id": f"IN-{facility_id}-{sku_id}-{cycle}", "quantity_units": int(round(daily * 14)),
                                  "promised_arrival_day": arrival, "current_eta_day": arrival,
                                  "expires_on": AS_OF.date() + timedelta(days=150), "status": "PENDING", "route_id": route_id})
    # Sparse configured directed routes. Travel durations are declared demo values,
    # not inferred from coordinates or presented as road navigation.
    for donor_index in range(9, 18):
        for recipient_index in range(9):
            if (donor_index + recipient_index) % 3 == 0 or donor_index in (9, 10):
                from_id, to_id = facilities[donor_index]["id"], facilities[recipient_index]["id"]
                routes.append({"id": f"T-{from_id}-{to_id}", "from_id": from_id, "to_id": to_id, "kind": "TRANSFER", "distance_km": round(float(rng.uniform(9, 44)), 1), "transit_days": 1 if donor_index in (9, 10) else 2, "enabled": True})
    return Snapshot.model_validate({"id": f"SNAP-{fixture_id}-{seed}", "as_of": AS_OF, "name": next(item["name"] for item in FIXTURES if item["id"] == fixture_id), "facilities": facilities, "depots": _depots(), "products": PRODUCTS, "batches": batches, "history": history, "shipments": shipments, "routes": routes, "deliveries": _deliveries(AS_OF, deterministic=False)})


def run() -> None:
    parser = argparse.ArgumentParser(description="Generate a reproducible ShelfWatch snapshot")
    parser.add_argument("--fixture", default="shared_depot_delay")
    parser.add_argument("--seed", type=int, default=HISTORY_SEED)
    parser.add_argument("--output", type=Path, default=Path("fixtures/snapshot.json"))
    args = parser.parse_args()
    snapshot = generate_snapshot(args.fixture, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    print(f"Wrote {len(snapshot.facilities)} facilities, {len(snapshot.products)} SKUs, {len(snapshot.history)} history rows to {args.output}")


if __name__ == "__main__":
    run()
