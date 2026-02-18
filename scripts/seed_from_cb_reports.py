#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT_DIR / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from fastapi.testclient import TestClient

from invoicing_web import api as api_module
from invoicing_web.cb_seed import (  # noqa: E402
    build_invoice_upsert_request,
    build_reconciliation_report,
    dataclass_list_to_dict,
    default_creator_overrides,
    parse_creator_overrides,
    parse_creator_stats,
    parse_sales_sessions,
    resolve_creator_identity,
)
from invoicing_web.main import create_app  # noqa: E402
from invoicing_web.models import ContactChannel, InvoiceUpsertItem  # noqa: E402
from invoicing_web.openclaw import StubOpenClawSender  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed deterministic invoice test data from CB report CSV inputs.")
    parser.add_argument("--sales-csv", required=True, type=Path, help="Path to CB Daily Sales CSV")
    parser.add_argument("--creator-csv", required=True, type=Path, help="Path to Creator statistics CSV")
    parser.add_argument("--year", type=int, default=2026, help="Year to apply to Date (PHT) month/day values")
    parser.add_argument("--creator-timezone", default="UTC", help="IANA timezone for generated invoice creator")
    parser.add_argument("--contact-channel", choices=["email", "sms"], default="email")
    parser.add_argument("--contact-target", default="creator@example.com")
    parser.add_argument("--due-days", type=int, default=7)
    parser.add_argument("--run-live", action="store_true", help="Run live reminder cycle after dry-run cycle")
    parser.add_argument("--now-override", default="2026-03-01T00:00:00Z")
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/cb-seed-artifacts"))
    parser.add_argument("--creator-override", action="append", default=[], help="Override mapping: from=to")
    parser.add_argument("--strict-reconciliation", action="store_true")
    parser.add_argument("--reconciliation-tolerance", type=float, default=0.15)
    parser.add_argument("--inject-scenario-pack", action="store_true")
    parser.add_argument("--simulate-payment-event", action="store_true")
    parser.add_argument("--skip-settle-first-invoice", action="store_true")
    parser.add_argument("--dispatch-email", default="kyle@erosops.com")
    parser.add_argument("--dispatch-phone", default="+15555550123")
    parser.add_argument("--dispatch-channels", default="email,sms", help="comma-separated channels: email,sms")
    parser.add_argument("--skip-first-ack", action="store_true")
    return parser.parse_args()


def parse_utc_datetime(raw: str) -> datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_channels(raw: str) -> list[ContactChannel]:
    parts = [item.strip().lower() for item in raw.split(",") if item.strip()]
    allowed = {"email", "sms"}
    deduped: list[ContactChannel] = []
    for part in parts:
        if part not in allowed:
            raise ValueError(f"invalid dispatch channel: {part}")
        if part in deduped:
            continue
        deduped.append(part)  # type: ignore[arg-type]
    if not deduped:
        raise ValueError("at least one dispatch channel is required")
    return deduped


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def make_scenario_items(now_date: date, *, creator_name: str, creator_id: str, creator_timezone: str, contact_channel: str, contact_target: str) -> list[InvoiceUpsertItem]:
    return [
        InvoiceUpsertItem(
            invoice_id="cb-scenario-optout-001",
            creator_id=creator_id,
            creator_name=creator_name,
            creator_timezone=creator_timezone,
            contact_channel=contact_channel,
            contact_target=contact_target,
            currency="USD",
            amount_due=125.0,
            amount_paid=0,
            issued_at=now_date - timedelta(days=14),
            due_date=now_date - timedelta(days=4),
            opt_out=True,
            metadata={"source": "scenario", "case": "opt_out"},
        ),
        InvoiceUpsertItem(
            invoice_id="cb-scenario-future-001",
            creator_id=creator_id,
            creator_name=creator_name,
            creator_timezone=creator_timezone,
            contact_channel=contact_channel,
            contact_target=contact_target,
            currency="USD",
            amount_due=210.0,
            amount_paid=0,
            issued_at=now_date,
            due_date=now_date + timedelta(days=30),
            opt_out=False,
            metadata={"source": "scenario", "case": "not_due_yet"},
        ),
        InvoiceUpsertItem(
            invoice_id="cb-scenario-paid-001",
            creator_id=creator_id,
            creator_name=creator_name,
            creator_timezone=creator_timezone,
            contact_channel=contact_channel,
            contact_target=contact_target,
            currency="USD",
            amount_due=140.0,
            amount_paid=140.0,
            issued_at=now_date - timedelta(days=21),
            due_date=now_date - timedelta(days=7),
            opt_out=False,
            metadata={"source": "scenario", "case": "paid"},
        ),
    ]


