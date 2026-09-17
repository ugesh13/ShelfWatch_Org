"""
ShelfWatch FastAPI Application
==============================
Exposes typed endpoints for scenario analysis, simulation paths,
contributing-factor evidence, Domino depot experiments, and transfer plans.
Follows Section 10 of docs/IMPLEMENTATION_PLAN.md.
"""
import logging
import os
from typing import Any, Dict, List, Literal, Optional
import numpy as np
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALGORITHM_VERSION, DISPLAY_DAYS, SCHEMA_VERSION
from app.data.generator import FIXTURES
from app.database import repo
from app.schemas import (
    Assumptions,
    Envelope,
    InvalidAssumptions,
    Plan,
    ReviewRequest,
    RunRequest,
    Scenario,
    ScenarioCreate,
    ScenarioPatch,
)
from app.services.explanations import compute_facility_explanations
from app.services.forecast import generate_paths
from app.services.impact import compute_depot_impact
from app.services.planner import build_plan, compare_policies
from app.services.simulator import simulate
from app.services.anomaly_detector import run as run_anomaly_detection
from app.services.shortage_fingerprinter import run as run_fingerprinting
from app.services.domino_index import run as run_domino_index
from app.services.diffusion_model import run as run_diffusion, run_what_if

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shelfwatch.api")

app = FastAPI(
    title="ShelfWatch API",
    description="Contagion-aware medicine shortage early warning and safe redistribution engine",
    version=SCHEMA_VERSION,
    redirect_slashes=False,
)

