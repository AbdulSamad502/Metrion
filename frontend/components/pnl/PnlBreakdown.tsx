"use client";

import { Section } from "@/components/ui/Section";
import { formatBps, formatPaise } from "@/lib/pnlText";
import type { PnlBreakdown, PnlLineShare } from "@/lib/pnlScenario";

/** Slice colours. They only tell slices apart; they carry no meaning (the label and percentage are always written beside each one). Profit is the accent. */
const PALETTE = ["#5BA8FF", "#E7AC42", "#A78BFA", "#F16B61", "#2DD4BF", "#F472B6", "#94A3B8", "#C084FC"] as const;
const PROFIT = "var(--accent)";

const colourOf = (id: string, index: number): string => (id === "profit" ? PROFIT : PALETTE[index % PALETTE.length]);
const isZero = (l: PnlLineShare): boolean => l.amount === "0" && l.shareBps === "0";
const negative = (v: string): boolean => v.startsWith("-");

/** "Where each rupee goes": a donut and a ranked bar list. Every percentage, amount and slice position here was computed by the engine; this component
 * only draws them (CSS stops take the server's positions as text, so there is no arithmetic in the browser). */
export function WhereEachRupeeGoes({ breakdown, marginBps, beforeMissing }: { breakdown: PnlBreakdown; marginBps: string | null; beforeMissing: boolean }) {
  const segments = breakdown.segments;
  // Position of each colour in the palette = its position among the costs, so legend, bars and donut agree.
  const costs = breakdown.lines.filter((l) => !isZero(l));
  const colourFor = (id: string): string => colourOf(id, costs.findIndex((l) => l.id === id));
  const gradient = segments?.map((g) => `${colourFor(g.id)} ${formatBps(g.startBps)} ${formatBps(g.endBps)}`).join(", ");
  const profitLabel = marginBps !== null ? formatBps(marginBps) : formatBps(breakdown.profitShareBps);

  return (
    <Section title="Where each ₹ of the sale goes" hint={beforeMissing ? "Before the costs listed as not entered. Shares are of revenue per order kept." : "Shares of revenue per order kept."} panel={false}>
      <div className="grid gap-5 rounded-2xl p-4 sm:grid-cols-[auto_minmax(0,1fr)]" style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }}>
        {segments ? (
          <div
            role="img"
            aria-label={`Donut chart. ${segments.map((g) => `${g.label} ${formatBps(g.shareBps)}`).join(", ")}.`}
            className="relative mx-auto h-44 w-44 flex-shrink-0 rounded-full"
            style={{ background: `conic-gradient(${gradient})` }}
            data-testid="donut"
          >
            <div className="absolute inset-[22%] flex flex-col items-center justify-center rounded-full text-center" style={{ background: "var(--bg-popover)" }}>
              <span className="t-label" style={{ color: "var(--text-5)" }}>Margin</span>
              <span className="t-headline font-semibold tabular-nums" style={{ color: PROFIT }}>{profitLabel}</span>
            </div>
          </div>
        ) : (
          <p className="max-w-[16rem] self-center t-body-sm" style={{ color: "var(--text-5)" }} data-testid="chart-unavailable">{breakdown.chartUnavailableReason}</p>
        )}

        <ul className="m-0 flex min-w-0 list-none flex-col gap-3 p-0">
          {costs.map((l) => (
            <li key={l.id}>
              <div className="flex items-baseline gap-2 t-body-sm">
                <span aria-hidden className="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-sm" style={{ background: colourFor(l.id) }} />
                <span className="min-w-0 flex-1" style={{ color: "var(--text-3)" }}>{l.label}</span>
                <span className="tabular-nums" style={{ color: "var(--text-4)" }}>{formatPaise(l.amount)} · {formatBps(l.shareBps)}</span>
              </div>
              {!negative(l.shareBps) && (
                <div className="mt-1 h-1.5 overflow-hidden rounded-full" style={{ background: "var(--fill-hover)" }} aria-hidden>
                  <div className="h-full rounded-full" style={{ width: formatBps(l.shareBps), background: colourFor(l.id) }} />
                </div>
              )}
            </li>
          ))}
          <li>
            <div className="flex items-baseline gap-2 t-body-sm font-semibold">
              <span aria-hidden className="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-sm" style={{ background: PROFIT }} />
              <span className="min-w-0 flex-1" style={{ color: "var(--text-2)" }}>Left as profit</span>
              <span className="tabular-nums" style={{ color: negative(breakdown.profitShareBps) ? "var(--negative)" : PROFIT }}>{formatBps(breakdown.profitShareBps)}</span>
            </div>
            {!negative(breakdown.profitShareBps) && (
              <div className="mt-1 h-1.5 overflow-hidden rounded-full" style={{ background: "var(--fill-hover)" }} aria-hidden>
                <div className="h-full rounded-full" style={{ width: formatBps(breakdown.profitShareBps), background: PROFIT }} />
              </div>
            )}
          </li>
        </ul>
      </div>
    </Section>
  );
}

const RANKS = ["1", "2", "3"] as const;

/** The three biggest costs, ranked by the engine, each as a share of revenue. */
export function WhatIsKillingYourMargin({ costs, beforeMissing }: { costs: PnlLineShare[]; beforeMissing: boolean }) {
  if (costs.length === 0) return null;
  return (
    <Section title="What's killing your margin?" hint={`Your biggest costs per order kept, as a share of revenue${beforeMissing ? ", before the costs not entered" : ""}.`} panel={false}>
      <ol className="m-0 flex list-none flex-col gap-2 p-0">
        {costs.map((c, i) => (
          <li key={c.id} className="flex items-center gap-3 rounded-xl px-4 py-3" style={{ border: "1px solid var(--border-default)", background: "var(--bg-card)" }}>
            <span aria-hidden className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full t-body-sm font-bold" style={{ background: "var(--accent-fill-default)", color: PROFIT }}>{RANKS[i]}</span>
            <span className="min-w-0 flex-1 t-body-sm font-medium" style={{ color: "var(--text-2)" }}><span className="sr-only">Number {RANKS[i]}: </span>{c.label}</span>
            <span className="tabular-nums t-body-sm" style={{ color: "var(--text-4)" }}>{formatPaise(c.amount)}</span>
            <span className="w-16 text-right tabular-nums t-body-sm font-semibold" style={{ color: "var(--text-1)" }}>{formatBps(c.shareBps)}</span>
          </li>
        ))}
      </ol>
    </Section>
  );
}
