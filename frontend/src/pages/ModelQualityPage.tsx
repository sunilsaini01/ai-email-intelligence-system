import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useModelQuality } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { useDrift, useHasRole, useRequestRetraining, useRetraining } from "../hooks/useAdmin";

const RETRAINABLE_MODULES = ["spam", "priority", "category", "intent"];

function percent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

// FR-72 drift panel (manager+).
function DriftPanel() {
  const query = useDrift(true);
  return (
    <section className="admin-section">
      <h3>Model drift (FR-72)</h3>
      <QueryState query={query}>
        {(data) => (
          <>
            <p className="page-note">
              Last {data.current_window_days} days vs. the {data.baseline_window_days} before. {data.note}
            </p>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Module</th>
                  <th>Prediction PSI</th>
                  <th>Status</th>
                  <th>Correction rate (baseline → current)</th>
                  <th>Alert</th>
                </tr>
              </thead>
              <tbody>
                {data.modules.map((m) => (
                  <tr key={m.module}>
                    <td>{m.module}</td>
                    <td>{m.psi === null ? "—" : m.psi.toFixed(3)}</td>
                    <td>{m.prediction_status.replace("_", " ")}</td>
                    <td>
                      {percent(m.baseline_correction_rate)} → {percent(m.current_correction_rate)}
                    </td>
                    <td>{m.alert ? "⚠ drift" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </QueryState>
    </section>
  );
}

// FR-61 retraining runs (manager+ view, admin trigger).
function RetrainingPanel() {
  const isAdmin = useHasRole("admin");
  const query = useRetraining(true);
  const retrain = useRequestRetraining();

  return (
    <section className="admin-section">
      <h3>Retraining (FR-61)</h3>
      <p className="page-note">
        Runs automatically when a module&apos;s corrections cross the feedback threshold, or on request. Each run trains
        on the original data plus logged corrections and registers an MLflow candidate; promoting it to production
        stays a reviewed step (scripts/mlops/promote_model.py).
      </p>
      {isAdmin && (
        <div className="toggle-row">
          {RETRAINABLE_MODULES.map((module) => (
            <button
              key={module}
              type="button"
              className="preset-btn"
              disabled={retrain.isPending}
              onClick={() => retrain.mutate(module)}
            >
              Retrain {module}
            </button>
          ))}
        </div>
      )}
      {retrain.error instanceof Error && (
        <div className="state-message state-message--error">{retrain.error.message}</div>
      )}
      <QueryState query={query}>
        {(data) =>
          data.triggers.length === 0 ? (
            <div className="state-message">No retraining runs yet.</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Module</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Requested</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {data.triggers.map((t) => (
                  <tr key={t.id}>
                    <td>{t.module}</td>
                    <td>{t.source}</td>
                    <td>{t.status}</td>
                    <td>{new Date(t.triggered_at).toLocaleString()}</td>
                    <td className="subject-cell" title={t.result_message ?? ""}>
                      {t.result_message?.split("\n")[0] ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </QueryState>
    </section>
  );
}

export function ModelQualityPage() {
  const { range, organizationId } = useDashboardFilters();
  const query = useModelQuality(range, organizationId);
  const isManager = useHasRole("manager");

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
                  <td>{m.retraining_threshold_reached ? "⚠ reached -- retraining queued" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
      {isManager && <DriftPanel />}
      {isManager && <RetrainingPanel />}
    </div>
  );
}
