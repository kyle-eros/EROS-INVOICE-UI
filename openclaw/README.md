# OpenClaw Agent Configuration for EROS Invoicing

OpenClaw is a self-hosted messaging gateway used by EROS Invoicing to deliver payment reminders via email and SMS. This directory contains the gateway configuration, agent definitions, Docker sandbox setup, and security scripts.

## Architecture

```
+----------------------------------+
|  OpenClaw Gateway (Docker)       |
|  127.0.0.1:8080, sandbox=all    |
|                                  |
|  +---------------------+        |
|  | Invoice Monitor     | (read)  |
|  | Agent A             |        |
|  +----------+----------+        |
|             | broker token       |
|  +----------v----------+        |
|  | Notification        | (send)  |
|  | Sender Agent B      |        |
|  +----------+----------+        |
+-----------+----------------------+
            | HTTP via host.docker.internal
+-----------v----------------------+
|  EROS Backend (FastAPI)          |
|  localhost:8000                   |
|  /agent/* endpoints              |
|  (broker-token authenticated)    |
+----------------------------------+
```

## Directory Structure

```
openclaw/
├── openclaw.json                   # Master gateway configuration
├── agents/
│   ├── invoice-monitor.json        # Read-only invoice monitoring agent
│   └── notification-sender.json    # Send-only notification agent
├── docker/
│   ├── docker-compose.yml          # Docker sandbox orchestration
│   └── Dockerfile.gateway          # Custom gateway image
├── scripts/
│   ├── verify-setup.sh             # Security verification script
│   └── rotate-broker-token.sh      # Token rotation helper
└── README.md                       # This file
```

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose installed
- EROS backend running on localhost:8000
- Environment variables configured (see below)

### 2. Environment Variables

Set these before deploying:

```bash
export BROKER_TOKEN_SECRET="your-production-secret-here"
export OPENCLAW_API_KEY="your-openclaw-api-key"
export ADMIN_PASSWORD="your-admin-password"
export OPENCLAW_SENDER_TYPE="http"
export OPENCLAW_API_BASE_URL="http://127.0.0.1:8080"
```

### 3. Verify Security Posture

```bash
./scripts/verify-setup.sh
```

Fix all FAIL items before proceeding.

### 4. Start the Gateway

```bash
cd docker
docker compose up -d
```

### 5. Create Broker Tokens

```bash
# Invoice Monitor agent
./scripts/rotate-broker-token.sh invoice-monitor "invoices:read,reminders:read,reminders:summary"

# Notification Sender agent
./scripts/rotate-broker-token.sh notification-sender "reminders:run,reminders:read"
```

## Security Model

### Defense-in-Depth Layers

| Layer | Protection |
|-------|-----------|
| Network | Gateway bound to 127.0.0.1 only (Docker: `127.0.0.1:8080:8080`) |
| Auth | HMAC-SHA256 broker tokens, short TTL (60min default), narrow scopes |
| Isolation | Docker sandbox, read-only filesystem, `no-new-privileges` |
| Least Privilege | Per-agent tool allowlists, scope-restricted tokens |
| Redaction | PII masked in logs via `mask_contact_target()` and custom patterns |
| Fail-Closed | Missing/invalid/expired tokens = HTTP 401 |
| Revocation | Instant token revocation via admin endpoint |
| Audit | All actions traceable via `token_id` and structured error codes |

### Agent Permissions Matrix

| Capability | Invoice Monitor | Notification Sender |
|-----------|----------------|-------------------|
| `invoices:read` | Yes | No |
| `reminders:read` | Yes | Yes |
| `reminders:summary` | Yes | No |
| `reminders:run` | No | Yes |
| `send_email` | No | Yes |
| `send_sms` | No | Yes |
| `shell` / `exec` | No | No |
| `browser` | No | No |
| `file_write` | No | No |

### Token Rotation

Rotate broker tokens regularly using the provided script:

```bash
# Rotate with revocation of old token
OLD_TOKEN_ID="previous-token-id" ./scripts/rotate-broker-token.sh invoice-monitor "invoices:read,reminders:read,reminders:summary"
```

## Verification Checklist

Before deploying to production, verify:

- [ ] `BROKER_TOKEN_SECRET` is not using the default `dev-broker-secret`
- [ ] `ADMIN_PASSWORD` is not using a placeholder value
- [ ] `OPENCLAW_API_KEY` is set
- [ ] Gateway is bound to `127.0.0.1` only (not `0.0.0.0`)
- [ ] Docker containers have `no-new-privileges` and `read_only: true`
- [ ] Agent configs deny `shell`, `exec`, `browser`, `file_write`
- [ ] `~/.openclaw` directory has permissions `700`
- [ ] All broker tokens have appropriate scope restrictions
- [ ] `./scripts/verify-setup.sh` passes with zero failures
