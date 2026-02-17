import Link from "next/link";
import { BrandWordmark } from "../components/BrandWordmark";
import { DataTable, type DataColumn } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge, type StatusTone } from "../components/StatusBadge";
import { SurfaceCard } from "../components/SurfaceCard";
import { listTasks, type TaskSummary } from "../../lib/api";

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

const STATUS_TONE: Record<TaskSummary["status"], StatusTone> = {
  previewed: "warning",
  confirmed: "brand",
  completed: "success",
};

function formatDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? value : DATE_FORMATTER.format(parsed);
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : TIMESTAMP_FORMATTER.format(parsed);
}

function getLatestTimestamp(tasks: TaskSummary[]): string | null {
  if (tasks.length === 0) {
    return null;
  }

  return tasks.reduce((latest, task) => (task.updated_at > latest ? task.updated_at : latest), tasks[0].updated_at);
}

export default async function InvoicingPage() {
  let tasks: TaskSummary[] = [];
  let loadError: string | null = null;

  try {
    tasks = await listTasks();
  } catch (error) {
    loadError = error instanceof Error ? error.message : "Unable to load tasks";
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

        {loadError ? (
          <SurfaceCard as="section" className="alert-panel reveal-item" data-delay="1" role="alert" aria-live="assertive">
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
          <SurfaceCard as="section" className="invoicing-table-card reveal-item" data-delay="1">
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
