"use client";

import { METRIC_LABEL, formatMetric, type MetricKey, type TrendPoint } from "@/lib/cmoPerformance";

/** One small line chart per metric (no shared or dual axis). A day without a value is a GAP in the line, never zero. The same numbers are available as a table under each chart, so nothing is
 * conveyed by the line alone. No animation. */

const W = 260;
const H = 64;
const PAD = 4;

function Spark({ k, points }: { k: MetricKey; points: TrendPoint[] }) {
  const vals = points.map((p) => p[k]);
  const known = vals.filter((v): v is number => v !== null);
  if (known.length < 2) {
    return (
      <p className="m-0 t-meta" style={{ color: "var(--text-4)" }} data-testid={`trend-${k}-none`}>
        {METRIC_LABEL[k]}: not enough days with a value to draw a trend ({known.length} of {points.length}).
      </p>
    );
  }
  const lo = Math.min(...known);
  const hi = Math.max(...known);
  const x = (i: number) => PAD + (points.length === 1 ? 0 : Math.floor(((W - 2 * PAD) * i) / (points.length - 1)));
  const y = (v: number) => (hi === lo ? Math.floor(H / 2) : PAD + Math.floor(((H - 2 * PAD) * (hi - v)) / (hi - lo)));
  const runs: string[] = [];
  let cur: string[] = [];
  vals.forEach((v, i) => {
    if (v === null) {
      if (cur.length) runs.push(cur.join(" "));
      cur = [];
    } else cur.push(`${x(i)},${y(v)}`);
  });
  if (cur.length) runs.push(cur.join(" "));
  const first = points[0].date;
  const last = points[points.length - 1].date;
  return (
    <figure className="m-0 flex flex-col gap-1" data-testid={`trend-${k}`}>
      <figcaption className="t-meta font-bold" style={{ color: "var(--text-2)" }}>{METRIC_LABEL[k]}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={`${METRIC_LABEL[k]} by day, ${first} to ${last}. Lowest ${formatMetric(k, lo)}, highest ${formatMetric(k, hi)}.`}>
        {runs.map((r) => (r.includes(" ") ? <polyline key={r} points={r} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" /> : <circle key={r} cx={r.split(",")[0]} cy={r.split(",")[1]} r="2.5" fill="var(--accent)" />))}
      </svg>
      <div className="flex justify-between t-meta" style={{ color: "var(--text-4)" }}>
        <span>{first}</span>
        <span>{formatMetric(k, lo)} – {formatMetric(k, hi)}</span>
        <span>{last}</span>
      </div>
    </figure>
  );
}

export function TrendCharts({ points, keys }: { points: TrendPoint[]; keys: MetricKey[] }) {
  if (!points.length) return <p className="m-0 t-body-sm" style={{ color: "var(--text-3)" }} data-testid="trend-empty">No imported days fall in this period, so there is no trend to draw.</p>;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>{keys.map((k) => <Spark key={k} k={k} points={points} />)}</div>
      <details>
        <summary className="mt-focus t-meta font-bold" style={{ color: "var(--text-3)", cursor: "pointer" }}>Show the daily numbers as a table</summary>
        <div style={{ overflowX: "auto" }}>
          <table className="t-meta" style={{ borderCollapse: "collapse", minWidth: 480 }} data-testid="trend-table">
            <caption className="sr-only">Daily values from your imported reports. A dash means the report has no value for that day.</caption>
            <thead><tr><th scope="col" className="p-1 text-left">Day</th>{keys.map((k) => <th key={k} scope="col" className="p-1 text-right">{METRIC_LABEL[k]}</th>)}</tr></thead>
            <tbody>{points.map((p) => <tr key={p.date}><th scope="row" className="p-1 text-left font-normal">{p.date}</th>{keys.map((k) => <td key={k} className="p-1 text-right">{p[k] === null ? "—" : formatMetric(k, p[k] as number)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
