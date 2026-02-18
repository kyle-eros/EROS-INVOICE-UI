#!/usr/bin/env bash
set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$FRONTEND_DIR/.next"
STATE_FILE="$FRONTEND_DIR/.next-mode-state"
LAST_MODE_FILE="$FRONTEND_DIR/.next-last-mode"

usage() {
  cat <<'EOF'
Usage: bash ./scripts/next-safe.sh <command> [next-args...]

Commands:
  dev     Start next dev with lifecycle guardrails.
  build   Run next build with lifecycle guardrails and artifact validation.
  start   Run next start with lifecycle guardrails.
  clean   Remove frontend .next artifacts and guard state files.
  status  Print lifecycle guard status.
EOF
}

fail() {
  echo "error: $*" >&2
  exit 1
}

is_pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

STATE_MODE=""
STATE_PID=""
STATE_STARTED_AT=""
STATE_COMMAND=""

read_state_file() {
  STATE_MODE=""
  STATE_PID=""
  STATE_STARTED_AT=""
  STATE_COMMAND=""

  if [[ ! -f "$STATE_FILE" ]]; then
    return 0
  fi

  while IFS='=' read -r key value; do
    case "$key" in
      mode) STATE_MODE="$value" ;;
      pid) STATE_PID="$value" ;;
      started_at) STATE_STARTED_AT="$value" ;;
      command) STATE_COMMAND="$value" ;;
    esac
  done < "$STATE_FILE"
}

write_state_file() {
  local mode="$1"
  local command="$2"
  cat > "$STATE_FILE" <<EOF
mode=$mode
pid=$$
started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
command=$command
EOF
}

clear_state_file() {
  rm -f "$STATE_FILE"
}

clear_stale_state_if_needed() {
  read_state_file
  if [[ -f "$STATE_FILE" ]] && ! is_pid_alive "$STATE_PID"; then
    echo "warning: removing stale Next state file ($STATE_FILE)."
    clear_state_file
  fi
}

active_state_guard_or_fail() {
  read_state_file
  if [[ -f "$STATE_FILE" ]] && is_pid_alive "$STATE_PID" && [[ "$STATE_PID" != "$$" ]]; then
    if [[ "$STATE_MODE" == "dev" ]]; then
      fail "next dev is currently running (pid=$STATE_PID). Stop it first (Ctrl+C in dev terminal or: kill $STATE_PID)."
    fi
    fail "another guarded Next process is running (mode=${STATE_MODE:-unknown}, pid=$STATE_PID). Stop it first."
  fi
}

record_last_mode() {
  local mode="$1"
  echo "$mode" > "$LAST_MODE_FILE"
}

read_last_mode() {
  if [[ -f "$LAST_MODE_FILE" ]]; then
    cat "$LAST_MODE_FILE"
  else
    echo ""
  fi
}

clean_on_mode_switch_if_needed() {
  local target_mode="$1"
  local previous_mode
  previous_mode="$(read_last_mode)"

  if [[ "$target_mode" == "$previous_mode" ]]; then
    return 0
  fi

  if [[ -d "$DIST_DIR" ]]; then
    echo "info: detected mode switch (${previous_mode:-none} -> $target_mode); cleaning $DIST_DIR to avoid mixed artifacts."
    rm -rf "$DIST_DIR"
  fi
}

entrypoint_has_chunk_resolution_error() {
  local entrypoint="$1"
  local output=""

  if [[ ! -f "$entrypoint" ]]; then
    return 1
  fi

  if output="$(node -e 'require(process.argv[1])' "$entrypoint" 2>&1)"; then
    return 1
  fi

  if [[ "$output" == *"Cannot find module './"* ]] && [[ "$output" == *"/.next/server/webpack-runtime.js"* ]]; then
    return 0
  fi

  return 1
}

clean_inconsistent_runtime_artifacts_if_needed() {
  if [[ ! -d "$DIST_DIR/server" ]]; then
    return 0
  fi

  local entrypoints=(
    "$DIST_DIR/server/app/page.js"
    "$DIST_DIR/server/app/_not-found.js"
    "$DIST_DIR/server/pages/_document.js"
  )
  local entrypoint

  for entrypoint in "${entrypoints[@]}"; do
    if entrypoint_has_chunk_resolution_error "$entrypoint"; then
      echo "warning: detected stale/mixed Next runtime artifacts (chunk resolution failed in $entrypoint)."
      echo "info: cleaning $DIST_DIR before continuing."
      rm -rf "$DIST_DIR"
      return 0
    fi
  done
}

