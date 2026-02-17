import { listTasks, type TaskSummary } from "../../lib/api";

export default async function InvoicingPage() {
  let tasks: TaskSummary[] = [];
  let loadError: string | null = null;

  try {
    tasks = await listTasks();
  } catch (error) {
    loadError = error instanceof Error ? error.message : "Unable to load tasks";
  }

  return (
    <main style={{ margin: "3rem auto", maxWidth: 860, fontFamily: "sans-serif" }}>
      <h1>Invoicing Tasks</h1>
      <p>Read-only task queue backed by the invoicing preview lifecycle API.</p>

      {loadError ? <p style={{ color: "#a00" }}>Error: {loadError}</p> : null}

      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th align="left">Task</th>
            <th align="left">Status</th>
            <th align="left">Agent</th>
            <th align="left">Window</th>
            <th align="right">Sources</th>
            <th align="left">Mode</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.task_id}>
              <td>{task.task_id}</td>
              <td>{task.status}</td>
              <td>{task.agent_slug}</td>
              <td>
                {task.window_start} to {task.window_end}
              </td>
              <td align="right">{task.source_count}</td>
              <td>{task.mode}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
