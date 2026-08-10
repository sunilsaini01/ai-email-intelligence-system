// Mirrors backend/app/schemas/dashboard.py exactly -- one field added or
// renamed on either side without the other is a real bug, not a typo, so
// keep these in sync deliberately when the backend schema changes.

export interface EvidenceBadge {
  status: "REAL_VALIDATED" | "SYNTHETIC" | "OFF_DOMAIN" | "UNVALIDATED" | "PROVISIONAL";
  note: string;
}

export interface OverviewResponse {
  total_emails_proxy: number;
  emails_per_day_avg: number;
  spam_rate: number | null;
  high_critical_priority_count: number;
  sla_breach_count: number;
  pending_human_reviews: number;
  feedback_correction_rate: number | null;
  reviewed_feedback_count: number;
  auto_reply_acceptance_rate: number | null;
  auto_reply_reviewed_count: number;
  date_range_start: string;
  date_range_end: string;
  note: string;
}

export interface VolumePoint {
  bucket: string;
  count: number;
}

export interface EmailVolumeResponse {
  granularity: "hour" | "day";
  points: VolumePoint[];
  total: number;
  note: string;
}

export interface CategoryCount {
  category: string;
  count: number;
}

export interface CategoryDistributionResponse {
  counts: CategoryCount[];
  evidence: EvidenceBadge;
}

export interface SentimentPoint {
  bucket: string;
  sentiment: string;
  count: number;
}

export interface SentimentTrendResponse {
  points: SentimentPoint[];
  evidence: EvidenceBadge;
}

export interface PriorityCount {
  priority: string;
  count: number;
}

export interface PriorityDistributionResponse {
  counts: PriorityCount[];
  evidence: EvidenceBadge;
}

export interface SLABucket {
  priority: string;
  within_sla: number;
  at_risk: number;
  breached: number;
}

export interface SLAResponse {
  buckets: SLABucket[];
  excluded_no_priority: number;
  sla_targets_hours: Record<string, number>;
  note: string;
}

export interface AgentWorkload {
  reviewer_id: string;
  assigned: number;
  pending: number;
  resolved: number;
  avg_resolution_minutes: number | null;
}

export interface AgentWorkloadResponse {
  agents: AgentWorkload[];
  note: string;
}

export interface ModelQualityEntry {
  module: string;
  evidence: EvidenceBadge;
  offline_reference_metric: string | null;
  correction_rate: number | null;
  reviewed_count: number;
  corrected_count: number;
  retraining_threshold_reached: boolean;
}

export interface ModelQualityResponse {
  modules: ModelQualityEntry[];
}

export interface ReviewQueueItem {
  prediction_id: string;
  module: string;
  subject: string;
  confidence: number;
  predicted_value: unknown;
  urgency_score: number;
  created_at: string;
  evidence: EvidenceBadge;
}

export interface ReviewQueueResponse {
  items: ReviewQueueItem[];
  note: string;
}

export interface ReviewQueueConfirmRequest {
  module: string;
  subject?: string;
  body?: string;
  predicted_value?: unknown;
  confidence?: number | null;
  reviewer_id?: string | null;
}

export interface ReviewQueueConfirmResponse {
  status: string;
  feedback_id: string;
}

export type DateRangeName = "today" | "week" | "month" | "custom";

export interface DateRangeParams {
  range: DateRangeName;
  start?: string;
  end?: string;
}
