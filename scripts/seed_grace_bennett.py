#!/usr/bin/env python3
"""Seed Grace Bennett's invoice data from CB reports into the live backend."""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from datetime import date, datetime
from pathlib import Path

# Add backend src to path so we can import the cb_seed module
sys.path.insert(0, str(Path("/Users/kylemerriman/EROS-CRM-TUI/EROS-Invoicing-Web/backend/src")))

from invoicing_web.cb_seed import (
    build_invoice_upsert_request,
    default_creator_overrides,
    parse_creator_stats,
    parse_sales_sessions,
    resolve_creator_identity,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "http://localhost:8000/api/v1/invoicing"

SALES_CSV = Path(
    "/Users/kylemerriman/EROS-CRM-TUI/eros-of-data/CB Daily Sales Report 2026 - February 2026.csv"
)
STATS_CSV = Path(
    "/Users/kylemerriman/EROS-CRM-TUI/eros-of-data/Creator statistics report 2026:01:17 to 2026:02:15.csv"
)

CREATOR_ID = "creator-grace-bennett"
CREATOR_NAME = "Grace Bennett"
CREATOR_TIMEZONE = "America/New_York"
CONTACT_CHANNEL = "email"
CONTACT_TARGET = "kyle@erosops.com"
DUE_DAYS = 7


# ---------------------------------------------------------------------------
# JSON serializer that handles date/datetime objects
# ---------------------------------------------------------------------------
def json_serial(obj: object) -> str:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


def post_json(url: str, data: dict) -> dict:
    """POST JSON to a URL and return parsed response."""
    body = json.dumps(data, default=json_serial).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("Seeding Grace Bennett Invoice Data")
    print("=" * 60)

    # 1. Parse CSVs
    print("\n[1/5] Parsing sales sessions...")
    sessions, profile = parse_sales_sessions(SALES_CSV)
    print(f"  Total rows: {profile.total_rows}")
    print(f"  Included sessions: {profile.included_rows}")
    print(f"  Excluded: {profile.excluded_rows} ({profile.exclusion_reasons})")
    print(f"  Sales total: ${profile.sales_total_usd:,.2f}")
    print(f"  Creator candidates: {profile.creator_candidates}")

    print("\n[2/5] Parsing creator stats...")
    stats_rows = parse_creator_stats(STATS_CSV)
    for row in stats_rows:
        if row.total_earnings_net:
            print(f"  {row.creator_name}: Net ${row.total_earnings_net:,.2f}")
        else:
            print(f"  {row.creator_name}: N/A")

    # 2. Resolve identity
    print("\n[3/5] Resolving creator identity...")
    overrides = default_creator_overrides()
    normalized, display_name, resolved_id = resolve_creator_identity(sessions, stats_rows, overrides)
    print(f"  Normalized: {normalized}")
    print(f"  Display name: {display_name}")
    print(f"  Creator ID: {resolved_id}")

    # 3. Build upsert request
    print("\n[4/5] Building invoice upsert request...")
    upsert_request = build_invoice_upsert_request(
        sessions,
        creator_name=CREATOR_NAME,
        creator_id=CREATOR_ID,
        creator_timezone=CREATOR_TIMEZONE,
        contact_channel=CONTACT_CHANNEL,
        contact_target=CONTACT_TARGET,
        due_days=DUE_DAYS,
    )
    print(f"  Invoices to upsert: {len(upsert_request.invoices)}")

    # Serialize using model_dump() and convert dates to ISO strings
    invoices_payload = []
    for inv in upsert_request.invoices:
        d = inv.model_dump()
        # Convert date objects to ISO strings
        if isinstance(d.get("issued_at"), date):
            d["issued_at"] = d["issued_at"].isoformat()
        if isinstance(d.get("due_date"), date):
            d["due_date"] = d["due_date"].isoformat()
        invoices_payload.append(d)

    # 4. POST upsert
    print("\n[5/5] Upserting invoices to backend...")
    upsert_url = f"{BASE_URL}/invoices/upsert"
    upsert_resp = post_json(upsert_url, {"invoices": invoices_payload})
    print(f"  Processed count: {upsert_resp['processed_count']}")

    # 5. Dispatch each invoice
    print("\nDispatching invoices...")
    dispatch_url = f"{BASE_URL}/invoices/dispatch"
    dispatched_count = 0
    total_amount = 0.0

    for inv_data, orig in zip(upsert_resp["invoices"], upsert_request.invoices):
        invoice_id = inv_data["invoice_id"]
        dispatch_payload = {
            "invoice_id": invoice_id,
            "channels": ["email"],
            "recipient_email": CONTACT_TARGET,
            "dispatched_at": "2026-02-17T00:00:00Z",
            "idempotency_key": f"seed-{invoice_id}",
        }
        try:
            dispatch_resp = post_json(dispatch_url, dispatch_payload)
            dispatched_count += 1
            print(f"  Dispatched {invoice_id} -> dispatch_id={dispatch_resp['dispatch_id']}")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else "unknown"
            print(f"  WARN: dispatch failed for {invoice_id}: {e.code} {error_body}")

        total_amount += orig.amount_due

    # 6. Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Invoices upserted:   {upsert_resp['processed_count']}")
    print(f"  Invoices dispatched: {dispatched_count}")
    print(f"  Total amount:        ${total_amount:,.2f}")
    print()
    print("Invoice details:")
    for inv_data, orig in zip(upsert_resp["invoices"], upsert_request.invoices):
        print(f"  {inv_data['invoice_id']:30s}  ${orig.amount_due:>10,.2f}  due {orig.due_date}")
    print()
    print("=" * 60)
    print("Generate a fresh Grace Bennett passkey in the admin dashboard or /passkeys/generate API.")
    print("=" * 60)


if __name__ == "__main__":
    main()
