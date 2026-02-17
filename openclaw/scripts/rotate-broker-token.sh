#!/usr/bin/env bash
set -euo pipefail

# EROS Broker Token Rotation Script
# Creates a new broker token for an agent and revokes the previous one.
#
# Usage:
#   ./rotate-broker-token.sh <agent_id> <scopes> [ttl_minutes]
#
# Example:
#   ./rotate-broker-token.sh invoice-monitor "invoices:read,reminders:read,reminders:summary"
#   ./rotate-broker-token.sh notification-sender "reminders:run,reminders:read" 120

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
API_PREFIX="${API_PREFIX:-/api/v1/invoicing}"

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <agent_id> <scopes> [ttl_minutes]"
    echo ""
    echo "  agent_id     Agent identifier (e.g., invoice-monitor)"
    echo "  scopes       Comma-separated scopes (e.g., invoices:read,reminders:read)"
    echo "  ttl_minutes  Token TTL in minutes (optional, default: server default)"
    echo ""
    echo "Environment variables:"
    echo "  ADMIN_PASSWORD   Required. Admin password for backend login."
    echo "  BACKEND_URL      Backend URL (default: http://localhost:8000)"
    echo "  OLD_TOKEN_ID     Token ID to revoke (optional)"
    exit 1
fi

AGENT_ID="$1"
SCOPES_CSV="$2"
TTL_MINUTES="${3:-}"

if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
    echo "ERROR: ADMIN_PASSWORD environment variable is required"
    exit 1
fi

echo "=== EROS Broker Token Rotation ==="
echo "Agent: $AGENT_ID"
echo "Scopes: $SCOPES_CSV"
echo ""

# Step 1: Admin login
echo "Step 1: Authenticating as admin..."
LOGIN_RESP=$(curl -sf -X POST "${BACKEND_URL}${API_PREFIX}/admin/login" \
    -H "Content-Type: application/json" \
    -d "{\"password\": \"${ADMIN_PASSWORD}\"}")

ADMIN_TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['session_token'])")
echo "  Authenticated successfully."
echo ""

# Step 2: Create new broker token
echo "Step 2: Creating new broker token..."
IFS=',' read -ra SCOPE_ARRAY <<< "$SCOPES_CSV"
SCOPES_JSON=$(python3 -c "
import json, sys
scopes = sys.argv[1:]
print(json.dumps(scopes))
" "${SCOPE_ARRAY[@]}")

TOKEN_BODY="{\"agent_id\": \"${AGENT_ID}\", \"scopes\": ${SCOPES_JSON}"
if [[ -n "$TTL_MINUTES" ]]; then
    TOKEN_BODY="${TOKEN_BODY}, \"ttl_minutes\": ${TTL_MINUTES}"
fi
TOKEN_BODY="${TOKEN_BODY}}"

TOKEN_RESP=$(curl -sf -X POST "${BACKEND_URL}${API_PREFIX}/agent/tokens" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -d "$TOKEN_BODY")

NEW_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
NEW_TOKEN_ID=$(echo "$TOKEN_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['token_id'])")
EXPIRES_AT=$(echo "$TOKEN_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['expires_at'])")

echo "  New token created."
echo "  Token ID: ${NEW_TOKEN_ID}"
echo "  Expires:  ${EXPIRES_AT}"
echo ""

# Step 3: Revoke old token (if provided)
if [[ -n "${OLD_TOKEN_ID:-}" ]]; then
    echo "Step 3: Revoking old token ${OLD_TOKEN_ID}..."
    curl -sf -X POST "${BACKEND_URL}${API_PREFIX}/agent/tokens/revoke" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -d "{\"token_id\": \"${OLD_TOKEN_ID}\"}" > /dev/null
    echo "  Old token revoked."
    echo ""
else
    echo "Step 3: No OLD_TOKEN_ID provided — skipping revocation."
    echo ""
fi

echo "=== Rotation Complete ==="
echo ""
echo "New broker token (save securely):"
echo "$NEW_TOKEN"
echo ""
echo "Token ID (for future revocation):"
echo "$NEW_TOKEN_ID"
