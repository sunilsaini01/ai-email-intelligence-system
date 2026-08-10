import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useOverview } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";
import { KpiCard } from "../components/KpiCard";

function pct(value: number | null): string | null {
  return value === null ? null : `${(value * 100).toFixed(1)}%`;
}

export function OverviewPage() {
  const { range, organizationId } = useDashboardFilters();
  const query = useOverview(range, organizationId);

  return (
    <div>
      <h2>Executive Overview</h2>
      <QueryState query={query}>
        {(data) => (
          <>
            <p className="page-note">{data.note}</p>
            <div className="kpi-grid">
              <KpiCard label="Total Emails (proxy)" value={data.total_emails_proxy} />
              <KpiCard label="Emails / Day (avg)" value={data.emails_per_day_avg} />
              <KpiCard label="Spam Rate" value={pct(data.spam_rate)} />
              <KpiCard label="High/Critical Priority" value={data.high_critical_priority_count} />
              <KpiCard label="SLA Breaches" value={data.sla_breach_count} />
              <KpiCard label="Pending Human Reviews" value={data.pending_human_reviews} />
              <KpiCard
                label="Feedback Correction Rate"
                value={pct(data.feedback_correction_rate)}
                hint={`${data.reviewed_feedback_count} reviewed`}
              />
              <KpiCard
                label="Auto-Reply Acceptance Rate"
                value={pct(data.auto_reply_acceptance_rate)}
                hint={`${data.auto_reply_reviewed_count} reviewed`}
              />
            </div>
          </>
        )}
      </QueryState>
    </div>
  );
}
