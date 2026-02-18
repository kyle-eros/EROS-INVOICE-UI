import Link from "next/link";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { BrandWordmark } from "../../../components/BrandWordmark";
import { SurfaceCard } from "../../../components/SurfaceCard";
import { BackendApiError, getCreatorInvoicesBySession, type CreatorInvoiceItem } from "../../../../lib/api";
import { LogoutButton } from "../../LogoutButton";

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

export default async function InvoicePdfPage({
  params,
}: {
  params: Promise<{ invoiceId: string }>;
}) {
  const { invoiceId } = await params;
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get("eros_session")?.value;
  if (!sessionToken) {
    redirect("/login");
  }

  let creatorName = "Creator";
  let invoices: CreatorInvoiceItem[] = [];
  let accountNotReady = false;
  let portalUnavailableMessage: string | null = null;
  try {
    const response = await getCreatorInvoicesBySession(sessionToken);
    creatorName = response.creator_name;
    invoices = response.invoices;
  } catch (error) {
    if (error instanceof BackendApiError && (error.status === 401 || error.status === 403)) {
      redirect("/login");
    }
    if (error instanceof BackendApiError && error.status === 404) {
      accountNotReady = true;
    } else if (error instanceof Error) {
      portalUnavailableMessage = error.message;
    } else {
      portalUnavailableMessage = "Unable to load invoice details right now.";
    }
  }

  if (accountNotReady) {
    return (
      <main id="main-content" className="page-wrap">
        <div className="section-stack">
          <header className="creator-header reveal-item">
            <BrandWordmark size="sm" />
            <div className="invoice-detail-header__row">
              <h1>Your Invoice PDF</h1>
              <LogoutButton />
            </div>
            <p className="kicker">Your passkey is valid, but invoice data is not ready yet.</p>
          </header>

          <SurfaceCard as="section" className="creator-state-card reveal-item" data-delay="1">
            <h2>Portal setup in progress</h2>
            <p>
              We could not find dispatched invoices for this account yet. Please contact your agency to confirm your creator
              profile and invoice dispatch setup.
            </p>
            <div className="invoice-detail-actions">
              <Link className="button-link button-link--secondary" href="/portal">Back to invoices</Link>
            </div>
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
            <div className="invoice-detail-header__row">
              <h1>Your Invoice PDF</h1>
              <LogoutButton />
            </div>
            <p className="kicker">We hit a temporary issue while loading your invoice.</p>
          </header>

          <SurfaceCard as="section" className="creator-state-card reveal-item" data-delay="1">
            <h2>Unable to load invoice</h2>
            <p>Please refresh and try again. If this continues, contact your agency for support.</p>
            <p className="muted-small">Details: {portalUnavailableMessage}</p>
            <div className="invoice-detail-actions">
              <Link className="button-link button-link--secondary" href="/portal">Back to invoices</Link>
            </div>
          </SurfaceCard>
        </div>
      </main>
    );
  }

  const invoice = invoices.find((item) => item.invoice_id === invoiceId);
  if (!invoice) {
    notFound();
  }

  const pdfPath = `/api/portal/invoices/${encodeURIComponent(invoice.invoice_id)}/pdf`;
  const downloadPath = `${pdfPath}?download=1`;

  return (
    <main id="main-content" className="page-wrap">
      <div className="section-stack">
        <header className="creator-header reveal-item">
          <BrandWordmark size="sm" />
          <div className="invoice-detail-header__row">
            <h1>{creatorName}&apos;s Invoice PDF</h1>
            <LogoutButton />
          </div>
          <p className="kicker">Review invoice details and download a copy for your records.</p>
        </header>

        <SurfaceCard as="section" className="invoice-detail-card reveal-item" data-delay="1">
          <div className="invoice-detail-meta">
            <p><strong>Invoice:</strong> {invoice.invoice_id}</p>
            <p><strong>Issued:</strong> {formatDate(invoice.issued_at)}</p>
            <p><strong>Due:</strong> {formatDate(invoice.due_date)}</p>
            <p><strong>Balance Due:</strong> {formatCurrency(invoice.balance_due)}</p>
          </div>
          <div className="invoice-detail-actions">
            <Link className="button-link button-link--secondary" href="/portal">Back to invoices</Link>
            {invoice.has_pdf ? (
              <a className="button-link" href={downloadPath}>Download PDF</a>
            ) : null}
          </div>
        </SurfaceCard>

        {!invoice.has_pdf ? (
          <SurfaceCard as="section" className="creator-state-card reveal-item" data-delay="2">
            <h2>PDF not available yet</h2>
            <p>This invoice does not have a renderable PDF payload yet. Please contact your agency for help.</p>
          </SurfaceCard>
        ) : (
          <SurfaceCard as="section" className="invoice-pdf-card reveal-item" data-delay="2">
            <div className="invoice-pdf-card__head">
              <h2>Invoice PDF</h2>
              <p className="kicker">Embedded viewer</p>
            </div>
            <iframe
              className="invoice-pdf-frame"
              title={`Invoice PDF ${invoice.invoice_id}`}
              src={pdfPath}
            />
          </SurfaceCard>
        )}
      </div>
    </main>
  );
}
