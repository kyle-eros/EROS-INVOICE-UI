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

interface InvoicingPageSearchParams {
  reminderRun?: string;
  mode?: string;
}

async function runRemindersAction(formData: FormData) {
  "use server";

  const mode = formData.get("mode") === "live" ? "live" : "dry";
  try {
    await runReminderCycle({ dry_run: mode !== "live" });
    revalidatePath("/invoicing");
    redirect(`/invoicing?reminderRun=success&mode=${mode}`);
  } catch {
    revalidatePath("/invoicing");
    redirect(`/invoicing?reminderRun=error&mode=${mode}`);
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
    return mode === "live" ? "Live reminder cycle completed." : "Dry-run reminder cycle completed.";
  }
  if (reminderRun === "error") {
    return mode === "live" ? "Live reminder cycle failed." : "Dry-run reminder cycle failed.";
  }
  return null;
}

export default async function InvoicingPage({
  searchParams,
}: {
  searchParams?: Promise<InvoicingPageSearchParams>;
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
    reminderError = error instanceof Error ? error.message : "Unable to load reminder telemetry";
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
        <header className="invoicing-header reveal-item">
          <div className="invoicing-header__copy">
            <BrandWordmark size="sm" />
            <h1>Invoicing Task Command</h1>
            <p className="kicker">Read-only queue backed by the invoicing preview lifecycle API.</p>
          </div>
          <SurfaceCard className="invoicing-metric-card" aria-label="Queue snapshot">
            <span className="eyebrow">Queue Snapshot</span>
            <p className="invoicing-metric-card__value">{loadError ? "--" : tasks.length}</p>
            <p className="invoicing-metric-card__label">
              {loadError ? "fetch interrupted" : `${tasks.length} task${tasks.length === 1 ? "" : "s"} in queue`}
            </p>
          </SurfaceCard>
        </header>

        <SurfaceCard as="section" className="reminder-ops-card reveal-item" data-delay="1">
          <div className="reminder-ops-card__head">
            <h2>OpenClaw Reminder Ops</h2>
            <p className="kicker">Monitor unpaid creator balances and run reminder cycles on demand.</p>
          </div>

          <div className="reminder-ops-card__actions">
            <form action={runRemindersAction}>
              <input type="hidden" name="mode" value="dry" />
              <button type="submit" className="button-link">
                Run Dry-Run Cycle
              </button>
            </form>
            <form action={runRemindersAction}>
              <input type="hidden" name="mode" value="live" />
              <button type="submit" className="button-link button-link--secondary">
                Run Live Cycle
              </button>
            </form>
          </div>

          {reminderRunText ? (
            <p className={`reminder-run-banner ${reminderRunState === "success" ? "reminder-run-banner--ok" : "reminder-run-banner--error"}`}>
              {reminderRunText}
            </p>
          ) : null}

          {reminderError ? (
            <p className="muted-small">Reminder telemetry unavailable: {reminderError}</p>
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
              Last run {formatTimestamp(reminderSummary.last_run_at)} ({reminderSummary.last_run_dry_run ? "dry-run" : "live"})
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
            <p className="muted-small">No invoices currently require escalation.</p>
          )}
        </SurfaceCard>

        {loadError ? (
          <SurfaceCard as="section" className="alert-panel reveal-item" data-delay="2" role="alert" aria-live="assertive">
            <h2>Unable to load task queue</h2>
            <p>
              The API returned an error while loading tasks. Try again after confirming backend availability.
              <br />
              <span className="muted-small">Details: {loadError}</span>
            </p>
            <Link className="button-link" href="/invoicing">
              Retry Queue Request
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
                description="No invoicing tasks are currently available. Preview or confirm a run to populate the command surface."
                action={
                  <Link className="button-link" href="/">
                    Return to Overview
                  </Link>
                }
              />
            ) : (
              <DataTable caption="Invoicing task queue" columns={columns} rows={tasks} rowKey={(task) => task.task_id} />
            )}
          </SurfaceCard>
        )}
      </div>
    </main>
  );
}
