import { API_BASE_URL, ApiError, apiGet, apiGetBlob, apiPatch, apiPost, apiPut, getAuthToken } from "./client";
import type {
  AdminUser,
  AdminUserUpdate,
  CategoryTaxonomyResponse,
  CreatedInvitation,
  Invitation,
  DriftResponse,
  GeneratedReport,
  NotificationListResponse,
  OrganizationSettings,
  OrganizationSettingsUpdate,
  RetrainingTrigger,
  SenderSentimentTrend,
} from "../types/admin";

export const adminApi = {
  settings: () => apiGet<OrganizationSettings>("/admin/settings"),
  updateSettings: (update: OrganizationSettingsUpdate) => apiPut<OrganizationSettings>("/admin/settings", update),
  taxonomy: () => apiGet<CategoryTaxonomyResponse>("/admin/category-taxonomy"),
  updateTaxonomy: (categories: { label: string; display_name: string | null; enabled: boolean }[]) =>
    apiPut<CategoryTaxonomyResponse>("/admin/category-taxonomy", { categories }),
  users: () => apiGet<{ users: AdminUser[] }>("/admin/users"),
  updateUser: (id: string, update: AdminUserUpdate) => apiPatch<AdminUser>(`/admin/users/${id}`, update),
  invitations: () => apiGet<{ invitations: Invitation[] }>("/admin/invitations"),
  createInvitation: (email: string, role: string) =>
    apiPost<CreatedInvitation>("/admin/invitations", { email, role }),
  revokeInvitation: async (id: string) => {
    const token = getAuthToken();
    const response = await fetch(`${API_BASE_URL}/admin/invitations/${id}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new ApiError(response.status, await response.text());
  },
  eraseSubject: (senderEmail: string) =>
    apiPost<{ status: string; deleted: Record<string, number> }>("/admin/privacy/erase", {
      sender_email: senderEmail,
      confirm: true,
    }),
};

export const notificationsApi = {
  list: () => apiGet<NotificationListResponse>("/notifications", { limit: 30 }),
  markAllRead: () => apiPost<{ updated: number }>("/notifications/read", {}),
};

export const modelsApi = {
  retraining: () => apiGet<{ triggers: RetrainingTrigger[] }>("/models/retraining"),
  retrain: (module: string) => apiPost<RetrainingTrigger>("/models/retrain", { module }),
  drift: () => apiGet<DriftResponse>("/models/drift"),
};

export const insightsApi = {
  generatedReports: () => apiGet<{ reports: GeneratedReport[] }>("/dashboard/reports/generated"),
  downloadGeneratedReport: (id: string) => apiGetBlob(`/dashboard/reports/generated/${id}`),
  senderTrends: () => apiGet<{ senders: SenderSentimentTrend[]; window_days: number }>("/dashboard/sentiment/senders"),
};
