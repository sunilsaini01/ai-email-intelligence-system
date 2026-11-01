import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminApi, insightsApi, modelsApi, notificationsApi } from "../api/admin";
import type { AdminUserUpdate, OrganizationSettingsUpdate, UserRole } from "../types/admin";
import { USER_ROLES } from "../types/admin";
import { useAuth } from "./useAuth";

// Same 30s cadence as every other dashboard query (FR-54) -- notifications
// are written by the agents process, which has no WebSocket of its own.
const POLL_MS = 30_000;

// PRD SS6.4 RBAC: agent < manager < admin. The backend enforces this on
// every endpoint; the UI only uses it to avoid showing controls that
// would just come back 403.
export function useHasRole(minimum: UserRole): boolean {
  const { user } = useAuth();
  const rank = USER_ROLES.indexOf((user?.role ?? "") as UserRole);
  return rank >= USER_ROLES.indexOf(minimum);
}

export function useNotifications() {
  return useQuery({ queryKey: ["notifications"], queryFn: notificationsApi.list, refetchInterval: POLL_MS });
}

export function useMarkNotificationsRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: notificationsApi.markAllRead,
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function useOrganizationSettings(enabled: boolean) {
  return useQuery({ queryKey: ["admin", "settings"], queryFn: adminApi.settings, enabled });
}

export function useUpdateOrganizationSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (update: OrganizationSettingsUpdate) => adminApi.updateSettings(update),
    onSuccess: (data) => client.setQueryData(["admin", "settings"], data),
  });
}

export function useCategoryTaxonomy() {
  return useQuery({ queryKey: ["admin", "taxonomy"], queryFn: adminApi.taxonomy });
}

export function useUpdateCategoryTaxonomy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: adminApi.updateTaxonomy,
    onSuccess: (data) => client.setQueryData(["admin", "taxonomy"], data),
  });
}

export function useAdminUsers(enabled: boolean) {
  return useQuery({ queryKey: ["admin", "users"], queryFn: adminApi.users, enabled });
}

export function useUpdateAdminUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, update }: { id: string; update: AdminUserUpdate }) => adminApi.updateUser(id, update),
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}

export function useInvitations(enabled: boolean) {
  return useQuery({ queryKey: ["admin", "invitations"], queryFn: adminApi.invitations, enabled });
}

export function useCreateInvitation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ email, role }: { email: string; role: string }) => adminApi.createInvitation(email, role),
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin", "invitations"] }),
  });
}

export function useRevokeInvitation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: adminApi.revokeInvitation,
    onSuccess: () => client.invalidateQueries({ queryKey: ["admin", "invitations"] }),
  });
}

export function useEraseSubject() {
  return useMutation({ mutationFn: adminApi.eraseSubject });
}

export function useRetraining(enabled: boolean) {
  return useQuery({
    queryKey: ["models", "retraining"],
    queryFn: modelsApi.retraining,
    refetchInterval: POLL_MS,
    enabled,
  });
}

export function useRequestRetraining() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: modelsApi.retrain,
    onSuccess: () => client.invalidateQueries({ queryKey: ["models", "retraining"] }),
  });
}

export function useDrift(enabled: boolean) {
  return useQuery({ queryKey: ["models", "drift"], queryFn: modelsApi.drift, refetchInterval: 5 * POLL_MS, enabled });
}

export function useGeneratedReports(enabled: boolean) {
  return useQuery({ queryKey: ["reports", "generated"], queryFn: insightsApi.generatedReports, enabled });
}

export function useSenderTrends() {
  return useQuery({ queryKey: ["sentiment", "senders"], queryFn: insightsApi.senderTrends, refetchInterval: POLL_MS });
}
