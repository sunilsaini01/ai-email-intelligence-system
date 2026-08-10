import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useReviewQueue } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { dashboardApi } from "../api/dashboard";
import type { ReviewQueueItem } from "../types/dashboard";

export function ReviewQueuePage() {
  const { organizationId, reviewerId } = useDashboardFilters();
  const query = useReviewQueue(organizationId);
  const queryClient = useQueryClient();

  const confirmMutation = useMutation({
    mutationFn: (item: ReviewQueueItem) =>
      dashboardApi.confirmReviewItem(
        item.prediction_id,
        {
          module: item.module,
          subject: item.subject,
          predicted_value: item.predicted_value,
          confidence: item.confidence,
          reviewer_id: reviewerId || null,
        },
        organizationId,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard", "review-queue"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard", "models"] });
    },
  });

  return (
    <div>
      <h2>Human Review Queue</h2>
      <p className="page-note">
        Low-confidence predictions, ranked by urgency (confidence &times; priority weight -- see
        docs/architecture_dashboard.md "Review Queue ranking"). Confirming a correct prediction here is what makes the
        Model Quality page's correction rate meaningful (it supplies the "reviewed, not corrected" half of that
        formula) -- to submit an actual CORRECTION instead, use the relevant module's own /feedback endpoint.
      </p>
      <QueryState query={query}>
        {(data) => (
          <>
            <p className="page-note">{data.note}</p>
            {data.items.length === 0 ? (
              <div className="state-message">Queue is empty -- nothing below the confidence threshold right now.</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Module</th>
                    <th>Subject</th>
                    <th>Predicted</th>
                    <th>Confidence</th>
                    <th>Urgency</th>
                    <th>Evidence</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={`${item.module}-${item.prediction_id}`}>
                      <td>{item.module}</td>
                      <td className="subject-cell">{item.subject || "(no subject)"}</td>
                      <td>{JSON.stringify(item.predicted_value)}</td>
                      <td>{item.confidence.toFixed(2)}</td>
                      <td>{item.urgency_score.toFixed(2)}</td>
                      <td>
                        <EvidenceBadge evidence={item.evidence} />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="preset-btn"
                          disabled={confirmMutation.isPending}
                          onClick={() => confirmMutation.mutate(item)}
                        >
                          Confirm correct
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </QueryState>
    </div>
  );
}
