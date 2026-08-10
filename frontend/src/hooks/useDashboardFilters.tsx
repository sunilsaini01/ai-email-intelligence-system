import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { DateRangeName, DateRangeParams } from "../types/dashboard";

interface DashboardFiltersValue {
  range: DateRangeParams;
  setRangeName: (name: DateRangeName) => void;
  setCustomRange: (start: string, end: string) => void;
  organizationId: string;
  setOrganizationId: (id: string) => void;
  reviewerId: string;
  setReviewerId: (id: string) => void;
}

const DashboardFiltersContext = createContext<DashboardFiltersValue | null>(null);

export function DashboardFiltersProvider({ children }: { children: ReactNode }) {
  const [range, setRange] = useState<DateRangeParams>({ range: "today" });
  const [organizationId, setOrganizationId] = useState("default");
  // Caller-supplied, unauthenticated -- same trust model as every
  // reviewer_id in this codebase since Phase 10 (see
  // docs/dashboard_security.md). Not a login; just a label attached to
  // feedback/review actions this browser tab submits.
  const [reviewerId, setReviewerId] = useState("");

  const value = useMemo<DashboardFiltersValue>(
    () => ({
      range,
      setRangeName: (name) => setRange(name === "custom" ? { range: "custom", start: range.start, end: range.end } : { range: name }),
      setCustomRange: (start, end) => setRange({ range: "custom", start, end }),
      organizationId,
      setOrganizationId,
      reviewerId,
      setReviewerId,
    }),
    [range, organizationId, reviewerId],
  );

  return <DashboardFiltersContext.Provider value={value}>{children}</DashboardFiltersContext.Provider>;
}

export function useDashboardFilters(): DashboardFiltersValue {
  const ctx = useContext(DashboardFiltersContext);
  if (!ctx) throw new Error("useDashboardFilters must be used within DashboardFiltersProvider");
  return ctx;
}
