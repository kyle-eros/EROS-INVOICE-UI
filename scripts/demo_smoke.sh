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
  echo "error: ADMIN_PASSWORD is required for demo smoke tests." >&2
  exit 1
fi

API_BASE_URL="$(resolve_api_base_url)"
REPORT_PATH="${DEMO_SMOKE_REPORT_PATH:-/tmp/eros-demo-smoke-report.json}"

echo "Running demo smoke checks against $API_BASE_URL"
python3 - "$API_BASE_URL" "$ADMIN_PASSWORD" "$REPORT_PATH" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

api_base_url = sys.argv[1].rstrip("/")
admin_password = sys.argv[2]
report_path = Path(sys.argv[3])


def _detail_from_payload(payload_bytes: bytes) -> str:
    if not payload_bytes:
        return ""
    raw = payload_bytes.decode("utf-8", errors="replace")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(body, dict):
        for key in ("detail", "error", "message"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return raw


def request_raw(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    accept: str = "application/json",
) -> tuple[dict[str, str], bytes]:
    url = f"{api_base_url}/{path.lstrip('/')}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers: dict[str, str] = {"Accept": accept}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        detail = _detail_from_payload(exc.read())
        raise RuntimeError(f"{method} {path} failed with {exc.code}: {detail}") from exc


def request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    headers, raw = request_raw(method, path, payload=payload, token=token, accept="application/json")
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {path} returned non-JSON payload: {headers}") from exc


# 1) API reachability
_ = request_json("GET", "tasks")

# 2) Admin login
admin_login = request_json("POST", "admin/login", payload={"password": admin_password})
admin_token = str(admin_login.get("session_token") or "")
if not admin_token:
    raise RuntimeError("Admin login did not return session_token")

# 3) Runtime guard posture
runtime = request_json("GET", "admin/runtime/security", token=admin_token)
runtime_issues = runtime.get("runtime_secret_issues")
if isinstance(runtime_issues, list) and runtime_issues:
    raise RuntimeError(f"Runtime secret issues detected: {runtime_issues}")

# 4) Creator directory
creator_dir = request_json("GET", "admin/creators", token=admin_token)
creators = creator_dir.get("creators")
if not isinstance(creators, list) or not creators:
    raise RuntimeError("No creators available in admin directory")

ready_creators = [item for item in creators if bool(item.get("ready_for_portal"))]
if not ready_creators:
    raise RuntimeError("No portal-ready creators found. Run reseed and dispatch flow first.")

chosen = ready_creators[0]
creator_id = str(chosen.get("creator_id") or "")
creator_name = str(chosen.get("creator_name") or "")
if not creator_id or not creator_name:
    raise RuntimeError("Selected creator is missing id or name")

# 5) Passkey generation
passkey_resp = request_json(
    "POST",
    "passkeys/generate",
    payload={"creator_id": creator_id, "creator_name": creator_name},
    token=admin_token,
)
passkey = str(passkey_resp.get("passkey") or "")
if not passkey:
    raise RuntimeError("Passkey generation did not return passkey")

# 6) Lookup + confirm
lookup = request_json("POST", "auth/lookup", payload={"passkey": passkey})
if str(lookup.get("creator_id") or "") != creator_id:
    raise RuntimeError("Passkey lookup returned unexpected creator_id")

confirm = request_json("POST", "auth/confirm", payload={"passkey": passkey})
creator_session = str(confirm.get("session_token") or "")
if not creator_session:
    raise RuntimeError("Passkey confirmation did not return creator session token")

# 7) Creator invoices + PDF
my_invoices = request_json("GET", "me/invoices", token=creator_session)
invoices = my_invoices.get("invoices")
if not isinstance(invoices, list) or not invoices:
    raise RuntimeError("Creator has no invoices in /me/invoices")

invoice_with_pdf = next((item for item in invoices if bool(item.get("has_pdf"))), None)
if invoice_with_pdf is None:
    raise RuntimeError("No invoice with PDF payload available for smoke test")

invoice_id = str(invoice_with_pdf.get("invoice_id") or "")
if not invoice_id:
    raise RuntimeError("Selected invoice missing invoice_id")

encoded_invoice_id = urllib.parse.quote(invoice_id, safe="")
pdf_headers, pdf_bytes = request_raw(
    "GET",
    f"me/invoices/{encoded_invoice_id}/pdf",
    token=creator_session,
    accept="application/pdf",
)
normalized_pdf_headers = {str(k).lower(): str(v) for k, v in pdf_headers.items()}
content_type = (normalized_pdf_headers.get("content-type") or "").lower()
if content_type:
    if "application/pdf" not in content_type:
        raise RuntimeError(f"PDF endpoint returned unexpected content type: {content_type}")
elif not pdf_bytes.startswith(b"%PDF-"):
    raise RuntimeError("PDF endpoint missing Content-Type and payload does not look like a PDF")
if len(pdf_bytes) < 100:
    raise RuntimeError("PDF payload is unexpectedly small")

summary = {
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "api_base_url": api_base_url,
    "creator_count": len(creators),
    "portal_ready_creator_count": len(ready_creators),
    "smoke_creator_id": creator_id,
    "smoke_invoice_id": invoice_id,
    "pdf_bytes": len(pdf_bytes),
    "runtime_secret_issues": runtime_issues if isinstance(runtime_issues, list) else [],
}

report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"Demo smoke passed. Report: {report_path}")
PY

echo "Demo smoke checks passed."
