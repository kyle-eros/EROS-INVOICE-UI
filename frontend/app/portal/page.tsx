import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import { BrandWordmark } from "../components/BrandWordmark";
import { DataTable, type DataColumn } from "../components/DataTable";
import { StatusBadge } from "../components/StatusBadge";
import { SurfaceCard } from "../components/SurfaceCard";
import { BackendApiError, getCreatorInvoicesBySession, type CreatorInvoiceItem } from "../../lib/api";
import { LogoutButton } from "./LogoutButton";

const DATE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

const CURRENCY_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
});

function formatDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? value : DATE_FORMATTER.format(parsed);
}

function formatCurrency(value: number): string {
  return CURRENCY_FORMATTER.format(value);
}

export default async function PortalPage() {
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

  const unfulfilledCount = invoices.filter((invoice) => invoice.notification_state !== "fulfilled").length;
  const hasUnfulfilled = unfulfilledCount > 0;

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
        <StatusBadge tone={invoice.notification_state === "fulfilled" ? "success" : "warning"}>
          {invoice.notification_state === "fulfilled" ? "paid" : "unpaid"}
        </StatusBadge>
      ),
    },
    {
      id: "balance",
      header: "Amount Due",
      align: "right",
      className: "cell-sources",
      render: (invoice) => <span className="numeric-cell">{formatCurrency(invoice.balance_due)}</span>,
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
          <p className="kicker">View your outstanding balances and confirm when you&apos;ve submitted payment.</p>
        </header>

        <SurfaceCard as="section" className="creator-state-card reveal-item" data-delay="1">
          <h2>{hasUnfulfilled ? "You have unpaid invoices" : "All invoices are paid"}</h2>
          <p>
            {hasUnfulfilled
              ? `You have ${unfulfilledCount} outstanding invoice${unfulfilledCount === 1 ? "" : "s"} that still need payment.`
              : "You're all caught up — no outstanding balances."}
          </p>
        </SurfaceCard>

        <SurfaceCard as="section" className="invoicing-table-card reveal-item" data-delay="2">
          <div className="invoicing-table-card__head">
            <h2>Your Invoices</h2>
            <p className="kicker">Review invoice balances, due dates, and open each available PDF from the portal.</p>
          </div>
          <DataTable
            caption="Your invoices and payment status"
            columns={columns}
            rows={invoices}
            rowKey={(invoice) => invoice.invoice_id}
          />
        </SurfaceCard>
      </div>
    </main>
  );
}
