from __future__ import annotations

import calendar
import csv
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from .models import InvoiceUpsertItem, InvoiceUpsertRequest


@dataclass(frozen=True)
class SalesSession:
    row_number: int
    session_date: date
    operator_name: str
    model_name: str
    start_time_pht: str
    end_time_pht: str
    stream_type: str
    converted_usd: float


@dataclass(frozen=True)
class CreatorStatsRow:
    creator_name: str
    total_earnings_net: float | None


@dataclass(frozen=True)
class EarningsAggregateRow:
    source: str
    source_file: str
    source_window: str
    creator_name_raw: str
    creator_name_normalized: str
    amount_usd: float
    period_start: date
    period_end: date


@dataclass(frozen=True)
class SalesProfile:
    total_rows: int
    included_rows: int
    excluded_rows: int
    exclusion_reasons: dict[str, int]
    creator_candidates: list[str]
    sales_total_usd: float


def parse_money(value: str | None) -> float | None:
    normalized = (value or "").strip().replace("$", "").replace(",", "")
    if not normalized:
        return None
    try:
        return round(float(normalized), 2)
    except ValueError:
        return None


def normalize_creator_name(value: str) -> str:
    lowered = value.lower().strip()
    ascii_only = lowered.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", ascii_only)
    return re.sub(r"\s+", " ", cleaned).strip()


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "unknown"


def default_creator_overrides() -> dict[str, str]:
    return {
        normalize_creator_name("Grace Bennett Paid"): normalize_creator_name("Grace Bennett"),
        normalize_creator_name("Oliva Hansley PAID"): normalize_creator_name("Olivia Hansley PAID"),
        normalize_creator_name("Scarlet Grace"): normalize_creator_name("Scarlett Grace"),
        normalize_creator_name("Tessatan FREE"): normalize_creator_name("Tessa Tan FREE"),
    }


