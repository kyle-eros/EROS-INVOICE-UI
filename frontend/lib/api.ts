export interface TaskSummary {
  task_id: string;
  status: "previewed" | "confirmed" | "completed";
  agent_slug: "payout-reconciliation" | "commission-payroll" | "chargeback-defense";
  mode: "plan_only" | "dry_run";
  window_start: string;
  window_end: string;
  source_count: number;
  created_at: string;
  updated_at: string;
}

export interface ReminderSummary {
  unpaid_count: number;
  overdue_count: number;
  eligible_now_count: number;
  escalated_count: number;
  last_run_at: string | null;
  last_run_dry_run: boolean | null;
  last_run_sent_count: number | null;
  last_run_failed_count: number | null;
  last_run_skipped_count: number | null;
}

export interface ReminderResult {
  invoice_id: string;
  status: "sent" | "skipped" | "failed" | "dry_run";
  reason: string;
  attempted_at: string | null;
  provider_message_id: string | null;
  error_code: string | null;
  error_message: string | null;
  next_eligible_at: string | null;
  contact_target_masked: string | null;
}

export interface ReminderRunRequest {
  dry_run?: boolean;
  limit?: number;
  now_override?: string;
  idempotency_key?: string;
}

export interface ReminderEvaluateRequest {
  limit?: number;
  now_override?: string;
  idempotency_key?: string;
}

export interface ReminderRunResponse {
  run_id: string | null;
  run_at: string;
  dry_run: boolean;
  evaluated_count: number;
  eligible_count: number;
  sent_count: number;
  failed_count: number;
  skipped_count: number;
  escalated_count: number;
  results: ReminderResult[];
}

export interface ReminderEscalation {
  invoice_id: string;
  creator_id: string;
  creator_name: string;
  balance_due: number;
  due_date: string;
  reminder_count: number;
  last_reminder_at: string | null;
  reason: string;
}

export interface ReminderEscalationResponse {
  items: ReminderEscalation[];
}

export interface ConversationThreadItem {
  thread_id: string;
  channel: "email" | "sms" | "imessage";
  external_contact_masked: string;
  creator_id: string | null;
  creator_name: string | null;
  invoice_id: string | null;
  status: "open" | "agent_paused" | "human_handoff" | "closed";
  auto_reply_count: number;
  last_message_preview: string | null;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationThreadListResponse {
  items: ConversationThreadItem[];
}

export interface CreatorInvoiceItem {
  invoice_id: string;
  amount_due: number;
  amount_paid: number;
  balance_due: number;
  currency: string;
  issued_at: string;
  due_date: string;
  status: "open" | "partial" | "paid" | "overdue" | "escalated";
  dispatch_id: string;
  dispatched_at: string;
  notification_state: "unseen" | "seen_unfulfilled" | "fulfilled";
  reminder_count: number;
  has_pdf: boolean;
  creator_payment_submitted_at: string | null;
  last_reminder_at: string | null;
}

export interface CreatorInvoicesResponse {
  creator_id: string;
  creator_name: string;
  invoices: CreatorInvoiceItem[];
}

export interface CreatorPaymentSubmissionResponse {
  invoice_id: string;
  creator_id: string;
  submitted_at: string;
  already_submitted: boolean;
  status: "open" | "partial" | "paid" | "overdue" | "escalated";
  balance_due: number;
}

const API_BASE_URL = process.env.INVOICING_API_BASE_URL ?? "http://localhost:8000";

export class BackendApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "BackendApiError";
    this.status = status;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  return value as Record<string, unknown>;
}

async function decodeJson<T>(response: Response, operation: string): Promise<T> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const body = asRecord(payload);
    const message =
      (typeof body?.detail === "string" && body.detail) ||
      (typeof body?.error === "string" && body.error) ||
      (typeof body?.message === "string" && body.message) ||
      `${operation} failed (${response.status})`;
    throw new BackendApiError(message, response.status);
  }
  return payload as T;
}

async function decodeAuthJson<T>(response: Response, fallbackMessage: string): Promise<T> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const body = asRecord(payload);
    const message =
      (typeof body?.detail === "string" && body.detail) ||
      (typeof body?.error === "string" && body.error) ||
      (typeof body?.message === "string" && body.message) ||
      fallbackMessage;
    throw new BackendApiError(message, response.status);
  }

  return payload as T;
}

export async function listTasks(): Promise<TaskSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/tasks`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  return decodeJson<TaskSummary[]>(response, "Task listing");
}

export async function getReminderSummary(adminToken: string): Promise<ReminderSummary> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/reminders/summary`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    cache: "no-store",
  });

  return decodeJson<ReminderSummary>(response, "Reminder summary");
}

export async function listReminderEscalations(adminToken: string): Promise<ReminderEscalationResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/reminders/escalations`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    cache: "no-store",
  });

  return decodeJson<ReminderEscalationResponse>(response, "Reminder escalations");
}

export async function listAdminConversations(adminToken: string): Promise<ConversationThreadListResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/admin/conversations`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    cache: "no-store",
  });

  return decodeJson<ConversationThreadListResponse>(response, "Conversation inbox");
}

