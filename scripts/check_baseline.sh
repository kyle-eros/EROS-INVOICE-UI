#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILURES=0
FRONTEND_STATE_FILE="$ROOT_DIR/frontend/.next-mode-state"

run_step() {
  local label="$1"
  shift

  echo
  echo "==> $label"
  if "$@"; then
    echo "PASS: $label"
  else
    echo "FAIL: $label"
    FAILURES=$((FAILURES + 1))
  fi
}

run_backend_tests() {
  (
    cd "$ROOT_DIR/backend"
    python3 -m pytest -q
  )
}

run_frontend_preflight() {
  if [[ ! -f "$FRONTEND_STATE_FILE" ]]; then
    return 0
  fi

  local mode=""
  local pid=""

  while IFS='=' read -r key value; do
    case "$key" in
      mode) mode="$value" ;;
      pid) pid="$value" ;;
    esac
  done < "$FRONTEND_STATE_FILE"

  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "error: guarded Next process is active (mode=${mode:-unknown}, pid=$pid)." >&2
    echo "hint: stop the frontend dev/start server before running baseline checks." >&2
    return 1
  fi

  echo "warning: removing stale frontend guard file: $FRONTEND_STATE_FILE" >&2
  rm -f "$FRONTEND_STATE_FILE"
}

run_frontend_lint() {
  (
    cd "$ROOT_DIR/frontend"
    npm run lint
  )
}

run_frontend_build() {
  (
    cd "$ROOT_DIR/frontend"
    npm run build
  )
}

run_step "Backend tests (python3 -m pytest -q)" run_backend_tests
run_step "Frontend preflight (no active guarded Next process)" run_frontend_preflight
run_step "Frontend lint (npm run lint)" run_frontend_lint
run_step "Frontend build (npm run build)" run_frontend_build

echo
if [[ "$FAILURES" -eq 0 ]]; then
  echo "Baseline checks passed."
else
  echo "Baseline checks completed with $FAILURES failure(s)."
fi

exit "$FAILURES"
