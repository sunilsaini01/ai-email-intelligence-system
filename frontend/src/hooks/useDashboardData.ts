import { useQuery } from "@tanstack/react-query";
import { dashboardApi } from "../api/dashboard";
import type { DateRangeParams } from "../types/dashboard";

// FR-54's "30-second refresh/fallback mechanism" -- every dashboard query
// polls on this interval regardless of WebSocket state (see
// hooks/useDashboardWebSocket.ts, which only makes updates arrive
// SOONER than this baseline, never replaces it).
const REFETCH_INTERVAL_MS = 30_000;

const rangeKey = (range: DateRangeParams) => [range.range, range.start ?? "", range.end ?? ""];

export function useOverview(range: DateRangeParams, organizationId: string) {
  return useQuery({
    queryKey: ["dashboard", "overview", organizationId, ...rangeKey(range)],
    queryFn: () => dashboardApi.overview(range, organizationId),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

export function useEmailVolume(range: DateRangeParams, organizationId: string, granularity: "hour" | "day") {
  return useQuery({
    queryKey: ["dashboard", "email-volume", organizationId, granularity, ...rangeKey(range)],
    queryFn: () => dashboardApi.emailVolume(range, organizationId, granularity),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

export function useCategories(range: DateRangeParams, organizationId: string) {
  return useQuery({
    queryKey: ["dashboard", "categories", organizationId, ...rangeKey(range)],
    queryFn: () => dashboardApi.categories(range, organizationId),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

export function useSentiment(range: DateRangeParams, organizationId: string) {
  return useQuery({
    queryKey: ["dashboard", "sentiment", organizationId, ...rangeKey(range)],
    queryFn: () => dashboardApi.sentiment(range, organizationId),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

export function usePriority(range: DateRangeParams, organizationId: string) {
  return useQuery({
    queryKey: ["dashboard", "priority", organizationId, ...rangeKey(range)],
    queryFn: () => dashboardApi.priority(range, organizationId),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

export function useSla(range: DateRangeParams, organizationId: string) {
  return useQuery({
    queryKey: ["dashboard", "sla", organizationId, ...rangeKey(range)],
    queryFn: () => dashboardApi.sla(range, organizationId),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

export function useAgents(range: DateRangeParams, organizationId: string) {
  return useQuery({
    queryKey: ["dashboard", "agents", organizationId, ...rangeKey(range)],
    queryFn: () => dashboardApi.agents(range, organizationId),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

export function useModelQuality(range: DateRangeParams, organizationId: string) {
  return useQuery({
    queryKey: ["dashboard", "models", organizationId, ...rangeKey(range)],
    queryFn: () => dashboardApi.models(range, organizationId),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

export function useReviewQueue(organizationId: string) {
  return useQuery({
    queryKey: ["dashboard", "review-queue", organizationId],
    queryFn: () => dashboardApi.reviewQueue(organizationId),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}
