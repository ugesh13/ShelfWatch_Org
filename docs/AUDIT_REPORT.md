# ShelfWatch — deep implementation audit

Date: 16 September 2026. Scope: inspect the implementation against the supplied Desktop plan and the newer repository implementation plan, reproduce defects, correct them, and verify the existing application. The documents were treated as design references, not independent authorization to build every proposed feature.

The running React/Vite and FastAPI stack was preserved. Source changes are applied directly in this workspace, which has no Git repository. The starting source is preserved in `.audit/before-audit-20260916-213731.zip` (45 files).

## Corrected findings

Priority indicates the defect's impact before correction. P1 covers incorrect results, lost state, or misleading decisions; P2 covers narrower logic, validation, integration, and interaction failures.

| Priority | Finding and consequence | Correction and main files |
| --- | --- | --- |
| P1 | The repository advertised persistence/immutability but kept mutable process-local state; restarts lost scenarios and reviews, and concurrent edits could race. | Real transactional SQLite storage, detached reads, atomic revision checks, durable plans/reviews in `backend/app/database.py`. |
| P1 | Regenerating plans reset review status, different SKUs could share plan IDs, and multiple alternatives could remain approved. | Scenario/revision/SKU/policy/version-scoped IDs; immutable saved proposals; preserved recommendation/review status; one selected proposal; idempotent review and stale-revision rejection. |
| P1 | The planner stopped after one donor even when another could close a recipient's deficit. Donor figures could describe an intermediate proposal. | Repeat recipient allocation while useful candidates remain; retain all batch commitments; recompute reserve and harm checks for the complete proposal. |
| P1 | Missing or stale evidence became reassuring zero probabilities, stock trajectories, and aggregate metrics. | Null unavailable estimates, explicit Unknown states, excluded-facility coverage, and eligibility filtering throughout forecasts, plans, impact, graph analytics, and UI. |
| P1 | Changing medicine could recreate/reset the selected scenario. Late async responses and assumption edits could overwrite the active context or unrelated overrides. | Cancellable requests, guarded scenario/revision/SKU context, separate initialization, explicit partial failures, and preservation of unrelated assumptions/windows. |
| P1 | Heuristic scores and UI copy implied probability, confirmed hoarding, clinical safety, optimality, or real dispatch. | Label experimental graph/rule scores explicitly; show isolated spikes as a pattern; report sampled donor checks and simulated proposal reviews. |
| P2 | Adding the standard depot shock to a valid 14-day scenario delay exceeded request-model limits and failed. | Perturb paired shipment arrival paths directly; retain horizon/coverage metadata in `impact.py`. |
| P2 | Residual shortfall included the internal reserve horizon, donor losses could be counted repeatedly, and first-shortfall quantiles interpolated a sentinel into fictional dates. | Consistent displayed-horizon residuals, unique donor accounting, and discrete censored shortfall timing. |
| P2 | Anomalies used capped fulfillment or historical closing stock instead of requested demand and current batches; historical windows could overlap or include inappropriate records. | Requested-demand features, current unexpired observations, past-only windows, evidence checks, and honest supporting-factor text. |
| P2 | Graph projections could recover from blocked/expired deliveries, ignore scenario changes, double-count routes, or miscount tied shortest paths. | Scenario-aware usable receipts, complete timelines, unknown masks, edge deduplication, and weighted Brandes centrality. These remain heuristics. |
| P2 | Invalid SKUs/assumption targets/path arrays were accepted or produced server errors; CORS allowed an unnecessarily broad credential configuration. | Central reference and revision checks, strict array/unit validation, clear 422/409 responses, configurable origins without wildcard credentials. |
| P2 | Map playback retained stockout states after replenishment; charts filled separate areas to zero; the drawer used unchanged source ETAs. | Actual daily simulation states, a P10–P90 range with median line, and scenario-adjusted usable arrival estimates. |
| P2 | The drawer lacked modal keyboard behavior, the custom route switch had a poor input target/focus indicator, and narrow controls were squeezed. | Native modal dialog with explicit Tab boundaries, Escape and focus restoration; operable switch target and focus styles; responsive controls and reduced-motion support. |
| P2 | README/contracts described obsolete stacks, models and capabilities, and Python requirements did not match the tested application. | Reconciled active documentation; separate audited runtime/test locks; removed unused runtime dependencies; added browser test tooling. |

