import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useModelQuality } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";
import { EvidenceBadge } from "../components/EvidenceBadge";

export function ModelQualityPage() {
  const { range, organizationId } = useDashboardFilters();
  const query = useModelQuality(range, organizationId);

  return (
    <div>
      <h2>Model Quality</h2>
      <p className="page-note">
        Correction rate = corrections / reviewed predictions (not / all predictions) -- see
        docs/architecture_dashboard.md.
      </p>
      <QueryState query={query}>
        {(data) => (
          <table className="data-table">
            <thead>
              <tr>
                <th>Module</th>
                <th>Evidence</th>
                <th>Offline Reference Metric</th>
                <th>Correction Rate</th>
                <th>Reviewed</th>
                <th>Retraining Threshold</th>
              </tr>
            </thead>
            <tbody>
              {data.modules.map((m) => (
                <tr key={m.module}>
                  <td>{m.module}</td>
                  <td>
                    <EvidenceBadge evidence={m.evidence} />
                  </td>
                  <td>{m.offline_reference_metric ?? "—"}</td>
                  <td>
                    {m.reviewed_count === 0
                      ? "No real observations yet"
                      : `${(m.correction_rate! * 100).toFixed(1)}% (${m.corrected_count}/${m.reviewed_count})`}
                  </td>
                  <td>{m.reviewed_count}</td>
                  <td>{m.retraining_threshold_reached ? "⚠ reached (audit only, no retrain)" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
    </div>
  );
}
