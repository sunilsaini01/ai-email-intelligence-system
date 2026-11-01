import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useSentiment } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { SimpleBarChart } from "../charts/SimpleBarChart";
import { useSenderTrends } from "../hooks/useAdmin";

// FR-32: per-sender trends, escalation candidates first.
function SenderTrends() {
  const query = useSenderTrends();
  return (
    <section className="admin-section">
      <h3>Sender sentiment trends (FR-32)</h3>
      <QueryState query={query}>
        {(data) =>
          data.senders.length === 0 ? (
            <div className="state-message">Not enough repeat senders in the last {data.window_days} days yet.</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Sender</th>
                  <th>Emails</th>
                  <th>Negative</th>
                  <th>Recent avg (−2…+2)</th>
                  <th>Trend</th>
                  <th>Escalate?</th>
                </tr>
              </thead>
              <tbody>
                {data.senders.map((s) => (
                  <tr key={s.sender_email}>
                    <td>{s.sender_email}</td>
                    <td>{s.email_count}</td>
                    <td>{s.negative_count}</td>
                    <td>{s.recent_average_score.toFixed(2)}</td>
                    <td>{s.trend}</td>
                    <td>{s.escalation_candidate ? "⚠ yes" : "—"}</td>
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

export function SentimentPage() {
  const { range, organizationId } = useDashboardFilters();
  const query = useSentiment(range, organizationId);

  return (
    <div>
      <h2>Sentiment Trend</h2>
      <QueryState query={query}>
        {(data) => {
          const totals = new Map<string, number>();
          for (const point of data.points) {
            totals.set(point.sentiment, (totals.get(point.sentiment) ?? 0) + point.count);
          }
          const chartData = Array.from(totals.entries()).map(([sentiment, count]) => ({ sentiment, count }));

          return (
            <>
              <div className="page-note">
                <EvidenceBadge evidence={data.evidence} /> <span>{data.evidence.note}</span>
              </div>
              <p className="page-note">Totals by sentiment across the selected range ({data.points.length} day-buckets).</p>
              <SimpleBarChart data={chartData as unknown as Record<string, unknown>[]} xKey="sentiment" yKey="count" color="#7a1fa0" />
            </>
          );
        }}
      </QueryState>
      <SenderTrends />
    </div>
  );
}
