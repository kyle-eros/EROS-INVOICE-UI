#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT_DIR / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from invoicing_web.cb_seed import (  # noqa: E402
    EarningsAggregateRow,
    compute_earnings_source_totals,
    dataclass_list_to_dict,
    default_creator_overrides,
    normalize_creator_name,
    parse_creator_overrides,
    parse_earnings_bundle,
    slugify,
)
from invoicing_web.models import (  # noqa: E402
    ContactChannel,
    InvoiceDetailPayload,
    InvoiceLineItemDetail,
    InvoicePaymentInstructions,
    InvoiceUpsertItem,
)

STATUS_MIX_OPTIONS = ("balanced", "mostly_unpaid", "as_reported")
DEFAULT_NOW_OVERRIDE = "2026-03-01T00:00:00Z"
DEFAULT_BASE_URL = "http://localhost:8000/api/v1/invoicing"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import 90-day OnlyFans + Chaturbate earnings into invoice records for demo environments."
    )
    parser.add_argument("--earnings-dir", type=Path, default=ROOT_DIR / "90d-earnings")
    parser.add_argument(
        "--onlyfans-csv",
        type=Path,
        default=None,
        help="Path to 90-day OnlyFans earnings CSV (defaults to earnings-dir/90-Onlyfans-Earnings - eros.csv)",
    )
    parser.add_argument(
        "--chaturbate-csv",
        type=Path,
        action="append",
        default=[],
        help="Path to creator_monthly_revenue_YYYY-MM.csv. Repeat flag for multiple files.",
    )
    parser.add_argument("--creator-timezone", default="America/New_York")
    parser.add_argument("--contact-channel", choices=["email", "sms", "imessage"], default="email")
    parser.add_argument("--contact-target", default="creator@example.com")
    parser.add_argument("--dispatch-channels", default="email,sms", help="Comma-separated channels: email,sms,imessage")
    parser.add_argument("--dispatch-email", default="kyle@erosops.com")
    parser.add_argument("--dispatch-phone", default="+15555550123")
    parser.add_argument("--due-days", type=int, default=7)
    parser.add_argument("--status-mix", choices=STATUS_MIX_OPTIONS, default="balanced")
    parser.add_argument("--now-override", default=DEFAULT_NOW_OVERRIDE)
    parser.add_argument("--seed-batch", default="eros-90d-demo-v1")
    parser.add_argument("--creator-override", action="append", default=[], help="Override mapping: from=to")
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/eros-90d-seed-artifacts"))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--apply", action="store_true", help="Apply upsert, dispatch, and synthetic payment events")
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
    allowed = {"email", "sms", "imessage"}
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


def as_iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def canonical_creator_name(raw_name: str, normalized_name: str) -> str:
    cleaned = raw_name.strip()
    if cleaned and normalize_creator_name(cleaned) == normalized_name:
        return cleaned
    return " ".join(part.capitalize() for part in normalized_name.split())


def source_label(source: str) -> str:
    if source == "onlyfans_90d":
        return "OnlyFans"
    if source == "chaturbate_monthly":
        return "Chaturbate"
    return source


def _target_status(invoice_key: str, *, mode: str, amount_due: float) -> str:
    if amount_due <= 0:
        return "paid"
    if mode == "as_reported":
        return "overdue"

    bucket = int(hashlib.sha256(invoice_key.encode("utf-8")).hexdigest()[:8], 16) % 100
    if mode == "mostly_unpaid":
        if bucket < 8:
            return "paid"
        if bucket < 18:
            return "partial"
        if bucket < 78:
            return "overdue"
        return "open"

    if bucket < 25:
        return "paid"
    if bucket < 50:
        return "partial"
    if bucket < 75:
        return "overdue"
    return "open"


def _adjust_dates_for_status(
    *,
    issued_at: date,
    baseline_due: date,
    target_status: str,
    now_date: date,
) -> tuple[date, date]:
    due_date = baseline_due
    if target_status in {"open", "partial"}:
        due_date = max(baseline_due, now_date + timedelta(days=10))
    elif target_status == "overdue":
        due_date = max(issued_at, min(baseline_due, now_date - timedelta(days=2)))
    return issued_at, due_date


def _build_detail(row: EarningsAggregateRow, amount_due: float) -> InvoiceDetailPayload:
    gross_total = round(amount_due * 2, 2)
    return InvoiceDetailPayload(
        service_description=f"{source_label(row.source)} creator earnings settlement",
        payment_method_label="Zelle or Direct Deposit",
        payment_instructions=InvoicePaymentInstructions(
            zelle_account_number="EROS-ZELLE-SETTLEMENT",
            direct_deposit_account_number="EROS-DD-ACCOUNT",
            direct_deposit_routing_number="EROS-DD-ROUTING",
        ),
        line_items=[
            InvoiceLineItemDetail(
                platform=source_label(row.source),
                period_start=row.period_start,
                period_end=row.period_end,
                line_label=f"{source_label(row.source)} earnings ({row.source_window})",
                gross_total=gross_total,
                split_percent=50.0,
            )
        ],
    )


