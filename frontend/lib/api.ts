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

const API_BASE_URL = process.env.INVOICING_API_BASE_URL ?? "http://localhost:8000";

export async function listTasks(): Promise<TaskSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/invoicing/tasks`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Task listing failed (${response.status})`);
  }

  return (await response.json()) as TaskSummary[];
}
