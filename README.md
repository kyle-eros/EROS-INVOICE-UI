# EROS-Invoicing-Web

EROS Invoicing Web is a FastAPI + Next.js system for:
- invoice lifecycle operations,
- creator passkey auth and portal access,
- payment state and reconciliation,
- durable reminder evaluation/send workflows,
- guarded two-way creator conversations.

## Source Of Truth

This file is the canonical runtime and operator reference.

Supporting docs:
- OpenClaw runtime and agent hardening: `openclaw/README.md`
- Cj&Jack repo access and governance: `docs/cj-jack-repo-access.md`
- Frontend visual QA checklist: `frontend/docs/visual-qa-checklist.md`

Last verified against code: February 18, 2026.

## Architecture

### Backend
- Code: `backend/src/invoicing_web`
- App entrypoint: `invoicing_web.main:app`
- Router: `invoicing_web.api`
- Core stores:
  - `invoicing_web.store` (invoice/payment/reminder domain state)
  - `invoicing_web.reminder_runs` (durable reminder run/attempt/outbox/idempotency)
  - `invoicing_web.conversations` (conversation thread/message/event/dedup)

### Frontend
- Code: `frontend/`
- Admin dashboard: `frontend/app/admin/page.tsx`
- Creator login: `frontend/app/login/page.tsx`
- Creator portal: `frontend/app/portal/page.tsx`
- API helper: `frontend/lib/api.ts`

### OpenClaw
- Config and agent definitions: `openclaw/`
- Uses broker-token scoped `/agent/*` backend endpoints

## API Catalog

All paths are under `/api/v1/invoicing`.

### Core Invoicing
- `POST /preview`
- `POST /confirm/{task_id}`
- `POST /run/once`
- `GET /tasks`
- `GET /tasks/{task_id}`
- `GET /artifacts/{task_id}`
- `POST /invoices/upsert`
- `POST /invoices/dispatch`
- `POST /invoices/dispatch/{dispatch_id}/ack`

### Payments
- `POST /payments/events`
- `POST /payments/checkout-session`
- `POST /payments/ach/link-token` (admin auth required)
- `POST /payments/ach/exchange` (admin auth required)
- `POST /payments/webhooks/{provider}`
- `GET /payments/invoices/{invoice_id}/status`
- `GET /admin/reconciliation/cases` (admin auth required)
- `POST /admin/reconciliation/cases/{case_id}/resolve` (admin auth required)
- `GET /admin/payouts` (admin auth required)
- `GET /admin/payouts/{payout_id}` (admin auth required)

### Reminder Operations
- `GET /reminders/summary` (admin auth required)
- `POST /reminders/run/once` (admin auth required)
- `POST /reminders/evaluate` (admin auth required)
- `POST /reminders/runs/{run_id}/send` (admin auth required)
- `GET /reminders/escalations` (admin auth required)

### Conversation Webhooks (Provider Ingress)
- `POST /webhooks/twilio/inbound`
- `POST /webhooks/twilio/status`
- `POST /webhooks/bluebubbles/inbound`
- `POST /webhooks/bluebubbles/status`
- `POST /webhooks/sendgrid/inbound`
- `POST /webhooks/sendgrid/status`

### Admin Conversation Operations
- `GET /admin/conversations` (admin auth required)
- `GET /admin/conversations/{thread_id}` (admin auth required)
- `POST /admin/conversations/{thread_id}/handoff` (admin auth required)
- `POST /admin/conversations/{thread_id}/reply` (admin auth required)

### Admin Auth + Creator Directory
- `POST /admin/login`
- `GET /admin/session` (admin auth required)
- `GET /admin/runtime/security` (admin auth required)
- `GET /admin/creators` (admin auth required)

### Passkey Management (Admin)
- `POST /passkeys/generate` (admin auth required)
- `GET /passkeys` (admin auth required)
- `POST /passkeys/revoke` (admin auth required)

### Creator Auth + Session APIs
- `POST /auth/lookup`
- `POST /auth/confirm`
- `GET /me/invoices` (creator session required)
- `GET /me/invoices/{invoice_id}/pdf` (creator session required)

