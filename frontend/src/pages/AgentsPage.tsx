import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useAgents } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";

export function AgentsPage() {
  const { range, organizationId } = useDashboardFilters();
  const query = useAgents(range, organizationId);

  return (
    <div>
      <h2>Agent Workload</h2>
      <QueryState query={query}>
        {(data) => (
          <>
            <p className="page-note">{data.note}</p>
            {data.agents.length === 0 ? (
              <div className="state-message">No reviewer activity in this range.</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Reviewer</th>
                    <th>Assigned</th>
                    <th>Pending</th>
                    <th>Resolved</th>
                    <th>Avg Resolution (min)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.agents.map((agent) => (
                    <tr key={agent.reviewer_id}>
                      <td>{agent.reviewer_id}</td>
                      <td>{agent.assigned}</td>
                      <td>{agent.pending}</td>
                      <td>{agent.resolved}</td>
                      <td>{agent.avg_resolution_minutes !== null ? agent.avg_resolution_minutes.toFixed(1) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </QueryState>
    </div>
  );
}
