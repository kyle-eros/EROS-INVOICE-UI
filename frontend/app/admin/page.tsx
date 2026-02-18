import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AdminLogoutButton } from "./AdminLogoutButton";
import { AdminPasskeyFlash } from "./AdminPasskeyFlash";
import { BrandWordmark } from "../components/BrandWordmark";
import { DataTable, type DataColumn } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge, type StatusTone } from "../components/StatusBadge";
import { SurfaceCard } from "../components/SurfaceCard";
import {
  ADMIN_PASSKEY_FLASH_COOKIE,
  adminPasskeyFlashCookieOptions,
  encodeAdminPasskeyFlash,
} from "../../lib/passkey-flash";
import {
  evaluateReminderCycle,
  listAdminCreators,
  listAdminConversations,
  generatePasskey,
  getReminderSummary,
  listPasskeys,
  listReminderEscalations,
  listTasks,
  revokePasskey,
  runReminderCycle,
  sendReminderRun,
  type AdminCreatorDirectoryItem,
  type ConversationThreadItem,
  type PasskeyListItem,
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

function formatConversationChannel(channel: ConversationThreadItem["channel"]): string {
  if (channel === "imessage") {
    return "iMessage";
  }
  return channel.toUpperCase();
}

interface AdminPageSearchParams {
  reminderRun?: string;
  reminderEval?: string;
  reminderSend?: string;
  pendingRunId?: string;
  pendingEligible?: string;
  pendingEvaluated?: string;
  mode?: string;
  passkeyGen?: string;
  passkeyGenReason?: string;
  passkeyRevoke?: string;
}

async function runRemindersAction(formData: FormData) {
  "use server";

  const mode = formData.get("mode") === "live" ? "live" : "dry";
  const cookieStore = await cookies();
  const adminToken = cookieStore.get("admin_session")?.value;
  if (!adminToken) {
    redirect("/admin/gate");
  }
  try {
    if (mode === "dry") {
      await runReminderCycle(
        {
          dry_run: true,
        },
        adminToken,
      );
      revalidatePath("/admin");
      redirect("/admin?reminderRun=success&mode=dry");
    }

    const evaluation = await evaluateReminderCycle(
      {
        idempotency_key: `admin-eval-${Date.now()}`,
      },
      adminToken,
    );
    if (!evaluation.run_id) {
      throw new Error("Reminder evaluation did not return a run_id");
    }
    revalidatePath("/admin");
    redirect(
      `/admin?reminderEval=success&pendingRunId=${encodeURIComponent(evaluation.run_id)}&pendingEligible=${evaluation.eligible_count}&pendingEvaluated=${evaluation.evaluated_count}`,
    );
  } catch {
    revalidatePath("/admin");
    if (mode === "dry") {
      redirect("/admin?reminderRun=error&mode=dry");
    }
    redirect("/admin?reminderEval=error");
  }
}

async function sendEvaluatedRemindersAction(formData: FormData) {
  "use server";

  const runId = (formData.get("run_id") as string | null)?.trim();
  if (!runId) {
    redirect("/admin?reminderSend=error");
  }

  const cookieStore = await cookies();
  const adminToken = cookieStore.get("admin_session")?.value;
  if (!adminToken) {
    redirect("/admin/gate");
  }

  try {
    await sendReminderRun(runId, adminToken);
    revalidatePath("/admin");
    redirect("/admin?reminderSend=success&mode=live");
  } catch {
    revalidatePath("/admin");
    redirect(`/admin?reminderSend=error&pendingRunId=${encodeURIComponent(runId)}`);
  }
}

async function generatePasskeyAction(formData: FormData) {
  "use server";
  const creatorId = (formData.get("creator_id") as string)?.trim();
  const creatorName = (formData.get("creator_name") as string)?.trim();
  const forceIssueUnready = formData.get("force_issue_unready") === "on";
  if (!creatorId || !creatorName) {
    redirect("/admin?passkeyGen=error&passkeyGenReason=missing_fields");
  }
  const cookieStore = await cookies();
  const adminToken = cookieStore.get("admin_session")?.value;
  if (!adminToken) {
    redirect("/admin/gate");
  }

  let targetCreatorId = creatorId;
  let targetCreatorName = creatorName;
  try {
    const creators = await listAdminCreators(adminToken);
    const matched = creators.creators.find((item) => item.creator_id === creatorId);
    if (!matched && !forceIssueUnready) {
      revalidatePath("/admin");
      redirect("/admin?passkeyGen=error&passkeyGenReason=unknown_creator");
    }
    if (matched && !matched.ready_for_portal && !forceIssueUnready) {
      revalidatePath("/admin");
      redirect("/admin?passkeyGen=error&passkeyGenReason=no_dispatched_invoices");
    }
    if (matched) {
      targetCreatorId = matched.creator_id;
      targetCreatorName = matched.creator_name;
    }
  } catch {
    if (!forceIssueUnready) {
      revalidatePath("/admin");
      redirect("/admin?passkeyGen=error&passkeyGenReason=directory_unavailable");
    }
  }

  try {
    const result = await generatePasskey(targetCreatorId, targetCreatorName, adminToken);
    cookieStore.set(
      ADMIN_PASSKEY_FLASH_COOKIE,
      encodeAdminPasskeyFlash({
        creator_name: targetCreatorName,
        passkey: result.passkey,
      }),
      adminPasskeyFlashCookieOptions(120),
    );
    revalidatePath("/admin");
    redirect("/admin?passkeyGen=success");
  } catch {
    revalidatePath("/admin");
    redirect("/admin?passkeyGen=error&passkeyGenReason=generate_failed");
  }
}

async function revokePasskeyAction(formData: FormData) {
  "use server";
  const creatorId = (formData.get("creator_id") as string)?.trim();
  if (!creatorId) {
    redirect("/admin?passkeyRevoke=error");
  }
  const cookieStore = await cookies();
  const adminToken = cookieStore.get("admin_session")?.value;
  if (!adminToken) {
    redirect("/admin/gate");
  }
  try {
    await revokePasskey(creatorId, adminToken);
    revalidatePath("/admin");
    redirect("/admin?passkeyRevoke=success");
  } catch {
    revalidatePath("/admin");
    redirect("/admin?passkeyRevoke=error");
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

function evalMessage(reminderEval: string | undefined): string | null {
  if (reminderEval === "success") {
    return "Live run evaluated successfully. Review the pending run details before sending.";
  }
  if (reminderEval === "error") {
    return "Failed to evaluate live reminder run. Please try again.";
  }
  return null;
}

function sendMessage(reminderSend: string | undefined): string | null {
  if (reminderSend === "success") {
    return "Evaluated reminder run sent successfully.";
  }
  if (reminderSend === "error") {
    return "Failed to send the evaluated reminder run. Please try again.";
  }
  return null;
}

function passkeyGenMessage(reason: string | undefined): string {
  if (reason === "missing_fields") {
    return "Creator ID and Creator Name are required.";
  }
  if (reason === "unknown_creator") {
    return "Creator ID not found in invoice records. Use a known creator or enable manual override.";
  }
  if (reason === "no_dispatched_invoices") {
    return "This creator has no dispatched invoices yet. Dispatch at least one invoice first, or use manual override.";
  }
  if (reason === "directory_unavailable") {
    return "Creator validation is currently unavailable. Retry, or use manual override if urgent.";
  }
  if (reason === "generate_failed") {
    return "Failed to generate passkey. Please try again.";
  }
  return "Failed to generate passkey. Please try again.";
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
  const reminderEvalText = evalMessage(resolvedSearchParams.reminderEval);
  const reminderSendText = sendMessage(resolvedSearchParams.reminderSend);
  const pendingRunId = resolvedSearchParams.pendingRunId ?? null;
  const pendingEligible = Number.parseInt(resolvedSearchParams.pendingEligible ?? "", 10);
  const pendingEvaluated = Number.parseInt(resolvedSearchParams.pendingEvaluated ?? "", 10);

  let tasks: TaskSummary[] = [];
  let loadError: string | null = null;
  let reminderSummary: ReminderSummary | null = null;
  let reminderEscalations: ReminderEscalation[] = [];
  let reminderError: string | null = null;
  const cookieStore = await cookies();
  const adminToken = cookieStore.get("admin_session")?.value ?? "";

  try {
    tasks = await listTasks();
  } catch (error) {
    loadError = error instanceof Error ? error.message : "Unable to load tasks";
  }

  try {
    if (!adminToken) {
      redirect("/admin/gate");
    }
    const [summary, escalations] = await Promise.all([
      getReminderSummary(adminToken),
      listReminderEscalations(adminToken),
    ]);
    reminderSummary = summary;
    reminderEscalations = escalations.items;
  } catch (error) {
    reminderError = error instanceof Error ? error.message : "Unable to load reminder data";
  }

  let passkeys: PasskeyListItem[] = [];
  let passkeyError: string | null = null;
  let creatorDirectory: AdminCreatorDirectoryItem[] = [];
  let creatorDirectoryError: string | null = null;
  let conversationThreads: ConversationThreadItem[] = [];
  let conversationError: string | null = null;

  try {
    if (adminToken) {
      const result = await listPasskeys(adminToken);
      passkeys = result.creators;
    }
  } catch (error) {
    passkeyError = error instanceof Error ? error.message : "Unable to load passkeys";
  }

  try {
    if (adminToken) {
      const result = await listAdminCreators(adminToken);
      creatorDirectory = result.creators;
    }
  } catch (error) {
    creatorDirectoryError = error instanceof Error ? error.message : "Unable to load creator directory";
  }

  try {
    if (adminToken) {
      const result = await listAdminConversations(adminToken);
      conversationThreads = result.items;
    }
  } catch (error) {
    conversationError = error instanceof Error ? error.message : "Unable to load conversation inbox";
  }

  const passkeyGenState = resolvedSearchParams.passkeyGen;
  const passkeyGenReason = resolvedSearchParams.passkeyGenReason;
  const passkeyRevokeState = resolvedSearchParams.passkeyRevoke;
  const passkeyGenError = passkeyGenState === "error" ? passkeyGenMessage(passkeyGenReason) : null;
  const readyCreators = creatorDirectory.filter((creator) => creator.ready_for_portal);

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
            <AdminLogoutButton />
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
            <p className="muted-small">
              Demo data note: reminder counts and overdue totals may include imported 90-day history. Use test runs first
              before any live send.
            </p>
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
                Evaluate Live Run
              </button>
            </form>
            {pendingRunId ? (
              <form action={sendEvaluatedRemindersAction}>
                <input type="hidden" name="run_id" value={pendingRunId} />
                <button type="submit" className="button-link button-link--secondary">
                  Send Evaluated Run
                </button>
              </form>
            ) : null}
          </div>

          {reminderRunText ? (
            <p className={`reminder-run-banner ${reminderRunState === "success" ? "reminder-run-banner--ok" : "reminder-run-banner--error"}`}>
              {reminderRunText}
            </p>
          ) : null}
          {reminderEvalText ? (
            <p className={`reminder-run-banner ${resolvedSearchParams.reminderEval === "success" ? "reminder-run-banner--ok" : "reminder-run-banner--error"}`}>
              {reminderEvalText}
            </p>
          ) : null}
          {reminderSendText ? (
            <p className={`reminder-run-banner ${resolvedSearchParams.reminderSend === "success" ? "reminder-run-banner--ok" : "reminder-run-banner--error"}`}>
              {reminderSendText}
            </p>
          ) : null}
          {pendingRunId ? (
            <p className="muted-small">
              Pending run <code>{pendingRunId}</code>
              {Number.isFinite(pendingEligible) && Number.isFinite(pendingEvaluated)
                ? `: ${pendingEligible} eligible out of ${pendingEvaluated} evaluated invoices.`
                : "."}
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

        {/* ── Conversation Inbox ── */}
        <SurfaceCard as="section" className="invoicing-table-card reveal-item" data-delay="1">
          <div className="invoicing-table-card__head">
            <h2>Conversation Inbox</h2>
            <p className="kicker">Monitor creator replies and handoff candidates from the two-way reminder channel.</p>
          </div>
          {conversationError ? (
            <p className="muted-small">Conversation data unavailable: {conversationError}</p>
          ) : conversationThreads.length === 0 ? (
            <p className="muted-small">No active conversation threads yet.</p>
          ) : (
            <div className="escalation-list" aria-label="Conversation queue">
              <ul>
                {conversationThreads.slice(0, 8).map((thread) => (
                  <li key={thread.thread_id}>
                    <span>{thread.creator_name || thread.external_contact_masked}</span>
                    <span>{formatConversationChannel(thread.channel)}</span>
                    <span>{thread.status.replace("_", " ")}</span>
                    <span>{thread.last_message_preview || "No messages yet"}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </SurfaceCard>

        {/* ── Creator Access ── */}
        <SurfaceCard as="section" className="invoicing-table-card reveal-item" data-delay="1">
          <div className="invoicing-table-card__head">
            <h2>Creator Access</h2>
            <p className="kicker">Generate and manage passkeys for creator portal access.</p>
          </div>

          <div className="passkey-mgmt">
            <form action={generatePasskeyAction} className="passkey-mgmt__form">
              <div className="passkey-mgmt__field">
                <label htmlFor="creator_id">Creator ID</label>
                <input
                  className="login-input"
                  id="creator_id"
                  name="creator_id"
                  list="creator-id-options"
                  required
                  placeholder="e.g. creator-001"
                />
              </div>
              <div className="passkey-mgmt__field">
                <label htmlFor="creator_name">Creator Name</label>
                <input
                  className="login-input"
                  id="creator_name"
                  name="creator_name"
                  list="creator-name-options"
                  required
                  placeholder="e.g. Jane Doe"
                />
              </div>
              <label className="muted-small" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                <input type="checkbox" name="force_issue_unready" />
                Allow manual override (issue passkey even if creator is not portal-ready)
              </label>
              <button type="submit" className="button-link">Generate Passkey</button>
            </form>

            <datalist id="creator-id-options">
              {readyCreators.map((creator) => (
                <option key={creator.creator_id} value={creator.creator_id}>
                  {creator.creator_name}
                </option>
              ))}
            </datalist>
            <datalist id="creator-name-options">
              {readyCreators.map((creator) => (
                <option key={creator.creator_id} value={creator.creator_name}>
                  {creator.creator_id}
                </option>
              ))}
            </datalist>
            <p className="muted-small">
              Recommended creators come from invoice records with at least one dispatched invoice.
            </p>
            {creatorDirectoryError ? (
              <p className="muted-small">Creator validation unavailable: {creatorDirectoryError}</p>
            ) : null}

            {passkeyGenState === "success" ? (
              <p className="reminder-run-banner reminder-run-banner--ok">Passkey generated successfully.</p>
            ) : passkeyGenError ? (
              <p className="login-error">{passkeyGenError}</p>
            ) : null}
            <AdminPasskeyFlash />

            {passkeyRevokeState === "success" ? (
              <p className="reminder-run-banner reminder-run-banner--ok">Passkey revoked successfully.</p>
            ) : passkeyRevokeState === "error" ? (
              <p className="login-error">Failed to revoke passkey.</p>
            ) : null}

            {passkeyError ? (
              <p className="muted-small">Passkey data unavailable: {passkeyError}</p>
            ) : passkeys.length > 0 ? (
              <div>
                <h3 style={{ fontSize: "1.04rem", color: "var(--text-strong)", marginBottom: "var(--space-3)" }}>Active Creators</h3>
                <div className="data-table-shell">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Creator ID</th>
                        <th>Name</th>
                        <th>Key Prefix</th>
                        <th>Created</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {passkeys.map((pk) => (
                        <tr key={pk.creator_id}>
                          <td><span className="task-id">{pk.creator_id}</span></td>
                          <td>{pk.creator_name}</td>
                          <td><code style={{ fontSize: "0.85rem", padding: "2px 6px", borderRadius: "4px", background: "rgba(123, 184, 244, 0.12)", color: "var(--brand-primary-soft)" }}>{pk.display_prefix}...</code></td>
                          <td><span className="muted-small">{formatTimestamp(pk.created_at)}</span></td>
                          <td>
                            <form action={revokePasskeyAction} style={{ display: "inline" }}>
                              <input type="hidden" name="creator_id" value={pk.creator_id} />
                              <button type="submit" className="button-link button-link--secondary" style={{ padding: "4px 12px", fontSize: "0.8rem" }}>Revoke</button>
                            </form>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <p className="muted-small">No active passkeys. Generate one above to give a creator access.</p>
            )}
          </div>
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

            {/* ── OpenClaw Agent Operations ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="1">
              <h2>OpenClaw Agent Operations</h2>
              <p>
                OpenClaw runs as the orchestration layer on the agency Mac mini and calls broker-token scoped{" "}
                <code>/agent/*</code> routes on this backend. The backend remains the source of truth for invoice state,
                reminder eligibility, conversation policy, and webhook security enforcement.
              </p>

              <h3>Mac mini Runtime Model</h3>
              <ol className="admin-doc-list">
                <li>
                  OpenClaw gateway runs from <code>openclaw/docker/docker-compose.yml</code> and is published to{" "}
                  <code>127.0.0.1:8080</code> (loopback-only).
                </li>
                <li>
                  Backend API runs on <code>127.0.0.1:8000</code>; agent traffic is allowlisted through{" "}
                  <code>host.docker.internal:8000</code>.
                </li>
                <li>
                  Admin creates/revokes broker tokens with <code>POST /agent/tokens</code> and{" "}
                  <code>POST /agent/tokens/revoke</code>; each agent receives least-privilege scopes and TTL limits.
                </li>
                <li>
                  On every agent request, backend validates token signature, scope, expiry, and revocation before any
                  read/write action executes.
                </li>
                <li>
                  Startup and secret posture should be checked with <code>GET /admin/runtime/security</code> and{" "}
                  <code>openclaw/scripts/verify-setup.sh</code> before live usage.
                </li>
              </ol>

              <h3>Agent Roles And API Surface</h3>
              <ul className="admin-doc-list">
                <li>
                  <strong>invoice-monitor</strong>: <code>GET /agent/invoices</code>,{" "}
                  <code>GET /agent/reminders/summary</code>, <code>GET /agent/reminders/escalations</code> for
                  read-only visibility.
                </li>
                <li>
                  <strong>notification-sender</strong>: <code>POST /agent/reminders/run/once</code> plus{" "}
                  <code>GET /agent/reminders/escalations</code> for reminder execution and follow-up visibility.
                </li>
                <li>
                  <strong>creator-conversation</strong>: <code>GET /agent/conversations/{"{thread_id}"}/context</code>,{" "}
                  <code>POST /agent/conversations/{"{thread_id}"}/suggest-reply</code>, and{" "}
                  <code>POST /agent/conversations/{"{thread_id}"}/execute-action</code> for guarded reply operations.
                </li>
              </ul>

              <h3>Policy, Safety, And Handoff</h3>
              <p>
                OpenClaw never bypasses backend policy gates. Conversation suggestions are scored against confidence/risk
                thresholds, auto-reply caps, and provider/channel rules. If thresholds are not met, the thread is forced
                to <strong>human handoff</strong> even when agent automation is enabled.
              </p>
              <div className="admin-doc-highlight">
                <strong>Pipeline summary:</strong> 90-day earnings import → invoice state + dispatch readiness → reminder
                evaluation/send runs → inbound provider replies → backend policy gate → agent suggest/execute → human
                handoff when needed.
              </div>
            </SurfaceCard>

            {/* ── Overview ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="2">
              <h2>Overview</h2>
              <p>
                EROS Invoicing Web combines earnings ingestion, invoice dispatch, creator portal access, payment
                tracking, reconciliation, reminder workflows, and guarded two-way creator conversations.
              </p>
              <ol className="admin-doc-list">
                <li>Import earnings data (CSV/API) into creator invoices</li>
                <li>Dispatch invoices to mark creators as portal-ready</li>
                <li>Generate creator passkeys and manage session access</li>
                <li>Track balances, payment events, and reconciliation cases</li>
                <li>Evaluate and send reminders with durable run IDs</li>
                <li>Handle creator replies in conversation inbox and escalation queues</li>
              </ol>
              <div className="admin-doc-highlight">
                <strong>Key defaults:</strong> Up to <strong>6 reminders</strong> per invoice, a{" "}
                <strong>48-hour cooldown</strong> between reminder attempts, and conversation auto-replies disabled by default.
              </div>
            </SurfaceCard>

            {/* ── Reminder Cycle ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="3">
              <h2>Reminder Cycle</h2>
              <p>
                Reminder runs are operator-triggered from this dashboard. For live sends, use the two-step workflow:
                evaluate first, then send the evaluated run.
              </p>
              <p className="muted-small">
                The pipeline is fully implemented, but automated scheduler/orchestrator triggering is intentionally pending.
                Until that handoff is enabled, all reminder runs are started manually by admins.
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
                  <h4>Live Evaluate + Send</h4>
                  <p>
                    Live sends require an evaluation pass first. The evaluation produces a durable run ID, then
                    the send step dispatches messages for that evaluated run.
                  </p>
                  <ul>
                    <li>Explicit review step before delivery</li>
                    <li>Outbox messages retry with exponential backoff</li>
                    <li>Messages move to dead-letter after retry cap is reached</li>
                  </ul>
                </div>
              </div>
            </SurfaceCard>

            {/* ── Eligibility ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="4">
              <h2>Who Gets Reminded</h2>
              <p>An invoice is eligible for a reminder when <strong>all</strong> of the following are true:</p>
              <ol className="admin-doc-list">
                <li>The invoice has been dispatched to the creator</li>
                <li>The creator has not opted out of reminders</li>
                <li>The outstanding balance is greater than $0</li>
                <li>Fewer than 6 reminders have been sent</li>
                <li>The invoice due date has passed (in the creator&apos;s timezone)</li>
                <li>At least 48 hours have passed since the last reminder attempt</li>
              </ol>
              <p>
                If any condition is not met, the invoice is skipped for that cycle. You can see the skip reason in test run
                results.
              </p>
            </SurfaceCard>

            {/* ── Conversation Ops ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Conversation Operations</h2>
              <p>
                Creator replies enter through Twilio, SendGrid, and BlueBubbles webhook endpoints. Each inbound
                message is deduplicated and attached to a conversation thread.
              </p>
              <ul className="admin-doc-list">
                <li>Conversation Inbox shows active threads, channel, status, and latest message preview</li>
                <li>Inbound replies are persisted even when auto-reply is disabled</li>
                <li>Delivery callbacks update outbound message delivery state</li>
                <li>Manual handoff/reply actions are currently API-level operations (not dashboard controls yet)</li>
              </ul>
              <p>
                If auto-reply is enabled, policy checks can still force handoff when content is risky or confidence is low.
              </p>
            </SurfaceCard>

            {/* ── Channels ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Email, SMS &amp; iMessage Channels</h2>
              <p>
                Each invoice dispatch specifies channels to attempt: email, SMS, iMessage, or a combination.
              </p>
              <ul className="admin-doc-list">
                <li>
                  <strong>All selected channels are attempted</strong> for every reminder
                </li>
                <li>
                  The reminder only counts as successful if <strong>all selected channels deliver</strong>
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
                After <strong>6 reminder attempts</strong> without payment, an invoice is escalated. Escalated
                invoices:
              </p>
              <ul className="admin-doc-list">
                <li>Stop receiving additional reminder attempts</li>
                <li>Appear in the Escalation Queue on the Invoicing Dashboard</li>
                <li>Require manual follow-up by an admin</li>
              </ul>
              <p>
                Use escalation data to choose manual follow-up actions and payment resolution steps.
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
                      <td>6 reminders sent, no full payment, manual follow-up required</td>
                    </tr>
                    <tr>
                      <td><strong>Paid</strong></td>
                      <td>Balance is $0, fully settled</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </SurfaceCard>

            {/* ── Creator Portal & Tokens ── */}
            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Creator Portal Access</h2>
              <p>
                Creators access their invoices through a persistent passkey. Admins generate a passkey per creator and send it
                out-of-band.
              </p>
              <ol className="admin-doc-list">
                <li>Generate a passkey for a creator in the Creator Access section above</li>
                <li>Send the passkey to the creator (email, SMS, or any secure channel)</li>
                <li>The creator pastes the passkey on the login page to access their portal</li>
                <li>Sessions last 2 hours; creators can log in again with the same passkey</li>
              </ol>
              <div className="admin-doc-highlight">
                <strong>Security:</strong> Passkeys are 256-bit random tokens, stored as SHA-256 hashes. Sessions use
                HMAC-SHA256 signed tokens with 2-hour expiry. Revoking a passkey immediately blocks all new and existing
                sessions for that creator. Generating a new passkey also rotates active sessions for that creator.
              </div>
            </SurfaceCard>

            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Webhook Security</h2>
              <p>
                Provider webhooks support enforceable signature verification modes. In production, set both payment
                and conversation webhook modes to <code>enforce</code> and provide non-placeholder secrets.
              </p>
              <ul className="admin-doc-list">
                <li>Payment webhooks use <code>PAYMENT_WEBHOOK_SIGNATURE_MODE</code> and provider secrets</li>
                <li>Conversation ingress uses <code>CONVERSATION_WEBHOOK_SIGNATURE_MODE</code></li>
                <li>Twilio, SendGrid, and BlueBubbles secrets are required only for enabled providers in enforce mode</li>
                <li>Use <code>GET /admin/runtime/security</code> to verify active provider and guard posture</li>
              </ul>
            </SurfaceCard>

            <SurfaceCard as="section" className="admin-doc-card reveal-item">
              <h2>Configuration</h2>
              <p>
                Reminder and conversation behavior is controlled by environment variables. These are set in the backend deployment and do
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
                      <td><code>NOTIFIER_ENABLED</code></td>
                      <td>Off</td>
                      <td>Master switch for live reminder sending.</td>
                    </tr>
                    <tr>
                      <td><code>REMINDER_LIVE_REQUIRES_IDEMPOTENCY</code></td>
                      <td>On</td>
                      <td>Requires idempotency keys for live reminder runs.</td>
                    </tr>
                    <tr>
                      <td><code>REMINDER_TRIGGER_RATE_LIMIT_MAX</code></td>
                      <td>10</td>
                      <td>Per-actor reminder trigger ceiling inside configured window.</td>
                    </tr>
                    <tr>
                      <td><code>CONVERSATION_AUTOREPLY_ENABLED</code></td>
                      <td>Off</td>
                      <td>Enables policy-approved automatic conversation replies.</td>
                    </tr>
                    <tr>
                      <td><code>CONVERSATION_CONFIDENCE_THRESHOLD</code></td>
                      <td>0.78</td>
                      <td>Minimum confidence for policy-approved conversation replies.</td>
                    </tr>
                    <tr>
                      <td><code>CONVERSATION_MAX_AUTO_REPLIES</code></td>
                      <td>3</td>
                      <td>Maximum auto-reply count per conversation thread.</td>
                    </tr>
                    <tr>
                      <td><code>CONVERSATION_WEBHOOK_SIGNATURE_MODE</code></td>
                      <td>log_only</td>
                      <td>Webhook signature behavior for Twilio/SendGrid/BlueBubbles ingress.</td>
                    </tr>
                    <tr>
                      <td><code>CONVERSATION_PROVIDER_TWILIO_ENABLED</code></td>
                      <td>Off</td>
                      <td>Enables Twilio inbound/status webhook ingestion.</td>
                    </tr>
                    <tr>
                      <td><code>CONVERSATION_PROVIDER_SENDGRID_ENABLED</code></td>
                      <td>Off</td>
                      <td>Enables SendGrid inbound/status webhook ingestion.</td>
                    </tr>
                    <tr>
                      <td><code>CONVERSATION_PROVIDER_BLUEBUBBLES_ENABLED</code></td>
                      <td>Off</td>
                      <td>Enables BlueBubbles iMessage inbound/status webhook ingestion.</td>
                    </tr>
                    <tr>
                      <td><code>PAYMENT_WEBHOOK_SIGNATURE_MODE</code></td>
                      <td>log_only</td>
                      <td>Webhook signature behavior for payment providers.</td>
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
                      <td>Creator session TTL</td>
                      <td><strong>120 minutes</strong></td>
                      <td>Configured via <code>CREATOR_SESSION_TTL_MINUTES</code></td>
                    </tr>
                    <tr>
                      <td>Broker token default TTL</td>
                      <td><strong>60 minutes</strong></td>
                      <td>Configured via <code>BROKER_TOKEN_DEFAULT_TTL_MINUTES</code></td>
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
            This page is for agency administrators only. Creators access their invoices through passkey-authenticated portal sessions and
            cannot see this page.
          </p>
        </footer>
      </div>
    </main>
  );
}