export async function runReminderCycle(payload: ReminderRunRequest = {}, adminToken: string): Promise<ReminderRunResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/reminders/run/once`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  return decodeJson<ReminderRunResponse>(response, "Reminder run");
}

export async function evaluateReminderCycle(
  payload: ReminderEvaluateRequest = {},
  adminToken: string,
): Promise<ReminderRunResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/reminders/evaluate`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  return decodeJson<ReminderRunResponse>(response, "Reminder evaluation");
}

export async function sendReminderRun(
  runId: string,
  adminToken: string,
  payload: { max_messages?: number } = {},
): Promise<ReminderRunResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/reminders/runs/${encodeURIComponent(runId)}/send`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return decodeJson<ReminderRunResponse>(response, "Reminder send");
}

export async function getCreatorInvoices(token: string): Promise<CreatorInvoicesResponse> {
  // Legacy alias: this now expects a creator session token and uses the session endpoint.
  return getCreatorInvoicesBySession(token);
}

// --- Passkey Auth (server-side → backend) ---

export async function backendLookupPasskey(passkey: string): Promise<{ creator_id: string; creator_name: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/auth/lookup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ passkey }),
    cache: "no-store",
  });
  return decodeAuthJson(response, "Passkey lookup failed");
}

export async function backendConfirmPasskey(passkey: string): Promise<{
  creator_id: string;
  creator_name: string;
  session_token: string;
  expires_at: string;
}> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/auth/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ passkey }),
    cache: "no-store",
  });
  return decodeAuthJson(response, "Passkey confirmation failed");
}

// --- Admin Auth (server-side → backend) ---

export async function backendAdminLogin(password: string): Promise<{
  authenticated: boolean;
  session_token: string;
  expires_at: string;
}> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/admin/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
    cache: "no-store",
  });
  return decodeAuthJson(response, "Admin login failed");
}

// --- Session-based Creator Data ---

export async function getCreatorInvoicesBySession(sessionToken: string): Promise<CreatorInvoicesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/me/invoices`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${sessionToken}`,
    },
    cache: "no-store",
  });
  return decodeJson(response, "Creator invoices (session)");
}

export async function fetchCreatorInvoicePdfBySession(sessionToken: string, invoiceId: string): Promise<Response> {
  return fetch(`${API_BASE_URL}/api/v1/invoicing/me/invoices/${encodeURIComponent(invoiceId)}/pdf`, {
    method: "GET",
    headers: {
      Accept: "application/pdf",
      Authorization: `Bearer ${sessionToken}`,
    },
    cache: "no-store",
  });
}

export async function submitCreatorInvoicePaymentSubmissionBySession(
  sessionToken: string,
  invoiceId: string,
): Promise<CreatorPaymentSubmissionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/me/invoices/${encodeURIComponent(invoiceId)}/payment-submission`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${sessionToken}`,
    },
    cache: "no-store",
  });
  return decodeJson(response, "Creator payment submission");
}

// --- Passkey Management (admin-only) ---

export async function generatePasskey(
  creatorId: string,
  creatorName: string,
  adminToken: string,
): Promise<{
  creator_id: string;
  creator_name: string;
  passkey: string;
  display_prefix: string;
  created_at: string;
}> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/passkeys/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    body: JSON.stringify({ creator_id: creatorId, creator_name: creatorName }),
    cache: "no-store",
  });
  return decodeJson(response, "Generate passkey");
}

export interface PasskeyListItem {
  creator_id: string;
  creator_name: string;
  display_prefix: string;
  created_at: string;
}

export interface AdminCreatorDirectoryItem {
  creator_id: string;
  creator_name: string;
  invoice_count: number;
  dispatched_invoice_count: number;
  unpaid_invoice_count: number;
  submitted_payment_invoice_count: number;
  total_balance_owed_usd: number;
  jan_full_invoice_usd: number;
  feb_current_owed_usd: number;
  has_non_usd_open_invoices: boolean;
  ready_for_portal: boolean;
}

export interface AdminRuntimeSecurityStatus {
  runtime_secret_guard_mode: "off" | "warn" | "enforce";
  conversation_webhook_signature_mode: "off" | "log_only" | "enforce";
  payment_webhook_signature_mode: "off" | "log_only" | "enforce";
  conversation_enabled: boolean;
  notifier_enabled: boolean;
  providers_enabled: Record<string, boolean>;
  runtime_secret_issues: string[];
}

export async function listPasskeys(adminToken: string): Promise<{ creators: PasskeyListItem[] }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/passkeys`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    cache: "no-store",
  });
  return decodeJson(response, "List passkeys");
}

export async function listAdminCreators(
  adminToken: string,
  options: { focusYear?: number } = {},
): Promise<{ creators: AdminCreatorDirectoryItem[] }> {
  const search = typeof options.focusYear === "number" ? `?focus_year=${encodeURIComponent(String(options.focusYear))}` : "";
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/admin/creators${search}`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    cache: "no-store",
  });
  return decodeJson(response, "List admin creators");
}

export async function getAdminRuntimeSecurity(adminToken: string): Promise<AdminRuntimeSecurityStatus> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/admin/runtime/security`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    cache: "no-store",
  });
  return decodeJson(response, "Runtime security status");
}

export async function revokePasskey(
  creatorId: string,
  adminToken: string,
): Promise<{ creator_id: string; revoked: boolean }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/passkeys/revoke`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${adminToken}`,
    },
    body: JSON.stringify({ creator_id: creatorId }),
    cache: "no-store",
  });
  return decodeJson(response, "Revoke passkey");
}
