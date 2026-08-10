import { useState } from "react";
import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useEmailVolume } from "../hooks/useDashboardData";
import { QueryState } from "../components/QueryState";
import { SimpleBarChart } from "../charts/SimpleBarChart";

export function EmailVolumePage() {
  const { range, organizationId } = useDashboardFilters();
  const [granularity, setGranularity] = useState<"hour" | "day">("day");
  const query = useEmailVolume(range, organizationId, granularity);

  return (
    <div>
      <h2>Email Volume</h2>
      <div className="toggle-row">
        <button className={granularity === "hour" ? "preset-btn preset-btn--active" : "preset-btn"} onClick={() => setGranularity("hour")}>
          Hourly
        </button>
        <button className={granularity === "day" ? "preset-btn preset-btn--active" : "preset-btn"} onClick={() => setGranularity("day")}>
          Daily
        </button>
      </div>
      <QueryState query={query}>
        {(data) => (
          <>
            <p className="page-note">
              {data.note} Total in range: {data.total}.
            </p>
            <SimpleBarChart data={data.points as unknown as Record<string, unknown>[]} xKey="bucket" yKey="count" />
          </>
        )}
      </QueryState>
    </div>
  );
}