def parse_creator_overrides(values: Iterable[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"invalid creator override (expected from=to): {raw}")
        left, right = raw.split("=", 1)
        source = normalize_creator_name(left)
        target = normalize_creator_name(right)
        if not source or not target:
            raise ValueError(f"invalid creator override (blank side): {raw}")
        overrides[source] = target
    return overrides


def _parse_month_day(raw: str, year: int) -> date | None:
    value = raw.strip()
    if not value or "/" not in value:
        return None
    month, day = value.split("/", 1)
    try:
        return date(year, int(month), int(day))
    except ValueError:
        return None


def parse_sales_sessions(path: Path, *, year: int = 2026) -> tuple[list[SalesSession], SalesProfile]:
    exclusion_reasons: Counter[str] = Counter()
    sessions: list[SalesSession] = []

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    for offset, row in enumerate(rows, start=2):
        model_name = (row.get("Model Name") or "").strip()
        start_time_pht = (row.get("Start Time (PHT)") or "").strip()
        converted_usd = parse_money(row.get("Converted to USD"))
        session_date = _parse_month_day((row.get("Date (PHT)") or ""), year)

        if "extraction" in model_name.lower():
            exclusion_reasons["extraction_row"] += 1
            continue
        if not start_time_pht or ":" not in start_time_pht:
            exclusion_reasons["invalid_session_time"] += 1
            continue
        if converted_usd is None:
            exclusion_reasons["missing_converted_usd"] += 1
            continue
        if session_date is None:
            exclusion_reasons["invalid_date"] += 1
            continue

        sessions.append(
            SalesSession(
                row_number=offset,
                session_date=session_date,
                operator_name=(row.get("Operator Name") or "").strip(),
                model_name=model_name,
                start_time_pht=start_time_pht,
                end_time_pht=(row.get("End Time (PHT)") or "").strip(),
                stream_type=(row.get("Stream Type") or "").strip(),
                converted_usd=converted_usd,
            )
        )

    creator_candidates = sorted({session.model_name for session in sessions})
    sales_total = round(sum(session.converted_usd for session in sessions), 2)
    profile = SalesProfile(
        total_rows=len(rows),
        included_rows=len(sessions),
        excluded_rows=len(rows) - len(sessions),
        exclusion_reasons=dict(exclusion_reasons),
        creator_candidates=creator_candidates,
        sales_total_usd=sales_total,
    )
    return sessions, profile


def parse_creator_stats(path: Path) -> list[CreatorStatsRow]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    stats_rows: list[CreatorStatsRow] = []
    for row in rows:
        creator_name = (row.get("Creator") or "").strip()
        if not creator_name:
            continue
        stats_rows.append(
            CreatorStatsRow(
                creator_name=creator_name,
                total_earnings_net=parse_money(row.get("Total earnings Net")),
            )
        )
    return stats_rows


def parse_onlyfans_earnings(path: Path, *, overrides: dict[str, str] | None = None) -> list[EarningsAggregateRow]:
    resolved_overrides = overrides or {}
    rows_out: list[EarningsAggregateRow] = []

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    for row in rows:
        creator_name_raw = (row.get("Creator") or "").strip()
        if not creator_name_raw:
            continue

        total_earnings = parse_money(row.get("Total earnings Net"))
        if total_earnings is None:
            continue

        date_range_raw = (row.get("Date/Time") or "").strip()
        period_start, period_end = _parse_date_range(date_range_raw)

        normalized = normalize_creator_name(creator_name_raw)
        normalized = resolved_overrides.get(normalized, normalized)

        rows_out.append(
            EarningsAggregateRow(
                source="onlyfans_90d",
                source_file=path.name,
                source_window=f"{period_start.isoformat()}_to_{period_end.isoformat()}",
                creator_name_raw=creator_name_raw,
                creator_name_normalized=normalized,
                amount_usd=total_earnings,
                period_start=period_start,
                period_end=period_end,
            )
        )

    return rows_out


def parse_chaturbate_monthly_revenue(path: Path, *, overrides: dict[str, str] | None = None) -> list[EarningsAggregateRow]:
    resolved_overrides = overrides or {}
    year_month = _parse_year_month_from_name(path)
    last_day = calendar.monthrange(year_month.year, year_month.month)[1]
    period_start = date(year_month.year, year_month.month, 1)
    period_end = date(year_month.year, year_month.month, last_day)

    rows_out: list[EarningsAggregateRow] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    for row in rows:
        creator_name_raw = (row.get("Model Name") or "").strip()
        if not creator_name_raw:
            continue

        total_revenue = parse_money(row.get("Total Revenue USD"))
        if total_revenue is None:
            continue

        normalized = normalize_creator_name(creator_name_raw)
        normalized = resolved_overrides.get(normalized, normalized)

        rows_out.append(
            EarningsAggregateRow(
                source="chaturbate_monthly",
                source_file=path.name,
                source_window=f"{year_month.year:04d}-{year_month.month:02d}",
                creator_name_raw=creator_name_raw,
                creator_name_normalized=normalized,
                amount_usd=total_revenue,
                period_start=period_start,
                period_end=period_end,
            )
        )

    return rows_out


def parse_earnings_bundle(
    *,
    onlyfans_csv: Path,
    chaturbate_monthly_csvs: Iterable[Path],
    overrides: dict[str, str] | None = None,
) -> list[EarningsAggregateRow]:
    rows: list[EarningsAggregateRow] = []
    rows.extend(parse_onlyfans_earnings(onlyfans_csv, overrides=overrides))
    for csv_path in sorted(chaturbate_monthly_csvs):
        rows.extend(parse_chaturbate_monthly_revenue(csv_path, overrides=overrides))
    return rows


def compute_earnings_source_totals(rows: Iterable[EarningsAggregateRow]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        existing = totals.get(row.source, 0.0)
        totals[row.source] = round(existing + row.amount_usd, 2)
    return totals


def resolve_creator_identity(
    sessions: list[SalesSession],
    stats_rows: list[CreatorStatsRow],
    overrides: dict[str, str],
) -> tuple[str, str, str]:
    if not sessions:
        raise ValueError("no normalized sales sessions available to resolve creator identity")

    normalized_session_counts: Counter[str] = Counter(normalize_creator_name(session.model_name) for session in sessions)
    normalized_to_display: dict[str, str] = {}
    for session in sessions:
        normalized = normalize_creator_name(session.model_name)
        normalized_to_display.setdefault(normalized, session.model_name)

    stats_candidates: set[str] = set()
    for row in stats_rows:
        normalized = normalize_creator_name(row.creator_name)
        stats_candidates.add(overrides.get(normalized, normalized))

    chosen_normalized: str
    if stats_candidates:
        matching = [name for name in normalized_session_counts if name in stats_candidates]
        if matching:
            chosen_normalized = sorted(matching, key=lambda key: (-normalized_session_counts[key], key))[0]
        else:
            chosen_normalized = normalized_session_counts.most_common(1)[0][0]
    else:
        chosen_normalized = normalized_session_counts.most_common(1)[0][0]

    display_name = normalized_to_display.get(chosen_normalized)
    if not display_name:
        display_name = " ".join(part.capitalize() for part in chosen_normalized.split())
    creator_id = f"creator-{slugify(chosen_normalized)}"
    return chosen_normalized, display_name, creator_id


def build_invoice_upsert_request(
    sessions: list[SalesSession],
    *,
    creator_name: str,
    creator_id: str,
    creator_timezone: str,
    contact_channel: str,
    contact_target: str,
    due_days: int,
    opt_out: bool = False,
) -> InvoiceUpsertRequest:
    if due_days < 0:
        raise ValueError("due_days must be non-negative")

    sorted_sessions = sorted(sessions, key=lambda value: (value.session_date, value.row_number))
    invoices: list[InvoiceUpsertItem] = []

    for index, session in enumerate(sorted_sessions, start=1):
        invoice_id = f"cb-{session.session_date:%Y%m%d}-{index:03d}"
        due_date = session.session_date + timedelta(days=due_days)
        invoices.append(
            InvoiceUpsertItem(
                invoice_id=invoice_id,
                creator_id=creator_id,
                creator_name=creator_name,
                creator_timezone=creator_timezone,
                contact_channel=contact_channel,
                contact_target=contact_target,
                currency="USD",
                amount_due=session.converted_usd,
                amount_paid=0,
                issued_at=session.session_date,
                due_date=due_date,
                opt_out=opt_out,
                metadata={
                    "source": "cb-daily-sales",
                    "row_number": str(session.row_number),
                    "operator_name": session.operator_name or "unknown",
                    "stream_type": session.stream_type or "unknown",
                },
            )
        )

    return InvoiceUpsertRequest(invoices=invoices)


def build_reconciliation_report(
    sessions: list[SalesSession],
    stats_rows: list[CreatorStatsRow],
    *,
    creator_normalized: str,
    overrides: dict[str, str],
) -> dict[str, float | str | None]:
    sales_total = round(sum(session.converted_usd for session in sessions), 2)

    matching_stats_totals: list[float] = []
    for row in stats_rows:
        normalized = normalize_creator_name(row.creator_name)
        normalized = overrides.get(normalized, normalized)
        if normalized == creator_normalized and row.total_earnings_net is not None:
            matching_stats_totals.append(row.total_earnings_net)

    if matching_stats_totals:
        stats_total = round(sum(matching_stats_totals), 2)
        delta = round(sales_total - stats_total, 2)
        relative_delta = round(abs(delta) / stats_total, 4) if stats_total else None
        status = "match" if delta == 0 else "variance"
    else:
        stats_total = None
        delta = None
        relative_delta = None
        status = "stats_unavailable"

    return {
        "status": status,
        "sales_total_usd": sales_total,
        "stats_total_usd": stats_total,
        "delta_usd": delta,
        "relative_delta": relative_delta,
    }


def dataclass_list_to_dict(items: Iterable[object]) -> list[dict[str, object]]:
    return [asdict(item) for item in items]


def _parse_date_range(value: str) -> tuple[date, date]:
    normalized = value.strip()
    match = re.match(r"^\s*(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})\s*$", normalized)
    if not match:
        raise ValueError(f"invalid date range: {value}")
    start = date.fromisoformat(match.group(1))
    end = date.fromisoformat(match.group(2))
    if end < start:
        raise ValueError(f"date range end is before start: {value}")
    return start, end


def _parse_year_month_from_name(path: Path) -> date:
    match = re.search(r"(\d{4})-(\d{2})", path.stem)
    if not match:
        raise ValueError(f"unable to derive year-month from filename: {path.name}")
    year = int(match.group(1))
    month = int(match.group(2))
    return date(year, month, 1)
