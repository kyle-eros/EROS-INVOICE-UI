# OpenClaw Runtime For EROS Invoicing

This directory contains the OpenClaw gateway and agent definitions used by EROS Invoicing.

Source of truth for application behavior remains backend code and `README.md`. This document is the source of truth for OpenClaw runtime setup and scope boundaries.

Last verified against code: February 18, 2026.

## OpenClaw Role In This System

OpenClaw is an orchestration layer for scoped agent actions. It is not the business source of truth.

Backend remains authoritative for:
- reminder eligibility and durability,
- conversation policy and handoff decisions,
- provider webhook verification and channel mapping (SMS/email/iMessage),
- session and broker-token auth enforcement,
- payment/reconciliation state.

## Directory Layout

```text
openclaw/
├── openclaw.json
├── agents/
│   ├── invoice-monitor.json
│   ├── notification-sender.json
│   └── creator-conversation.json
├── docker/
│   ├── Dockerfile.gateway
│   ├── docker-compose.yml
│   └── entrypoint.sh
├── scripts/
│   ├── rotate-broker-token.sh
│   └── verify-setup.sh
└── README.md
```

## Agents And Responsibilities

### 1) `invoice-monitor`
- Purpose: read-only invoice/reminder observability.
- Allowed tool: `http_request`.
- Scope: `invoices:read`, `reminders:read`, `reminders:summary`.

### 2) `notification-sender`
- Purpose: trigger reminder runs and monitor escalation queue.
- Allowed tools: `http_request`, `send_email`, `send_sms`.
- Scope: `reminders:run`, `reminders:read`.

### 3) `creator-conversation`
- Purpose: guarded two-way conversation workflow via backend policy gates.
- Allowed tool: `http_request`.
- Scope: `conversations:read`, `conversations:reply`.

## Endpoint Access By Agent

All endpoints below are backend paths under `/api/v1/invoicing`.

### invoice-monitor
- `GET /agent/reminders/summary`
- `GET /agent/invoices`
- `GET /agent/reminders/escalations`

### notification-sender
- `POST /agent/reminders/run/once`
- `GET /agent/reminders/escalations`

### creator-conversation
- `GET /agent/conversations/{thread_id}/context`
- `POST /agent/conversations/{thread_id}/suggest-reply`
- `POST /agent/conversations/{thread_id}/execute-action`

## Security Model

### Network + Isolation
- Gateway binds to loopback in Docker publish (`127.0.0.1:8080:8080`).
- Containers are read-only with `no-new-privileges`.
- Agent network allowlist points only to `host.docker.internal:8000`.

### Tool Boundaries
- Dangerous tools are denied by default (`shell`, `exec`, `browser`, `file_write`, `system.run`).
- Conversation agent does not get direct email/sms tools; it must execute through backend API policy gates.

### Auth Boundaries
- Backend agent endpoints require broker tokens.
- Tokens are scope-bound and revocable.
- Admin creates/revokes broker tokens via backend admin-auth endpoints.

## Setup

### 1) Required environment

```bash
export BROKER_TOKEN_SECRET="replace-with-strong-secret"
export OPENCLAW_API_KEY="replace-with-strong-key"
export ADMIN_PASSWORD="replace-with-strong-password"
export OPENCLAW_SENDER_TYPE="http"
export OPENCLAW_API_BASE_URL="http://127.0.0.1:8080"
```

### 2) Verify baseline

```bash
./scripts/verify-setup.sh
```

### 3) Start gateway

```bash
cd docker
docker compose up -d
```

## Broker Token Rotation

```bash
# invoice-monitor
./scripts/rotate-broker-token.sh invoice-monitor "invoices:read,reminders:read,reminders:summary"

# notification-sender
./scripts/rotate-broker-token.sh notification-sender "reminders:run,reminders:read"

# creator-conversation
./scripts/rotate-broker-token.sh creator-conversation "conversations:read,conversations:reply"
```

To revoke old token on rotation:

```bash
OLD_TOKEN_ID="<old-token-id>" ./scripts/rotate-broker-token.sh creator-conversation "conversations:read,conversations:reply"
```

## Verification Checklist

Before production use:
- [ ] `BROKER_TOKEN_SECRET` is not a placeholder.
- [ ] `ADMIN_PASSWORD` is not a placeholder.
- [ ] `OPENCLAW_API_KEY` is set.
- [ ] Gateway is localhost-bound only.
- [ ] Dangerous tools denied in all agent configs.
- [ ] `~/.openclaw` permissions are restricted (`700`).
- [ ] Broker token scopes match least privilege per agent.
- [ ] `./scripts/verify-setup.sh` passes cleanly.

## Operational Notes

- If backend conversation policy blocks an action, OpenClaw should not retry with bypass behavior.
- Keep conversation autonomy feature flags controlled in backend env:
  - `CONVERSATION_ENABLED`
  - `CONVERSATION_AUTOREPLY_ENABLED`
  - `CONVERSATION_PROVIDER_TWILIO_ENABLED`
  - `CONVERSATION_PROVIDER_SENDGRID_ENABLED`
  - `CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED`
- Enforce webhook signatures in production:
  - `CONVERSATION_WEBHOOK_SIGNATURE_MODE=enforce`
  - `PAYMENT_WEBHOOK_SIGNATURE_MODE=enforce`
