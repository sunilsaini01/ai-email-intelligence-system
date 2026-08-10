import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useSentiment } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { SimpleBarChart } from "../charts/SimpleBarChart";

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
    </div>
  );
}
