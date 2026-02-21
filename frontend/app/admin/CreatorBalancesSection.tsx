"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { DataTable, type DataColumn } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { SurfaceCard } from "../components/SurfaceCard";
import type { AdminCreatorDirectoryItem } from "../../lib/api";

const USD_CURRENCY_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
});

interface CreatorBalancesSectionProps {
  creators: AdminCreatorDirectoryItem[];
  loadError: string | null;
  focusYear: number;
  initialQuery: string;
  initialOwedOnly: boolean;
}

interface CreatorBalanceRow {
  creator_id: string;
  creator_name: string;
  total_balance_owed_usd: number;
  unpaid_invoice_count: number;
  dispatched_invoice_count: number;
  submitted_payment_invoice_count: number;
  ready_for_portal: boolean;
}

function formatUsd(value: number): string {
  return USD_CURRENCY_FORMATTER.format(value);
}

function compareBalanceRows(left: CreatorBalanceRow, right: CreatorBalanceRow): number {
  if (right.total_balance_owed_usd !== left.total_balance_owed_usd) {
    return right.total_balance_owed_usd - left.total_balance_owed_usd;
  }
  if (right.unpaid_invoice_count !== left.unpaid_invoice_count) {
    return right.unpaid_invoice_count - left.unpaid_invoice_count;
  }
  if (left.creator_name !== right.creator_name) {
    return left.creator_name.localeCompare(right.creator_name, "en", { sensitivity: "base" });
  }
  return left.creator_id.localeCompare(right.creator_id, "en", { sensitivity: "base" });
}

function normalizeCreatorQuery(value: string): string {
  return value.trim();
}

function parseOwedOnlyParam(value: string | null): boolean {
  if (!value) {
    return true;
  }
  return !["0", "false", "off", "no"].includes(value.trim().toLowerCase());
}

function creatorMatchesQuery(row: CreatorBalanceRow, normalizedQuery: string): boolean {
  if (!normalizedQuery) {
    return true;
  }
  const loweredQuery = normalizedQuery.toLowerCase();
  return (
    row.creator_name.toLowerCase().includes(loweredQuery) ||
    row.creator_id.toLowerCase().includes(loweredQuery)
  );
}

