// Phase 22 admin / notifications / model-ops / FR-32 contracts -- mirror
// backend app/schemas/admin.py.

export const USER_ROLES = ["agent", "manager", "admin"] as const;
export type UserRole = (typeof USER_ROLES)[number];

export const ASSIGNMENT_STRATEGIES = ["none", "round_robin", "skills"] as const;
export type AssignmentStrategy = (typeof ASSIGNMENT_STRATEGIES)[number];

export interface OrganizationSettings {
  notification_webhook_url: string | null;
  notify_on_critical: boolean;
  notify_on_sla_at_risk: boolean;
  category_taxonomy: Record<string, { display_name: string | null; enabled: boolean }>;
  assignment_strategy: AssignmentStrategy;
  routing_thresholds: Record<string, number>;
  data_retention_days: number | null;
  weekly_reports_enabled: boolean;
}

export interface OrganizationSettingsUpdate {
  notification_webhook_url?: string | null;
  notify_on_critical?: boolean;
  notify_on_sla_at_risk?: boolean;
  assignment_strategy?: AssignmentStrategy;
  data_retention_days?: number | null;
  weekly_reports_enabled?: boolean;
  clear_webhook?: boolean;
  clear_retention?: boolean;
}

export interface CategoryTaxonomyEntry {
  label: string;
  display_name: string;
  enabled: boolean;
  can_disable: boolean;
}

export interface CategoryTaxonomyResponse {
  categories: CategoryTaxonomyEntry[];
  note: string;
}

export interface AdminUser {
  id: string;
  email: string;
  role: UserRole;
  department: string | null;
  skills: string[];
  is_active: boolean;
  membership_source: "organization_creator" | "invitation" | "admin_verified" | "legacy_unverified";
  last_assigned_at: string | null;
  created_at: string;
}

export interface AdminUserUpdate {
  role?: UserRole;
  department?: string;
  skills?: string[];
  is_active?: boolean;
  clear_department?: boolean;
  confirm_membership?: boolean;
}

export interface Invitation {
  id: string;
  email: string;
  role: UserRole;
  status: "pending" | "accepted" | "expired" | "revoked";
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
}

export interface CreatedInvitation extends Invitation {
  token: string;
  accept_path: string;
}

export interface AppNotification {
  id: string;
  kind: string;
  severity: "critical" | "warning" | "info";
  title: string;
  message: string;
  email_id: string | null;
  is_read: boolean;
  webhook_status: string;
  created_at: string;
}

export interface NotificationListResponse {
  notifications: AppNotification[];
  unread_count: number;
}

export interface RetrainingTrigger {
  id: string;
  module: string;
  status: string;
  source: string;
  feedback_count_at_trigger: number;
  triggered_at: string;
  completed_at: string | null;
  result_message: string | null;
}

export interface DriftModule {
  module: string;
  psi: number | null;
  prediction_status: string;
  baseline_count: number;
  current_count: number;
  baseline_correction_rate: number | null;
  current_correction_rate: number | null;
  performance_drift: boolean;
  alert: boolean;
}

export interface DriftResponse {
  modules: DriftModule[];
  current_window_days: number;
  baseline_window_days: number;
  note: string;
}

export interface GeneratedReport {
  id: string;
  period_start: string;
  period_end: string;
  report_format: "csv" | "pdf";
  size_bytes: number;
  created_at: string;
}

export interface SenderSentimentTrend {
  sender_email: string;
  email_count: number;
  negative_count: number;
  average_score: number;
  recent_average_score: number;
  trend: "improving" | "stable" | "declining";
  escalation_candidate: boolean;
}