The current algorithm identifier is `inventory-1.1`, which separates plan identities from earlier numerical behavior.

## Verification record

- **Backend: 60 tests passed**, including 44 additional regression/boundary cases beyond the starting 16-test suite. Coverage includes SQLite restart and concurrent revision edits, review idempotency, invalid targets, unknown evidence, multi-donor rescue, full-plan reserves, FEFO/expiry, future-data exclusion, and horizon boundaries.
- **Exhaustive quantity checks:** four demand/arrival combinations enumerate every available donor quantity and confirm the greedy search chooses the smallest quantity achieving the maximum feasible shortage reduction.
- **API smoke coverage:** 112 analytical requests across all ten fixtures and every available SKU passed, plus ten facility-detail requests. All policies' required constraint checks passed. Results are recorded in `.audit/api-smoke.json`.
- **Optimization parity:** all 30 complete policy-plan payloads matched exactly across ten fixtures before/after reducing repeated feasibility and unrelated-recipient simulations. This comparison was performed before the intentional algorithm-version increment. Evidence is in `.audit/planner-before.json` and `.audit/planner-after.json`.
- **Frontend: production TypeScript/Vite build passed; all ten browser regressions passed** in headless Microsoft Edge (53.2 seconds for the final suite). Checks cover SKU/fixture preservation, unrelated assumptions, persistent approvals, obsolete responses, unknown evidence, maximum depot delay, mobile layout, failed-request recovery, modal focus, and closed routes. Desktop and 390-pixel mobile screenshots were also inspected.
- **Dependencies:** the installed Python dependency check passed. The npm dependency installation reported no known vulnerabilities. Runtime locks record the packages actually used and tested; a separate clean-machine installation was not performed.

The tests confirm the deterministic example: baseline unmet demand is 140 units; transfers of 100 from B to A and 40 from B to C remove that modeled deficit. B's tightest closing stock is 235 against a 175-unit reserve. Doubling A's demand leaves a 100-unit residual after the 200-unit donor limit; closing B→A leaves A's shortage unresolved. These are fixture results, not clinical validation.

Commands from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest --tb=short -p no:cacheprovider
```

Commands from `frontend`:

```powershell
npm run build
npm run test:e2e
```

The browser suite uses temporary local servers and an in-memory database; online map tiles are blocked intentionally. The schematic, calculations, and reviews remain functional without the basemap. Windows sandbox restrictions required approved host execution for Vite/browser verification. The failed sandbox startup's temporary server was identified and stopped before rerunning; unrelated processes were left alone.

Source comparison is recorded in `.audit/change-manifest.json`. Audit screenshots are retained in `.audit/screenshots/`. The original ZIP covers 45 selected source/configuration files; the manifest labels other edited files that were outside that backup.

## Remaining implementation-plan gaps and limits

1. **Transfer quantity revisions:** schemas exist, but the planned revision/revalidation endpoint and quantity-edit UI do not. Current approve/reject operations are implemented and verified.
2. **CSV import:** validate/commit endpoints from the extended plan are absent. The application uses seeded fixtures and stored snapshots.
3. **Saved-state navigation:** scenarios and review events now persist, but the dashboard starts a new scenario on opening and has no saved-scenario/review-history browser.
4. **Model validation:** held-out calibration, Brier scores, interval coverage, and independent future-policy evaluation have not been implemented. Graph diffusion and fingerprint labels are explicitly experimental. Sampled no-harm checks do not guarantee unseen outcomes.
5. **Performance:** the server is synchronous, and larger fixture calculations take longer than the deterministic example. Repeated checks within a candidate are cached; process-wide analysis caching from the plan remains absent. The production bundle still produces Vite's size advisory (approximately 947 kB JavaScript before gzip, 273 kB gzip).

Two third-party Python test deprecation warnings remain (Starlette/httpx and AnyIO). They do not fail the suite. Authentication, live integrations, cold-chain handling, patient-flow modeling, and actual dispatch remain outside this prototype's declared scope.

The audit corrected verified defects in the implemented workflows. It does not represent completion of every feature in either design document or certification for operational healthcare use.
