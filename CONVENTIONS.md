# ShelfWatch — coding conventions

These conventions describe the active React/Vite and FastAPI code. Historical architecture notes are in `docs/legacy/`. Preserve the existing stack when fixing defects.

## Backend

Use snake_case for functions/files, PascalCase for models, and uppercase names for constants. Tunable simulation assumptions live in `backend/app/config.py`. Use exact `facility_id`, `sku_id`, `batch_id`, and `route_id` names. Legacy heuristic payloads retain `drug_id` for compatibility.

Pydantic models in `backend/app/schemas.py` validate inputs and reference integrity. Numerical services stay callable without HTTP. Existing service `run` aliases may be preserved, but use descriptive entry points in new call sites. Keep FEFO accounting in the single inventory simulator.

Treat stored snapshots and scenario revisions as immutable. Repository reads return detached models; all writes and revision checks use SQLite transactions. Do not silently overwrite a reviewed plan or catch calculation failures and return reassuring zeros.

Use the common success envelope. Raise explicit FastAPI errors for API validation; catch specific expected exceptions and log unexpected calculation failures. Keep patient data, medical substitution, and actual dispatch outside this prototype.

## Frontend

Use PascalCase component files, camelCase functions/state, and typed props. API field names keep the backend's snake_case spelling in TypeScript DTOs. All HTTP calls go through `src/lib/api.ts`.

This is a Vite client app: use `import.meta.env`, not Next.js environment conventions. No `use client` directive or Next.js router is needed. Abort obsolete read requests, guard async state against the current scenario/revision/SKU, and display partial failures explicitly.

Preserve null values for missing evidence. Never replace unknown probabilities with zero, label a heuristic score as confidence, label P50 as expected mean, or claim clinical safety from sampled donor checks. Review approval is a record, not dispatch.

Use existing Tailwind tokens and accessible native controls. Dialogs require modal semantics, labelled close controls, Escape handling, focus containment/restoration, and usable mobile layout. Keep visible keyboard focus, reduced-motion support, and text equivalents for map states.

Inventory map colors remain: Lower risk green, Watch amber, High risk red, Empty zinc, Unknown slate. Text labels must accompany colors. Charts must use actual API values; P10–P90 is a range between two quantiles.

## Verification and maintenance

Reproduce significant bugs with regression coverage, correct the root cause, and run relevant checks. For numerical changes verify accounting, shared random paths, donor constraints, and outcome consistency. Browser checks cover selection races, preserved assumptions, reviews, unknown evidence, and responsive controls.

Update `CONTRACTS.md` and all consumers when response semantics change. Update `memory.md` at the end of an audit or implementation session. Runtime packages are listed in `backend/requirements.in`; exact audited locks are `requirements.txt` and `requirements-dev.txt`. Keep the npm lockfile current.

Do not add packages for features that the application does not use. Explain necessary additions, and keep unsupported feature claims out of documentation and UI.
