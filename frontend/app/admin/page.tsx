import { revalidatePath } from "next/cache";
import Link from "next/link";
import { redirect } from "next/navigation";
import { BrandWordmark } from "../components/BrandWordmark";
import { DataTable, type DataColumn } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge, type StatusTone } from "../components/StatusBadge";
import { SurfaceCard } from "../components/SurfaceCard";
import {
  getReminderSummary,
  listReminderEscalations,
  listTasks,
  runReminderCycle,
  type ReminderEscalation,
  type ReminderSummary,
  type TaskSummary,
} from "../../lib/api";

const DATE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

const TIMESTAMP_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZone: "UTC",
});

const CURRENCY_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
});

const STATUS_TONE: Record<TaskSummary["status"], StatusTone> = {
  previewed: "warning",
  confirmed: "brand",
  completed: "success",
};

interface AdminPageSearchParams {
  reminderRun?: string;
  mode?: string;
}

async function runRemindersAction(formData: FormData) {
  "use server";

  const mode = formData.get("mode") === "live" ? "live" : "dry";
  try {
    await runReminderCycle({ dry_run: mode !== "live" });
    revalidatePath("/admin");
    redirect(`/admin?reminderRun=success&mode=${mode}`);
  } catch {
    revalidatePath("/admin");
    redirect(`/admin?reminderRun=error&mode=${mode}`);
  }
}

function formatDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? value : DATE_FORMATTER.format(parsed);
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : TIMESTAMP_FORMATTER.format(parsed);
}

function formatCurrency(amount: number): string {
  return CURRENCY_FORMATTER.format(amount);
}

function getLatestTimestamp(tasks: TaskSummary[]): string | null {
  if (tasks.length === 0) {
    return null;
  }

  return tasks.reduce((latest, task) => (task.updated_at > latest ? task.updated_at : latest), tasks[0].updated_at);
}

function runMessage(reminderRun: string | undefined, mode: string): string | null {
  if (reminderRun === "success") {
    return mode === "live" ? "Reminders sent successfully." : "Test run complete — no messages were sent.";
  }
  if (reminderRun === "error") {
    return mode === "live" ? "Failed to send reminders. Please try again." : "Test run failed. Please try again.";
  }
  return null;
}

