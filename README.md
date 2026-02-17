# EROS-Invoicing-Web

Standalone scaffold containing:
- `backend/`: FastAPI API for invoicing preview/confirm/run lifecycle
- `frontend/`: Next.js app skeleton with basic invoicing pages

## Architecture

### Backend (`backend/`)
- Source: `backend/src/invoicing_web`
- Entry point: `invoicing_web.main:app`
- API router: `invoicing_web.api`
- Deterministic in-memory store: `invoicing_web.store`
- Models: `invoicing_web.models`
- Contract compatibility: accepts legacy preview payload shape used by `EROS_TUI_CRM_BUNDLE` bridge

Endpoints:
- `POST /api/v1/invoicing/preview`
- `POST /api/v1/invoicing/confirm/{task_id}`
- `POST /api/v1/invoicing/run/once`
- `GET /api/v1/invoicing/tasks`
- `GET /api/v1/invoicing/tasks/{task_id}`
- `GET /api/v1/invoicing/artifacts/{task_id}`

Preview payload example:

```json
{
  "agent_slug": "payout-reconciliation",
  "window_start": "2026-02-01",
  "window_end": "2026-02-28",
  "source_refs": ["/tmp/exports/invoices.csv"],
  "mode": "plan_only",
  "idempotency_key": "invoicing-feb-2026",
  "principal_employee_id": "employee-123",
  "metadata": {"legacy_command": "preview-invoicing"}
}
```

### Frontend (`frontend/`)
- Next.js app-router skeleton
- `app/page.tsx`: landing page
- `app/invoicing/page.tsx`: basic task list page
- `lib/api.ts`: backend API helper

## Run Commands

### Bootstrap (backend + frontend)
```bash
./scripts/bootstrap_dev.sh
```

Notes:
- Uses `python3` explicitly for backend tooling.
- Uses `npm ci` when `frontend/package-lock.json` is present; otherwise falls back to `npm install`.

### Backend
```bash
cd backend
python3 -m pip install -e ".[dev]"
python3 -m uvicorn invoicing_web.main:app --app-dir src --reload
```

### Backend tests
```bash
cd backend
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Baseline checks (exact matrix)
```bash
./scripts/check_baseline.sh
```
Runs:
- `cd backend && python3 -m pytest -q`
- `cd frontend && npm run lint`
- `cd frontend && npm run build`

### TUI bridge integration

Set these in `EROS_TUI_CRM_BUNDLE/.env` to route legacy invoicing CLI/tools into this backend:

```bash
INVOICING_WEB_BASE_URL=http://localhost:8000
INVOICING_WEB_LEGACY_SHIM_ENABLED=true
```
