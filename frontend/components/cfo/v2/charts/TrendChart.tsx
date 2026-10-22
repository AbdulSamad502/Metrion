"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CompletenessBadge } from "@/components/cfo/v2/trust/CompletenessBadge";
import type { Completeness } from "@/lib/cfoV2/types";

/** One chart point. `plot` is a position the server chose for the point (it is only used to place it); the figure the seller reads is `display`, the server's
 * own string. `plot: null` is a gap — an unavailable period is never drawn as zero. */
export type ChartPoint = { label: string; plot: number | null; display: string | null; status: Completeness };

/** A line chart with an equivalent table underneath (a chart is never the only carrier of a value) and a keyboard-reachable summary. Colours come from tokens. This
 * is the only place Recharts is imported (docs/specs/cfo-dashboard-implementation.md §7). */
export function TrendChart({ title, points, height = 220 }: { title: string; points: ChartPoint[]; height?: number }) {
  return (
    <figure className="flex flex-col gap-3" aria-label={title}>
      <figcaption className="t-label">{title}</figcaption>
      <div style={{ width: "100%", height }} role="img" aria-label={`${title}: ${points.length} periods, see the table below`}>
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border-subtle, rgba(255,255,255,0.08))" vertical={false} />
            <XAxis dataKey="label" stroke="var(--text-5)" tick={{ fontSize: 11 }} />
            <YAxis hide />
            <Tooltip formatter={(_v, _n, item) => (item.payload as ChartPoint).display ?? "Not available"} />
            <Line type="monotone" dataKey="plot" stroke="var(--accent)" strokeWidth={2} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <table className="t-meta">
        <caption className="sr-only">{title} as a table</caption>
        <thead>
          <tr>
            <th scope="col" className="text-left">
              Period
            </th>
            <th scope="col" className="text-left">
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.label}>
              <th scope="row" className="text-left font-normal">
                {p.label}
              </th>
              <td>
                {p.display === null || p.status === "UNAVAILABLE" ? (
                  <span aria-label="not available">—</span>
                ) : (
                  <span className="inline-flex items-center gap-1.5">
                    {p.display}
                    {p.status !== "COMPLETE" && <CompletenessBadge completeness={p.status} />}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
