import { useState } from "react";
import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { dashboardApi } from "../api/dashboard";

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

  return (
    <div>
      <h2>Reports</h2>
      <p className="page-note">
        On-demand export for the selected date range -- CSV and PDF cover the same overview, volume, category,
        sentiment, priority, SLA, agent-workload, and model-quality sections shown elsewhere in this dashboard, each
        with the same evidence labeling. "Auto-generated weekly" (FR-56) is on-demand this phase, not a scheduled
        job -- no scheduler/cron dependency exists in this codebase yet; see
        docs/requirements_traceability_phase11.md.
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
    </div>
  );
}