export function CreatorBalancesSection({
  creators,
  loadError,
  focusYear,
  initialQuery,
  initialOwedOnly,
}: CreatorBalancesSectionProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [creatorQuery, setCreatorQuery] = useState(initialQuery);
  const [owedOnly, setOwedOnly] = useState(initialOwedOnly);
  const previousOwedOnlyRef = useRef(initialOwedOnly);

  useEffect(() => {
    const queryParam = normalizeCreatorQuery(searchParams.get("creator_q") ?? "");
    const owedOnlyParam = parseOwedOnlyParam(searchParams.get("creator_owed_only"));
    setCreatorQuery((current) => (normalizeCreatorQuery(current) === queryParam ? current : queryParam));
    setOwedOnly((current) => (current === owedOnlyParam ? current : owedOnlyParam));
    previousOwedOnlyRef.current = owedOnlyParam;
  }, [searchParams]);

  useEffect(() => {
    const syncFiltersToUrl = () => {
      const params = new URLSearchParams(searchParams.toString());
      let changed = false;
      const normalizedQuery = normalizeCreatorQuery(creatorQuery);
      const currentQuery = searchParams.get("creator_q");
      const currentOwedOnly = searchParams.get("creator_owed_only");

      if (normalizedQuery) {
        if (currentQuery !== normalizedQuery) {
          params.set("creator_q", normalizedQuery);
          changed = true;
        }
      } else if (currentQuery !== null) {
        params.delete("creator_q");
        changed = true;
      }

      if (owedOnly) {
        if (currentOwedOnly !== null) {
          params.delete("creator_owed_only");
          changed = true;
        }
      } else if (currentOwedOnly !== "0") {
        params.set("creator_owed_only", "0");
        changed = true;
      }

      if (!changed) {
        return;
      }

      const nextQuery = params.toString();
      router.replace(nextQuery ? `${pathname}?${nextQuery}` : pathname, { scroll: false });
    };

    const owedOnlyChanged = previousOwedOnlyRef.current !== owedOnly;
    previousOwedOnlyRef.current = owedOnly;

    if (owedOnlyChanged) {
      syncFiltersToUrl();
      return;
    }

    const timeoutId = window.setTimeout(syncFiltersToUrl, 240);
    return () => window.clearTimeout(timeoutId);
  }, [creatorQuery, owedOnly, pathname, router, searchParams]);

  const normalizedQuery = normalizeCreatorQuery(creatorQuery);
  const hasActiveFilters = normalizedQuery.length > 0 || !owedOnly;

  const balanceRows = useMemo(
    () =>
      creators
        .filter((creator) => creator.invoice_count > 0)
        .map((creator) => ({
          creator_id: creator.creator_id,
          creator_name: creator.creator_name,
          total_balance_owed_usd: creator.total_balance_owed_usd,
          unpaid_invoice_count: creator.unpaid_invoice_count,
          dispatched_invoice_count: creator.dispatched_invoice_count,
          submitted_payment_invoice_count: creator.submitted_payment_invoice_count,
          ready_for_portal: creator.ready_for_portal,
        }))
        .sort(compareBalanceRows),
    [creators],
  );

  const filteredRows = useMemo(
    () =>
      balanceRows.filter((row) => {
        if (owedOnly && row.total_balance_owed_usd <= 0) {
          return false;
        }
        return creatorMatchesQuery(row, normalizedQuery);
      }),
    [balanceRows, owedOnly, normalizedQuery],
  );

  const creatorsInScope = filteredRows.length;
  const totalOutstandingUsd = filteredRows.reduce((sum, row) => sum + row.total_balance_owed_usd, 0);
  const unpaidInvoiceCount = filteredRows.reduce((sum, row) => sum + row.unpaid_invoice_count, 0);
  const dispatchedInvoiceCount = filteredRows.reduce((sum, row) => sum + row.dispatched_invoice_count, 0);
  const submittedPaymentNoticeCount = filteredRows.reduce((sum, row) => sum + row.submitted_payment_invoice_count, 0);
  const readyForPortalCount = filteredRows.filter((row) => row.ready_for_portal).length;
  const hasExcludedNonUsdInvoices = creators.some((creator) => creator.has_non_usd_open_invoices);

  const columns: DataColumn<CreatorBalanceRow>[] = [
    {
      id: "creator",
      header: "Creator",
      render: (row) => (
        <span className="creator-balance-row__creator">
          <span>{row.creator_name}</span>
          <span className="creator-balance-row__creator-id">{row.creator_id}</span>
        </span>
      ),
    },
    {
      id: "owed",
      header: "Total Owed (USD)",
      align: "right",
      className: "numeric-cell",
      render: (row) => <span className="creator-balance-row__amount">{formatUsd(row.total_balance_owed_usd)}</span>,
    },
    {
      id: "unpaid",
      header: "Unpaid Invoices",
      align: "right",
      className: "numeric-cell",
      render: (row) => <span className="creator-balance-row__amount">{row.unpaid_invoice_count}</span>,
    },
    {
      id: "dispatched",
      header: "Dispatched",
      align: "right",
      className: "numeric-cell",
      render: (row) => <span className="creator-balance-row__amount">{row.dispatched_invoice_count}</span>,
    },
    {
      id: "submitted",
      header: "Payment Submitted",
      align: "right",
      className: "numeric-cell",
      render: (row) => <span className="creator-balance-row__amount">{row.submitted_payment_invoice_count}</span>,
    },
  ];

  return (
    <SurfaceCard as="section" className="invoicing-table-card creator-balance-card reveal-item" data-delay="1">
      <div className="invoicing-table-card__head">
        <h2>Creator Balances</h2>
        <p className="kicker">Track outstanding balances, unpaid invoices, and submitted payment confirmations.</p>
        <p className="muted-small">Focus year for creator directory totals: {focusYear}.</p>
      </div>

      {loadError ? (
        <p className="muted-small">Creator balance data unavailable: {loadError}</p>
      ) : balanceRows.length === 0 ? (
        <>
          <EmptyState
            title="No creator balances to show"
            description={`No creators currently have invoice records in scope for ${focusYear}.`}
          />
          {hasExcludedNonUsdInvoices ? (
            <p className="muted-small creator-balance-note">
              Some open non-USD invoices were excluded from USD totals.
            </p>
          ) : null}
        </>
      ) : (
        <>
          <div className="creator-balance-controls" role="search" aria-label="Filter creator balances">
            <div className="creator-balance-controls__search">
              <label htmlFor="creator-balance-search">Search creators</label>
              <input
                id="creator-balance-search"
                className="creator-balance-search-input"
                type="search"
                value={creatorQuery}
                onChange={(event) => setCreatorQuery(event.target.value)}
                placeholder="Search by creator name or ID"
                autoComplete="off"
              />
            </div>
            <label className="creator-balance-toggle">
              <input
                type="checkbox"
                checked={owedOnly}
                onChange={(event) => setOwedOnly(event.target.checked)}
              />
              Owed only
            </label>
            {hasActiveFilters ? (
              <button
                type="button"
                className="button-link button-link--secondary creator-balance-clear"
                onClick={() => {
                  setCreatorQuery("");
                  setOwedOnly(true);
                }}
              >
                Clear filters
              </button>
            ) : null}
          </div>
          <p className="muted-small creator-balance-results" aria-live="polite">
            {filteredRows.length} creator{filteredRows.length === 1 ? "" : "s"} shown
          </p>

          {filteredRows.length === 0 ? (
            <>
              <EmptyState
                title="No creators match filters"
                description={
                  normalizedQuery && owedOnly
                    ? `No creators match "${normalizedQuery}" with owed-only enabled.`
                    : normalizedQuery
                      ? `No creators match "${normalizedQuery}".`
                      : "No creators match the current filters."
                }
              />
              {hasExcludedNonUsdInvoices ? (
                <p className="muted-small creator-balance-note">
                  Some open non-USD invoices were excluded from USD totals.
                </p>
              ) : null}
            </>
          ) : (
            <>
              <div className="creator-balance-kpi-grid" aria-label="Creator balance summary">
                <div className="creator-balance-kpi">
                  <span>Creators In Scope</span>
                  <strong>{creatorsInScope}</strong>
                </div>
                <div className="creator-balance-kpi">
                  <span>Total Owed (USD)</span>
                  <strong>{formatUsd(totalOutstandingUsd)}</strong>
                </div>
                <div className="creator-balance-kpi">
                  <span>Unpaid Invoices</span>
                  <strong>{unpaidInvoiceCount}</strong>
                </div>
                <div className="creator-balance-kpi">
                  <span>Payments Submitted</span>
                  <strong>{submittedPaymentNoticeCount}</strong>
                </div>
              </div>

              <p className="muted-small">
                {readyForPortalCount} creator{readyForPortalCount === 1 ? "" : "s"} currently portal-ready and {dispatchedInvoiceCount} dispatched invoice{dispatchedInvoiceCount === 1 ? "" : "s"} in view.
              </p>

              {hasExcludedNonUsdInvoices ? (
                <p className="muted-small creator-balance-note">
                  Some open non-USD invoices were excluded from USD totals.
                </p>
              ) : null}

              <DataTable
                caption="Creator balances, unpaid invoices, and payment-submission status"
                columns={columns}
                rows={filteredRows}
                rowKey={(row) => row.creator_id}
              />
            </>
          )}
        </>
      )}
    </SurfaceCard>
  );
}