def call_json(client: TestClient, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.request(method, path, json=payload)
    if not response.is_success:
        raise RuntimeError(f"{method} {path} failed with {response.status_code}: {response.text}")
    return response.json()


def main() -> int:
    args = parse_args()
    if args.due_days < 0:
        raise ValueError("--due-days must be non-negative")

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    now_override = parse_utc_datetime(args.now_override)
    channels = parse_channels(args.dispatch_channels)

    overrides = default_creator_overrides()
    overrides.update(parse_creator_overrides(args.creator_override))

    sessions, sales_profile = parse_sales_sessions(args.sales_csv, year=args.year)
    stats_rows = parse_creator_stats(args.creator_csv)
    creator_normalized, creator_name, creator_id = resolve_creator_identity(sessions, stats_rows, overrides)

    base_request = build_invoice_upsert_request(
        sessions,
        creator_name=creator_name,
        creator_id=creator_id,
        creator_timezone=args.creator_timezone,
        contact_channel=args.contact_channel,
        contact_target=args.contact_target,
        due_days=args.due_days,
    )

    invoice_items = list(base_request.invoices)
    if args.inject_scenario_pack:
        invoice_items.extend(
            make_scenario_items(
                now_override.date(),
                creator_name=creator_name,
                creator_id=creator_id,
                creator_timezone=args.creator_timezone,
                contact_channel=args.contact_channel,
                contact_target=args.contact_target,
            )
        )

    invoice_payload = {"invoices": [item.model_dump(mode="json") for item in invoice_items]}
    reconciliation = build_reconciliation_report(
        sessions,
        stats_rows,
        creator_normalized=creator_normalized,
        overrides=overrides,
    )

    profile_payload = {
        "sales_profile": dataclass_list_to_dict([sales_profile])[0],
        "creator_normalized": creator_normalized,
        "creator_name": creator_name,
        "creator_id": creator_id,
        "overrides": overrides,
        "dispatch_channels": channels,
    }
    write_json(output_dir / "profile.json", profile_payload)
    write_json(output_dir / "normalized_sessions.json", dataclass_list_to_dict(sessions))
    write_json(output_dir / "creator_stats_rows.json", dataclass_list_to_dict(stats_rows))
    write_json(output_dir / "invoice_upsert_payload.json", invoice_payload)
    write_json(output_dir / "reconciliation.json", reconciliation)

    strict_failed = False
    if args.strict_reconciliation:
        if reconciliation.get("status") == "variance":
            relative_delta = float(reconciliation.get("relative_delta") or 0)
            strict_failed = relative_delta > float(args.reconciliation_tolerance)
        elif reconciliation.get("status") != "match":
            strict_failed = True

    api_module.reset_runtime_state_for_tests()
    api_module.openclaw_sender = StubOpenClawSender(
        enabled=True, channel=",".join(channels)
    )
    client = TestClient(create_app())

    api_results: dict[str, Any] = {}
    api_results["invoices_upsert"] = call_json(client, "POST", "/api/v1/invoicing/invoices/upsert", invoice_payload)

    dispatch_results: list[dict[str, Any]] = []
    for idx, invoice in enumerate(api_results["invoices_upsert"]["invoices"], start=1):
        dispatch_payload: dict[str, Any] = {
            "invoice_id": invoice["invoice_id"],
            "dispatched_at": now_override.isoformat().replace("+00:00", "Z"),
            "channels": channels,
            "idempotency_key": f"cb-seed-dispatch-{idx:03d}",
        }
        if "email" in channels:
            dispatch_payload["recipient_email"] = args.dispatch_email
        if "sms" in channels:
            dispatch_payload["recipient_phone"] = args.dispatch_phone
        dispatch_results.append(call_json(client, "POST", "/api/v1/invoicing/invoices/dispatch", dispatch_payload))
    api_results["dispatches"] = dispatch_results

    if dispatch_results and not args.skip_first_ack:
        first_dispatch_id = dispatch_results[0]["dispatch_id"]
        api_results["creator_ack"] = call_json(client, "POST", f"/api/v1/invoicing/invoices/dispatch/{first_dispatch_id}/ack")
    if api_results["invoices_upsert"]["invoices"]:
        first_invoice_id = api_results["invoices_upsert"]["invoices"][0]["invoice_id"]
        api_results["first_invoice_status_after_ack"] = call_json(
            client,
            "GET",
            f"/api/v1/invoicing/payments/invoices/{first_invoice_id}/status",
        )

    dry_run_payload = {
        "dry_run": True,
        "now_override": now_override.isoformat().replace("+00:00", "Z"),
        "idempotency_key": "cb-seed-reminder-dry-001",
    }
    api_results["reminders_dry_run"] = call_json(client, "POST", "/api/v1/invoicing/reminders/run/once", dry_run_payload)

    if args.run_live:
        live_payload = {
            "dry_run": False,
            "now_override": now_override.isoformat().replace("+00:00", "Z"),
            "idempotency_key": "cb-seed-reminder-live-001",
        }
        api_results["reminders_live_run"] = call_json(client, "POST", "/api/v1/invoicing/reminders/run/once", live_payload)
        api_results["reminders_live_run_idempotent"] = call_json(client, "POST", "/api/v1/invoicing/reminders/run/once", live_payload)

    if args.simulate_payment_event and api_results["invoices_upsert"]["invoices"]:
        first_invoice = api_results["invoices_upsert"]["invoices"][0]
        payment_amount = round(min(float(first_invoice["amount_due"]), max(float(first_invoice["amount_due"]) * 0.25, 1.0)), 2)
        payment_payload = {
            "event_id": "cb-seed-payment-001",
            "invoice_id": first_invoice["invoice_id"],
            "amount": payment_amount,
            "paid_at": now_override.isoformat().replace("+00:00", "Z"),
            "source": "cb-seed-simulation",
            "metadata": {"source": "cb-seed-script"},
        }
        api_results["payment_event_applied"] = call_json(client, "POST", "/api/v1/invoicing/payments/events", payment_payload)
        api_results["payment_event_duplicate"] = call_json(client, "POST", "/api/v1/invoicing/payments/events", payment_payload)

        if not args.skip_settle_first_invoice:
            remaining = round(float(api_results["payment_event_applied"]["balance_due"]), 2)
            if remaining > 0:
                settlement_payload = {
                    "event_id": "cb-seed-payment-002",
                    "invoice_id": first_invoice["invoice_id"],
                    "amount": remaining,
                    "paid_at": (now_override + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
                    "source": "cb-seed-settlement",
                    "metadata": {"source": "cb-seed-script", "phase": "settlement"},
                }
                api_results["payment_event_settlement"] = call_json(
                    client,
                    "POST",
                    "/api/v1/invoicing/payments/events",
                    settlement_payload,
                )

    if api_results["invoices_upsert"]["invoices"]:
        first_invoice_id = api_results["invoices_upsert"]["invoices"][0]["invoice_id"]
        api_results["first_invoice_status_after_payment"] = call_json(
            client,
            "GET",
            f"/api/v1/invoicing/payments/invoices/{first_invoice_id}/status",
        )
    api_results["reminders_summary"] = call_json(client, "GET", "/api/v1/invoicing/reminders/summary")
    api_results["reminders_escalations"] = call_json(client, "GET", "/api/v1/invoicing/reminders/escalations")

    write_json(output_dir / "api_results.json", api_results)

    print(f"Output directory: {output_dir}")
    print(
        "Sales rows: "
        f"{sales_profile.total_rows}, included={sales_profile.included_rows}, excluded={sales_profile.excluded_rows}"
    )
    print(f"Invoices generated: {len(invoice_items)}")
    print(
        "Reconciliation: "
        f"status={reconciliation['status']}, sales_total={reconciliation['sales_total_usd']}, "
        f"stats_total={reconciliation['stats_total_usd']}, delta={reconciliation['delta_usd']}"
    )

    if strict_failed:
        print(
            "Strict reconciliation failed: "
            f"relative_delta={reconciliation.get('relative_delta')} > tolerance={args.reconciliation_tolerance}",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
