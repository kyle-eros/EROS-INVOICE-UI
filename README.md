# EROS-Invoicing-Web

Standalone scaffold containing:
- `backend/`: FastAPI API for invoicing preview/confirm/run lifecycle plus invoice reminder automation
- `frontend/`: Next.js app with branded invoicing command UI and reminder operations panel

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
- `POST /api/v1/invoicing/invoices/upsert`
- `POST /api/v1/invoicing/payments/events`
- `GET /api/v1/invoicing/reminders/summary`
- `POST /api/v1/invoicing/reminders/run/once`
- `GET /api/v1/invoicing/reminders/escalations`

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
- Next.js app-router experience with EROS branded design system
- `app/page.tsx`: executive landing page
- `app/invoicing/page.tsx`: task queue + reminder operations panel
- `lib/api.ts`: backend API helper for tasks and reminder endpoints

## Reminder Automation (OpenClaw-ready)

The reminder pipeline is deterministic and run-once driven:
- Invoice state and reminder counters are stored in-memory.
- Payment updates arrive via API events (`/payments/events`).
- Reminder runs execute through `/reminders/run/once`.
- OpenClaw adapter is pluggable and defaults to dry-run-safe behavior.

Reminder policy defaults:
- First reminder at due date.
- Re-send cooldown: 48 hours.
- Stops when paid or opted out.
- Escalates to manual queue after 6 reminders.

### Invoice upsert payload example

```json
{
  "invoices": [
    {
      "invoice_id": "inv-2026-0001",
      "creator_id": "creator-123",
      "creator_name": "Creator Prime",
      "creator_timezone": "America/New_York",
      "contact_channel": "email",
      "contact_target": "creator@example.com",
      "currency": "USD",
      "amount_due": 4500.0,
      "amount_paid": 0.0,
      "issued_at": "2026-02-01",
      "due_date": "2026-02-10",
      "opt_out": false,
      "metadata": {"source": "erp-sync"}
    }
  ]
}
```

### Payment event payload example

```json
{
  "event_id": "payevt-2026-02-15-001",
  "invoice_id": "inv-2026-0001",
  "amount": 1200.0,
  "paid_at": "2026-02-15T14:30:00Z",
  "source": "bank-transfer",
  "metadata": {"batch": "2026-02-15"}
}
```

### Reminder run payload example

```json
{
  "dry_run": true,
  "limit": 50
}
```

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

## Environment Variables

Set these in the service environment (see `.env.example`):
- `INVOICING_APP_NAME`
- `INVOICING_API_PREFIX`
- `OPENCLAW_ENABLED`
- `OPENCLAW_DRY_RUN_DEFAULT`
- `OPENCLAW_CHANNEL`
- `OPENCLAW_API_BASE_URL`
- `OPENCLAW_API_KEY`
- `INVOICING_API_BASE_URL` (frontend server env)
