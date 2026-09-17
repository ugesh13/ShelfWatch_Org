"""The only inventory accounting engine: batch FEFO across vectorized paths."""

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from numpy.typing import NDArray

from app.config import DISPLAY_DAYS
from app.schemas import Snapshot, Transfer

IntArray = NDArray[np.int64]


@dataclass(frozen=True)
class Paths:
    sku_id: str
    facility_ids: tuple[str, ...]
    demand: IntArray  # path, facility, day
    shipment_arrivals: dict[str, IntArray]  # shipment -> day for each path
    depot_lateness: dict[str, IntArray]
    evidence: dict[str, dict]
    assumptions: tuple[str, ...] = ()
    closed_route_ids: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return self.demand.shape[0]

    @property
    def days(self) -> int:
        return self.demand.shape[2]


@dataclass
class SimulationResult:
    paths: Paths
    opening: IntArray
    closing: IntArray
    fulfilled: IntArray
    unmet: IntArray
    expired: IntArray
    receipts: IntArray
    transfer_arrivals: IntArray
    dispatched: IntArray
    in_transit: IntArray  # path, day
    transit_expired: IntArray
    initial_stock: IntArray  # path
    batch_trace: list[dict]

    def metrics(self, horizon: int = DISPLAY_DAYS) -> dict:
        included = [index for index, facility_id in enumerate(self.paths.facility_ids)
                    if self.paths.evidence.get(facility_id, {}).get("is_eligible", True)]
        unmet = self.unmet[:, included, :horizon]
        return {
            "expected_unmet_units": round(float(unmet.sum(axis=(1, 2)).mean()), 3),
            "expected_facility_days": round(float((unmet > 0).sum(axis=(1, 2)).mean()), 3),
            "expected_expiry_units": round(float((self.expired[:, included, :horizon].sum(axis=(1, 2)) + self.transit_expired[:, :horizon].sum(axis=1)).mean()), 3),
        }

    def assert_conservation(self) -> None:
        if any((ledger < 0).any() for ledger in (
            self.opening, self.closing, self.fulfilled, self.unmet, self.expired,
            self.receipts, self.transfer_arrivals, self.dispatched, self.in_transit,
        )):
            raise AssertionError("inventory quantities must never be negative")
        available = self.opening - self.expired + self.receipts + self.transfer_arrivals - self.dispatched
        if not np.array_equal(available - self.fulfilled, self.closing):
            raise AssertionError("facility inventory ledger does not reconcile")
        incoming = self.initial_stock[:, None] + self.receipts.sum(axis=1).cumsum(axis=1)
        outgoing = self.closing.sum(axis=1) + self.in_transit + self.fulfilled.sum(axis=1).cumsum(axis=1) + self.expired.sum(axis=1).cumsum(axis=1) + self.transit_expired.cumsum(axis=1)
        if not np.array_equal(incoming, outgoing):
            raise AssertionError("network inventory is not conserved")
        if not np.array_equal(self.paths.demand, self.fulfilled + self.unmet):
            raise AssertionError("requested demand was lost")


