#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILURES=0

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
run_step "Frontend lint (npm run lint)" run_frontend_lint
run_step "Frontend build (npm run build)" run_frontend_build

echo
if [[ "$FAILURES" -eq 0 ]]; then
  echo "Baseline checks passed."
else
  echo "Baseline checks completed with $FAILURES failure(s)."
fi

exit "$FAILURES"
