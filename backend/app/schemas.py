"""Canonical units, immutable snapshot inputs, and validated scenario requests."""

from datetime import date, datetime, timezone
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import DISPLAY_DAYS, SCENARIO_SEED

Units = Annotated[int, Field(ge=0, strict=True)]
PositiveUnits = Annotated[int, Field(gt=0, strict=True)]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Facility(Model):
    id: Identifier
    name: str
    type: Literal["DH", "CHC", "PHC", "SC"]
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    depot_id: Identifier
    is_simulated: bool = True


class Depot(Model):
    id: Identifier
    name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Product(Model):
    sku_id: Identifier
    generic_name: str
    strength: str
    dosage_form: str
    base_unit: str
    storage_class: Literal["ROOM_TEMPERATURE", "COLD_CHAIN"]


class Batch(Model):
    batch_id: Identifier
    facility_id: Identifier
    sku_id: Identifier
    usable_units: Units
    expires_on: date
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        return value.astimezone(timezone.utc)


class HistoryRow(Model):
    facility_id: Identifier
    sku_id: Identifier
    date: date
    requested_units: Units | None = None
    fulfilled_units: Units
    opening_units: Units
    received_units: Units
    expired_units: Units
    closing_units: Units

    @model_validator(mode="after")
    def reconcile(self):
        if self.opening_units + self.received_units - self.expired_units - self.fulfilled_units != self.closing_units:
            raise ValueError("history ledger does not balance")
        if self.requested_units is not None and self.fulfilled_units > self.requested_units:
            raise ValueError("fulfilled_units exceeds requested_units")
        return self


class Shipment(Model):
    id: Identifier
    depot_id: Identifier
    facility_id: Identifier
    sku_id: Identifier
    batch_id: Identifier
    quantity_units: PositiveUnits
    promised_arrival_day: int = Field(strict=True)
    current_eta_day: int = Field(strict=True)
    expires_on: date
    status: Literal["PENDING", "RECEIVED", "CANCELLED"]
    route_id: Identifier

    @model_validator(mode="after")
    def pending_eta(self):
        if self.status == "PENDING" and self.current_eta_day < 0:
            raise ValueError("pending shipment needs a non-negative current ETA")
        return self


class Delivery(Model):
    depot_id: Identifier
    promised_date: date
    actual_date: date


class Route(Model):
    id: Identifier
    from_id: Identifier
    to_id: Identifier
    kind: Literal["SUPPLY", "TRANSFER"]
    distance_km: float = Field(ge=0, allow_inf_nan=False)
    transit_days: int = Field(ge=1, le=30, strict=True)
    enabled: bool = True


class Snapshot(Model):
    id: Identifier
    as_of: datetime
    name: str
    facilities: list[Facility]
    depots: list[Depot]
    products: list[Product]
    batches: list[Batch]
    history: list[HistoryRow]
    shipments: list[Shipment]
    routes: list[Route]
    deliveries: list[Delivery]
    assumed_delay_days: list[Units] | None = None

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def catalogue_integrity(self):
        facilities = {item.id: item for item in self.facilities}
        depots = {item.id: item for item in self.depots}
        products = {item.sku_id: item for item in self.products}
        routes = {item.id: item for item in self.routes}
        batches = {item.batch_id: item for item in self.batches}
        for name, records, keys in [
            ("facilities", self.facilities, facilities), ("depots", self.depots, depots),
            ("products", self.products, products), ("routes", self.routes, routes),
            ("batches", self.batches, batches),
            ("shipments", self.shipments, {item.id for item in self.shipments}),
        ]:
            if len(records) != len(keys):
                raise ValueError(f"duplicate IDs in {name}")
        if not facilities or not products or not depots:
            raise ValueError("facilities, products and depots must not be empty")
        if set(facilities) & set(depots):
            raise ValueError("facility and depot IDs must be distinct")
        for facility in self.facilities:
            if facility.depot_id not in depots:
                raise ValueError(f"unknown depot on facility {facility.id}")
        for item in [*self.batches, *self.history, *self.shipments]:
            if item.facility_id not in facilities or item.sku_id not in products:
                raise ValueError("unknown facility or SKU reference")
        history_keys = {(row.facility_id, row.sku_id, row.date) for row in self.history}
        if len(history_keys) != len(self.history):
            raise ValueError("duplicate facility/SKU/date history rows")
        for route in self.routes:
            origins = depots if route.kind == "SUPPLY" else facilities
            if route.from_id not in origins or route.to_id not in facilities or route.from_id == route.to_id:
                raise ValueError(f"invalid endpoints for route {route.id}")
        pending_batches: set[str] = set()
        for shipment in self.shipments:
            route = routes.get(shipment.route_id)
            if shipment.depot_id not in depots or not route or route.kind != "SUPPLY" or route.from_id != shipment.depot_id or route.to_id != shipment.facility_id:
                raise ValueError(f"shipment {shipment.id} has an incompatible supply route")
            if shipment.status == "PENDING":
                if shipment.batch_id in batches or shipment.batch_id in pending_batches:
                    raise ValueError("pending shipment batch already exists or is duplicated")
                pending_batches.add(shipment.batch_id)
        if any(item.depot_id not in depots for item in self.deliveries):
            raise ValueError("unknown depot in delivery history")
        if any(batch.observed_at > self.as_of for batch in self.batches):
            raise ValueError("stock observation is after snapshot as_of")
        if self.assumed_delay_days is not None and not self.assumed_delay_days:
            raise ValueError("assumed delay distribution must not be empty")
        return self