def validate_transfers(snapshot: Snapshot, paths: Paths, transfers: list[Transfer]) -> None:
    """Validate physical stock/route constraints before any dispatch takes place."""
    products = {product.sku_id: product for product in snapshot.products}
    product = products.get(paths.sku_id)
    routes = {route.id: route for route in snapshot.routes}
    batches = {batch.batch_id: batch for batch in snapshot.batches}
    facilities = set(paths.facility_ids)
    committed: dict[str, int] = {}
    donors = {item.from_facility_id for item in transfers}
    recipients = {item.to_facility_id for item in transfers}
    if donors & recipients:
        raise ValueError("donors and recipients must be disjoint; forwarding is not allowed")
    if len({item.id for item in transfers}) != len(transfers):
        raise ValueError("duplicate transfer IDs")
    for transfer in transfers:
        if transfer.sku_id != paths.sku_id or not product or product.storage_class != "ROOM_TEMPERATURE":
            raise ValueError("transfer requires the exact eligible room-temperature SKU")
        if transfer.from_facility_id not in facilities or transfer.to_facility_id not in facilities:
            raise ValueError("unknown transfer facility")
        route = routes.get(transfer.route_id)
        if not route or not route.enabled or route.id in paths.closed_route_ids or route.kind != "TRANSFER":
            raise ValueError("transfer route is unavailable")
        if (route.from_id, route.to_id, route.transit_days) != (transfer.from_facility_id, transfer.to_facility_id, transfer.arrival_day):
            raise ValueError("transfer route endpoints or arrival day do not match")
        arrival_date = snapshot.as_of.date() + timedelta(days=transfer.arrival_day)
        for allocation in transfer.batch_allocations:
            batch = batches.get(allocation.batch_id)
            if not batch or batch.facility_id != transfer.from_facility_id or batch.sku_id != transfer.sku_id:
                raise ValueError("batch does not belong to this donor and SKU")
            if batch.expires_on < arrival_date:
                raise ValueError("batch expires before transfer arrival")
            committed[batch.batch_id] = committed.get(batch.batch_id, 0) + allocation.quantity_units
            if committed[batch.batch_id] > batch.usable_units:
                raise ValueError("donor snapshot batch is overallocated")


