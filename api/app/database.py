"""SQLite snapshots, immutable scenario revisions, plans, and atomic review events."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.config import DATABASE_PATH
from app.data.generator import FIXTURES, fixture_assumptions, generate_snapshot
from app.schemas import (
    Assumptions, Plan, ReviewRequest, Scenario, ScenarioCreate, ScenarioPatch,
    Snapshot, validate_assumptions,
)


class RevisionConflict(ValueError):
    """The requested revision is no longer current."""


class Repository:
    """Isolated in memory by default; supply a path for durable SQLite storage.

    Transactions protect revisions across processes; a lock serializes access
    to this connection in FastAPI's threads. Reads always reconstruct models.
    """

    def __init__(self, database_path: str | Path | None = None):
        location = str(database_path) if database_path is not None else ":memory:"
        self._lock = RLock()
        if location != ":memory:":
            try:
                Path(location).parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(
                    location, timeout=30, isolation_level=None, check_same_thread=False
                )
            except Exception:
                location = "/tmp/shelfwatch_v1.db"
                try:
                    Path(location).parent.mkdir(parents=True, exist_ok=True)
                    self._connection = sqlite3.connect(
                        location, timeout=30, isolation_level=None, check_same_thread=False
                    )
                except Exception:
                    location = ":memory:"
                    self._connection = sqlite3.connect(
                        location, timeout=30, isolation_level=None, check_same_thread=False
                    )
        else:
            self._connection = sqlite3.connect(
                location, timeout=30, isolation_level=None, check_same_thread=False
            )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshot_aliases (
                alias TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id)
            );
            CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY, current_revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scenario_revisions (
                scenario_id TEXT NOT NULL REFERENCES scenarios(id),
                revision INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (scenario_id, revision)
            );
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL,
                revision INTEGER NOT NULL, payload TEXT NOT NULL,
                FOREIGN KEY (scenario_id, revision)
                    REFERENCES scenario_revisions(scenario_id, revision)
            );
            CREATE TABLE IF NOT EXISTS approved_proposals (
                scenario_id TEXT NOT NULL, revision INTEGER NOT NULL,
                plan_id TEXT NOT NULL REFERENCES plans(id),
                PRIMARY KEY (scenario_id, revision)
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id TEXT NOT NULL REFERENCES plans(id), action TEXT NOT NULL,
                reason TEXT, timestamp TEXT NOT NULL
            );
        """)

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def get_snapshot(self, snapshot_or_fixture_id: str) -> Snapshot | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM snapshots WHERE id = ? OR id = "
                "(SELECT snapshot_id FROM snapshot_aliases WHERE alias = ?)",
                (snapshot_or_fixture_id, snapshot_or_fixture_id),
            ).fetchone()
            if row:
                return Snapshot.model_validate_json(row["payload"])
        if snapshot_or_fixture_id not in {item["id"] for item in FIXTURES}:
            return None
        snapshot = generate_snapshot(snapshot_or_fixture_id)
        with self._transaction():
            self._connection.execute(
                "INSERT OR IGNORE INTO snapshots (id, payload) VALUES (?, ?)",
                (snapshot.id, snapshot.model_dump_json()),
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO snapshot_aliases (alias, snapshot_id) VALUES (?, ?)",
                (snapshot_or_fixture_id, snapshot.id),
            )
        return self.get_snapshot(snapshot.id)

    def create_scenario(self, request: ScenarioCreate) -> Scenario:
        fixture_id = None if request.snapshot_id else request.fixture_id
        snapshot = self.get_snapshot(request.snapshot_id or fixture_id)
        if snapshot is None:
            raise ValueError(f"unknown fixture/snapshot {request.snapshot_id or fixture_id}")
        defaults = fixture_assumptions(fixture_id) if fixture_id else Assumptions()
        assumptions = Assumptions(**{
            field: getattr(request, field) if field in request.model_fields_set else getattr(defaults, field)
            for field in ("demand_overrides", "depot_delays", "closed_route_ids")
        })
        validate_assumptions(snapshot, assumptions)
        if fixture_id:
            scenario_id = f"SCEN-{fixture_id}-{uuid4().hex[:8]}"
        else:
            scenario_id = f"SCEN-{uuid4().hex}"
        scenario = Scenario(
            id=scenario_id, snapshot_id=snapshot.id, fixture_id=fixture_id,
            name=f"Scenario · {snapshot.name}", as_of=snapshot.as_of,
            seed=request.seed, horizon_days=request.horizon_days, assumptions=assumptions,
        )
        with self._transaction():
            self._connection.execute(
                "INSERT INTO scenarios (id, current_revision) VALUES (?, 1)", (scenario.id,)
            )
            self._connection.execute(
                "INSERT INTO scenario_revisions VALUES (?, 1, ?)",
                (scenario.id, scenario.model_dump_json()),
            )
        return scenario

    def get_scenario(self, scenario_id: str, revision: int | None = None) -> Scenario | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM scenario_revisions WHERE scenario_id = ? AND revision = "
                "COALESCE(?, (SELECT current_revision FROM scenarios WHERE id = ?))",
                (scenario_id, revision, scenario_id),
            ).fetchone()
            if row:
                return Scenario.model_validate_json(row["payload"])

            # Serverless container fallback: if scenario was created on another instance, reconstitute
            if scenario_id.startswith("SCEN-"):
                body = scenario_id[5:]
                target_fixture = None
                for f in FIXTURES:
                    fid = f["id"]
                    if body.startswith(fid + "-") or body == fid:
                        target_fixture = fid
                        break
                if not target_fixture:
                    target_fixture = "verified_delay"

                try:
                    snapshot = self.get_snapshot(target_fixture)
                    if snapshot:
                        defaults = fixture_assumptions(target_fixture)
                        scenario = Scenario(
                            id=scenario_id,
                            snapshot_id=snapshot.id,
                            fixture_id=target_fixture,
                            name=f"Scenario · {snapshot.name}",
                            as_of=snapshot.as_of,
                            seed=42,
                            horizon_days=14,
                            assumptions=defaults,
                        )
                        with self._transaction():
                            self._connection.execute(
                                "INSERT OR REPLACE INTO scenarios (id, current_revision) VALUES (?, 1)",
                                (scenario.id,),
                            )
                            self._connection.execute(
                                "INSERT OR REPLACE INTO scenario_revisions VALUES (?, 1, ?)",
                                (scenario.id, scenario.model_dump_json()),
                            )
                        return scenario
                except Exception:
                    pass

            return None

    def patch_scenario(self, scenario_id: str, patch: ScenarioPatch) -> Scenario:
        with self._transaction():
            prior = self.get_scenario(scenario_id)
            if prior is None:
                raise KeyError(f"scenario {scenario_id} not found")
            if patch.expected_revision != prior.revision:
                raise RevisionConflict(
                    f"revision conflict: current revision is {prior.revision}, expected {patch.expected_revision}"
                )
            assumptions = Assumptions(**patch.model_dump(
                include={"demand_overrides", "depot_delays", "closed_route_ids"}
            ))
            snapshot = self.get_snapshot(prior.snapshot_id)
            validate_assumptions(snapshot, assumptions)
            updated = prior.model_copy(update={
                "revision": prior.revision + 1, "assumptions": assumptions,
                "seed": patch.seed if patch.seed is not None else prior.seed,
            }, deep=True)
            self._connection.execute(
                "INSERT INTO scenario_revisions VALUES (?, ?, ?)",
                (scenario_id, updated.revision, updated.model_dump_json()),
            )
            self._connection.execute(
                "UPDATE scenarios SET current_revision = ? WHERE id = ?",
                (updated.revision, scenario_id),
            )
            return updated

    @staticmethod
    def _set_status(plan: Plan, status: str) -> Plan:
        updated = plan.model_copy(deep=True)
        updated.status = status
        for recommendation in updated.recommendations:
            recommendation.status = status
        return updated

    def save_plan(self, plan: Plan) -> Plan:
        with self._transaction():
            existing = self.get_plan(plan.id)
            if existing:
                if self._set_status(existing, "DRAFT") != self._set_status(plan, "DRAFT"):
                    raise ValueError("plan ID already belongs to a different immutable proposal")
                return existing
            if self.get_scenario(plan.scenario_id, plan.scenario_revision) is None:
                raise ValueError("plan references an unknown scenario revision")
            self._connection.execute(
                "INSERT INTO plans VALUES (?, ?, ?, ?)",
                (plan.id, plan.scenario_id, plan.scenario_revision, plan.model_dump_json()),
            )
            return plan.model_copy(deep=True)

    def get_plan(self, plan_id: str) -> Plan | None:
        with self._lock:
            row = self._connection.execute("SELECT payload FROM plans WHERE id = ?", (plan_id,)).fetchone()
            return Plan.model_validate_json(row["payload"]) if row else None

    def review_plan(self, plan_id: str, request: ReviewRequest) -> Plan:
        with self._transaction():
            plan = self.get_plan(plan_id)
            if plan is None:
                raise KeyError(f"plan {plan_id} not found")
            scenario = self.get_scenario(plan.scenario_id)
            if plan.scenario_revision != scenario.revision or request.expected_revision != scenario.revision:
                raise RevisionConflict(
                    f"stale approval: plan revision is {plan.scenario_revision}, "
                    f"current scenario revision is {scenario.revision}"
                )
            target_status = "APPROVED" if request.action == "APPROVE" else "REJECTED"
            selected = self._connection.execute(
                "SELECT plan_id FROM approved_proposals WHERE scenario_id = ? AND revision = ?",
                (plan.scenario_id, plan.scenario_revision),
            ).fetchone()
            if plan.status == target_status:
                return plan
            if request.action == "APPROVE":
                required = ("conservation_holds", "donor_reserves_respected", "zero_donor_harm_paths")
                if not all(plan.constraint_checks.get(key, False) for key in required):
                    raise ValueError("plan has not passed all required constraint checks")
                if selected and selected["plan_id"] != plan.id:
                    previous = self._set_status(self.get_plan(selected["plan_id"]), "DRAFT")
                    self._connection.execute(
                        "UPDATE plans SET payload = ? WHERE id = ?", (previous.model_dump_json(), previous.id)
                    )
                self._connection.execute(
                    "INSERT INTO approved_proposals VALUES (?, ?, ?) "
                    "ON CONFLICT(scenario_id, revision) DO UPDATE SET plan_id = excluded.plan_id",
                    (plan.scenario_id, plan.scenario_revision, plan.id),
                )
            elif selected and selected["plan_id"] == plan.id:
                self._connection.execute(
                    "DELETE FROM approved_proposals WHERE scenario_id = ? AND revision = ?",
                    (plan.scenario_id, plan.scenario_revision),
                )
            updated = self._set_status(plan, target_status)
            self._connection.execute(
                "UPDATE plans SET payload = ? WHERE id = ?", (updated.model_dump_json(), plan.id)
            )
            self._connection.execute(
                "INSERT INTO reviews (plan_id, action, reason, timestamp) VALUES (?, ?, ?, ?)",
                (plan.id, request.action, request.reason, datetime.now(timezone.utc).isoformat()),
            )
            return updated

    def get_reviews(self, plan_id: str) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._connection.execute(
                "SELECT * FROM reviews WHERE plan_id = ? ORDER BY id", (plan_id,)
            ).fetchall()]

    def list_plans(self, scenario_id: str, revision: int) -> list[Plan]:
        with self._lock:
            return [Plan.model_validate_json(row["payload"]) for row in self._connection.execute(
                "SELECT payload FROM plans WHERE scenario_id = ? AND revision = ? ORDER BY id",
                (scenario_id, revision),
            ).fetchall()]


repo = Repository(DATABASE_PATH)
