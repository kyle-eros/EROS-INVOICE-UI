#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
FRONTEND_ENV_FILE="$ROOT_DIR/frontend/.env.local"

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "error: required command not found: $name" >&2
    exit 1
  fi
}

require_cmd npm

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -z "${INVOICING_API_BASE_URL:-}" && -f "$FRONTEND_ENV_FILE" ]]; then
  frontend_api_base_url="$(awk -F= '/^INVOICING_API_BASE_URL=/{print substr($0, index($0, "=")+1); exit}' "$FRONTEND_ENV_FILE" || true)"
  if [[ -n "$frontend_api_base_url" ]]; then
    export INVOICING_API_BASE_URL="$frontend_api_base_url"
    echo "Using INVOICING_API_BASE_URL from frontend/.env.local: $INVOICING_API_BASE_URL"
  fi
fi

if [[ -z "${INVOICING_API_BASE_URL:-}" ]]; then
  export INVOICING_API_BASE_URL="http://localhost:8000"
  echo "warning: INVOICING_API_BASE_URL not set; defaulting to $INVOICING_API_BASE_URL" >&2
fi

cd "$ROOT_DIR/frontend"
echo "Starting frontend on http://127.0.0.1:3000"
if [[ $# -gt 0 ]]; then
  exec npm run dev -- "$@"
fi
exec npm run dev
