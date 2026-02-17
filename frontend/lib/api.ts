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
}

export interface ReminderRunResponse {
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

const API_BASE_URL = process.env.INVOICING_API_BASE_URL ?? "http://localhost:8000";

async function decodeJson<T>(response: Response, operation: string): Promise<T> {
  if (!response.ok) {
    throw new Error(`${operation} failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function listTasks(): Promise<TaskSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/tasks`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  return decodeJson<TaskSummary[]>(response, "Task listing");
}

export async function getReminderSummary(): Promise<ReminderSummary> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/reminders/summary`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  return decodeJson<ReminderSummary>(response, "Reminder summary");
}

export async function listReminderEscalations(): Promise<ReminderEscalationResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/reminders/escalations`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  return decodeJson<ReminderEscalationResponse>(response, "Reminder escalations");
}

export async function runReminderCycle(payload: ReminderRunRequest = {}): Promise<ReminderRunResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/reminders/run/once`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  return decodeJson<ReminderRunResponse>(response, "Reminder run");
}
