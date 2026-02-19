#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
ROUTE="/admin/gate"
TMP_DIR="$(mktemp -d "/tmp/next-dev-css-diagnose.XXXXXX")"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

section() {
  echo
  echo "=== $1 ==="
}

normalize_css_ref() {
  local ref="$1"
  # Normalize escaped variants seen in inline JSON/script payloads.
  ref="${ref#href=\"}"
  ref="${ref%\"}"
  ref="${ref%\\}"
  printf '%s\n' "$ref"
}

is_pid_descendant_of() {
  local ancestor="$1"
  local pid="$2"
  local current="$pid"
  local ppid=""

  while [[ -n "$current" && "$current" != "0" ]]; do
    if [[ "$current" == "$ancestor" ]]; then
      return 0
    fi
    ppid="$(ps -o ppid= -p "$current" 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ -z "$ppid" || "$ppid" == "$current" ]]; then
      break
    fi
    current="$ppid"
  done

  return 1
}

safe_cat() {
  local path="$1"
  if [[ -f "$path" ]]; then
    cat "$path"
  else
    echo "<missing>"
  fi
}

probe_url() {
  local base_url="$1"
  local name
  name="$(echo "$base_url" | tr '/:' '_')"
  local html_file="$TMP_DIR/${name}_gate.html"
  local hdr_file="$TMP_DIR/${name}_gate.headers"
  local http_code

  echo "target=${base_url}${ROUTE}"
  http_code="$(curl -sS -D "$hdr_file" -o "$html_file" -w "%{http_code}" "${base_url}${ROUTE}" 2>/dev/null || true)"
  echo "http_code=$http_code"

  if [[ "$http_code" != "200" ]]; then
    echo "result=unreachable_or_non_200"
    echo "headers:"
    sed -n '1,20p' "$hdr_file" || true
    return 0
  fi

  local css_refs=()
  if command -v rg >/dev/null 2>&1; then
    while IFS= read -r ref; do
      ref="$(normalize_css_ref "$ref")"
      [[ -n "$ref" ]] || continue
      css_refs+=("$ref")
    done < <(rg -o 'href="/_next/static/css[^"]+"' "$html_file" | sort -u)
  else
    while IFS= read -r ref; do
      ref="$(normalize_css_ref "$ref")"
      [[ -n "$ref" ]] || continue
      css_refs+=("$ref")
    done < <(grep -Eo 'href="/_next/static/css[^"]+"' "$html_file" | sort -u || true)
  fi

  if [[ "${#css_refs[@]}" -eq 0 ]]; then
    echo "css_refs=none_found_in_html"
    return 0
  fi

  echo "css_refs_count=${#css_refs[@]}"
  local bad_css=0
  local ref code plain code_plain
  for ref in "${css_refs[@]}"; do
    code="$(curl -sS -o /dev/null -w "%{http_code}" "${base_url}${ref}" 2>/dev/null || true)"
    plain="${ref%%\?*}"
    code_plain="$(curl -sS -o /dev/null -w "%{http_code}" "${base_url}${plain}" 2>/dev/null || true)"
    echo "css_ref=$ref status=$code plain_status=$code_plain"
    if [[ "$code" != "200" ]]; then
      bad_css=1
    fi
  done

  if [[ "$bad_css" -eq 1 ]]; then
    echo "css_health=broken"
  else
    echo "css_health=ok"
  fi
}

section "Context"
echo "timestamp_utc=$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "repo=$ROOT_DIR"
echo "frontend_dir=$FRONTEND_DIR"

section "Tool Versions"
echo "node=$(node -v 2>/dev/null || echo '<missing>')"
echo "npm=$(npm -v 2>/dev/null || echo '<missing>')"
next_declared="$(
  node -e "const p=require(process.argv[1]); process.stdout.write((p.dependencies && p.dependencies.next) || '<missing>')" \
    "$FRONTEND_DIR/package.json" 2>/dev/null || echo '<missing>'
)"
next_installed="$(
  cd "$FRONTEND_DIR" && node -e "process.stdout.write(require('next/package.json').version)" 2>/dev/null || echo '<missing>'
)"
echo "next_declared=$next_declared"
echo "next_installed=$next_installed"

section "Next Guard Files"
echo ".next-last-mode:"
safe_cat "$FRONTEND_DIR/.next-last-mode"
echo
echo ".next-mode-state:"
safe_cat "$FRONTEND_DIR/.next-mode-state"

section "next-safe Status"
(cd "$FRONTEND_DIR" && npm run status) || true

section "Port 3000 Listener"
lsof -iTCP:3000 -sTCP:LISTEN -n -P || true

section "Related Processes"
ps -ef 2>/dev/null | grep -E 'next-safe\.sh|next dev|next start|next-server \(v' | grep -v grep || true

section ".next Artifact Snapshot"
if [[ -d "$FRONTEND_DIR/.next" ]]; then
  echo "BUILD_ID=$(safe_cat "$FRONTEND_DIR/.next/BUILD_ID")"
  ls -la "$FRONTEND_DIR/.next" | sed -n '1,80p'
  echo "static_css_files:"
  find "$FRONTEND_DIR/.next/static/css" -maxdepth 3 -type f 2>/dev/null | sed -n '1,80p' || true
else
  echo ".next=<missing>"
fi

section "Live Probe 127.0.0.1"
probe_url "http://127.0.0.1:3000"

section "Live Probe localhost"
probe_url "http://localhost:3000"

section "Heuristic Flags"
state_pid="$(awk -F= '/^pid=/{print $2; exit}' "$FRONTEND_DIR/.next-mode-state" 2>/dev/null || true)"
listener_pid="$(lsof -tiTCP:3000 -sTCP:LISTEN 2>/dev/null | head -n1 || true)"
last_mode="$(cat "$FRONTEND_DIR/.next-last-mode" 2>/dev/null || true)"
has_build_id=0
if [[ -f "$FRONTEND_DIR/.next/BUILD_ID" ]]; then
  has_build_id=1
fi

if [[ -n "$state_pid" ]] && ! kill -0 "$state_pid" 2>/dev/null; then
  echo "flag_stale_state_pid=1"
else
  echo "flag_stale_state_pid=0"
fi

if [[ -n "$listener_pid" ]] && [[ -n "$state_pid" ]] && [[ "$listener_pid" != "$state_pid" ]]; then
  if is_pid_descendant_of "$state_pid" "$listener_pid"; then
    echo "flag_state_pid_differs_from_listener=0"
    echo "pid_relation=listener_is_child_of_state_pid"
  else
    echo "flag_state_pid_differs_from_listener=1"
    echo "pid_relation=listener_not_child_of_state_pid"
  fi
else
  echo "flag_state_pid_differs_from_listener=0"
fi

if [[ "$last_mode" == "dev" ]] && [[ "$has_build_id" -eq 1 ]]; then
  echo "flag_mode_marker_mismatch=1"
else
  echo "flag_mode_marker_mismatch=0"
fi

echo
echo "done=1"
