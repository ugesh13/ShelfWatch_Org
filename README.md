# ShelfWatch

ShelfWatch is a local medicine-inventory decision-support prototype for the Manipal Hackathon. It forecasts shortages for exact medicine SKUs, compares direct redistribution proposals, and exposes remaining shortages and model assumptions.

The running stack is React 18 + TypeScript + Vite + Tailwind, Leaflet, Recharts, and FastAPI with NumPy and SQLite. The main forecast, depot-delay experiment, and transfer planner share one FEFO inventory simulator. Experimental anomaly, fingerprint, and graph-diffusion analyses are displayed separately as uncalibrated heuristics.

## Run locally

Use Python 3.12+ for the audited dependency lock, Node.js 22.12+ or a supported newer LTS release, and npm. Run these commands from the project root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. The Vite server proxies `/api` to the local backend. API documentation is at http://127.0.0.1:8000/docs. For runtime-only installation, use `backend/requirements.txt`; the development file also installs pytest and HTTP test dependencies.

Dependency versions in `requirements.txt` and `requirements-dev.txt` match the audited environment. `requirements.in` lists direct runtime dependencies. SQLite uses Python's standard library; SQLAlchemy, NetworkX, SciPy, pandas, and Faker are not required by the active application.

## Configuration and persistence

- `SHELFWATCH_DB`: SQLite file location. Defaults to `data/shelfwatch_v1.db` under this project. Set it to `:memory:` for an isolated disposable run.
- `SHELFWATCH_ALLOWED_ORIGINS`: comma-separated frontend origins for direct API requests; defaults to localhost/127.0.0.1 on port 3000.
- `SHELFWATCH_API_TARGET`: Vite development proxy target; defaults to `http://127.0.0.1:8000`.
- `VITE_API_BASE_URL`: optional frontend API base, including `/api`, baked in at build time. The default is `/api`.

Snapshots, immutable scenario revisions, generated plans, and review events persist in SQLite. Opening the dashboard starts a new scenario; there is currently no saved-scenario browser in the UI. An approval records a proposal review. It does not dispatch stock or change the snapshot.

## Verify

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest --tb=short -p no:cacheprovider
```

From `frontend`:

```powershell
npm run build
npm run test:e2e
```

Browser tests use headless Microsoft Edge on Windows, Chromium elsewhere, and isolated servers on ports 8041 and 3041 with an in-memory database. On other platforms install the Playwright Chromium browser first. Tests deliberately block online map tiles to check the offline schematic. Keep these two test ports free.

A static deployment must also serve or proxy `/api`; the production bundle does not embed the Python backend.

## Demo and model boundaries

The initial three-facility fixture has 140 unmet units without transfers. Its proposal moves 100 units from B to A and 40 from B to C. The other fixtures include delayed supply, demand increases, insufficient donors, expiry, closed routes, and incomplete records. Larger fixtures have 18 facilities and five SKUs.

Forecasts display 14 days from 200 reproducible sample paths, with 21 internal days for forward reserve checks. Unknown or stale evidence is excluded from regional totals and automatic planning. Donor checks apply to the sampled futures and the declared P80 planning case; they do not establish real-world clinical safety or forecast calibration.

CSV imports, manually revised transfer quantities, held-out model evaluation, and a UI for browsing saved scenarios/review history remain implementation-plan gaps. Details and verification evidence are recorded in [the audit report](docs/AUDIT_REPORT.md).

## Project references

- [Current implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Active API and model contracts](CONTRACTS.md)
- [Coding conventions](CONVENTIONS.md)
- [Current project state and audit session](memory.md)

The original attachment and older documentation describe earlier architectural proposals. They do not describe the current Vite application.
