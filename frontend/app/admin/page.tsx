import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AdminLogoutButton } from "./AdminLogoutButton";
import { CreatorBalancesSection } from "./CreatorBalancesSection";
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
  getAdminRuntimeSecurity,
  getReminderSummary,
  listPasskeys,
  listReminderEscalations,
  listTasks,
  revokePasskey,
  runReminderCycle,
  sendReminderRun,
  type AdminCreatorDirectoryItem,
  type AdminRuntimeSecurityStatus,
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

// Keep this env key for compatibility with existing backend/admin creator APIs.
const CREATOR_DIRECTORY_FOCUS_YEAR = (() => {
  const parsed = Number.parseInt(process.env.DEMO_FOCUS_YEAR ?? "2026", 10);
  if (Number.isFinite(parsed) && parsed >= 2000 && parsed <= 2100) {
    return parsed;
  }
  return 2026;
})();

const STATUS_TONE: Record<TaskSummary["status"], StatusTone> = {
  previewed: "warning",
  confirmed: "brand",
  completed: "success",
};

type ProductionHealthState = "good" | "attention" | "unavailable";

interface ProductionHealthSignal {
  key: string;
  label: string;
  state: ProductionHealthState;
  detail: string;
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
  creator_q?: string;
  creator_owed_only?: string;
}

function formatConversationChannel(channel: ConversationThreadItem["channel"]): string {
  if (channel === "imessage") {
    return "iMessage";
  }
  return channel.toUpperCase();
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
    const creators = await listAdminCreators(adminToken, { focusYear: CREATOR_DIRECTORY_FOCUS_YEAR });
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
        creator_id: result.creator_id,
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
    return mode === "live"
      ? "Live reminders were sent successfully."
      : "Preview complete. No reminders were sent.";
  }
  if (reminderRun === "error") {
    return mode === "live"
      ? "Live reminder send failed. Please try again."
      : "Preview failed. Please try again.";
  }
  return null;
}

function evalMessage(reminderEval: string | undefined): string | null {
  if (reminderEval === "success") {
    return "Live send prepared. Review the pending run details, then send when ready.";
  }
  if (reminderEval === "error") {
    return "Could not prepare live send. Please try again.";
  }
  return null;
}

function sendMessage(reminderSend: string | undefined): string | null {
  if (reminderSend === "success") {
    return "Prepared reminder run sent successfully.";
  }
  if (reminderSend === "error") {
    return "Prepared reminder run failed to send. Please try again.";
  }
  return null;
}

function passkeyGenMessage(reason: string | undefined): string {
  if (reason === "missing_fields") {
    return "Creator ID and creator name are required.";
  }
  if (reason === "unknown_creator") {
    return "Creator ID was not found in current records. Use a known creator or enable manual override.";
  }
  if (reason === "no_dispatched_invoices") {
    return "This creator does not have a dispatched invoice yet. Dispatch first, or use manual override.";
  }
  if (reason === "directory_unavailable") {
    return "Creator validation is currently unavailable. Try again, or use manual override if needed.";
  }
  return "Passkey generation failed. Please try again.";
}

function healthTone(state: ProductionHealthState): StatusTone {
  if (state === "good") {
    return "success";
  }
  if (state === "attention") {
    return "warning";
  }
  return "muted";
}

