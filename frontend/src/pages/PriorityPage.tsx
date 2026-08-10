import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { usePriority } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { SimpleBarChart } from "../charts/SimpleBarChart";

export function PriorityPage() {
  const { range, organizationId } = useDashboardFilters();
  const query = usePriority(range, organizationId);

  return (
    <div>
      <h2>Priority Distribution</h2>
      <QueryState query={query}>
        {(data) => (
          <>
            <div className="page-note">
              <EvidenceBadge evidence={data.evidence} /> <span>{data.evidence.note}</span>
            </div>
            <SimpleBarChart data={data.counts as unknown as Record<string, unknown>[]} xKey="priority" yKey="count" color="#c0392b" />
          </>
        )}
      </QueryState>
    </div>
  );
}
