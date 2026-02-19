# Demo Readiness Checklist

Use this checklist before every live demo run.

## 1) Baseline Quality Gate
- [ ] Run `./scripts/check_baseline.sh`
- [ ] Confirm backend tests, frontend lint, and frontend build all pass

## 2) Start Services
- [ ] In terminal A, run `./scripts/start_backend_dev.sh`
- [ ] In terminal B, run `./scripts/start_frontend_dev.sh`
- [ ] Confirm backend reachable at `http://localhost:8000/api/v1/invoicing/tasks`
- [ ] Confirm frontend reachable at `http://localhost:3000`

## 3) Seed Demo Data
- [ ] Run `./scripts/reseed_demo_data.sh`
- [ ] Confirm `demo_reseed_summary.json` was written under `/tmp/eros-90d-seed-artifacts` (or custom output dir)
- [ ] Confirm portal-ready creators are present after reseed

## 4) Run Demo Smoke
- [ ] Run `./scripts/demo_smoke.sh`
- [ ] Confirm smoke report exists at `/tmp/eros-demo-smoke-report.json`
- [ ] Confirm report includes `smoke_creator_id`, `smoke_invoice_id`, and non-zero `pdf_bytes`

## 5) Manual UI Sanity
- [ ] Admin gate: `http://localhost:3000/admin/gate`
- [ ] Admin dashboard loads creator directory and reminder metrics
- [ ] Creator Balances Owed section loads Jan full invoice + Feb current owed columns for the demo focus year
- [ ] Creator login: `http://localhost:3000/login`
- [ ] Creator portal only shows Jan/Feb demo-window invoices and invoice PDF view/download works

## 6) Recovery Drill
- [ ] Restart backend once
- [ ] Re-run `./scripts/reseed_demo_data.sh`
- [ ] Re-run `./scripts/demo_smoke.sh`
- [ ] Confirm smoke passes again after restart

## Notes
- Invoice/task state resets on restart only when `INVOICE_STORE_BACKEND=inmemory`.
- Auth/reminder/conversation/invoice state may be DB-backed depending on `*_STORE_BACKEND` env settings.