def _payment_amount_for_partial(amount_due: float) -> float:
    if amount_due <= 0.01:
        return 0.0
    candidate = round(amount_due * 0.4, 2)
    if candidate <= 0:
        candidate = 0.01
    if candidate >= amount_due:
        candidate = round(amount_due - 0.01, 2)
    return max(candidate, 0.0)


def build_invoice_items(
    rows: list[EarningsAggregateRow],
    *,
    creator_timezone: str,
    contact_channel: str,
    contact_target: str,
    due_days: int,
    status_mix: str,
    now_date: date,
    seed_batch: str,
) -> tuple[list[InvoiceUpsertItem], dict[str, str]]:
    if due_days < 0:
        raise ValueError("--due-days must be non-negative")

    creator_name_map: dict[str, str] = {}
    for row in rows:
        chosen = canonical_creator_name(row.creator_name_raw, row.creator_name_normalized)
        existing = creator_name_map.get(row.creator_name_normalized)
        if existing is None or len(chosen) > len(existing):
            creator_name_map[row.creator_name_normalized] = chosen

    sorted_rows = sorted(
        rows,
        key=lambda value: (value.source, value.source_window, value.creator_name_normalized),
    )

    items: list[InvoiceUpsertItem] = []
    target_status_by_invoice: dict[str, str] = {}
    for row in sorted_rows:
        creator_id = f"creator-{slugify(row.creator_name_normalized)}"
        creator_name = creator_name_map[row.creator_name_normalized]

        invoice_key = f"{row.source}:{row.source_window}:{creator_id}"
        status_target = _target_status(invoice_key, mode=status_mix, amount_due=row.amount_usd)

        issued_at = row.period_end
        baseline_due = issued_at + timedelta(days=due_days)
        issued_at, due_date = _adjust_dates_for_status(
            issued_at=issued_at,
            baseline_due=baseline_due,
            target_status=status_target,
            now_date=now_date,
        )

        digest = hashlib.sha1(invoice_key.encode("utf-8")).hexdigest()[:10]
        invoice_id = f"earn-{digest}-{slugify(row.source_window)}-{slugify(creator_id)[:40]}"
        detail = _build_detail(row, row.amount_usd)

        items.append(
            InvoiceUpsertItem(
                invoice_id=invoice_id,
                creator_id=creator_id,
                creator_name=creator_name,
                creator_timezone=creator_timezone,
                contact_channel=contact_channel,  # type: ignore[arg-type]
                contact_target=contact_target,
                currency="USD",
                amount_due=row.amount_usd,
                amount_paid=0,
                issued_at=issued_at,
                due_date=due_date,
                opt_out=False,
                metadata={
                    "source": row.source,
                    "source_file": row.source_file,
                    "source_window": row.source_window,
                    "seed_batch": seed_batch,
                    "seed_status_target": status_target,
                },
                detail=detail,
            )
        )
        target_status_by_invoice[invoice_id] = status_target

    return items, target_status_by_invoice


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if payload is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8") if exc.fp else "unknown"
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {err}") from exc