### Agent APIs (Broker Token)
- `GET /agent/reminders/summary`
- `GET /agent/invoices`
- `POST /agent/reminders/run/once`
- `GET /agent/reminders/escalations`
- `GET /agent/conversations/{thread_id}/context`
- `POST /agent/conversations/{thread_id}/suggest-reply`
- `POST /agent/conversations/{thread_id}/execute-action`
- `POST /agent/tokens` (admin auth required)
- `POST /agent/tokens/revoke` (admin auth required)

## Runtime Modes

### Reminders
- `dry_run=true`:
  - evaluates eligibility,
  - records run artifacts,
  - does not send messages.
- Live send options:
  - single-step: `POST /reminders/run/once` with `dry_run=false`,
  - two-step: `POST /reminders/evaluate`, then `POST /reminders/runs/{run_id}/send`.

### Conversations
- `CONVERSATION_ENABLED=true` enables webhook ingestion and thread APIs.
- `CONVERSATION_AUTOREPLY_ENABLED=true` allows policy-approved automated replies.
- Provider ingress is independently controlled by:
  - `CONVERSATION_PROVIDER_TWILIO_ENABLED`
  - `CONVERSATION_PROVIDER_SENDGRID_ENABLED`
  - `CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED`
- If auto-reply is disabled, inbound messages are still persisted and visible to admins.
- Providers are explicit opt-in for local/dev. Keep provider flags `false` unless that ingress is in use.

### Signature Validation Modes
- Payment webhooks: `PAYMENT_WEBHOOK_SIGNATURE_MODE=off|log_only|enforce`
- Conversation webhooks: `CONVERSATION_WEBHOOK_SIGNATURE_MODE=off|log_only|enforce`
- In conversation `enforce` mode, provider secrets are required only for providers explicitly enabled.

## Security Guardrails

### Reminder Guardrails
- Live reminder requests require idempotency key when `REMINDER_LIVE_REQUIRES_IDEMPOTENCY=true`.
- Reminder trigger requests are rate-limited.
- Eligibility enforces due-date, cooldown, opt-out, paid-state, and escalation threshold checks.
- Durable outbox tracks retries and dead-letter outcomes.
- Reminder summary last-run fields are sourced from durable reminder-run records.

### Conversation Guardrails
- Inbound webhook dedup is keyed by provider message identity.
- Policy layer can force `human_handoff` for risky content or low confidence.
- Auto-reply count is capped per thread.
- Agent conversation actions are scope-gated and policy-gated.
- Provider ingress can be toggled independently (`twilio`, `sendgrid`, `bluebubbles`).

### Auth + Token Guardrails
- Admin auth uses signed admin session tokens.
- Creator portal auth uses passkeys + signed creator session tokens.
- Broker tokens are scoped, short-lived, and revocable.

## Environment Variables

Use `.env.example` as baseline.

### App Core
- `INVOICING_APP_NAME`
- `INVOICING_API_PREFIX`

### Legacy OpenClaw Compatibility (fallback)
- `OPENCLAW_ENABLED`
- `OPENCLAW_DRY_RUN_DEFAULT`
- `OPENCLAW_CHANNEL`
- `OPENCLAW_API_BASE_URL`
- `OPENCLAW_API_KEY`
- `OPENCLAW_SENDER_TYPE`
- `OPENCLAW_TIMEOUT_SECONDS`

### Preferred Notifier Transport
- `NOTIFIER_ENABLED`
- `NOTIFIER_DRY_RUN_DEFAULT`
- `NOTIFIER_CHANNEL`
- `NOTIFIER_API_BASE_URL`
- `NOTIFIER_API_KEY`
- `NOTIFIER_SENDER_TYPE`
- `NOTIFIER_TIMEOUT_SECONDS`

### Reminder Controls
- `REMINDER_LIVE_REQUIRES_IDEMPOTENCY`
- `REMINDER_RUN_LIMIT_MAX`
- `REMINDER_ALLOW_LIVE_NOW_OVERRIDE`
- `REMINDER_TRIGGER_RATE_LIMIT_MAX`
- `REMINDER_TRIGGER_RATE_LIMIT_WINDOW_SECONDS`
- `REMINDER_STORE_BACKEND` (`inmemory` or `postgres`)

