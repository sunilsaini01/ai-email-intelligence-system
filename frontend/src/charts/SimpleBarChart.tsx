import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface SimpleBarChartProps {
  data: Record<string, unknown>[];
  xKey: string;
  yKey: string;
  color?: string;
}

// `data` is intentionally typed as the permissive Record<string, unknown>[]
// (not a generic keyof-constrained type) -- recharts v3's own strict
// TypedDataKey inference resolves to plain `string | number` dataKeys for
// this shape (Record<string, unknown>'s keyof IS string), which is exactly
// the permissiveness a small, reused chart wrapper needs. Callers passing a
// concrete interface (e.g. CategoryCount[]) cast explicitly at the call
// site -- see pages/CategoriesPage.tsx.
export function SimpleBarChart({ data, xKey, yKey, color = "#3f6fd6" }: SimpleBarChartProps) {
  if (data.length === 0) {
    return <div className="chart-empty">No data in this range.</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
        <XAxis dataKey={xKey} tick={{ fontSize: 11 }} interval="preserveStartEnd" />
        <YAxis allowDecimals={false} />
        <Tooltip />
        <Bar dataKey={yKey} fill={color} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
