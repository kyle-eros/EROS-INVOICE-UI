#!/usr/bin/env python3
"""Seed Grace Bennett's invoice data from CB reports into the live backend."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import date, datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT_DIR / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

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
BASE_URL_DEFAULT = "http://localhost:8000/api/v1/invoicing"
SALES_CSV_DEFAULT = ROOT_DIR / "data" / "CB Daily Sales Report 2026 - February 2026.csv"
STATS_CSV_DEFAULT = ROOT_DIR / "data" / "Creator statistics report 2026:01:17 to 2026:02:15.csv"

CREATOR_ID = "creator-grace-bennett"
CREATOR_NAME = "Grace Bennett"
CREATOR_TIMEZONE = "America/New_York"
CONTACT_CHANNEL = "email"
CONTACT_TARGET = "kyle@erosops.com"
DUE_DAYS = 7
DISPATCHED_AT = "2026-02-17T00:00:00Z"


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Grace Bennett invoices from CB CSV reports.")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT, help="Invoicing backend API base URL")
    parser.add_argument("--sales-csv", type=Path, default=SALES_CSV_DEFAULT, help="Path to CB daily sales CSV")
    parser.add_argument("--stats-csv", type=Path, default=STATS_CSV_DEFAULT, help="Path to creator stats CSV")
    parser.add_argument("--creator-id", default=CREATOR_ID)
    parser.add_argument("--creator-name", default=CREATOR_NAME)
    parser.add_argument("--creator-timezone", default=CREATOR_TIMEZONE)
    parser.add_argument("--contact-channel", default=CONTACT_CHANNEL, choices=["email"])
    parser.add_argument("--contact-target", default=CONTACT_TARGET)
    parser.add_argument("--due-days", type=int, default=DUE_DAYS)
    parser.add_argument("--dispatched-at", default=DISPATCHED_AT)
    return parser.parse_args()


def _require_file(path: Path, label: str) -> None:
    if path.is_file():
        return
    raise FileNotFoundError(
        f"{label} not found: {path}\n"
        f"Provide --{label.lower().replace(' ', '-')} or place the file under {ROOT_DIR / 'data'}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    _require_file(args.sales_csv, "sales csv")
    _require_file(args.stats_csv, "stats csv")

    print("=" * 60)
    print("Seeding Grace Bennett Invoice Data")
    print("=" * 60)

    # 1. Parse CSVs
    print("\n[1/5] Parsing sales sessions...")
    sessions, profile = parse_sales_sessions(args.sales_csv)
    print(f"  Total rows: {profile.total_rows}")
    print(f"  Included sessions: {profile.included_rows}")
    print(f"  Excluded: {profile.excluded_rows} ({profile.exclusion_reasons})")
    print(f"  Sales total: ${profile.sales_total_usd:,.2f}")
    print(f"  Creator candidates: {profile.creator_candidates}")

    print("\n[2/5] Parsing creator stats...")
    stats_rows = parse_creator_stats(args.stats_csv)
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
        creator_name=args.creator_name,
        creator_id=args.creator_id,
        creator_timezone=args.creator_timezone,
        contact_channel=args.contact_channel,
        contact_target=args.contact_target,
        due_days=args.due_days,
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
    upsert_url = f"{args.base_url}/invoices/upsert"
    upsert_resp = post_json(upsert_url, {"invoices": invoices_payload})
    print(f"  Processed count: {upsert_resp['processed_count']}")

    # 5. Dispatch each invoice
    print("\nDispatching invoices...")
    dispatch_url = f"{args.base_url}/invoices/dispatch"
    dispatched_count = 0
    total_amount = 0.0

    for inv_data, orig in zip(upsert_resp["invoices"], upsert_request.invoices):
        invoice_id = inv_data["invoice_id"]
        dispatch_payload = {
            "invoice_id": invoice_id,
            "channels": ["email"],
            "recipient_email": args.contact_target,
            "dispatched_at": args.dispatched_at,
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