class DemandOverride(Model):
    facility_id: Identifier
    sku_id: Identifier
    multiplier: float = Field(ge=0, le=3, allow_inf_nan=False)
    start_day: int = Field(default=0, ge=0, lt=DISPLAY_DAYS, strict=True)
    end_day: int = Field(default=DISPLAY_DAYS - 1, ge=0, lt=DISPLAY_DAYS, strict=True)

    @model_validator(mode="after")
    def ordered_days(self):
        if self.end_day < self.start_day:
            raise ValueError("end_day must not precede start_day")
        return self


class DepotDelay(Model):
    depot_id: Identifier
    extra_days: int = Field(ge=0, le=14, strict=True)


class Assumptions(Model):
    demand_overrides: list[DemandOverride] = Field(default_factory=list)
    depot_delays: list[DepotDelay] = Field(default_factory=list)
    closed_route_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def no_ambiguous_overrides(self):
        if len({item.depot_id for item in self.depot_delays}) != len(self.depot_delays):
            raise ValueError("duplicate depot delay")
        if len(set(self.closed_route_ids)) != len(self.closed_route_ids):
            raise ValueError("duplicate closed route")
        for index, left in enumerate(self.demand_overrides):
            for right in self.demand_overrides[index + 1:]:
                if (left.facility_id, left.sku_id) == (right.facility_id, right.sku_id) and max(left.start_day, right.start_day) <= min(left.end_day, right.end_day):
                    raise ValueError("overlapping demand overrides")
        return self


class ScenarioCreate(Assumptions):
    fixture_id: Identifier | None = "shared_depot_delay"
    snapshot_id: Identifier | None = None
    seed: int = Field(default=SCENARIO_SEED, ge=0, le=2**32 - 1, strict=True)
    horizon_days: Literal[14] = DISPLAY_DAYS

    @model_validator(mode="after")
    def one_source(self):
        if self.snapshot_id and self.fixture_id and "fixture_id" in self.model_fields_set:
            raise ValueError("choose either snapshot_id or fixture_id, not both")
        if not self.snapshot_id and not self.fixture_id:
            raise ValueError("a snapshot_id or fixture_id is required")
        return self


class ScenarioPatch(Assumptions):
    expected_revision: PositiveUnits
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1, strict=True)


class Scenario(Model):
    id: Identifier
    snapshot_id: Identifier
    fixture_id: str | None
    name: str
    as_of: datetime
    seed: int
    horizon_days: Literal[14] = DISPLAY_DAYS
    revision: PositiveUnits = 1
    assumptions: Assumptions


class RunRequest(Model):
    sku_id: Identifier = "AMX500_CAP"
    expected_revision: PositiveUnits


class BatchAllocation(Model):
    batch_id: Identifier
    quantity_units: PositiveUnits


