import { apiGet, apiGetBlob, apiPost } from "./client";
import type {
  AgentWorkloadResponse,
  CategoryDistributionResponse,
  DateRangeParams,
  EmailVolumeResponse,
  ModelQualityResponse,
  OverviewResponse,
  PriorityDistributionResponse,
  ReviewQueueConfirmRequest,
  ReviewQueueConfirmResponse,
  ReviewQueueResponse,
  SentimentTrendResponse,
  SLAResponse,
} from "../types/dashboard";

function rangeParams(range: DateRangeParams): Record<string, string | undefined> {
  return { range: range.range, start: range.start, end: range.end };
}

export const dashboardApi = {
  overview: (range: DateRangeParams, organizationId: string) =>
    apiGet<OverviewResponse>("/dashboard/overview", { ...rangeParams(range), organization_id: organizationId }),

  emailVolume: (range: DateRangeParams, organizationId: string, granularity: "hour" | "day") =>
    apiGet<EmailVolumeResponse>("/dashboard/email-volume", {
      ...rangeParams(range),
      organization_id: organizationId,
      granularity,
    }),

  categories: (range: DateRangeParams, organizationId: string) =>
    apiGet<CategoryDistributionResponse>("/dashboard/categories", { ...rangeParams(range), organization_id: organizationId }),

  sentiment: (range: DateRangeParams, organizationId: string) =>
    apiGet<SentimentTrendResponse>("/dashboard/sentiment", { ...rangeParams(range), organization_id: organizationId }),

  priority: (range: DateRangeParams, organizationId: string) =>
    apiGet<PriorityDistributionResponse>("/dashboard/priority", { ...rangeParams(range), organization_id: organizationId }),

  sla: (range: DateRangeParams, organizationId: string) =>
    apiGet<SLAResponse>("/dashboard/sla", { ...rangeParams(range), organization_id: organizationId }),

  agents: (range: DateRangeParams, organizationId: string) =>
    apiGet<AgentWorkloadResponse>("/dashboard/agents", { ...rangeParams(range), organization_id: organizationId }),

  models: (range: DateRangeParams, organizationId: string) =>
    apiGet<ModelQualityResponse>("/dashboard/models", { ...rangeParams(range), organization_id: organizationId }),

  reviewQueue: (organizationId: string, limit = 100) =>
    apiGet<ReviewQueueResponse>("/dashboard/review-queue", { organization_id: organizationId, limit }),

  confirmReviewItem: (predictionId: string, body: ReviewQueueConfirmRequest, organizationId: string) =>
    apiPost<ReviewQueueConfirmResponse>(
      `/dashboard/review-queue/${predictionId}/confirm?organization_id=${encodeURIComponent(organizationId)}`,
      body,
    ),

  exportReport: (range: DateRangeParams, organizationId: string, format: "csv" | "pdf") =>
    apiGetBlob("/dashboard/reports/export", {
      range: range.range,
      ...(range.start ? { start: range.start } : {}),
      ...(range.end ? { end: range.end } : {}),
      organization_id: organizationId,
      format,
    }),
};