def simulate(snapshot: Snapshot, paths: Paths, transfers: list[Transfer] | None = None, *, trace: bool = False) -> SimulationResult:
    """Dispatch on day 0; expire, receive, then serve demand on every day.

    Batch quantities are vectors over paths. This keeps one FEFO implementation for
    stochastic evaluation, planning stress cases, counterfactuals, and tests.
    """
    transfers = transfers or []
    if (paths.demand.ndim != 3 or not all(paths.demand.shape)
            or len(paths.facility_ids) != paths.demand.shape[1]
            or (paths.demand < 0).any() or paths.demand.dtype.kind not in "iu"):
        raise ValueError("demand paths must contain non-negative integer units")
    if len(set(paths.facility_ids)) != len(paths.facility_ids):
        raise ValueError("duplicate facility IDs in paths")
    if not set(paths.facility_ids) <= {facility.id for facility in snapshot.facilities}:
        raise ValueError("unknown facility in paths")
    if paths.sku_id not in {product.sku_id for product in snapshot.products}:
        raise ValueError("unknown SKU in paths")
    validate_transfers(snapshot, paths, transfers)
    path_count, facility_count, days = paths.demand.shape
    facility_index = {facility_id: index for index, facility_id in enumerate(paths.facility_ids)}
    ledgers = [np.zeros_like(paths.demand) for _ in range(8)]
    opening, closing, fulfilled, unmet, expired, receipts, transfer_arrivals, dispatched = ledgers
    in_transit = np.zeros((path_count, days), dtype=np.int64)
    transit_expired = np.zeros_like(in_transit)
    stores: list[list[dict]] = [[] for _ in paths.facility_ids]
    batch_by_id: dict[str, dict] = {}
    initial_stock = np.zeros(path_count, dtype=np.int64)
    traces: list[dict] = []
    as_of_date = snapshot.as_of.date()
    for batch in snapshot.batches:
        if batch.sku_id != paths.sku_id or batch.facility_id not in facility_index:
            continue
        entry = {"id": batch.batch_id, "expiry": (batch.expires_on - as_of_date).days, "quantity": np.full(path_count, batch.usable_units, dtype=np.int64)}
        stores[facility_index[batch.facility_id]].append(entry)
        batch_by_id[batch.batch_id] = entry
        initial_stock += batch.usable_units

    transit: list[dict] = []
    for transfer in transfers:
        donor_index = facility_index[transfer.from_facility_id]
        for allocation in transfer.batch_allocations:
            batch = batch_by_id[allocation.batch_id]
            batch["quantity"] -= allocation.quantity_units
            transit.append({"id": f"{transfer.id}:{allocation.batch_id}", "expiry": batch["expiry"], "quantity": np.full(path_count, allocation.quantity_units, dtype=np.int64), "arrival": transfer.arrival_day, "to": facility_index[transfer.to_facility_id]})
            dispatched[:, donor_index, 0] += allocation.quantity_units
            if trace:
                traces.append({"event": "dispatch", "day": 0, "batch_id": allocation.batch_id, "transfer_id": transfer.id, "quantity_units": allocation.quantity_units})

    pending = [shipment for shipment in snapshot.shipments if shipment.sku_id == paths.sku_id and shipment.status == "PENDING" and shipment.facility_id in facility_index]
    routes = {route.id: route for route in snapshot.routes}
    for shipment in pending:
        if shipment.id not in paths.shipment_arrivals:
            raise ValueError(f"missing arrival paths for shipment {shipment.id}")
        if paths.shipment_arrivals[shipment.id].shape != (path_count,):
            raise ValueError("shipment path count does not match demand paths")
        arrival_days = paths.shipment_arrivals[shipment.id]
        if arrival_days.dtype.kind not in "iu" or (arrival_days < 0).any():
            raise ValueError("shipment arrivals must contain non-negative integer days")

    for day in range(days):
        for index, store in enumerate(stores):
            if store:
                opening[:, index, day] = sum((item["quantity"] for item in store), start=np.zeros(path_count, dtype=np.int64))
            if day == 0:
                opening[:, index, day] += dispatched[:, index, 0]
            for batch in store:
                if batch["expiry"] < day:
                    expired[:, index, day] += batch["quantity"]
                    batch["quantity"] = np.zeros(path_count, dtype=np.int64)

        for batch in transit:
            if batch["expiry"] < day:
                transit_expired[:, day] += batch["quantity"]
                batch["quantity"] = np.zeros(path_count, dtype=np.int64)
            if batch["arrival"] == day:
                transfer_arrivals[:, batch["to"], day] += batch["quantity"]
                stores[batch["to"]].append({"id": batch["id"], "expiry": batch["expiry"], "quantity": batch["quantity"].copy()})
                batch["quantity"] = np.zeros(path_count, dtype=np.int64)

        for shipment in pending:
            route = routes[shipment.route_id]
            if not route.enabled or route.id in paths.closed_route_ids:
                continue
            arriving = paths.shipment_arrivals[shipment.id] == day
            if not arriving.any():
                continue
            expiry_day = (shipment.expires_on - as_of_date).days
            if expiry_day < day:
                continue  # Already expired at the external supplier; not a network receipt.
            quantity = arriving.astype(np.int64) * shipment.quantity_units
            index = facility_index[shipment.facility_id]
            receipts[:, index, day] += quantity
            stores[index].append({"id": shipment.batch_id, "expiry": expiry_day, "quantity": quantity})

        for index, store in enumerate(stores):
            remaining = paths.demand[:, index, day].copy()
            store.sort(key=lambda item: (item["expiry"], item["id"]))
            for batch in store:
                served = np.minimum(remaining, batch["quantity"])
                batch["quantity"] -= served
                remaining -= served
                if trace and served.any():
                    traces.append({"event": "fulfilled", "day": day, "facility_id": paths.facility_ids[index], "batch_id": batch["id"], "units_by_path": served.tolist()})
            unmet[:, index, day] = remaining
            fulfilled[:, index, day] = paths.demand[:, index, day] - remaining
            if store:
                closing[:, index, day] = sum((item["quantity"] for item in store), start=np.zeros(path_count, dtype=np.int64))
        if transit:
            in_transit[:, day] = sum((item["quantity"] for item in transit), start=np.zeros(path_count, dtype=np.int64))

    result = SimulationResult(paths, opening, closing, fulfilled, unmet, expired, receipts, transfer_arrivals, dispatched, in_transit, transit_expired, initial_stock, traces)
    result.assert_conservation()
    return result


run = simulate