class Transfer(Model):
    id: Identifier
    from_facility_id: Identifier
    to_facility_id: Identifier
    sku_id: Identifier
    quantity_units: PositiveUnits
    route_id: Identifier
    dispatch_day: Literal[0] = 0
    arrival_day: int = Field(ge=1, strict=True)
    batch_allocations: list[BatchAllocation] = Field(min_length=1)

    @model_validator(mode="after")
    def check_allocation(self):
        if self.from_facility_id == self.to_facility_id:
            raise ValueError("same-facility transfer is invalid")
        if sum(item.quantity_units for item in self.batch_allocations) != self.quantity_units:
            raise ValueError("batch allocations must sum to quantity_units")
        if len({item.batch_id for item in self.batch_allocations}) != len(self.batch_allocations):
            raise ValueError("duplicate batch allocation")
        return self


class RecommendationItem(Model):
    id: Identifier
    from_facility_id: Identifier
    to_facility_id: Identifier
    sku_id: Identifier
    quantity_units: PositiveUnits
    route_id: Identifier
    dispatch_day: Literal[0] = 0
    arrival_day: int = Field(ge=1, strict=True)
    batch_allocations: list[BatchAllocation] = Field(min_length=1)
    planning_unmet_units_avoided: int = Field(ge=0)
    donor_minimum_planning_stock: int = Field(ge=0)
    donor_reserve_at_minimum_day: int = Field(ge=0)
    sampled_donor_harm_paths: int = Field(default=0, ge=0)
    status: Literal["DRAFT", "APPROVED", "REJECTED"] = "DRAFT"


class PlanMetrics(Model):
    expected_unmet_units: float = Field(ge=0.0)
    expected_facility_days: float = Field(ge=0.0)
    expected_expiry_units: float = Field(ge=0.0)
    expected_additional_donor_unmet: float = Field(default=0.0, ge=0.0)
    transfer_units: int = Field(ge=0)
    transfer_distance: float = Field(ge=0.0)
    unmet_units_avoided: float = Field(default=0.0)


class Plan(Model):
    id: Identifier
    scenario_id: Identifier
    scenario_revision: PositiveUnits = 1
    sku_id: Identifier
    policy: Literal["no_action", "nearest_donor", "shelfwatch"] = "shelfwatch"
    status: Literal["DRAFT", "APPROVED", "REJECTED"] = "DRAFT"
    transfers: list[Transfer] = Field(default_factory=list)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    metrics: PlanMetrics
    residual_deficit: int = Field(default=0, ge=0)
    constraint_checks: dict[str, bool] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    excluded_facility_ids: list[str] = Field(default_factory=list)
    modeled_facility_count: int = Field(default=0, ge=0)


class QuantityChange(Model):
    transfer_id: Identifier
    quantity_units: Units


class PlanRevisionRequest(Model):
    expected_revision: PositiveUnits
    changes: list[QuantityChange] = Field(min_length=1)


class ReviewRequest(Model):
    expected_revision: PositiveUnits
    action: Literal["APPROVE", "REJECT"]
    reason: str | None = Field(default=None, max_length=1000)


T = TypeVar("T")


class Meta(Model):
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = "1.0"


class Envelope(Model, Generic[T]):
    data: T
    meta: Meta = Field(default_factory=Meta)


class InvalidAssumptions(ValueError):
    """A syntactically valid scenario references data outside its snapshot."""


def validate_assumptions(snapshot: Snapshot, assumptions: Assumptions) -> None:
    facilities = {facility.id for facility in snapshot.facilities}
    products = {product.sku_id for product in snapshot.products}
    depots = {depot.id for depot in snapshot.depots}
    routes = {route.id for route in snapshot.routes}
    for override in assumptions.demand_overrides:
        if override.facility_id not in facilities or override.sku_id not in products:
            raise InvalidAssumptions("demand override references an unknown facility or SKU")
    if any(delay.depot_id not in depots for delay in assumptions.depot_delays):
        raise InvalidAssumptions("depot delay references an unknown depot")
    if any(route_id not in routes for route_id in assumptions.closed_route_ids):
        raise InvalidAssumptions("route closure references an unknown route")
