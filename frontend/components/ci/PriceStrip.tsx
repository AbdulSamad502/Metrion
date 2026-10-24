"use client";

import { formatPaise } from "@/lib/piShowcase";

export type StripPoint = { id: string; label: string; paise: number };
export type StripBand = { q1: number; q3: number; low: number; high: number };

/** Where competitors' verified prices sit. Positions are a display scale only: every number written on it is the backend's, formatted by `formatPaise`. */
export function PriceStrip({ points, band }: { points: StripPoint[]; band: StripBand | null }) {
  const values = [...points.map((p) => p.paise), ...(band ? [band.q1, band.q3, band.low, band.high] : [])];
  if (values.length === 0) return null;
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const pad = lo === hi ? Math.max(1, Math.round(lo * 0.1)) : Math.round((hi - lo) * 0.08);
  lo -= pad;
  hi += pad;
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const sorted = [...points].sort((a, b) => a.paise - b.paise);
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  // Dots that would sit on top of each other go on a second lane, so every number stays readable.
  const lanes: number[] = [];
  let lastAt = -Infinity;
  let lastLane = 1;
  for (const p of sorted) {
    const at = (p.paise - lo) / (hi - lo);
    const lane = at - lastAt < 0.06 ? 1 - lastLane : 0;
    lanes.push(lane);
    lastAt = at;
    lastLane = lane;
  }
  const summary =
    `Verified competitor prices: ${sorted.map((p) => `${p.label} ${formatPaise(p.paise)}`).join(", ")}.` +
    (band ? ` Typical range ${formatPaise(band.low)} to ${formatPaise(band.high)}; the middle half is ${formatPaise(band.q1)} to ${formatPaise(band.q3)}.` : "");
  return (
    <figure className="ci-strip" data-testid="price-strip">
      <div className="ci-strip-plot" style={{ height: lanes.some(Boolean) ? 116 : 88 }} role="img" aria-label={summary}>
        <div className="ci-strip-track" />
        {band && <div className="ci-strip-band" style={{ left: pos(band.q1), width: `calc(${pos(band.q3)} - ${pos(band.q1)})` }} />}
        {band && (
          <>
            <div className="ci-strip-tick" style={{ left: pos(band.low) }}><span>Low</span></div>
            <div className="ci-strip-tick" style={{ left: pos(band.high) }}><span>High</span></div>
          </>
        )}
        {sorted.map((p, i) => (
          <div key={p.id} className="ci-strip-dot" style={{ left: pos(p.paise), top: 32 + lanes[i] * 28 }} aria-hidden>
            {points.indexOf(p) + 1}
          </div>
        ))}
      </div>
      <div className="ci-strip-axis" aria-hidden>
        <span>Lowest {formatPaise(dataMin)}</span>
        <span>Highest {formatPaise(dataMax)}</span>
      </div>
      <ol className="ci-legend" aria-label="Verified competitor prices" style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {points.map((p, i) => (
          <li key={p.id}><b aria-hidden>{i + 1}</b>{p.label} · {formatPaise(p.paise)}</li>
        ))}
      </ol>
    </figure>
  );
}
