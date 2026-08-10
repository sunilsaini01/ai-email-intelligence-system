import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useSla } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";

export function SlaPage() {
  const { range, organizationId } = useDashboardFilters();
  const query = useSla(range, organizationId);

  return (
    <div>
      <h2>SLA Status</h2>
      <QueryState query={query}>
        {(data) => (
          <>
            <p className="page-note">{data.note}</p>
            <p className="page-note">
              Targets (hours):{" "}
              {Object.entries(data.sla_targets_hours)
                .map(([p, h]) => `${p}=${h}h`)
                .join(", ")}{" "}
              &middot; Excluded (no priority set): {data.excluded_no_priority}
            </p>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={data.buckets} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="priority" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Bar dataKey="within_sla" stackId="sla" fill="#1b7f3a" name="Within SLA" />
                <Bar dataKey="at_risk" stackId="sla" fill="#c98a1f" name="At Risk" />
                <Bar dataKey="breached" stackId="sla" fill="#c0392b" name="Breached" />
              </BarChart>
            </ResponsiveContainer>
          </>
        )}
      </QueryState>
    </div>
  );
}