def _status_counts(base_url: str, invoice_ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for invoice_id in invoice_ids:
        status_payload = _request_json("GET", f"{base_url}/payments/invoices/{invoice_id}/status")
        status = str(status_payload.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def main() -> int:
    args = parse_args()
    now_override = parse_utc_datetime(args.now_override)
    dispatch_channels = parse_channels(args.dispatch_channels)

    onlyfans_csv = args.onlyfans_csv or (args.earnings_dir / "90-Onlyfans-Earnings - eros.csv")
    chaturbate_csvs = list(args.chaturbate_csv)
    if not chaturbate_csvs:
        chaturbate_csvs = sorted(args.earnings_dir.glob("creator_monthly_revenue_*.csv"))

    if not onlyfans_csv.is_file():
        raise FileNotFoundError(f"onlyfans csv not found: {onlyfans_csv}")
    if not chaturbate_csvs:
        raise FileNotFoundError("no chaturbate monthly csv files found")
    for csv_path in chaturbate_csvs:
        if not csv_path.is_file():
            raise FileNotFoundError(f"chaturbate csv not found: {csv_path}")

    overrides = default_creator_overrides()
    overrides.update(parse_creator_overrides(args.creator_override))

    rows = parse_earnings_bundle(
        onlyfans_csv=onlyfans_csv,
        chaturbate_monthly_csvs=chaturbate_csvs,
        overrides=overrides,
    )
    invoice_items, target_status_by_invoice = build_invoice_items(
        rows,
        creator_timezone=args.creator_timezone,
        contact_channel=args.contact_channel,
        contact_target=args.contact_target,
        due_days=args.due_days,
        status_mix=args.status_mix,
        now_date=now_override.date(),
        seed_batch=args.seed_batch,
    )
    invoice_payload = {"invoices": [item.model_dump(mode="json") for item in invoice_items]}

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "rows.json", dataclass_list_to_dict(rows))
    write_json(output_dir / "invoice_upsert_payload.json", invoice_payload)
    write_json(
        output_dir / "seed_plan.json",
        {
            "status_mix": args.status_mix,
            "source_totals": compute_earnings_source_totals(rows),
            "creator_count": len({item.creator_id for item in invoice_items}),
            "invoice_count": len(invoice_items),
            "onlyfans_csv": str(onlyfans_csv),
            "chaturbate_csvs": [str(path) for path in chaturbate_csvs],
        },
    )

    target_status_counts: dict[str, int] = {}
    for status in target_status_by_invoice.values():
        target_status_counts[status] = target_status_counts.get(status, 0) + 1

    summary: dict[str, Any] = {
        "apply": args.apply,
        "status_mix": args.status_mix,
        "invoice_count": len(invoice_items),
        "creator_count": len({item.creator_id for item in invoice_items}),
        "target_status_counts": target_status_counts,
        "source_totals": compute_earnings_source_totals(rows),
        "output_dir": str(output_dir),
    }

    if not args.apply:
        write_json(output_dir / "seed_report.json", summary)
        print(f"Prepared {len(invoice_items)} invoices for {summary['creator_count']} creators (dry-run).")
        print(f"Artifacts written to {output_dir}")
        return 0

    upsert_result = _request_json("POST", f"{args.base_url}/invoices/upsert", invoice_payload)
    upserted_invoices: list[dict[str, Any]] = list(upsert_result.get("invoices") or [])

    dispatches: list[dict[str, Any]] = []
    for invoice in upserted_invoices:
        invoice_id = str(invoice["invoice_id"])
        key_digest = hashlib.sha1(f"dispatch:{invoice_id}".encode("utf-8")).hexdigest()[:20]
        dispatch_payload: dict[str, Any] = {
            "invoice_id": invoice_id,
            "dispatched_at": as_iso_z(now_override),
            "channels": dispatch_channels,
            "idempotency_key": f"seed90d-d-{key_digest}",
        }
        if "email" in dispatch_channels:
            dispatch_payload["recipient_email"] = args.dispatch_email
        if "sms" in dispatch_channels or "imessage" in dispatch_channels:
            dispatch_payload["recipient_phone"] = args.dispatch_phone
        dispatches.append(_request_json("POST", f"{args.base_url}/invoices/dispatch", dispatch_payload))

    payment_events: list[dict[str, Any]] = []
    for invoice in upserted_invoices:
        invoice_id = str(invoice["invoice_id"])
        amount_due = float(invoice["amount_due"])
        target_status = target_status_by_invoice.get(invoice_id, "open")

        payment_amount = 0.0
        if target_status == "paid" and amount_due > 0:
            payment_amount = amount_due
        elif target_status == "partial" and amount_due > 0:
            payment_amount = _payment_amount_for_partial(amount_due)

        if payment_amount <= 0:
            continue

        event_digest = hashlib.sha1(f"payment:{invoice_id}:{target_status}".encode("utf-8")).hexdigest()[:20]
        event_payload = {
            "event_id": f"seed90d-p-{event_digest}",
            "invoice_id": invoice_id,
            "amount": payment_amount,
            "paid_at": as_iso_z(now_override),
            "source": "seed-90d",
            "metadata": {"seed_batch": args.seed_batch, "target_status": target_status},
        }
        payment_events.append(_request_json("POST", f"{args.base_url}/payments/events", event_payload))

    final_counts = _status_counts(
        args.base_url,
        [str(invoice["invoice_id"]) for invoice in upserted_invoices],
    )

    summary.update(
        {
            "upserted_count": int(upsert_result.get("processed_count") or 0),
            "dispatch_count": len(dispatches),
            "payment_event_count": len(payment_events),
            "final_status_counts": final_counts,
        }
    )
    write_json(output_dir / "api_results.json", {"upsert": upsert_result, "dispatches": dispatches, "payments": payment_events})
    write_json(output_dir / "seed_report.json", summary)

    print(
        f"Applied seed: upserted={summary['upserted_count']}, dispatched={summary['dispatch_count']}, "
        f"payment_events={summary['payment_event_count']}"
    )
    print(f"Final status counts: {final_counts}")
    print(f"Artifacts written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
