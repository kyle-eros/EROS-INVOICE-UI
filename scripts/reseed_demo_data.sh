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

resolve_api_base_url() {
  if [[ -n "${DEMO_API_BASE_URL:-}" ]]; then
    printf '%s' "$DEMO_API_BASE_URL"
    return
  fi

  if [[ -n "${INVOICING_API_BASE_URL:-}" ]]; then
    case "$INVOICING_API_BASE_URL" in
      */api/v1/invoicing)
        printf '%s' "$INVOICING_API_BASE_URL"
        ;;
      *)
        printf '%s/api/v1/invoicing' "${INVOICING_API_BASE_URL%/}"
        ;;
    esac
    return
  fi

  printf '%s' "http://localhost:8000/api/v1/invoicing"
}

require_cmd python3

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
  echo "error: ADMIN_PASSWORD is required for reseed validation." >&2
  exit 1
fi

API_BASE_URL="$(resolve_api_base_url)"
OUTPUT_DIR="${DEMO_SEED_OUTPUT_DIR:-/tmp/eros-90d-seed-artifacts}"
DEMO_FOCUS_YEAR="${DEMO_FOCUS_YEAR:-2026}"
ONLYFANS_MONTHLY_CSV="$ROOT_DIR/90d-earnings/onlyfans_monthly_revenue_${DEMO_FOCUS_YEAR}-01_${DEMO_FOCUS_YEAR}-02.csv"
CB_MONTHLY_JAN_CSV="$ROOT_DIR/90d-earnings/creator_monthly_revenue_${DEMO_FOCUS_YEAR}-01.csv"
CB_MONTHLY_FEB_CSV="$ROOT_DIR/90d-earnings/creator_monthly_revenue_${DEMO_FOCUS_YEAR}-02.csv"

if [[ ! -f "$ONLYFANS_MONTHLY_CSV" ]]; then
  echo "error: expected OnlyFans monthly CSV not found: $ONLYFANS_MONTHLY_CSV" >&2
  exit 1
fi
if [[ ! -f "$CB_MONTHLY_JAN_CSV" ]]; then
  echo "error: expected Chaturbate January CSV not found: $CB_MONTHLY_JAN_CSV" >&2
  exit 1
fi
if [[ ! -f "$CB_MONTHLY_FEB_CSV" ]]; then
  echo "error: expected Chaturbate February CSV not found: $CB_MONTHLY_FEB_CSV" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "Applying demo seed using $API_BASE_URL"
python3 "$ROOT_DIR/scripts/seed_from_90d_earnings.py" \
  --apply \
  --status-mix as_reported \
  --onlyfans-csv "$ONLYFANS_MONTHLY_CSV" \
  --chaturbate-csv "$CB_MONTHLY_JAN_CSV" \
  --chaturbate-csv "$CB_MONTHLY_FEB_CSV" \
  --base-url "$API_BASE_URL" \
  --output-dir "$OUTPUT_DIR"

python3 - "$OUTPUT_DIR" "$API_BASE_URL" "${ADMIN_PASSWORD}" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

output_dir = Path(sys.argv[1])
api_base_url = sys.argv[2].rstrip("/")
admin_password = sys.argv[3].strip()

seed_report_path = output_dir / "seed_report.json"
if not seed_report_path.is_file():
    raise SystemExit(f"seed report not found: {seed_report_path}")

with seed_report_path.open("r", encoding="utf-8") as handle:
    seed_report = json.load(handle)

creator_count = int(seed_report.get("creator_count") or 0)
upserted_count = int(seed_report.get("upserted_count") or 0)
dispatch_count = int(seed_report.get("dispatch_count") or 0)

if creator_count <= 0:
    raise SystemExit("seed validation failed: creator_count must be > 0")
if upserted_count <= 0:
    raise SystemExit("seed validation failed: upserted_count must be > 0")
if dispatch_count <= 0:
    raise SystemExit("seed validation failed: dispatch_count must be > 0")


def request_json(method: str, url: str, payload: dict[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {detail}") from exc

summary: dict[str, Any] = {
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "api_base_url": api_base_url,
    "creator_count": creator_count,
    "upserted_count": upserted_count,
    "dispatch_count": dispatch_count,
}

login = request_json(
    "POST",
    f"{api_base_url}/admin/login",
    payload={"password": admin_password},
)
admin_token = str(login.get("session_token") or "")
if not admin_token:
    raise SystemExit("seed validation failed: admin login did not return session_token")

creators = request_json(
    "GET",
    f"{api_base_url}/admin/creators",
    token=admin_token,
).get("creators")
if not isinstance(creators, list) or not creators:
    raise SystemExit("seed validation failed: /admin/creators returned no creators")

ready_for_portal = [item for item in creators if bool(item.get("ready_for_portal"))]
if not ready_for_portal:
    raise SystemExit("seed validation failed: no portal-ready creators found after reseed")

summary["admin_creator_count"] = len(creators)
summary["portal_ready_creator_count"] = len(ready_for_portal)

summary_path = output_dir / "demo_reseed_summary.json"
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"Reseed validation passed. Summary: {summary_path}")
PY

echo "Demo reseed complete. Artifacts in $OUTPUT_DIR"
