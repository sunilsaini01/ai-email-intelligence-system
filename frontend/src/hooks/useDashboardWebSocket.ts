import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { dashboardSocket } from "../websocket/DashboardSocket";

/**
 * Mount once near the app root. On any server-pushed event, invalidates
 * every dashboard query so the next render refetches fresh data sooner
 * than the 30s polling fallback each query already has via
 * `refetchInterval` (see hooks/useDashboardData.ts) -- this hook is an
 * optimization layered on top of that baseline, not a replacement for it.
 */
export function useDashboardWebSocket(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    dashboardSocket.connect();
    const unsubscribe = dashboardSocket.subscribe(() => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    });
    return () => {
      unsubscribe();
      dashboardSocket.disconnect();
    };
  }, [queryClient]);
}
