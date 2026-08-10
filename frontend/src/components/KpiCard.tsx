interface KpiCardProps {
  label: string;
  value: string | number | null;
  fallbackText?: string;
  hint?: string;
}

// Renders `fallbackText` (default "No real observations yet") when value
// is null -- the master prompt's own explicit instruction: never render
// a null/undefined metric as 0%, since zero observations is not the
// same claim as a measured 0% rate.
export function KpiCard({ label, value, fallbackText = "No real observations yet", hint }: KpiCardProps) {
  const isMissing = value === null || value === undefined;
  return (
    <div className="kpi-card">
      <div className="kpi-label">{label}</div>
      <div className={isMissing ? "kpi-value kpi-value--missing" : "kpi-value"}>{isMissing ? fallbackText : value}</div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  );
}
