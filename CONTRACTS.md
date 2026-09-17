# ShelfWatch — active contracts

This document describes the running Vite/FastAPI application. It supersedes the earlier table-oriented and Next.js contracts retained in `docs/legacy/`. Canonical model definitions are in `backend/app/schemas.py`; frontend consumers are in `frontend/src/lib/types.ts`.

## Common rules

Successful API responses use `{ "data": ..., "meta": { "computed_at": "<UTC ISO time>", "schema_version": "1.0" } }`. FastAPI errors use `{ "detail": "<message>" }` or a list of field-validation errors. Missing resources return 404, malformed or incompatible inputs 422, and stale revisions 409. Calculation failures are errors, never successful zero-risk fallbacks.

IDs are exact strings. A product is identified by its complete `sku_id` (for example `AMX500_CAP`), including strength/form; no substitution or pack conversion occurs. The legacy heuristic endpoints retain `drug_id`, whose value is the same exact SKU.

Dates use ISO 8601 and units are strict nonnegative integers. Pending shipment ETAs and scenario-relative days are integers. A batch is usable through its expiry date and expires before demand on the next day. Authoritative future stock comes from batch observations, not historical closing-stock rows.

## Persistence

`Repository()` is isolated in memory; `Repository(path)` persists. The API repository reads `SHELFWATCH_DB`, defaulting to `data/shelfwatch_v1.db`. SQLite stores validated JSON model payloads in `snapshots`, `scenario_revisions`, and `plans`, plus fixture aliases, current revision pointers, selected approved proposals, and append-only review events.

Reads reconstruct independent model objects. Writes use transactions; revision comparison and append happen atomically across connections. Historical revisions and plans remain readable after scenario edits. There is at most one selected approved proposal per scenario revision, across policies and SKUs, as specified in the current plan.

## Scenario API

| Endpoint | Input | Result |
| --- | --- | --- |
| GET /api/health | None | Status, schema version, algorithm version |
| GET /api/demo/fixtures | None | Fixture IDs, names, descriptions, stochastic/deterministic mode |
| POST /api/scenarios | Fixture or snapshot source, optional seed and assumptions | Scenario at revision 1 |
| GET /api/scenarios/{id} | Optional revision query | Scenario and snapshot summary with facilities, products, depots, routes |
| PATCH /api/scenarios/{id} | expected_revision, replacement assumptions, optional seed | New immutable revision |
| POST /api/scenarios/{id}/run | sku_id, expected_revision | Inventory forecast, regional metrics, facility summaries |
| GET /api/scenarios/{id}/facilities/{facility_id} | sku_id, optional current revision | Explanation, stock trajectory, history, pending shipments |
| POST /api/scenarios/{id}/impact | sku_id, expected_revision | Paired depot-delay results |
| POST /api/scenarios/{id}/plans | sku_id, expected_revision; optional policy query | Selected plan and three-policy comparison |
| GET /api/plans/{id} | None | Saved plan including review status |
| POST /api/plans/{id}/review | expected_revision, APPROVE/REJECT action, optional reason | Updated saved review status |

`ScenarioCreate` accepts one source: `fixture_id` or `snapshot_id`. Omitted assumptions use fixture defaults; explicitly empty arrays override those defaults. The horizon is fixed at 14 displayed days.

Assumptions comprise `demand_overrides`, `depot_delays`, and `closed_route_ids`. Multipliers range from 0 to 3, depot delays from 0 to 14 days, and every target must exist in the snapshot. Override windows are inclusive within days 0–13. Nonoverlapping windows are allowed; windows ending on day 13 continue through internal day 20 for reserve checks.

PATCH replaces all three assumption arrays, rather than merging individual entries. Clients must preserve unrelated SKUs, facilities, time windows, and routes. The seed is retained unless changed. Analysis, plan generation, and review validate the expected current revision.

## Forecast and missing evidence

`/run` returns `scenario_id`, `revision`, `sku_id`, `horizon_days`, `path_count`, declared `assumptions`, `excluded_facility_ids`, `metrics`, and `facilities`.

Each facility summary includes:

- `risk_state`: Empty, High risk, Watch, Lower risk, or Unknown.
- Nullable 7-day/14-day shortage probabilities, expected 14-day unmet units, and P10/P50/P90 first-shortfall days.
- Nullable observed usable stock, daily shortage probabilities, median closing stock, and daily risk states.
- Supporting factors with code, category, title, description, priority, and data-quality flags.

Forecast inputs use only known requested demand before the snapshot time. Insufficient observations, zero observed demand, missing stock, or stale stock prevent automatic eligibility. Known stock may still be shown when demand is unknown. Missing estimates must not be rendered as 0%, zero days, or a green risk state.

First-shortfall quantiles retain paths with no event as censored observations. A null quantile means that percentile has no shortfall within the displayed horizon. Stock bands are pointwise P10–P90 summaries and P50 is the median, not the mean or a guaranteed outcome.

Regional inventory metrics exclude ineligible facilities. They remain numeric in the API; consumers must check coverage and show unavailable estimates if no facility is modeled. Metrics use the first 14 days: mean unmet units, mean facility-days with unmet demand, and mean expiry units.

Facility detail also carries scenario/revision/SKU, path count and assumptions. `stock_trajectory` uses parallel day/P10/P50/P90 arrays; values are null when evidence is inadequate. Pending shipments include source ETA/status, `route_blocked`, and a nullable `projected_arrival_day` that accounts for scenario delays, closures, expiry, and the internal horizon.

## Plans and reviews

All policies use identical underlying sample paths. A proposal uses direct day-0 dispatches, exact SKU and batch allocations, configured directed routes, and positive integer quantities. Donors and recipients are disjoint. Every batch must remain usable at arrival. Multiple donors may serve the same recipient, and commitments are retained across all recipients.

The planner checks the entire proposal against pointwise P80 demand/arrival paths and a seven-day forward donor reserve after each displayed day. It also rejects any additional donor unmet demand on the sampled paths. The recommendation's donor-stock and reserve figures describe the tightest reserve-margin day after all proposed transfers.

A plan contains identity, scenario/revision/SKU, policy, DRAFT/APPROVED/REJECTED status, transfers, recommendations, metrics, residual deficit, constraint checks, notes, and coverage. Metrics include expected donor shortfall added, transfer units, total route distance, and unmet units avoided. `residual_deficit` is the ceiling of expected remaining unmet units over 14 days.

Generating the same immutable plan preserves its review status. Repeated identical reviews are idempotent. Approving another proposal demotes the previous selected proposal. Reviews do not alter stock; comparison simulations apply hypothetical transfers regardless of review status.

## Experimental heuristic endpoints

POST `/risk-scores`, `/fingerprints`, `/domino-index`, `/diffusion`, and `/analytics` under a scenario accept `sku_id` and `expected_revision`.

Anomaly risk levels include UNKNOWN with null scores. Fingerprint `rule_score` and legacy `confidence` are uncalibrated rule scores; `confidence_kind` is `heuristic_not_probability`. The legacy PANIC_HOARDING code is displayed as an isolated demand spike and is not a diagnosis of hoarding.

Domino estimates can be null for insufficient evidence. Graph diffusion declares `model_kind: heuristic_graph`, assumptions, unknown counts, and explicit timeline days. Regional graph scores are nullable and must not be rendered as percentages or substituted for sampled inventory probabilities.

## Not implemented

The plan's quantity-revision and CSV import endpoints are absent. Review events can be inspected through the repository API, but there is no public review-history endpoint or saved-scenario browser. Do not advertise these as available.
