import { useId, type ReactNode } from "react";

/** Drawing only. Every figure shown beside a chart is the backend's own string; the numbers passed in here size a slice or a point and are never displayed.
 *  Colours come from the --ov-c1…c7 tokens, so a new palette recolours every chart. */

export const CHART_TONES = ["var(--ov-c1)", "var(--ov-c2)", "var(--ov-c3)", "var(--ov-c4)", "var(--ov-c5)", "var(--ov-c6)", "var(--ov-c7)"] as const;
export const toneAt = (i: number) => CHART_TONES[i % CHART_TONES.length];

export type DonutPart = { key: string; label: string; share: number; color?: string };

/** A ring. `share` is 0..1 per part; the parts are drawn as given (they should already sum to about 1). The text alternative is `summary`. */
export function Donut({ parts, summary, size = 160, center }: { parts: DonutPart[]; summary: string; size?: number; center?: ReactNode }) {
  const r = 40;
  const c = 2 * Math.PI * r;
  const gap = parts.length > 1 ? 1.2 : 0;
  const sweep = `ov-sweep-${useId().replace(/:/g, "")}`;
  return (
    <div className="ov-donut" style={{ width: size, height: size }}>
      <svg viewBox="0 0 100 100" width={size} height={size} role="img" aria-label={summary}>
        <circle cx="50" cy="50" r={r} fill="none" stroke="var(--ov-track, var(--ov-soft))" strokeWidth="14" />
        <mask id={sweep} maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
          <circle className="ov-donut-sweep" cx="50" cy="50" r={r} fill="none" stroke="#fff" strokeWidth="16" pathLength={1} transform="rotate(-90 50 50)" />
        </mask>
        <g mask={`url(#${sweep})`}>
        {parts.filter((p) => p.share > 0).map((p, i, shown) => {
          const offset = shown.slice(0, i).reduce((sum, q) => sum + q.share * c, 0);
          const len = Math.max(0, p.share * c - gap);
          const el = (
            <circle
              key={p.key}
              cx="50" cy="50" r={r} fill="none" strokeWidth="14" strokeLinecap="butt"
              stroke={p.color ?? toneAt(i)}
              strokeDasharray={`${len} ${c - len}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 50 50)"
              style={{ ["--i" as string]: i }}
            />
          );
          return el;
        })}
        </g>
      </svg>
      {center && <div className="ov-donut-center">{center}</div>}
    </div>
  );
}

export type LinePoint = { key: string; label: string; y: number | null };

/** A line over ordered points. Points with no readable value (`y: null`) break the line; they are never drawn as zero. */
export function LineChart({ points, summary, height = 160 }: { points: LinePoint[]; summary: string; height?: number }) {
  const W = 320;
  const pad = 16;
  const ys = points.map((p) => p.y).filter((y): y is number => y !== null);
  if (points.length < 2 || ys.length < 2) return null;
  const lo = Math.min(...ys, 0);
  const hi = Math.max(...ys, 0);
  const span = hi - lo || 1;
  const x = (i: number) => pad + (i * (W - pad * 2)) / (points.length - 1);
  const y = (v: number) => pad + ((hi - v) / span) * (height - pad * 2);
  const runs: { x: number; y: number; key: string }[][] = [[]];
  points.forEach((p, i) => {
    if (p.y === null) runs.push([]);
    else runs[runs.length - 1].push({ x: x(i), y: y(p.y), key: p.key });
  });
  const lines = runs.filter((r) => r.length > 0);
  const zero = y(0);
  return (
    <svg className="ov-line" viewBox={`0 0 ${W} ${height}`} style={{ width: "100%", height: "auto", maxHeight: height * 1.6 }} role="img" aria-label={summary}>
      <line x1={pad} x2={W - pad} y1={zero} y2={zero} stroke="var(--ov-edge)" strokeWidth="1" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
      {lines.map((run, i) => {
        const d = run.map((p, j) => `${j === 0 ? "M" : "L"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
        const area = run.length > 1 ? `${d} L${run[run.length - 1].x.toFixed(1)} ${zero.toFixed(1)} L${run[0].x.toFixed(1)} ${zero.toFixed(1)} Z` : null;
        return (
          <g key={i}>
            {area && <path d={area} fill="var(--ov-brand-soft)" />}
            <path className="ov-line-path" d={d} fill="none" stroke="var(--ov-brand)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" pathLength={1} />
            {run.map((p) => <circle key={p.key} cx={p.x} cy={p.y} r="3.5" fill="var(--ov-card)" stroke="var(--ov-brand)" strokeWidth="2" vectorEffect="non-scaling-stroke" />)}
          </g>
        );
      })}
    </svg>
  );
}

export type BarRow = { key: string; label: string; value: string; size: number | null; negative?: boolean; color?: string };

/** Horizontal bars to compare a few figures side by side. `size` only sets the length; the written `value` is the backend's. A row with no readable size shows its words and no bar. */
export function Bars({ rows, summary }: { rows: BarRow[]; summary: string }) {
  const top = Math.max(1, ...rows.map((r) => Math.abs(r.size ?? 0)));
  return (
    <ul className="ov-bars" role="img" aria-label={summary}>
      {rows.map((r, i) => (
        <li key={r.key}>
          <span className="ov-bars-top"><span>{r.label}</span><b>{r.value}</b></span>
          {r.size !== null && (
            <span className="ov-bars-track" aria-hidden>
              <i style={{ width: `${Math.max(2, (Math.abs(r.size) / top) * 100)}%`, background: r.negative ? "var(--ov-bad)" : r.color ?? toneAt(i), ["--i" as string]: i }} />
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
