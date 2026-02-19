import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import { BrandWordmark } from "../components/BrandWordmark";
import { DataTable, type DataColumn } from "../components/DataTable";
import { StatusBadge } from "../components/StatusBadge";
import { SurfaceCard } from "../components/SurfaceCard";
import {
  BackendApiError,
  getCreatorInvoicesBySession,
  submitCreatorInvoicePaymentSubmissionBySession,
  type CreatorInvoiceItem,
} from "../../lib/api";
import { LogoutButton } from "./LogoutButton";

const DATE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

const CURRENCY_FORMATTERS = new Map<string, Intl.NumberFormat>();
const DEMO_FOCUS_YEAR = (() => {
  const parsed = Number.parseInt(process.env.DEMO_FOCUS_YEAR ?? "2026", 10);
  if (Number.isFinite(parsed) && parsed >= 2000 && parsed <= 2100) {
    return parsed;
  }
  return 2026;
})();

function formatDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? value : DATE_FORMATTER.format(parsed);
}

function normalizeCurrency(currency: string): string {
  const normalized = currency.trim().toUpperCase();
  return normalized || "USD";
}

function formatterForCurrency(currency: string): Intl.NumberFormat | null {
  const normalized = normalizeCurrency(currency);
  const existing = CURRENCY_FORMATTERS.get(normalized);
  if (existing) {
    return existing;
  }
  try {
    const formatter = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: normalized,
      minimumFractionDigits: 2,
    });
    CURRENCY_FORMATTERS.set(normalized, formatter);
    return formatter;
  } catch {
    return null;
  }
}

function formatCurrency(value: number, currency: string): string {
  const normalized = normalizeCurrency(currency);
  const formatter = formatterForCurrency(normalized);
  if (!formatter) {
    return `${normalized} ${value.toFixed(2)}`;
  }
  return formatter.format(value);
}

function formatInvoiceStatus(status: CreatorInvoiceItem["status"]): string {
  if (status === "paid") return "Paid";
  if (status === "partial") return "Partial";
  if (status === "overdue") return "Overdue";
  if (status === "escalated") return "Escalated";
  return "Open";
}

function statusTone(status: CreatorInvoiceItem["status"]): "success" | "warning" | "brand" | "danger" {
  if (status === "paid") return "success";
  if (status === "partial") return "warning";
  if (status === "overdue" || status === "escalated") return "danger";
  return "brand";
}