function healthLabel(state: ProductionHealthState): string {
  if (state === "good") {
    return "good";
  }
  if (state === "attention") {
    return "attention";
  }
  return "unavailable";
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
  const initialCreatorQuery = (resolvedSearchParams.creator_q ?? "").trim();
  const creatorOwedOnlyParam = (resolvedSearchParams.creator_owed_only ?? "").trim().toLowerCase();
  const initialCreatorOwedOnly = creatorOwedOnlyParam === "" || !["0", "false", "off", "no"].includes(creatorOwedOnlyParam);

  const cookieStore = await cookies();
  const adminToken = cookieStore.get("admin_session")?.value ?? "";
  if (!adminToken) {
    redirect("/admin/gate");
  }

  let tasks: TaskSummary[] = [];
  let loadError: string | null = null;
  let reminderSummary: ReminderSummary | null = null;
  let reminderEscalations: ReminderEscalation[] = [];
  let reminderError: string | null = null;
  let runtimeSecurity: AdminRuntimeSecurityStatus | null = null;
  let runtimeSecurityError: string | null = null;

  try {
    const result = await listTasks();
    tasks = Array.isArray(result) ? result : [];
  } catch (error) {
    loadError = error instanceof Error ? error.message : "Unable to load tasks";
  }

  try {
    const [summary, escalations] = await Promise.all([
      getReminderSummary(adminToken),
      listReminderEscalations(adminToken),
    ]);
    reminderSummary = summary;
    reminderEscalations = Array.isArray(escalations.items) ? escalations.items : [];
  } catch (error) {
    reminderError = error instanceof Error ? error.message : "Unable to load reminder data";
  }

  try {
    runtimeSecurity = await getAdminRuntimeSecurity(adminToken);
  } catch (error) {
    runtimeSecurityError = error instanceof Error ? error.message : "Unable to load runtime security";
  }

  let passkeys: PasskeyListItem[] = [];
  let passkeyError: string | null = null;
  let creatorDirectory: AdminCreatorDirectoryItem[] = [];
  let creatorDirectoryError: string | null = null;
  let conversationThreads: ConversationThreadItem[] = [];
  let conversationError: string | null = null;

  try {
    const result = await listPasskeys(adminToken);
    passkeys = Array.isArray(result.creators) ? result.creators : [];
  } catch (error) {
    passkeyError = error instanceof Error ? error.message : "Unable to load passkeys";
  }

  try {
    const result = await listAdminCreators(adminToken, { focusYear: CREATOR_DIRECTORY_FOCUS_YEAR });
    creatorDirectory = Array.isArray(result.creators) ? result.creators : [];
  } catch (error) {
    creatorDirectoryError = error instanceof Error ? error.message : "Unable to load creator directory";
  }

  try {
    const result = await listAdminConversations(adminToken);
    conversationThreads = Array.isArray(result.items) ? result.items : [];
  } catch (error) {
    conversationError = error instanceof Error ? error.message : "Unable to load conversation inbox";
  }

  const passkeyGenState = resolvedSearchParams.passkeyGen;
  const passkeyGenReason = resolvedSearchParams.passkeyGenReason;
  const passkeyRevokeState = resolvedSearchParams.passkeyRevoke;
  const passkeyGenError = passkeyGenState === "error" ? passkeyGenMessage(passkeyGenReason) : null;
  const readyCreators = creatorDirectory.filter((creator) => creator.ready_for_portal);
  const runtimeIssueCount = runtimeSecurity?.runtime_secret_issues.length ?? 0;

  const productionHealthSignals: ProductionHealthSignal[] = [
    {
      key: "queue",
      label: "Invoice Queue",
      state: loadError ? "unavailable" : tasks.length > 0 ? "attention" : "good",
      detail: loadError
        ? `Queue unavailable: ${loadError}`
        : tasks.length > 0
          ? `${tasks.length} background task${tasks.length === 1 ? " is" : "s are"} active.`
          : "No background invoice tasks are waiting.",
    },
    {
      key: "due_now",
      label: "Follow-Ups Due Now",
      state: reminderError
        ? "unavailable"
        : (reminderSummary?.eligible_now_count ?? 0) > 0
          ? "attention"
          : "good",
      detail: reminderError
        ? `Reminder data unavailable: ${reminderError}`
        : `${reminderSummary?.eligible_now_count ?? 0} invoice${(reminderSummary?.eligible_now_count ?? 0) === 1 ? "" : "s"} currently eligible for reminders.`,
    },
    {
      key: "escalations",
      label: "Escalations",
      state: reminderError
        ? "unavailable"
        : (reminderSummary?.escalated_count ?? 0) > 0
          ? "attention"
          : "good",
      detail: reminderError
        ? "Escalation count unavailable."
        : `${reminderSummary?.escalated_count ?? 0} invoice${(reminderSummary?.escalated_count ?? 0) === 1 ? "" : "s"} need manual follow-up.`,
    },
    {
      key: "conversations",
      label: "Creator Replies",
      state: conversationError
        ? "unavailable"
        : conversationThreads.length > 0
          ? "attention"
          : "good",
      detail: conversationError
        ? `Conversation inbox unavailable: ${conversationError}`
        : conversationThreads.length > 0
          ? `${conversationThreads.length} conversation thread${conversationThreads.length === 1 ? "" : "s"} currently active.`
          : "No active conversation threads right now.",
    },
    {
      key: "security",
      label: "Security Checks",
      state: runtimeSecurityError ? "unavailable" : runtimeIssueCount > 0 ? "attention" : "good",
      detail: runtimeSecurityError
        ? `Security status unavailable: ${runtimeSecurityError}`
        : runtimeIssueCount > 0
          ? `${runtimeIssueCount} runtime security issue${runtimeIssueCount === 1 ? "" : "s"} detected.`
          : "Runtime security checks are clear.",
    },
  ];

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
        <header className="admin-header reveal-item">
          <div className="admin-header__copy">
            <BrandWordmark size="sm" />
            <h1>Admin Dashboard</h1>
            <p className="kicker">
              Manage live invoicing operations, monitor follow-ups, and keep creator access moving.
            </p>
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

        <SurfaceCard as="section" className="demo-readiness-card reveal-item" data-delay="1">
          <div className="demo-readiness-card__head">
            <h2>Production Health</h2>
            <p className="kicker">A quick view of what needs attention right now.</p>
          </div>
          <div className="demo-readiness-grid" aria-label="Production health signals">
            {productionHealthSignals.map((signal) => (
              <article key={signal.key} className="demo-readiness-item">
                <div className="demo-readiness-item__head">
                  <h3>{signal.label}</h3>
                  <StatusBadge tone={healthTone(signal.state)}>{healthLabel(signal.state)}</StatusBadge>
                </div>
                <p className="muted-small">{signal.detail}</p>
              </article>
            ))}
          </div>
        </SurfaceCard>

        <SurfaceCard as="section" className="reminder-ops-card reveal-item" data-delay="1">
          <div className="reminder-ops-card__head">
            <h2>Payment Reminders</h2>
            <p className="kicker">
              Review unpaid invoices, preview who will be contacted, and send reminders when ready.
            </p>
          </div>

          <div className="reminder-ops-card__actions">
            <form action={runRemindersAction}>
              <input type="hidden" name="mode" value="dry" />
              <button type="submit" className="button-link">
                Preview Contacts
              </button>
            </form>
            <form action={runRemindersAction}>
              <input type="hidden" name="mode" value="live" />
              <button type="submit" className="button-link button-link--secondary">
                Prepare Live Send
              </button>
            </form>
            {pendingRunId ? (
              <form action={sendEvaluatedRemindersAction}>
                <input type="hidden" name="run_id" value={pendingRunId} />
                <button type="submit" className="button-link button-link--secondary">
                  Send Prepared Reminders
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
              Prepared run <code>{pendingRunId}</code>
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
                <span>Unpaid Invoices</span>
                <strong>{reminderSummary.unpaid_count}</strong>
              </div>
              <div className="reminder-metric-card">
                <span>Overdue Invoices</span>
                <strong>{reminderSummary.overdue_count}</strong>
              </div>
              <div className="reminder-metric-card">
                <span>Ready To Send</span>
                <strong>{reminderSummary.eligible_now_count}</strong>
              </div>
              <div className="reminder-metric-card">
                <span>Escalations</span>
                <strong>{reminderSummary.escalated_count}</strong>
              </div>
            </div>
          ) : null}

          {reminderSummary?.last_run_at ? (
            <p className="muted-small">
              Last run {formatTimestamp(reminderSummary.last_run_at)} ({reminderSummary.last_run_dry_run ? "preview" : "live send"})
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

        <CreatorBalancesSection
          creators={creatorDirectory}
          loadError={creatorDirectoryError}
          focusYear={CREATOR_DIRECTORY_FOCUS_YEAR}
          initialQuery={initialCreatorQuery}
          initialOwedOnly={initialCreatorOwedOnly}
        />

        <SurfaceCard as="section" className="invoicing-table-card reveal-item" data-delay="1">
          <div className="invoicing-table-card__head">
            <h2>Conversation Inbox</h2>
            <p className="kicker">Review incoming creator replies and identify messages that need manual follow-up.</p>
          </div>
          {conversationError ? (
            <p className="muted-small">Conversation data unavailable: {conversationError}</p>
          ) : conversationThreads.length === 0 ? (
            <p className="muted-small">No active conversation threads right now.</p>
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

        <SurfaceCard as="section" className="invoicing-table-card reveal-item" data-delay="1">
          <div className="invoicing-table-card__head">
            <h2>Creator Access</h2>
            <p className="kicker">Generate and manage creator passkeys for portal login.</p>
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
                Allow manual override (issue passkey even if this creator is not portal-ready)
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
              Recommended creators come from current invoice records with at least one dispatched invoice.
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
                <h3 style={{ fontSize: "1.04rem", color: "var(--text-strong)", marginBottom: "var(--space-3)" }}>
                  Active Creators
                </h3>
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
                          <td><code className="passkey-prefix-code" suppressHydrationWarning>{pk.display_prefix}...</code></td>
                          <td><span className="muted-small">{formatTimestamp(pk.created_at)}</span></td>
                          <td>
                            <form action={revokePasskeyAction} style={{ display: "inline" }}>
                              <input type="hidden" name="creator_id" value={pk.creator_id} />
                              <button type="submit" className="button-link button-link--secondary" style={{ padding: "4px 12px", fontSize: "0.8rem" }}>
                                Revoke
                              </button>
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
              <p className="kicker">
                {latestTimestamp ? `Latest update ${formatTimestamp(latestTimestamp)}` : "No updates yet"}
              </p>
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

        <details className="admin-docs-disclosure reveal-item">
          <summary><h2>Quick Guides</h2></summary>
          <div className="admin-docs-disclosure__body">
            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="1">
              <h2>What This Dashboard Is For</h2>
              <p>
                This page helps operations teams monitor balances, run reminder workflows, and manage creator portal access.
              </p>
              <ul className="admin-doc-list">
                <li>Check production health cards to see what needs attention now</li>
                <li>Use Payment Reminders to preview, prepare, and send reminder runs</li>
                <li>Use Creator Access to issue or revoke portal passkeys</li>
              </ul>
            </SurfaceCard>

            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="2">
              <h2>Reminder Workflow</h2>
              <ol className="admin-doc-list">
                <li>Select <strong>Preview Contacts</strong> to verify who would be contacted</li>
                <li>Select <strong>Prepare Live Send</strong> to create a reviewed run</li>
                <li>Select <strong>Send Prepared Reminders</strong> to send that reviewed run</li>
              </ol>
              <p>
                If a run fails, the error banner explains what happened so you can retry safely.
              </p>
            </SurfaceCard>

            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="3">
              <h2>Creator Access Basics</h2>
              <ul className="admin-doc-list">
                <li>Generate one passkey per creator and send it through a secure channel</li>
                <li>Use active passkey list to confirm who currently has access</li>
                <li>Revoke passkeys immediately when access should be removed</li>
              </ul>
            </SurfaceCard>

            <SurfaceCard as="section" className="admin-doc-card reveal-item" data-delay="4">
              <h2>When To Escalate</h2>
              <p>
                Use the Escalation Queue when invoices need manual follow-up after repeated reminder attempts.
              </p>
              <ul className="admin-doc-list">
                <li>Review creator, invoice, balance, and reminder count</li>
                <li>Coordinate direct follow-up outside the automated reminder flow</li>
                <li>Track outcomes in your team’s operations process</li>
              </ul>
            </SurfaceCard>
          </div>
        </details>

        <footer className="admin-footer reveal-item">
          <p className="muted-small">
            This page is for agency administrators only. Creators access invoices through passkey-authenticated portal sessions.
          </p>
        </footer>
      </div>
    </main>
  );
}
