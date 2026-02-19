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
}

interface CreatorBalanceRow {
  creator_id: string;
  creator_name: string;
  jan_full_invoice_usd: number;
  feb_current_owed_usd: number;
  submitted_payment_invoice_count: number;
}

function formatUsd(value: number): string {
  return USD_CURRENCY_FORMATTER.format(value);
}

function compareBalanceRows(left: CreatorBalanceRow, right: CreatorBalanceRow): number {
  if (right.feb_current_owed_usd !== left.feb_current_owed_usd) {
    return right.feb_current_owed_usd - left.feb_current_owed_usd;
  }
  if (right.jan_full_invoice_usd !== left.jan_full_invoice_usd) {
    return right.jan_full_invoice_usd - left.jan_full_invoice_usd;
  }
  if (left.creator_name !== right.creator_name) {
    return left.creator_name.localeCompare(right.creator_name, "en", { sensitivity: "base" });
  }
  return left.creator_id.localeCompare(right.creator_id, "en", { sensitivity: "base" });
}

export function CreatorBalancesSection({ creators, loadError, focusYear }: CreatorBalancesSectionProps) {
  const balanceRows = creators
    .filter((creator) => creator.jan_full_invoice_usd > 0 || creator.feb_current_owed_usd > 0)
    .map((creator) => ({
      creator_id: creator.creator_id,
      creator_name: creator.creator_name,
      jan_full_invoice_usd: creator.jan_full_invoice_usd,
      feb_current_owed_usd: creator.feb_current_owed_usd,
      submitted_payment_invoice_count: creator.submitted_payment_invoice_count,
    }))
    .sort(compareBalanceRows);

  const creatorsInScope = balanceRows.length;
  const januaryInvoiceTotalUsd = balanceRows.reduce((sum, row) => sum + row.jan_full_invoice_usd, 0);
  const februaryCurrentOwedUsd = balanceRows.reduce((sum, row) => sum + row.feb_current_owed_usd, 0);
  const submittedPaymentNoticeCount = balanceRows.reduce((sum, row) => sum + row.submitted_payment_invoice_count, 0);
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
      id: "january",
      header: `Jan ${focusYear} Invoice`,
      align: "right",
      className: "numeric-cell",
      render: (row) => <span className="creator-balance-row__amount">{formatUsd(row.jan_full_invoice_usd)}</span>,
    },
    {
      id: "february",
      header: `Feb ${focusYear} Owed`,
      align: "right",
      className: "numeric-cell",
      render: (row) => <span className="creator-balance-row__amount">{formatUsd(row.feb_current_owed_usd)}</span>,
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
        <h2>Creator Balances Owed</h2>
        <p className="kicker">Review January full invoices and current February owed balances for the demo window.</p>
      </div>

      {loadError ? (
        <p className="muted-small">Creator balance data unavailable: {loadError}</p>
      ) : balanceRows.length === 0 ? (
        <>
          <EmptyState
            title="No Jan/Feb creator balances"
            description={`No creators currently have January or February ${focusYear} USD balances in scope.`}
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
              <span>Creators in Scope</span>
              <strong>{creatorsInScope}</strong>
            </div>
            <div className="creator-balance-kpi">
              <span>January Full Invoices</span>
              <strong>{formatUsd(januaryInvoiceTotalUsd)}</strong>
            </div>
            <div className="creator-balance-kpi">
              <span>February Current Owed</span>
              <strong>{formatUsd(februaryCurrentOwedUsd)}</strong>
            </div>
            <div className="creator-balance-kpi">
              <span>Payment Submitted</span>
              <strong>{submittedPaymentNoticeCount}</strong>
            </div>
          </div>

          {hasExcludedNonUsdInvoices ? (
            <p className="muted-small creator-balance-note">
              Some open non-USD invoices were excluded from USD totals.
            </p>
          ) : null}

          <DataTable
            caption="Creator January full invoices and February current owed balances"
            columns={columns}
            rows={balanceRows}
            rowKey={(row) => row.creator_id}
          />
        </>
      )}
    </SurfaceCard>
  );
}
