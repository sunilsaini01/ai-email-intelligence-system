import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useCategories } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { SimpleBarChart } from "../charts/SimpleBarChart";

export function CategoriesPage() {
  const { range, organizationId } = useDashboardFilters();
  const query = useCategories(range, organizationId);

  return (
    <div>
      <h2>Category Distribution</h2>
      <QueryState query={query}>
        {(data) => (
          <>
            <div className="page-note">
              <EvidenceBadge evidence={data.evidence} /> <span>{data.evidence.note}</span>
            </div>
            <SimpleBarChart data={data.counts as unknown as Record<string, unknown>[]} xKey="category" yKey="count" color="#a15c00" />
          </>
        )}
      </QueryState>
    </div>
  );
}