export default async function AdminPage({
  searchParams,
}: {
  searchParams?: Promise<AdminPageSearchParams>;
}) {
  const resolvedSearchParams = (await searchParams) ?? {};
  const reminderRunState = resolvedSearchParams.reminderRun;
  const reminderRunMode = resolvedSearchParams.mode === "live" ? "live" : "dry";
  const reminderRunText = runMessage(reminderRunState, reminderRunMode);

  let tasks: TaskSummary[] = [];
  let loadError: string | null = null;
  let reminderSummary: ReminderSummary | null = null;
  let reminderEscalations: ReminderEscalation[] = [];
  let reminderError: string | null = null;

  try {
    tasks = await listTasks();
  } catch (error) {
    loadError = error instanceof Error ? error.message : "Unable to load tasks";
  }

  try {
    const [summary, escalations] = await Promise.all([getReminderSummary(), listReminderEscalations()]);
    reminderSummary = summary;
    reminderEscalations = escalations.items;
  } catch (error) {
    reminderError = error instanceof Error ? error.message : "Unable to load reminder data";
  }

  const latestTimestamp = getLatestTimestamp(tasks);
  const columns: DataColumn<TaskSummary>[] = [
    {
      id: "task",
      header: "Task",
      className: "cell-task",
      render: (task) => <span className="task-id">{task.task_id}</span>,
    },
    {
      id: "status",
      header: "Status",
      render: (task) => <StatusBadge tone={STATUS_TONE[task.status]}>{task.status}</StatusBadge>,
    },
    {
      id: "agent",
      header: "Agent",
      className: "cell-agent",
      render: (task) => <span>{task.agent_slug}</span>,
    },
    {
      id: "window",
      header: "Window",
      className: "cell-window",
      render: (task) => (
        <span className="window-range">
          <span>{formatDate(task.window_start)}</span>
          <span className="window-range__to">to</span>
          <span>{formatDate(task.window_end)}</span>
        </span>
      ),
    },
    {
      id: "sources",
      header: "Sources",
      align: "right",
      className: "cell-sources",
      render: (task) => <span className="numeric-cell">{task.source_count}</span>,
    },
    {
      id: "mode",
      header: "Mode",
      className: "cell-mode",
      render: (task) => <span>{task.mode.replace("_", " ")}</span>,
    },
    {
      id: "updated",
      header: "Updated",
      className: "cell-updated",
      render: (task) => <span className="muted-small">{formatTimestamp(task.updated_at)}</span>,
    },
  ];

  return (
    <main id="main-content" className="page-wrap">
      <div className="section-stack">
        {/* ── Header ── */}
        <header className="admin-header reveal-item">
          <div className="admin-header__copy">
            <BrandWordmark size="sm" />
            <h1>Admin Dashboard</h1>
            <p className="kicker">Manage creator invoices, track payments, and monitor reminder activity.</p>
          </div>
          <SurfaceCard className="invoicing-metric-card" aria-label="Queue snapshot">
            <span className="eyebrow">Queue Snapshot</span>
            <p className="invoicing-metric-card__value">{loadError ? "--" : tasks.length}</p>
            <p className="invoicing-metric-card__label">
              {loadError ? "unable to load" : `${tasks.length} task${tasks.length === 1 ? "" : "s"} in queue`}
            </p>
          </SurfaceCard>
        </header>

        {/* ── Payment Reminders ── */}
        <SurfaceCard as="section" className="reminder-ops-card reveal-item" data-delay="1">
          <div className="reminder-ops-card__head">
            <h2>Payment Reminders</h2>
            <p className="kicker">Track unpaid creator balances and send payment reminders via email and SMS.</p>
          </div>

          <div className="reminder-ops-card__actions">
            <form action={runRemindersAction}>
              <input type="hidden" name="mode" value="dry" />
              <button type="submit" className="button-link">
                Test Run (No Messages Sent)
              </button>
            </form>
            <form action={runRemindersAction}>
              <input type="hidden" name="mode" value="live" />
              <button type="submit" className="button-link button-link--secondary">
                Send Reminders
              </button>
            </form>
          </div>

          {reminderRunText ? (
            <p className={`reminder-run-banner ${reminderRunState === "success" ? "reminder-run-banner--ok" : "reminder-run-banner--error"}`}>
              {reminderRunText}
            </p>
          ) : null}

          {reminderError ? (
            <p className="muted-small">Reminder data unavailable: {reminderError}</p>
          ) : reminderSummary ? (
            <div className="reminder-metric-grid" aria-label="Reminder metrics">
              <div className="reminder-metric-card">
                <span>Unpaid</span>
                <strong>{reminderSummary.unpaid_count}</strong>
              </div>
              <div className="reminder-metric-card">
                <span>Overdue</span>
                <strong>{reminderSummary.overdue_count}</strong>
              </div>
              <div className="reminder-metric-card">
                <span>Eligible Now</span>
                <strong>{reminderSummary.eligible_now_count}</strong>
              </div>
              <div className="reminder-metric-card">
                <span>Escalated</span>
                <strong>{reminderSummary.escalated_count}</strong>
              </div>
            </div>
          ) : null}

          {reminderSummary?.last_run_at ? (
            <p className="muted-small">
              Last run {formatTimestamp(reminderSummary.last_run_at)} ({reminderSummary.last_run_dry_run ? "test run" : "live"})
            </p>
          ) : null}

          {reminderEscalations.length > 0 ? (
            <div className="escalation-list" aria-label="Escalation queue">
              <h3>Escalation Queue</h3>
              <ul>
                {reminderEscalations.slice(0, 5).map((item) => (
                  <li key={item.invoice_id}>
                    <span>{item.invoice_id}</span>
                    <span>{item.creator_name}</span>
                    <span>{formatCurrency(item.balance_due)}</span>
                    <span>{item.reminder_count} reminders</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="muted-small">No invoices currently need manual follow-up.</p>
          )}
        </SurfaceCard>

        {/* ── Current Tasks ── */}
        {loadError ? (
          <SurfaceCard as="section" className="alert-panel reveal-item" data-delay="2" role="alert" aria-live="assertive">
            <h2>Unable to Load Dashboard</h2>
            <p>
              Something went wrong while loading the dashboard. Please check that the backend is running and try again.
              <br />
              <span className="muted-small">Details: {loadError}</span>
            </p>
            <Link className="button-link" href="/admin">
              Try Again
            </Link>
          </SurfaceCard>
        ) : (
          <SurfaceCard as="section" className="invoicing-table-card reveal-item" data-delay="2">
            <div className="invoicing-table-card__head">
              <h2>Current Tasks</h2>
              <p className="kicker">{latestTimestamp ? `Latest update ${formatTimestamp(latestTimestamp)}` : "No updates yet"}</p>
            </div>

            {tasks.length === 0 ? (
              <EmptyState
                title="No tasks in queue"
                description="No invoicing tasks are currently active. Create a new invoice batch or confirm a pending preview to get started."
              />
            ) : (
              <DataTable caption="Invoicing tasks" columns={columns} rows={tasks} rowKey={(task) => task.task_id} />
            )}
          </SurfaceCard>
        )}

        {/* ── Reference Documentation (collapsible) ── */}
        <details className="admin-docs-disclosure reveal-item">
          <summary><h2>Reference Documentation</h2></summary>
          <div className="admin-docs-disclosure__body">

            {/* ── Overview ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="1">
              <h2>Overview</h2>
              <p>
                When a creator has an unpaid invoice past its due date, OpenClaw automatically sends payment reminders via
                email and SMS. Reminders continue on a schedule until the creator pays or the invoice is escalated for
                manual follow-up.
              </p>
              <div className="admin-doc-highlight">
                <strong>Key numbers:</strong> Up to <strong>6 reminders</strong> per invoice, with a{" "}
                <strong>48-hour cooldown</strong> between each. After 6 attempts with no payment, the invoice is escalated.
              </div>
            </SurfaceCard>

            {/* ── Reminder Cycle ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="2">
              <h2>Reminder Cycle</h2>
              <p>
                Reminders are triggered manually from the Invoicing Dashboard. Each run evaluates all dispatched invoices
                and sends reminders to eligible ones.
              </p>

              <h3>Two modes</h3>
              <div className="admin-doc-grid">
                <div className="admin-doc-mode-card">
                  <h4>Test Run</h4>
                  <p>
                    Simulates the full cycle without sending any messages. Use this to preview which creators would be
                    contacted and verify everything looks correct before sending.
                  </p>
                  <ul>
                    <li>No emails or SMS sent</li>
                    <li>Reminder counts are not incremented</li>
                    <li>Results logged for review</li>
                  </ul>
                </div>
                <div className="admin-doc-mode-card">
                  <h4>Live Run</h4>
                  <p>
                    Sends actual reminder messages to creators. Each creator receives notifications on all configured
                    channels (email and/or SMS).
                  </p>
                  <ul>
                    <li>Messages delivered to creators</li>
                    <li>Reminder counts incremented on success</li>
                    <li>Failed deliveries tracked separately</li>
                  </ul>
                </div>
              </div>
            </SurfaceCard>

            {/* ── Eligibility ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="3">
              <h2>Who Gets Reminded</h2>
              <p>An invoice is eligible for a reminder when <strong>all</strong> of the following are true:</p>
              <ol className="admin-doc-list">
                <li>The invoice has been dispatched to the creator</li>
                <li>The creator has not opted out of reminders</li>
                <li>The outstanding balance is greater than $0</li>
                <li>Fewer than 6 reminders have been sent</li>
                <li>The invoice due date has passed (in the creator&apos;s timezone)</li>
                <li>At least 48 hours have passed since the last reminder</li>
              </ol>
              <p>
                If any condition is not met, the invoice is skipped for that cycle. You can see the skip reason in test run
                results.
              </p>
            </SurfaceCard>

            {/* ── Channels ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Email &amp; SMS Channels</h2>
              <p>
                Each invoice dispatch specifies which channels to use &mdash; email, SMS, or both. When both are
                configured:
              </p>
              <ul className="admin-doc-list">
                <li>
                  <strong>Both channels are attempted</strong> for every reminder
                </li>
                <li>
                  The reminder only counts as successful if <strong>all channels deliver</strong>
                </li>
                <li>If either channel fails, the entire reminder is marked as failed and the count is not incremented</li>
              </ul>
              <p>
                Contact information (email addresses and phone numbers) is stored securely and masked in all dashboard
                views and API responses.
              </p>
            </SurfaceCard>

            {/* ── Escalation ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Escalation</h2>
              <p>
                After <strong>6 reminder attempts</strong> without payment, an invoice is automatically escalated. Escalated
                invoices:
              </p>
              <ul className="admin-doc-list">
                <li>Stop receiving automated reminders</li>
                <li>Appear in the Escalation Queue on the Invoicing Dashboard</li>
                <li>Require manual follow-up by an admin</li>
              </ul>
              <p>
                The Escalation Queue shows the creator name, invoice ID, outstanding balance, and how many reminders were
                sent. Use this to decide next steps &mdash; direct outreach, payment plan, or other resolution.
              </p>
            </SurfaceCard>

            {/* ── Invoice Status Lifecycle ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Invoice Status Lifecycle</h2>
              <p>Invoice statuses update automatically based on payment activity and reminder history:</p>
              <div className="admin-doc-table-wrap">
                <table className="admin-doc-table">
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Meaning</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><strong>Open</strong></td>
                      <td>Invoice created, not yet due or no payments received</td>
                    </tr>
                    <tr>
                      <td><strong>Partial</strong></td>
                      <td>Some payment received but balance remains</td>
                    </tr>
                    <tr>
                      <td><strong>Overdue</strong></td>
                      <td>Due date has passed with outstanding balance</td>
                    </tr>
                    <tr>
                      <td><strong>Escalated</strong></td>
                      <td>6 reminders sent, no full payment &mdash; needs manual follow-up</td>
                    </tr>
                    <tr>
                      <td><strong>Paid</strong></td>
                      <td>Balance is $0 &mdash; fully settled</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </SurfaceCard>

            {/* ── Creator Portal & Tokens ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Creator Portal Access</h2>
              <p>
                Creators access their invoices through a secure link (magic link) included in reminder emails and SMS
                messages. Here&apos;s how it works:
              </p>
              <ol className="admin-doc-list">
                <li>When an invoice is dispatched, a unique signed token is generated for the creator</li>
                <li>The token is embedded in a URL that links directly to the creator&apos;s invoice portal</li>
                <li>Tokens expire after a configurable time (default: 60 minutes, max: 7 days)</li>
                <li>The portal shows only that creator&apos;s invoices &mdash; they cannot see other creators or admin pages</li>
              </ol>
              <div className="admin-doc-highlight">
                <strong>Security:</strong> Tokens use HMAC-SHA256 signatures to prevent tampering. Expired or invalid tokens
                are rejected with a 401 error. Creators see a friendly error message and can request a new link.
              </div>
            </SurfaceCard>

            {/* ── Configuration ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Configuration</h2>
              <p>
                The reminder system is controlled by environment variables. These are set in the backend deployment and do
                not require code changes.
              </p>
              <div className="admin-doc-table-wrap">
                <table className="admin-doc-table">
                  <thead>
                    <tr>
                      <th>Setting</th>
                      <th>Default</th>
                      <th>Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><code>OPENCLAW_ENABLED</code></td>
                      <td>Off</td>
                      <td>Master switch for live reminder sending. When off, live runs behave like test runs.</td>
                    </tr>
                    <tr>
                      <td><code>OPENCLAW_DRY_RUN_DEFAULT</code></td>
                      <td>On</td>
                      <td>Default mode when triggering a reminder cycle via the API without specifying a mode.</td>
                    </tr>
                    <tr>
                      <td><code>OPENCLAW_CHANNEL</code></td>
                      <td>email,sms</td>
                      <td>Which channels the system supports. Options: &ldquo;email&rdquo;, &ldquo;sms&rdquo;, or &ldquo;email,sms&rdquo;.</td>
                    </tr>
                    <tr>
                      <td><code>CREATOR_MAGIC_LINK_SECRET</code></td>
                      <td>dev-creator-secret</td>
                      <td>Secret key for signing creator portal tokens. Must be changed for production.</td>
                    </tr>
                    <tr>
                      <td><code>CREATOR_PORTAL_BASE_URL</code></td>
                      <td>http://localhost:3000/creator</td>
                      <td>Base URL used when generating creator portal links in reminder messages.</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </SurfaceCard>

            {/* ── Timing Reference ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Timing Reference</h2>
              <div className="admin-doc-table-wrap">
                <table className="admin-doc-table">
                  <thead>
                    <tr>
                      <th>Parameter</th>
                      <th>Value</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Max reminders per invoice</td>
                      <td><strong>6</strong></td>
                      <td>After 6, invoice is escalated</td>
                    </tr>
                    <tr>
                      <td>Cooldown between reminders</td>
                      <td><strong>48 hours</strong></td>
                      <td>Minimum time between reminder attempts for the same invoice</td>
                    </tr>
                    <tr>
                      <td>Due date timezone</td>
                      <td>Creator&apos;s timezone</td>
                      <td>Falls back to UTC if no timezone is set for the creator</td>
                    </tr>
                    <tr>
                      <td>Magic link default TTL</td>
                      <td><strong>60 minutes</strong></td>
                      <td>Configurable per token, max 7 days (10,080 minutes)</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </SurfaceCard>

          </div>
        </details>

        {/* ── Footer ── */}
        <footer className="admin-footer reveal-item">
          <p className="muted-small">
            This page is for agency administrators only. Creators access their invoices through secure portal links and
            cannot see this page.
          </p>
        </footer>
      </div>
    </main>
  );
}
