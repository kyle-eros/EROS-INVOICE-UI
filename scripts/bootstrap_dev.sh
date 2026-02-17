#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

require_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "error: required command not found: $name" >&2
    exit 1
  fi
}

require_cmd python3
require_cmd npm

backend_deps_present() {
  python3 - <<'PY'
import importlib.util
import sys

for module_name in ("fastapi", "pytest"):
    if importlib.util.find_spec(module_name) is None:
        sys.exit(1)
PY
}

frontend_deps_present() {
  [[ -d "$ROOT_DIR/frontend/node_modules/next" ]] &&
    [[ -d "$ROOT_DIR/frontend/node_modules/eslint" ]] &&
    [[ -d "$ROOT_DIR/frontend/node_modules/eslint-config-next" ]]
}

echo "[1/2] Installing backend dependencies"
if backend_deps_present; then
  echo "Backend dependencies already available; skipping install."
else
  (
    cd "$ROOT_DIR/backend"
    python3 -m pip install -e ".[dev]"
  ) || {
    echo "error: backend dependency install failed (likely offline or package index unavailable)." >&2
    echo "hint: restore network/package index access or pre-install fastapi/pytest into python3." >&2
    exit 1
  }
fi

echo "[2/2] Installing frontend dependencies"
if frontend_deps_present; then
  echo "Frontend dependencies already available; skipping install."
else
  if [[ -f "$ROOT_DIR/frontend/package-lock.json" ]]; then
    if ! (
      cd "$ROOT_DIR/frontend"
      npm ci
    ); then
      echo "npm ci failed; retrying with npm install."
      (
        cd "$ROOT_DIR/frontend"
        npm install
      )
    fi
  else
    (
      cd "$ROOT_DIR/frontend"
      npm install
    )
  fi || {
    echo "error: frontend dependency install failed (likely offline or npm registry unavailable)." >&2
    echo "hint: restore npm registry access or provide pre-populated frontend/node_modules." >&2
    exit 1
  }
fi

echo "Bootstrap complete."
