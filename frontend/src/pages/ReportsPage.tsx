import { useState } from "react";
import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { dashboardApi } from "../api/dashboard";
import { insightsApi } from "../api/admin";
import { QueryState } from "../components/QueryState";
import { useGeneratedReports, useHasRole } from "../hooks/useAdmin";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function ReportsPage() {
  const { range, organizationId } = useDashboardFilters();
  const [downloading, setDownloading] = useState<"csv" | "pdf" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isManager = useHasRole("manager");
  const generated = useGeneratedReports(isManager);

  async function handleGeneratedDownload(id: string, filename: string) {
    setError(null);
    try {
      downloadBlob(await insightsApi.downloadGeneratedReport(id), filename);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    }
  }

  async function handleExport(format: "csv" | "pdf") {
    setDownloading(format);
    setError(null);
    try {
      const blob = await dashboardApi.exportReport(range, organizationId, format);
      downloadBlob(blob, `email_intelligence_report.${format}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setDownloading(null);
    }
  }

  if (!isManager) {
    return <div className="state-message">Reports are available to managers and admins.</div>;
  }

  return (
    <div>
      <h2>Reports</h2>
      <p className="page-note">
        On-demand export for the selected date range -- CSV and PDF cover the same overview, volume, category,
        sentiment, priority, SLA, agent-workload, and model-quality sections shown elsewhere in this dashboard, each
        with the same evidence labeling. Weekly reports (FR-56) are also generated automatically every Monday for the
        previous week and listed below.
      </p>
      <div className="toggle-row">
        <button type="button" className="preset-btn" disabled={downloading !== null} onClick={() => void handleExport("csv")}>
          {downloading === "csv" ? "Exporting..." : "Export CSV"}
        </button>
        <button type="button" className="preset-btn" disabled={downloading !== null} onClick={() => void handleExport("pdf")}>
          {downloading === "pdf" ? "Exporting..." : "Export PDF"}
        </button>
      </div>
      {error && <div className="state-message state-message--error">{error}</div>}
      <h3>Weekly reports</h3>
      <QueryState query={generated}>
        {(data) =>
          data.reports.length === 0 ? (
            <div className="state-message">No weekly report has been generated yet.</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Week</th>
                  <th>Format</th>
                  <th>Size</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.reports.map((r) => {
                  const week = r.period_start.slice(0, 10);
                  return (
                    <tr key={r.id}>
                      <td>
                        {week} → {r.period_end.slice(0, 10)}
                      </td>
                      <td>{r.report_format.toUpperCase()}</td>
                      <td>{(r.size_bytes / 1024).toFixed(1)} KB</td>
                      <td>
                        <button
                          type="button"
                          className="preset-btn"
                          onClick={() => void handleGeneratedDownload(r.id, `weekly_report_${week}.${r.report_format}`)}
                        >
                          Download
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )
        }
      </QueryState>
    </div>
  );
}