### Conversation Controls
- `CONVERSATION_ENABLED`
- `CONVERSATION_AUTOREPLY_ENABLED`
- `CONVERSATION_STORE_BACKEND` (`inmemory` or `postgres`)
- `CONVERSATION_CONFIDENCE_THRESHOLD`
- `CONVERSATION_MAX_AUTO_REPLIES`
- `CONVERSATION_WEBHOOK_SIGNATURE_MODE` (`off`, `log_only`, `enforce`)
- `CONVERSATION_WEBHOOK_MAX_AGE_SECONDS`
- `CONVERSATION_PROVIDER_TWILIO_ENABLED`
- `CONVERSATION_PROVIDER_SENDGRID_ENABLED`
- `CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED`
- `TWILIO_AUTH_TOKEN`
- `SENDGRID_INBOUND_SECRET`
- `BLUEBUBBLES_WEBHOOK_SECRET`
- In `CONVERSATION_WEBHOOK_SIGNATURE_MODE=enforce`, each secret is required only when its provider flag is enabled.

### Payment Controls
- `PAYMENTS_PROVIDER`
- `PAYMENTS_PROVIDER_NAME`
- `AGENCY_SETTLEMENT_ACCOUNT_LABEL`
- `PAYMENT_WEBHOOK_SIGNATURE_MODE`
- `PAYMENT_WEBHOOK_SIGNATURE_MAX_AGE_SECONDS`
- `PAYMENT_WEBHOOK_SECRET_DEFAULT`
- `PAYMENT_WEBHOOK_SECRET_STRIPE`
- `PAYMENT_WEBHOOK_SECRET_PLAID`

### Auth + Sessions
- `AUTH_STORE_BACKEND` (`inmemory` or `postgres`)
- `DATABASE_URL`
- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`
- `CREATOR_SESSION_SECRET`
- `CREATOR_SESSION_TTL_MINUTES`
- `COOKIE_SECURE`
- `BROKER_TOKEN_SECRET`
- `BROKER_TOKEN_DEFAULT_TTL_MINUTES`
- `BROKER_TOKEN_MAX_TTL_MINUTES`
- `RUNTIME_SECRET_GUARD_MODE` (`off`, `warn`, `enforce`)

### Legacy-Named Secret (still required)
- `CREATOR_MAGIC_LINK_SECRET`
  - Variable name is legacy, but it remains part of runtime secret guard checks.

### Proxy / Portal
- `CREATOR_PORTAL_BASE_URL`
- `TRUST_PROXY_HEADERS`
- `TRUSTED_PROXY_IPS`

### Frontend Server Env
- `INVOICING_API_BASE_URL`

## Developer Commands

### Bootstrap
```bash
./scripts/bootstrap_dev.sh
```

### Backend
```bash
cd backend
python3 -m pip install -e ".[dev]"
python3 -m uvicorn invoicing_web.main:app --app-dir src --reload
```

If startup fails with `runtime secret guard blocked startup`, either:
- disable unused conversation providers (`CONVERSATION_PROVIDER_*_ENABLED=false`), or
- configure the corresponding provider secret while enforce mode is enabled.

### Migrations
```bash
cd backend
alembic -c alembic.ini upgrade head
```

### Tests
```bash
cd backend
python3 -m pytest -q

cd ../frontend
npm run lint
npm run build
```

### Baseline Matrix
```bash
./scripts/check_baseline.sh
```

## Seed Workflow

CSV-to-invoice seed helpers are in `scripts/`:
- `scripts/seed_from_cb_reports.py`
- `scripts/test_cb_seed_flow.sh`
- `scripts/seed_grace_bennett.py`

By default, local seed scripts read source CSVs from the repo-local `data/` folder:
- `data/CB Daily Sales Report 2026 - February 2026.csv`
- `data/Creator statistics report 2026:01:17 to 2026:02:15.csv`

You can override file locations with CLI flags:
- `./scripts/test_cb_seed_flow.sh /path/to/sales.csv /path/to/creator.csv`
- `python3 scripts/seed_grace_bennett.py --sales-csv /path/to/sales.csv --stats-csv /path/to/creator.csv`

Artifacts default to `/tmp/cb-seed-artifacts` (or `/tmp/cb-seed-flow` for the shell helper).

## Governance

For Cj&Jack onboarding and branch governance, see `docs/cj-jack-repo-access.md`.