validate_runtime_artifacts_or_fail() {
  local context="$1"
  local required_paths=(
    "$DIST_DIR/server"
    "$DIST_DIR/server/app"
    "$DIST_DIR/server/webpack-runtime.js"
  )
  local missing=()
  local has_chunk_artifacts=0

  for path in "${required_paths[@]}"; do
    if [[ ! -e "$path" ]]; then
      missing+=("$path")
    fi
  done

  if [[ -d "$DIST_DIR/server/chunks" ]] && find "$DIST_DIR/server/chunks" -maxdepth 1 -type f -name '*.js' | grep -q .; then
    has_chunk_artifacts=1
  fi
  if [[ -d "$DIST_DIR/server/vendor-chunks" ]] && find "$DIST_DIR/server/vendor-chunks" -maxdepth 1 -type f -name '*.js' | grep -q .; then
    has_chunk_artifacts=1
  fi

  if [[ "$has_chunk_artifacts" -eq 0 ]]; then
    missing+=("$DIST_DIR/server/chunks/*.js or $DIST_DIR/server/vendor-chunks/*.js")
  fi

  if command -v rg >/dev/null 2>&1; then
    if rg -n "vendor-chunks/next\\.js" "$DIST_DIR/server/app" -g '*.js' >/dev/null 2>&1 && [[ ! -f "$DIST_DIR/server/vendor-chunks/next.js" ]]; then
      missing+=("$DIST_DIR/server/vendor-chunks/next.js (referenced by compiled app route)")
    fi
  elif grep -R -n --include='*.js' "vendor-chunks/next.js" "$DIST_DIR/server/app" >/dev/null 2>&1 && [[ ! -f "$DIST_DIR/server/vendor-chunks/next.js" ]]; then
    missing+=("$DIST_DIR/server/vendor-chunks/next.js (referenced by compiled app route)")
  fi

  if entrypoint_has_chunk_resolution_error "$DIST_DIR/server/app/page.js"; then
    missing+=("$DIST_DIR/server/app/page.js cannot resolve required chunks via webpack-runtime.js (mixed or stale .next artifacts)")
  fi
  if entrypoint_has_chunk_resolution_error "$DIST_DIR/server/app/_not-found.js"; then
    missing+=("$DIST_DIR/server/app/_not-found.js cannot resolve required chunks via webpack-runtime.js (mixed or stale .next artifacts)")
  fi
  if entrypoint_has_chunk_resolution_error "$DIST_DIR/server/pages/_document.js"; then
    missing+=("$DIST_DIR/server/pages/_document.js cannot resolve required chunks via webpack-runtime.js (mixed or stale .next artifacts)")
  fi

  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "error: Next runtime artifact validation failed after '$context':" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    echo "hint: run 'npm run clean && npm run build'." >&2
    exit 1
  fi
}

release_guard_on_exit() {
  clear_state_file
}

status_command() {
  read_state_file
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "next-safe status: idle (no active guard file)."
    return 0
  fi

  if is_pid_alive "$STATE_PID"; then
    echo "next-safe status: active mode=${STATE_MODE:-unknown} pid=$STATE_PID started_at=${STATE_STARTED_AT:-unknown}."
    return 0
  fi

  echo "next-safe status: stale state file present (mode=${STATE_MODE:-unknown}, pid=${STATE_PID:-unknown})."
  return 0
}

dev_command() {
  clear_stale_state_if_needed
  active_state_guard_or_fail
  clean_on_mode_switch_if_needed "dev"
  clean_inconsistent_runtime_artifacts_if_needed
  record_last_mode "dev"

  write_state_file "dev" "next dev"
  trap release_guard_on_exit EXIT INT TERM

  cd "$FRONTEND_DIR"
  next dev "$@"
}

build_command() {
  clear_stale_state_if_needed
  active_state_guard_or_fail
  clean_on_mode_switch_if_needed "prod"
  clean_inconsistent_runtime_artifacts_if_needed
  record_last_mode "prod"

  write_state_file "build" "next build"
  trap release_guard_on_exit EXIT INT TERM

  cd "$FRONTEND_DIR"
  next build "$@"
  validate_runtime_artifacts_or_fail "next build"
}

start_command() {
  clear_stale_state_if_needed
  active_state_guard_or_fail
  clean_on_mode_switch_if_needed "prod"
  record_last_mode "prod"
  validate_runtime_artifacts_or_fail "next start preflight"

  write_state_file "start" "next start"
  trap release_guard_on_exit EXIT INT TERM

  cd "$FRONTEND_DIR"
  next start "$@"
}

clean_command() {
  clear_stale_state_if_needed
  active_state_guard_or_fail

  rm -rf "$DIST_DIR"
  rm -f "$STATE_FILE" "$LAST_MODE_FILE"
  echo "next-safe clean: removed $DIST_DIR and guard state files."
}

command="${1:-}"
if [[ -z "$command" ]]; then
  usage
  exit 1
fi
shift || true

case "$command" in
  dev)
    dev_command "$@"
    ;;
  build)
    build_command "$@"
    ;;
  start)
    start_command "$@"
    ;;
  clean)
    clean_command
    ;;
  status)
    status_command
    ;;
  *)
    usage
    fail "unknown command: $command"
    ;;
esac
