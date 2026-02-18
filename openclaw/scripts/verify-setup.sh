#!/usr/bin/env bash
set -euo pipefail

# EROS OpenClaw Security Verification Script
# Validates that the OpenClaw gateway and agent configuration meet security requirements.

PASS=0
FAIL=0
WARN=0

pass() { ((PASS++)); printf "  [PASS] %s\n" "$1"; }
fail() { ((FAIL++)); printf "  [FAIL] %s\n" "$1"; }
warn() { ((WARN++)); printf "  [WARN] %s\n" "$1"; }

echo "========================================"
echo "  EROS OpenClaw Security Verification"
echo "========================================"
echo ""

# --- 1. Gateway binding ---
echo "1. Gateway Network Binding"
if command -v docker &>/dev/null; then
    BINDING=$(docker port eros-openclaw-gateway 8080 2>/dev/null || echo "not_running")
    if [[ "$BINDING" == "not_running" ]]; then
        warn "OpenClaw container not running — skipping port check"
    elif [[ "$BINDING" == *"0.0.0.0"* ]]; then
        fail "Gateway bound to 0.0.0.0 — MUST be 127.0.0.1 only"
    else
        pass "Gateway bound to localhost only: $BINDING"
    fi
else
    warn "Docker not found — cannot verify port binding"
fi
echo ""

# --- 2. Config directory permissions ---
echo "2. Config Directory Permissions"
OPENCLAW_DIR="$HOME/.openclaw"
if [[ -d "$OPENCLAW_DIR" ]]; then
    DIR_PERMS=$(stat -f "%Lp" "$OPENCLAW_DIR" 2>/dev/null || stat -c "%a" "$OPENCLAW_DIR" 2>/dev/null)
    if [[ "$DIR_PERMS" == "700" ]]; then
        pass "~/.openclaw directory permissions: 700"
    else
        fail "~/.openclaw directory permissions: $DIR_PERMS (expected 700)"
    fi
else
    warn "~/.openclaw directory not found — will be created on first run"
fi
echo ""

# --- 3. Docker daemon ---
echo "3. Docker Daemon"
if command -v docker &>/dev/null && docker info &>/dev/null; then
    pass "Docker daemon is reachable"
else
    fail "Docker daemon not reachable — required for sandbox mode"
fi
echo ""

# --- 4. Environment secrets ---
echo "4. Environment Secrets"
if [[ "${BROKER_TOKEN_SECRET:-dev-broker-secret}" == "dev-broker-secret" ]]; then
    fail "BROKER_TOKEN_SECRET is using the default dev value"
else
    pass "BROKER_TOKEN_SECRET is set to a non-default value"
fi

if [[ -z "${OPENCLAW_API_KEY:-}" ]]; then
    fail "OPENCLAW_API_KEY is not set"
else
    pass "OPENCLAW_API_KEY is set"
fi

if [[ "${ADMIN_PASSWORD:-}" == "change-me-in-production" || -z "${ADMIN_PASSWORD:-}" ]]; then
    fail "ADMIN_PASSWORD is not set or using default placeholder"
else
    pass "ADMIN_PASSWORD is set to a non-default value"
fi
echo ""

# --- 5. Backend API ---
echo "5. Backend API Reachability"
if curl -sf http://localhost:8000/api/v1/invoicing/tasks &>/dev/null; then
    pass "Backend API reachable at localhost:8000"
else
    warn "Backend API not reachable at localhost:8000 — start the backend first"
fi
echo ""

# --- 6. Config file validation ---
echo "6. Configuration Files"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -f "$CONFIG_DIR/openclaw.json" ]]; then
    # Check gateway host binding in config
    if python3 -c "
import json, sys
with open('$CONFIG_DIR/openclaw.json') as f:
    config = json.load(f)
host = config.get('gateway', {}).get('host', '')
if host != '127.0.0.1':
    print(f'Gateway host is {host}, expected 127.0.0.1', file=sys.stderr)
    sys.exit(1)
sandbox = config.get('sandbox', {}).get('mode', '')
if sandbox != 'all':
    print(f'Sandbox mode is {sandbox}, expected all', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; then
        pass "openclaw.json: host=127.0.0.1, sandbox=all"
    else
        fail "openclaw.json: invalid gateway host or sandbox mode"
    fi
else
    fail "openclaw.json not found at $CONFIG_DIR/openclaw.json"
fi

for AGENT_FILE in "$CONFIG_DIR/agents"/*.json; do
    AGENT_NAME=$(basename "$AGENT_FILE" .json)
    if python3 -c "
import json, sys
with open('$AGENT_FILE') as f:
    config = json.load(f)
denied = config.get('tools', {}).get('denied', [])
required_denied = {'shell', 'exec', 'browser', 'file_write'}
missing = required_denied - set(denied)
if missing:
    print(f'Missing denied tools: {missing}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; then
        pass "Agent $AGENT_NAME: dangerous tools denied"
    else
        fail "Agent $AGENT_NAME: missing required tool denials"
    fi
done
echo ""

# --- Summary ---
echo "========================================"
printf "  Results: %d passed, %d failed, %d warnings\n" "$PASS" "$FAIL" "$WARN"
echo "========================================"

if [[ $FAIL -gt 0 ]]; then
    echo ""
    echo "  ACTION REQUIRED: Fix all FAIL items before deploying to production."
    exit 1
fi

exit 0
