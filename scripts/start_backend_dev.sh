#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "error: required command not found: $name" >&2
    exit 1
  fi
}

require_python_module() {
  local module_name="$1"
  if ! python3 - "$module_name" <<'PY'
import importlib.util
import sys

module_name = sys.argv[1]
if importlib.util.find_spec(module_name) is None:
    sys.exit(1)
PY
  then
    echo "error: required python module not found: $module_name" >&2
    exit 1
  fi
}

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

is_truthy() {
  local value
  value="$(lower "${1:-}")"
  [[ "$value" == "1" || "$value" == "true" || "$value" == "yes" || "$value" == "on" ]]
}

require_cmd python3

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  echo "warning: $ENV_FILE not found; using process environment only." >&2
fi

if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
  echo "error: ADMIN_PASSWORD is required for demo operations." >&2
  echo "hint: set ADMIN_PASSWORD in .env or your shell environment." >&2
  exit 1
fi

auth_backend="$(lower "${AUTH_STORE_BACKEND:-inmemory}")"
reminder_backend="$(lower "${REMINDER_STORE_BACKEND:-inmemory}")"
conversation_backend="$(lower "${CONVERSATION_STORE_BACKEND:-inmemory}")"
invoice_backend="$(lower "${INVOICE_STORE_BACKEND:-inmemory}")"

if [[ "$auth_backend" == "postgres" || "$reminder_backend" == "postgres" || "$conversation_backend" == "postgres" || "$invoice_backend" == "postgres" ]]; then
  require_python_module alembic

  if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "error: DATABASE_URL is required when a *_STORE_BACKEND is set to postgres." >&2
    exit 1
  fi

  echo "Running Alembic migrations (postgres backends enabled)..."
  (
    cd "$ROOT_DIR/backend"
    python3 -m alembic -c alembic.ini upgrade head
  )
fi

cd "$ROOT_DIR/backend"
echo "Starting backend on http://127.0.0.1:8000"

uvicorn_args=(invoicing_web.main:app --app-dir src)
if ! is_truthy "${BACKEND_DISABLE_RELOAD:-}"; then
  uvicorn_args+=(--reload)
else
  echo "info: BACKEND_DISABLE_RELOAD enabled; starting without --reload."
fi

exec python3 -m uvicorn "${uvicorn_args[@]}" "$@"