function issuedDate(invoice: CreatorInvoiceItem): Date | null {
  const parsed = new Date(`${invoice.issued_at}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function isDemoWindowInvoice(invoice: CreatorInvoiceItem): boolean {
  const parsed = issuedDate(invoice);
  if (!parsed) {
    return false;
  }
  const year = parsed.getUTCFullYear();
  const month = parsed.getUTCMonth();
  return year === DEMO_FOCUS_YEAR && (month === 0 || month === 1);
}

function isJanuaryInvoice(invoice: CreatorInvoiceItem): boolean {
  const parsed = issuedDate(invoice);
  return parsed ? parsed.getUTCFullYear() === DEMO_FOCUS_YEAR && parsed.getUTCMonth() === 0 : false;
}

function isFebruaryInvoice(invoice: CreatorInvoiceItem): boolean {
  const parsed = issuedDate(invoice);
  return parsed ? parsed.getUTCFullYear() === DEMO_FOCUS_YEAR && parsed.getUTCMonth() === 1 : false;
}

function formatCurrencyBreakdown(amountsByCurrency: Map<string, number>): string {
  const parts = Array.from(amountsByCurrency.entries())
    .filter(([, total]) => total > 0)
    .sort(([left], [right]) => left.localeCompare(right, "en", { sensitivity: "base" }))
    .map(([currency, total]) => formatCurrency(total, currency));
  return parts.length > 0 ? parts.join(", ") : formatCurrency(0, "USD");
}

function canSubmitPaymentNotice(invoice: CreatorInvoiceItem): boolean {
  return (invoice.status === "open" || invoice.status === "overdue") && invoice.balance_due > 0;
}

async function confirmPaymentSubmittedAction(formData: FormData) {
  "use server";

  const invoiceId = (formData.get("invoice_id") as string | null)?.trim();
  if (!invoiceId) {
    redirect("/portal?paymentSubmission=error&reason=missing_invoice");
  }

  const cookieStore = await cookies();
  const sessionToken = cookieStore.get("eros_session")?.value;
  if (!sessionToken) {
    redirect("/login");
  }

  try {
    await submitCreatorInvoicePaymentSubmissionBySession(sessionToken, invoiceId);
    revalidatePath("/portal");
    redirect(`/portal?paymentSubmission=success&invoiceId=${encodeURIComponent(invoiceId)}`);
  } catch (error) {
    if (error instanceof BackendApiError && (error.status === 401 || error.status === 403)) {
      redirect("/login");
    }
    let reason = "request_failed";
    if (error instanceof BackendApiError && error.status === 404) {
      reason = "invoice_not_found";
    } else if (error instanceof BackendApiError && error.status === 409) {
      reason = "invoice_not_eligible";
    }
    revalidatePath("/portal");
    redirect(`/portal?paymentSubmission=error&invoiceId=${encodeURIComponent(invoiceId)}&reason=${encodeURIComponent(reason)}`);
  }
}

interface PortalPageSearchParams {
  paymentSubmission?: string;
  invoiceId?: string;
  reason?: string;
}

export default async function PortalPage({
  searchParams,
}: {
  searchParams?: Promise<PortalPageSearchParams>;
}) {
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get("eros_session")?.value;

  if (!sessionToken) {
    redirect("/login");
  }

  let invoices: CreatorInvoiceItem[] = [];
  let creatorName = "Creator";
  let accountNotReady = false;
  let portalUnavailableMessage: string | null = null;

  try {
    const response = await getCreatorInvoicesBySession(sessionToken);
    invoices = response.invoices;
    creatorName = response.creator_name;
  } catch (error) {
    if (error instanceof BackendApiError && (error.status === 401 || error.status === 403)) {
      redirect("/login");
    }
    if (error instanceof BackendApiError && error.status === 404) {
      accountNotReady = true;
    } else if (error instanceof Error) {
      portalUnavailableMessage = error.message;
    } else {
      portalUnavailableMessage = "Unable to load your invoices right now.";
    }
  }

  if (accountNotReady) {
    return (
      <main id="main-content" className="page-wrap">
        <div className="section-stack">
          <header className="creator-header reveal-item">
            <BrandWordmark size="sm" />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
              <h1>Your Invoices</h1>
              <LogoutButton />
            </div>
            <p className="kicker">Your passkey was verified, but your portal data is not ready yet.</p>
          </header>

          <SurfaceCard as="section" className="creator-state-card reveal-item" data-delay="1">
            <h2>Portal setup in progress</h2>
            <p>
              We could not find dispatched invoices for this account yet. Please contact your agency to confirm your creator
              profile and invoice dispatch setup.
            </p>
          </SurfaceCard>
        </div>
      </main>
    );
  }

  if (portalUnavailableMessage) {
    return (
      <main id="main-content" className="page-wrap">
        <div className="section-stack">
          <header className="creator-header reveal-item">
            <BrandWordmark size="sm" />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
              <h1>Your Invoices</h1>
              <LogoutButton />
            </div>
            <p className="kicker">We hit a temporary issue while loading your portal.</p>
          </header>

          <SurfaceCard as="section" className="creator-state-card reveal-item" data-delay="1">
            <h2>Unable to load invoices</h2>
            <p>Please refresh and try again. If this continues, contact your agency for support.</p>
            <p className="muted-small">Details: {portalUnavailableMessage}</p>
          </SurfaceCard>
        </div>
      </main>
    );
  }

  const scopedInvoices = invoices.filter(isDemoWindowInvoice);
  const januaryInvoices = scopedInvoices.filter(isJanuaryInvoice);
  const februaryInvoices = scopedInvoices.filter(isFebruaryInvoice);
  const outstandingInvoices = februaryInvoices.filter((invoice) => invoice.balance_due > 0);
  const outstandingCount = outstandingInvoices.length;
  const outstandingByCurrency = new Map<string, number>();
  for (const invoice of outstandingInvoices) {
    const currency = normalizeCurrency(invoice.currency);
    const total = outstandingByCurrency.get(currency) ?? 0;
    outstandingByCurrency.set(currency, total + invoice.balance_due);
  }
  const januaryInvoiceByCurrency = new Map<string, number>();
  for (const invoice of januaryInvoices) {
    const currency = normalizeCurrency(invoice.currency);
    const total = januaryInvoiceByCurrency.get(currency) ?? 0;
    januaryInvoiceByCurrency.set(currency, total + invoice.amount_due);
  }
  const januaryInvoiceBreakdown = formatCurrencyBreakdown(januaryInvoiceByCurrency);
  const outstandingBreakdown = formatCurrencyBreakdown(outstandingByCurrency);
  const hasOutstanding = outstandingCount > 0;
  const paymentSubmissionState = resolvedSearchParams?.paymentSubmission;
  const paymentSubmissionInvoiceId = resolvedSearchParams?.invoiceId;
  const paymentSubmissionReason = resolvedSearchParams?.reason;
  const paymentSubmissionBanner =
    paymentSubmissionState === "success"
      ? {
          tone: "ok" as const,
          message: paymentSubmissionInvoiceId
            ? `Payment submission recorded for invoice ${paymentSubmissionInvoiceId}.`
            : "Payment submission recorded.",
        }
      : paymentSubmissionState === "error"
        ? {
            tone: "error" as const,
            message:
              paymentSubmissionReason === "invoice_not_eligible"
                ? "This invoice cannot be confirmed right now. Only open or overdue invoices with an outstanding balance are eligible."
                : paymentSubmissionReason === "invoice_not_found"
                  ? "Invoice not found for this creator session."
                  : "Unable to submit your payment confirmation right now. Please try again.",
          }
        : null;

  const columns: DataColumn<CreatorInvoiceItem>[] = [
    {
      id: "invoice",
      header: "Invoice",
      className: "cell-task",
      render: (invoice) => <span className="task-id">{invoice.invoice_id}</span>,
    },
    {
      id: "status",
      header: "Status",
      render: (invoice) => (
        <StatusBadge tone={statusTone(invoice.status)}>
          {formatInvoiceStatus(invoice.status)}
        </StatusBadge>
      ),
    },
    {
      id: "currency",
      header: "Currency",
      render: (invoice) => <span className="task-id">{normalizeCurrency(invoice.currency)}</span>,
    },
    {
      id: "paid",
      header: "Amount Paid",
      align: "right",
      className: "cell-sources",
      render: (invoice) => <span className="numeric-cell">{formatCurrency(invoice.amount_paid, invoice.currency)}</span>,
    },
    {
      id: "balance",
      header: "Balance Due",
      align: "right",
      className: "cell-sources",
      render: (invoice) => <span className="numeric-cell">{formatCurrency(invoice.balance_due, invoice.currency)}</span>,
    },
    {
      id: "due",
      header: "Due Date",
      render: (invoice) => <span>{formatDate(invoice.due_date)}</span>,
    },
    {
      id: "issued",
      header: "Issued",
      render: (invoice) => <span>{formatDate(invoice.issued_at)}</span>,
    },
    {
      id: "pdf",
      header: "PDF",
      render: (invoice) =>
        invoice.has_pdf ? (
          <Link
            className="button-link button-link--secondary invoice-pdf-link"
            href={`/portal/invoices/${encodeURIComponent(invoice.invoice_id)}`}
          >
            View PDF
          </Link>
        ) : (
          <span className="muted-small">Unavailable</span>
        ),
    },
    {
      id: "payment-submission",
      header: "Payment Submission",
      render: (invoice) => {
        if (invoice.creator_payment_submitted_at) {
          return <span className="invoice-payment-submitted-label">Payment submitted</span>;
        }

        if (!canSubmitPaymentNotice(invoice)) {
          return <span className="muted-small">Unavailable</span>;
        }

        return (
          <form action={confirmPaymentSubmittedAction} className="invoice-payment-submit-form">
            <input type="hidden" name="invoice_id" value={invoice.invoice_id} />
            <button type="submit" className="button-link button-link--secondary invoice-payment-submit-button">
              Click here to confirm payment submitted
            </button>
          </form>
        );
      },
    },
  ];

  return (
    <main id="main-content" className="page-wrap">
      <div className="section-stack">
        <header className="creator-header reveal-item">
          <BrandWordmark size="sm" />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
            <h1>{creatorName}&apos;s Invoices</h1>
            <LogoutButton />
          </div>
          <p className="kicker">View your January full invoice and February current owed balances, plus invoice PDFs.</p>
          <p className="muted-small">
            Demo scope: this portal view is filtered to January and February {DEMO_FOCUS_YEAR} invoices only.
          </p>
        </header>

        {paymentSubmissionBanner ? (
          <p
            className={`reminder-run-banner ${paymentSubmissionBanner.tone === "ok" ? "reminder-run-banner--ok" : "reminder-run-banner--error"}`}
          >
            {paymentSubmissionBanner.message}
          </p>
        ) : null}

        <SurfaceCard as="section" className="creator-state-card reveal-item" data-delay="1">
          <h2>
            {scopedInvoices.length === 0
              ? "No Jan/Feb invoices found"
              : hasOutstanding
                ? `February ${DEMO_FOCUS_YEAR} balances are outstanding`
                : `February ${DEMO_FOCUS_YEAR} balances are clear`}
          </h2>
          <p>
            {scopedInvoices.length === 0
              ? `No invoices were found for January or February ${DEMO_FOCUS_YEAR}.`
              : `January ${DEMO_FOCUS_YEAR} full invoice total: ${januaryInvoiceBreakdown}. February ${DEMO_FOCUS_YEAR} current owed: ${outstandingBreakdown}.`}
          </p>
          {scopedInvoices.length > 0 ? (
            <p className="muted-small">
              {januaryInvoices.length} January invoice{januaryInvoices.length === 1 ? "" : "s"} and {februaryInvoices.length} February invoice{februaryInvoices.length === 1 ? "" : "s"} in this demo window.
            </p>
          ) : null}
        </SurfaceCard>

        <SurfaceCard as="section" className="invoicing-table-card reveal-item" data-delay="2">
          <div className="invoicing-table-card__head">
            <h2>Jan/Feb Invoices</h2>
            <p className="kicker">Review January and February invoice balances, due dates, and open each available PDF.</p>
          </div>
          <DataTable
            caption="Your January and February invoices and payment status"
            columns={columns}
            rows={scopedInvoices}
            rowKey={(invoice) => invoice.invoice_id}
          />
        </SurfaceCard>
      </div>
    </main>
  );
}
