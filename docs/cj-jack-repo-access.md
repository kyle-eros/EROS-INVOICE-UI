# Cj&Jack Private Repo Access Playbook

This playbook defines safe defaults before granting private-repo access to Cj&Jack.

Last verified against repository state: February 18, 2026.

## 1) Baseline Branch Protection (`main`)

Configure in GitHub:
- Require pull request before merge.
- Require at least 1 approval.
- Require review from CODEOWNERS.
- Dismiss stale approvals on new commits.
- Require status checks before merge:
  - `backend-tests`
  - `frontend-quality`
- Require conversation resolution before merge.
- Restrict direct pushes to maintainers.
- Require linear history.

## 2) Repository Roles

### Owner/Maintainer (engineering)
- Admin access.
- Can merge to `main`.
- Can change branch protection and secrets.

### Cj&Jack
- Default: `Read` access.
- Optional temporary `Triage` if issue/label support is needed.
- No direct push to protected branches.

## 3) Pull Request Policy

Every PR should use `.github/pull_request_template.md` and include:
- scope summary,
- risk level,
- validation evidence,
- rollback note for schema/runtime changes.

Mandatory test update requirement:
- any auth, payment, reminder, conversation, migration, or deployment change must include explicit test coverage changes.

## 4) Secrets And Token Guardrails Before Inviting Cj&Jack

Rotate all placeholder or development secrets:
- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`
- `CREATOR_SESSION_SECRET`
- `BROKER_TOKEN_SECRET`
- `CREATOR_MAGIC_LINK_SECRET` (legacy-named variable still guarded)
- `PAYMENT_WEBHOOK_SECRET_*` when payment webhook enforce mode is used
- `TWILIO_AUTH_TOKEN` when conversation webhook enforce mode is used and Twilio ingress is enabled
- `SENDGRID_INBOUND_SECRET` when conversation webhook enforce mode is used and SendGrid ingress is enabled

Production hardening defaults:
- `RUNTIME_SECRET_GUARD_MODE=enforce`
- `PAYMENT_WEBHOOK_SIGNATURE_MODE=enforce`
- `CONVERSATION_WEBHOOK_SIGNATURE_MODE=enforce`

Before invites:
- run secret scanner and resolve findings,
- confirm no passkeys/tokens/credentials in committed fixtures or screenshots,
- confirm broker-token scope usage follows least privilege.

## 5) Safe Demo Checklist For Cj&Jack

- CI green on latest `main`.
- Backend tests pass locally (`cd backend && python3 -m pytest -q`).
- Frontend lint/build pass locally (`cd frontend && npm run lint && npm run build`).
- Admin login flow verified.
- Passkey generation/revocation flow verified.
- Reminder evaluate/send flow verified.
- Conversation inbox visibility verified.
- Conversation webhook signature enforcement verified in staging.
- Payment webhook signature enforcement verified in staging.
- No sensitive credentials visible in URLs, logs, screenshots, or docs.
