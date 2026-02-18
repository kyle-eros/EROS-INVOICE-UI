from __future__ import annotations

import csv
from pathlib import Path

from invoicing_web.cb_seed import (
    build_invoice_upsert_request,
    build_reconciliation_report,
    compute_earnings_source_totals,
    default_creator_overrides,
    parse_chaturbate_monthly_revenue,
    parse_earnings_bundle,
    parse_onlyfans_earnings,
    parse_creator_stats,
    parse_sales_sessions,
    resolve_creator_identity,
)


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_parse_sales_sessions_filters_non_revenue_rows(tmp_path: Path) -> None:
    sales_path = tmp_path / "sales.csv"
    headers = [
        "Date (PHT)",
        "Operator Name",
        "Model Name",
        "Start Time (PHT)",
        "End Time (PHT)",
        "Converted to USD",
        "Stream Type",
    ]
    rows = [
        ["2/3", "Ross", "Grace Bennett", "6:39 AM", "12:29 PM", "$665.65", "Solo"],
        ["2/3", "Grace Bennett💰", "Extraction💰", " Tokens Before extraction", "", "$665.65", ""],
        ["2/4", "Ross", "Grace Bennett", "7:00 AM", "10:00 AM", "", "Solo"],
    ]
    _write_csv(sales_path, headers, rows)

    sessions, profile = parse_sales_sessions(sales_path, year=2026)

    assert profile.total_rows == 3
    assert profile.included_rows == 1
    assert profile.excluded_rows == 2
    assert profile.exclusion_reasons["extraction_row"] == 1
    assert profile.exclusion_reasons["missing_converted_usd"] == 1
    assert profile.sales_total_usd == 665.65
    assert sessions[0].model_name == "Grace Bennett"
    assert sessions[0].converted_usd == 665.65


def test_invoice_derivation_and_reconciliation(tmp_path: Path) -> None:
    sales_path = tmp_path / "sales.csv"
    creator_path = tmp_path / "creator.csv"

    sales_headers = [
        "Date (PHT)",
        "Operator Name",
        "Model Name",
        "Start Time (PHT)",
        "End Time (PHT)",
        "Converted to USD",
        "Stream Type",
    ]
    sales_rows = [
        ["2/3", "Ross", "Grace Bennett", "6:39 AM", "12:29 PM", "$665.65", "Solo"],
        ["2/4", "Dave", "Grace Bennett", "7:10 AM", "11:10 AM", "$100.00", "Solo"],
    ]
    _write_csv(sales_path, sales_headers, sales_rows)

    creator_headers = ["Date/Time", "Creator", "Total earnings Net"]
    creator_rows = [["2026-01-17 - 2026-02-15", "Grace Bennett Paid", "$765.65"]]
    _write_csv(creator_path, creator_headers, creator_rows)

    sessions, _ = parse_sales_sessions(sales_path, year=2026)
    stats_rows = parse_creator_stats(creator_path)

    creator_normalized, creator_name, creator_id = resolve_creator_identity(
        sessions,
        stats_rows,
        default_creator_overrides(),
    )

    request = build_invoice_upsert_request(
        sessions,
        creator_name=creator_name,
        creator_id=creator_id,
        creator_timezone="UTC",
        contact_channel="email",
        contact_target="billing@example.com",
        due_days=7,
    )

    assert len(request.invoices) == 2
    assert request.invoices[0].invoice_id == "cb-20260203-001"
    assert request.invoices[0].due_date.isoformat() == "2026-02-10"
    assert request.invoices[1].invoice_id == "cb-20260204-002"
    assert request.invoices[1].due_date.isoformat() == "2026-02-11"

    reconciliation = build_reconciliation_report(
        sessions,
        stats_rows,
        creator_normalized=creator_normalized,
        overrides=default_creator_overrides(),
    )

    assert reconciliation["status"] == "match"
    assert reconciliation["sales_total_usd"] == 765.65
    assert reconciliation["stats_total_usd"] == 765.65
    assert reconciliation["delta_usd"] == 0.0


def test_parse_onlyfans_earnings_applies_overrides(tmp_path: Path) -> None:
    onlyfans_path = tmp_path / "90-Onlyfans-Earnings - eros.csv"
    headers = ["Date/Time", "Creator", "Total earnings Net"]
    rows = [
        ["2025-11-20 - 2026-02-17", "Grace Bennett Paid", "$8,410.11"],
        ["2025-11-20 - 2026-02-17", "Oliva Hansley PAID", "$10,660.54"],
    ]
    _write_csv(onlyfans_path, headers, rows)

    parsed = parse_onlyfans_earnings(onlyfans_path, overrides=default_creator_overrides())
    assert len(parsed) == 2
    assert parsed[0].source == "onlyfans_90d"
    assert parsed[0].period_start.isoformat() == "2025-11-20"
    assert parsed[0].period_end.isoformat() == "2026-02-17"
    assert parsed[0].creator_name_normalized == "grace bennett"
    assert parsed[1].creator_name_normalized == "olivia hansley paid"


def test_parse_chaturbate_monthly_revenue_from_filename(tmp_path: Path) -> None:
    monthly_path = tmp_path / "creator_monthly_revenue_2026-02.csv"
    headers = ["Model Name", "Total Revenue USD"]
    rows = [
        ["Scarlet Grace", "7781.00"],
        ["Grace Bennett", "4834.80"],
    ]
    _write_csv(monthly_path, headers, rows)

    parsed = parse_chaturbate_monthly_revenue(monthly_path, overrides=default_creator_overrides())
    assert len(parsed) == 2
    assert parsed[0].source == "chaturbate_monthly"
    assert parsed[0].source_window == "2026-02"
    assert parsed[0].period_start.isoformat() == "2026-02-01"
    assert parsed[0].period_end.isoformat() == "2026-02-28"
    assert parsed[0].creator_name_normalized == "scarlett grace"


def test_parse_earnings_bundle_and_totals(tmp_path: Path) -> None:
    onlyfans_path = tmp_path / "90-Onlyfans-Earnings - eros.csv"
    monthly_path = tmp_path / "creator_monthly_revenue_2026-01.csv"

    _write_csv(
        onlyfans_path,
        ["Date/Time", "Creator", "Total earnings Net"],
        [["2025-11-20 - 2026-02-17", "Grace Bennett", "$17010.49"]],
    )
    _write_csv(
        monthly_path,
        ["Model Name", "Total Revenue USD"],
        [["Grace Bennett", "6570.85"]],
    )

    parsed = parse_earnings_bundle(
        onlyfans_csv=onlyfans_path,
        chaturbate_monthly_csvs=[monthly_path],
        overrides=default_creator_overrides(),
    )
    totals = compute_earnings_source_totals(parsed)
    assert len(parsed) == 2
    assert totals["onlyfans_90d"] == 17010.49
    assert totals["chaturbate_monthly"] == 6570.85
