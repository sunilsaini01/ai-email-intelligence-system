import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface SimpleLineChartProps {
  data: Record<string, unknown>[];
  xKey: string;
  yKey: string;
  color?: string;
}

// See SimpleBarChart.tsx's docstring for why `data` is typed
// Record<string, unknown>[] rather than a generic keyof-constrained type.
export function SimpleLineChart({ data, xKey, yKey, color = "#3f6fd6" }: SimpleLineChartProps) {
  if (data.length === 0) {
    return <div className="chart-empty">No data in this range.</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
        <XAxis dataKey={xKey} tick={{ fontSize: 11 }} interval="preserveStartEnd" />
        <YAxis allowDecimals={false} />
        <Tooltip />
        <Line type="monotone" dataKey={yKey} stroke={color} strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
