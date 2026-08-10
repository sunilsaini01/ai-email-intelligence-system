import { useDashboardFilters } from "../hooks/useDashboardFilters";
import type { DateRangeName } from "../types/dashboard";

const OPTIONS: { value: DateRangeName; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "week", label: "This Week" },
  { value: "month", label: "This Month" },
  { value: "custom", label: "Custom" },
];

export function DateRangePicker() {
  const { range, setRangeName, setCustomRange, organizationId, setOrganizationId, reviewerId, setReviewerId } =
    useDashboardFilters();

  return (
    <div className="date-range-picker">
      <div className="date-range-picker__presets">
        {OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={range.range === opt.value ? "preset-btn preset-btn--active" : "preset-btn"}
            onClick={() => setRangeName(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {range.range === "custom" && (
        <div className="date-range-picker__custom">
          <input
            type="datetime-local"
            value={range.start?.slice(0, 16) ?? ""}
            onChange={(e) => setCustomRange(new Date(e.target.value).toISOString(), range.end ?? new Date().toISOString())}
          />
          <span>to</span>
          <input
            type="datetime-local"
            value={range.end?.slice(0, 16) ?? ""}
            onChange={(e) => setCustomRange(range.start ?? new Date().toISOString(), new Date(e.target.value).toISOString())}
          />
        </div>
      )}

      <label className="filter-field">
        Org
        <input value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} size={10} />
      </label>
      <label className="filter-field">
        Reviewer
        <input
          value={reviewerId}
          onChange={(e) => setReviewerId(e.target.value)}
          placeholder="unauthenticated"
          size={12}
        />
      </label>
    </div>
  );
}
