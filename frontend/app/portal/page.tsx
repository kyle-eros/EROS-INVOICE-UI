import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { BrandWordmark } from "../components/BrandWordmark";
import { DataTable, type DataColumn } from "../components/DataTable";
import { StatusBadge } from "../components/StatusBadge";
import { SurfaceCard } from "../components/SurfaceCard";
import { getCreatorInvoicesBySession, type CreatorInvoiceItem } from "../../lib/api";
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

  try {
    const response = await getCreatorInvoicesBySession(sessionToken);
    invoices = response.invoices;
    creatorName = response.creator_name;
  } catch {
    redirect("/login");
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
            <p className="kicker">Review your invoices below. Once you&apos;ve submitted payment, mark the invoice as paid.</p>
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