allowed_origins_env = os.environ.get("SHELFWATCH_ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


from starlette.types import ASGIApp, Receive, Scope, Send

class VercelPathMiddleware:
    """Restores original request path from x-matched-path header when Vercel rewrites to /api/index.py."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            matched_path = headers.get(b"x-matched-path", b"").decode("latin1")
            if matched_path and not matched_path.endswith(".py"):
                scope["path"] = matched_path.split("?")[0]
        await self.app(scope, receive, send)

app.add_middleware(VercelPathMiddleware)


@app.middleware("http")
async def debug_path_middleware(request, call_next):
    if "debug" in request.url.path:
        from fastapi.responses import JSONResponse
        return JSONResponse({
            "url_path": request.url.path,
            "scope_path": request.scope.get("path"),
            "scope_raw_path": str(request.scope.get("raw_path")),
            "routes": [getattr(r, "path", "") for r in request.app.routes if getattr(r, "path", "")],
        })
    return await call_next(request)


def _validate_sku(snapshot, sku_id: str) -> None:
    if sku_id not in {product.sku_id for product in snapshot.products}:
        raise HTTPException(status_code=422, detail=f"Unknown SKU {sku_id}")


def _current_context(scenario_id: str, req: RunRequest):
    scenario = repo.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if req.expected_revision != scenario.revision:
        raise HTTPException(status_code=409, detail=f"Revision conflict: current revision is {scenario.revision}")
    snapshot = repo.get_snapshot(scenario.snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    _validate_sku(snapshot, req.sku_id)
    return scenario, snapshot


@app.get("/api/health")
def health() -> Envelope[Dict[str, str]]:
    """API readiness and schema/algorithm version check."""
    return Envelope(data={
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
    })


@app.get("/api/demo/fixtures")
def list_fixtures() -> Envelope[List[Dict[str, Any]]]:
    """Returns available demonstration fixtures."""
    return Envelope(data=FIXTURES)


@app.post("/api/scenarios", status_code=status.HTTP_201_CREATED)
def create_scenario(req: ScenarioCreate) -> Envelope[Scenario]:
    """Creates a new scenario from a fixture or snapshot."""
    try:
        scenario = repo.create_scenario(req)
        return Envelope(data=scenario)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, revision: Optional[int] = Query(None, ge=1)) -> Envelope[Dict[str, Any]]:
    """Retrieves scenario metadata, snapshot summary, facilities, and routes."""
    scenario = repo.get_scenario(scenario_id, revision)
    if not scenario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")

    snapshot = repo.get_snapshot(scenario.snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Underlying snapshot not found")

    return Envelope(data={
        "scenario": scenario,
        "snapshot": {
            "id": snapshot.id,
            "name": snapshot.name,
            "as_of": snapshot.as_of,
            "facilities": snapshot.facilities,
            "depots": snapshot.depots,
            "products": snapshot.products,
            "routes": snapshot.routes,
        }
    })


@app.patch("/api/scenarios/{scenario_id}")
def patch_scenario(scenario_id: str, patch: ScenarioPatch) -> Envelope[Scenario]:
    """Replaces scenario assumptions and advances revision."""
    try:
        updated = repo.patch_scenario(scenario_id, patch)
        return Envelope(data=updated)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    except InvalidAssumptions as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@app.post("/api/scenarios/{scenario_id}/run")
def run_scenario(scenario_id: str, req: RunRequest) -> Envelope[Dict[str, Any]]:
    """
    Computes simulation paths, baseline facility risk summaries,
    and network metrics for a selected medicine SKU.
    """
    scenario, snapshot = _current_context(scenario_id, req)

    try:
        paths = generate_paths(snapshot, scenario, req.sku_id)
        sim_result = simulate(snapshot, paths)
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Simulation failed: {e}")

    # Facility risk summaries
    facility_summaries = []
    for fac_id in paths.facility_ids:
        expl = compute_facility_explanations(snapshot, scenario, paths, sim_result, fac_id)
        facility_summaries.append(expl)

    metrics = sim_result.metrics(DISPLAY_DAYS)

    return Envelope(data={
        "scenario_id": scenario_id,
        "revision": scenario.revision,
        "sku_id": req.sku_id,
        "horizon_days": DISPLAY_DAYS,
        "metrics": metrics,
        "facilities": facility_summaries,
        "path_count": paths.count,
        "assumptions": list(paths.assumptions),
        "excluded_facility_ids": [item["facility_id"] for item in facility_summaries if item["risk_state"] == "Unknown"],
    })


@app.get("/api/scenarios/{scenario_id}/facilities/{facility_id}")
def get_facility_detail(
    scenario_id: str,
    facility_id: str,
    sku_id: str = Query("AMX500_CAP"),
    revision: Optional[int] = Query(None, ge=1)
) -> Envelope[Dict[str, Any]]:
    """
    Retrieves deep-dive facility analysis: historical ledger,
    projected inventory quantiles (P10, P50, P90), receipts, and evidence reasons.
    """
    scenario = repo.get_scenario(scenario_id, revision)
    if not scenario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")

    snapshot = repo.get_snapshot(scenario.snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")

    if facility_id not in {f.id for f in snapshot.facilities}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found")

    _validate_sku(snapshot, sku_id)

    paths = generate_paths(snapshot, scenario, sku_id)
    sim_result = simulate(snapshot, paths)

    expl = compute_facility_explanations(snapshot, scenario, paths, sim_result, facility_id)
    fac_idx = paths.facility_ids.index(facility_id)

    # Daily closing stock quantiles across paths: shape (DISPLAY_DAYS,)
    closing_slice = sim_result.closing[:, fac_idx, :DISPLAY_DAYS]  # (path, day)
    stock_p10, stock_p50, stock_p90 = [
        [int(np.quantile(closing_slice[:, day], quantile, method="higher"))
         if not expl["flags"] else None for day in range(DISPLAY_DAYS)]
        for quantile in (0.1, 0.5, 0.9)
    ]

    # Historical demand history (last 30 days)
    history_rows = sorted(
        [h for h in snapshot.history if h.facility_id == facility_id and h.sku_id == sku_id
         and h.date < scenario.as_of.date()],
        key=lambda h: h.date
    )[-30:]

    history_data = [
        {
            "date": str(h.date),
            "requested_units": h.requested_units,
            "fulfilled_units": h.fulfilled_units,
            "closing_units": h.closing_units,
            "received_units": h.received_units,
        }
        for h in history_rows
    ]

    # Pending supplier shipments
    routes = {route.id: route for route in snapshot.routes}
    shipments = []
    for s in snapshot.shipments:
        if s.facility_id != facility_id or s.sku_id != sku_id or s.status != "PENDING":
            continue
        route = routes[s.route_id]
        blocked = not route.enabled or route.id in paths.closed_route_ids
        arrivals = paths.shipment_arrivals[s.id]
        expiry_day = (s.expires_on - snapshot.as_of.date()).days
        median_arrival = int(np.quantile(np.where(arrivals <= expiry_day, arrivals, paths.days + 1), 0.5, method="higher"))
        shipments.append({
            "id": s.id,
            "depot_id": s.depot_id,
            "quantity_units": s.quantity_units,
            "promised_arrival_day": s.promised_arrival_day,
            "current_eta_day": s.current_eta_day,
            "status": s.status,
            "route_id": s.route_id,
            "route_blocked": blocked,
            "projected_arrival_day": median_arrival if not blocked and median_arrival < paths.days else None,
            "expires_on": str(s.expires_on),
        })

    return Envelope(data={
        "facility_id": facility_id,
        "sku_id": sku_id,
        "scenario_id": scenario.id,
        "revision": scenario.revision,
        "path_count": paths.count,
        "assumptions": list(paths.assumptions),
        "explanation": expl,
        "stock_trajectory": {
            "days": list(range(DISPLAY_DAYS)),
            "p10": stock_p10,
            "p50": stock_p50,
            "p90": stock_p90,
        },
        "history": history_data,
        "pending_shipments": shipments,
    })


@app.post("/api/scenarios/{scenario_id}/impact")
def run_impact(scenario_id: str, req: RunRequest) -> Envelope[List[Dict[str, Any]]]:
    """Runs paired depot delay counterfactual experiments to measure Domino impact."""
    scenario, snapshot = _current_context(scenario_id, req)

    results = compute_depot_impact(snapshot, scenario, req.sku_id)
    return Envelope(data=results)


@app.post("/api/scenarios/{scenario_id}/plans")
def create_plan(
    scenario_id: str,
    req: RunRequest,
    policy: Literal["shelfwatch", "nearest_donor", "no_action"] = Query("shelfwatch")
) -> Envelope[Dict[str, Any]]:
    """
    Generates redistribution plans and policy comparisons (ShelfWatch vs. Nearest Donor vs. No Action).
    """
    scenario, snapshot = _current_context(scenario_id, req)

    paths = generate_paths(snapshot, scenario, req.sku_id)
    comparison = compare_policies(snapshot, scenario, paths)

    # Save generated plans
    comparison = {key: repo.save_plan(plan) for key, plan in comparison.items()}

    selected_plan = comparison.get(policy, comparison["shelfwatch"])

    return Envelope(data={
        "selected_plan": selected_plan,
        "comparison": {
            k: {
                "id": v.id,
                "policy": v.policy,
                "metrics": v.metrics,
                "transfer_count": len(v.transfers),
                "residual_deficit": v.residual_deficit,
            }
            for k, v in comparison.items()
        }
    })


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: str) -> Envelope[Plan]:
    """Retrieves full details of a generated transfer plan."""
    plan = repo.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return Envelope(data=plan)


@app.post("/api/plans/{plan_id}/review")
def review_plan(plan_id: str, req: ReviewRequest) -> Envelope[Plan]:
    """Approve or reject a transfer plan for a specific scenario revision."""
    try:
        updated = repo.review_plan(plan_id, req)
        return Envelope(data=updated)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# DIFFERENTIATOR ENDPOINTS — D1 Domino Index, D2 Fingerprinting, D3 Diffusion
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/scenarios/{scenario_id}/risk-scores")
def get_risk_scores(scenario_id: str, req: RunRequest) -> Envelope[List[Dict[str, Any]]]:
    """
    ⭐ CUSUM + z-score anomaly detection for all facilities.
    Returns per-facility risk scores, z-scores, CUSUM statistics, and flag reasons.
    """
    scenario, snapshot = _current_context(scenario_id, req)

    try:
        anomalies = run_anomaly_detection(snapshot, req.sku_id, scenario=scenario)
        return Envelope(data=anomalies)
    except Exception as e:
        logger.error(f"Anomaly detection failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/scenarios/{scenario_id}/fingerprints")
def get_fingerprints(scenario_id: str, req: RunRequest) -> Envelope[List[Dict[str, Any]]]:
    """
    ⭐ D2 Shortage Fingerprinting — classifies the TYPE of shortage.
    Returns shortage archetype (DEMAND_SURGE, SUPPLY_DISRUPTION, PANIC_HOARDING,
    CHRONIC_EROSION, MIXED) with confidence and recommended intervention.
    """
    scenario, snapshot = _current_context(scenario_id, req)

    try:
        anomalies = run_anomaly_detection(snapshot, req.sku_id, scenario=scenario)
        fingerprints = run_fingerprinting(snapshot, anomalies, req.sku_id)
        return Envelope(data=fingerprints)
    except Exception as e:
        logger.error(f"Fingerprinting failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/scenarios/{scenario_id}/domino-index")
def get_domino_index(scenario_id: str, req: RunRequest) -> Envelope[List[Dict[str, Any]]]:
    """
    ⭐ D1 Domino Index — structural vulnerability scoring.
    For every facility: 'If this stocks out, how many others cascade within 7 days?'
    Includes betweenness centrality, isolation score, and risk narrative.
    """
    scenario, snapshot = _current_context(scenario_id, req)

    try:
        domino_results = run_domino_index(snapshot, req.sku_id, scenario=scenario)
        return Envelope(data=domino_results)
    except Exception as e:
        logger.error(f"Domino Index computation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/scenarios/{scenario_id}/diffusion")
def simulate_diffusion(scenario_id: str, req: RunRequest) -> Envelope[Dict[str, Any]]:
    """
    ⭐ D3 SIS Contagion Diffusion — epidemiological spread simulation.
    Projects how shortage contagion spreads across the facility network.
    Returns cascade timeline and per-facility risk trajectories.
    """
    scenario, snapshot = _current_context(scenario_id, req)

    try:
        anomalies = run_anomaly_detection(snapshot, req.sku_id, scenario=scenario)
        diffusion_result = run_diffusion(snapshot, anomalies, req.sku_id, scenario=scenario)
        return Envelope(data=diffusion_result)
    except Exception as e:
        logger.error(f"Diffusion simulation failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/scenarios/{scenario_id}/analytics")
def get_analytics_summary(scenario_id: str, req: RunRequest) -> Envelope[Dict[str, Any]]:
    """
    Regional analytics summary combining anomaly detection, fingerprinting,
    domino index, and diffusion results into a single dashboard payload.
    """
    scenario, snapshot = _current_context(scenario_id, req)

    try:
        anomalies = run_anomaly_detection(snapshot, req.sku_id, scenario=scenario)
        fingerprints = run_fingerprinting(snapshot, anomalies, req.sku_id)
        domino_results = run_domino_index(snapshot, req.sku_id, scenario=scenario)
        diffusion_result = run_diffusion(snapshot, anomalies, req.sku_id, scenario=scenario)

        # Aggregate statistics
        at_risk_facilities = [a for a in anomalies if a["risk_level"] in ("AT_RISK", "CRITICAL")]
        critical_facilities = [a for a in anomalies if a["risk_level"] in ("CRITICAL", "STOCKOUT")]
        known_anomalies = [a for a in anomalies if a["local_risk_score"] is not None]

        # Find worst facility and drug
        worst_facility = max(known_anomalies, key=lambda a: a["local_risk_score"]) if known_anomalies else None
        top_domino = next((item for item in domino_results if item["domino_index"] is not None), None)

        # Fingerprint type distribution
        type_counts: Dict[str, int] = {}
        for fp in fingerprints:
            t = fp["shortage_type"]
            type_counts[t] = type_counts.get(t, 0) + 1

        summary = {
            "total_facilities": len(snapshot.facilities),
            "facilities_at_risk": len(at_risk_facilities),
            "facilities_critical": len(critical_facilities),
            "regional_risk_score": round(
                sum(a["local_risk_score"] for a in known_anomalies) / len(known_anomalies), 3
            ) if known_anomalies else None,
            "facilities_unknown": len(anomalies) - len(known_anomalies),
            "score_kind": "heuristic_not_probability",
            "worst_facility": {
                "id": worst_facility["facility_id"],
                "risk_score": worst_facility["local_risk_score"],
                "days_of_stock": worst_facility["days_of_stock"],
            } if worst_facility else None,
            "top_domino_facility": {
                "id": top_domino["facility_id"],
                "domino_index": top_domino["domino_index"],
                "vulnerability_rank": top_domino["vulnerability_rank"],
            } if top_domino else None,
            "shortage_type_distribution": type_counts,
            "diffusion_day_14": diffusion_result["timeline"][-1] if diffusion_result["timeline"] else None,
            "pending_recommendations": sum(
                len(plan.recommendations) for plan in repo.list_plans(scenario.id, scenario.revision)
                if plan.sku_id == req.sku_id and plan.policy == "shelfwatch" and plan.status == "DRAFT"
            ),
        }

        return Envelope(data=summary)
    except Exception as e:
        logger.error(f"Analytics summary failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ── Dual Route Registration (Vercel strips /api prefix on serverless calls) ──
from fastapi.routing import APIRoute

_api_routes = [r for r in list(app.routes) if isinstance(r, APIRoute) and r.path.startswith("/api/")]
for r in _api_routes:
    stripped = r.path[4:]
    app.router.add_api_route(
        stripped,
        endpoint=r.endpoint,
        methods=r.methods,
        response_model=r.response_model,
        status_code=r.status_code,
    )

# ── Static Files and SPA Fallback ─────────────────────────────────────────────
from pathlib import Path
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

_possible_dirs = [
    Path(__file__).resolve().parents[1] / "static",
    Path(__file__).resolve().parents[2] / "frontend" / "dist",
    Path("/var/task/api/static"),
    Path("/var/task/static"),
]
_static_dir = next((d for d in _possible_dirs if d.is_dir()), None)

if _static_dir and (_static_dir / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(_static_dir / "assets")), name="assets")

INDEX_HTML_FALLBACK = """<!doctype html>
<html lang="en" class="dark">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ShelfWatch — Medicine Shortage Early Warning & Safe Redistribution</title>
    <script type="module" crossorigin src="/assets/index-BpeiOg7g.js"></script>
    <link rel="stylesheet" crossorigin href="/assets/index-BrAPOKXB.css">
  </head>
  <body class="bg-background text-foreground antialiased font-sans overflow-x-hidden min-h-screen">
    <div id="root"></div>
  </body>
</html>"""

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if _static_dir:
        target = _static_dir / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        index_file = _static_dir / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
    return HTMLResponse(content=INDEX_HTML_FALLBACK, media_type="text/html")
