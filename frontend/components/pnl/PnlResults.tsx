"use client";

import { useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { MetricCard } from "@/components/ui/MetricCard";
import { Section } from "@/components/ui/Section";
import { WhatIsKillingYourMargin, WhereEachRupeeGoes } from "@/components/pnl/PnlBreakdown";
import { StatusBadge, type Tone } from "@/components/ui/StatusBadge";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { formatBps, formatPaise, formatRoas } from "@/lib/pnlText";
import type { PnlScenarioResponse, PnlSolution, PnlStatus, PnlView } from "@/lib/pnlScenario";

const STATUS: Record<PnlStatus, { tone: Tone; label: string; detail: string }> = {
  incomplete: { tone: "negative", label: "Incomplete", detail: "Not enough information for a profit figure yet. Nothing below is guessed." },
  provisional: { tone: "warning", label: "Provisional", detail: "Profit before the costs listed below. They were not entered, so they are left out, not counted as zero." },
  estimate: { tone: "info", label: "Estimate", detail: "Every cost that matters was entered or marked not applicable. Still a what-if, not your recorded results." },
};

/** The standing label that keeps this separate from verified results. It is on every state of the panel, including errors and stale results. */
export function EstimateBanner() {
  return (
    <div className="flex flex-col items-start gap-2 rounded-xl px-4 py-3 sm:flex-row sm:gap-3" style={{ background: "var(--info-fill)", border: "1px solid var(--info-border)" }} data-testid="estimate-banner">
      <StatusBadge tone="info" dot>Hypothetical estimate — not verified</StatusBadge>
      <p className="min-w-0 flex-1 t-body-sm" style={{ color: "var(--text-4)" }}>
        Worked out from the numbers you typed. It is not saved, is not part of your Profit &amp; Finance results, and never changes your records.
      </p>
    </div>
  );
}

/** The engine's assumptions that exist because the seller left an input blank. Any other assumption is a rule of the calculation (for example fees
 * applied to the GST-inclusive price), so an unknown code is shown as a rule, never wrongly described as a blank input. */
const BLANK_INPUT_ASSUMPTIONS: ReadonlySet<string> = new Set(["purchase_gst_default", "services_gst_default", "recovery_default", "refund_default"]);

const CARD = { background: "var(--bg-card)", border: "1px solid var(--border-subtle)" } as const;
const money = (v: string | null | undefined) => formatPaise(v);

/** The statement's blocks, in the order the public calculator shows them. A line whose group is not listed here still prints, after the blocks. */
const LEDGER_BLOCKS = [
  { title: "Cost of goods", groups: ["product", "stock_loss"] },
  { title: "Marketplace charges", groups: ["commission", "shipping", "fulfilment", "other_fee", "fee_gst", "fee_refund"] },
  { title: "Packaging and advertising", groups: ["packaging", "advertising"] },
] as const;
const KNOWN_GROUPS: ReadonlySet<string> = new Set(LEDGER_BLOCKS.flatMap((b) => b.groups));

function Ledger({ view, label }: { view: PnlView; label: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full t-body-sm" style={{ borderCollapse: "collapse" }}>
        <caption className="sr-only">{label}</caption>
        <thead>
          <tr style={{ color: "var(--text-6)", textAlign: "left" }}>
            <th scope="col" className="py-2 pr-4 font-medium">Line</th>
            <th scope="col" className="py-2 text-right font-medium">Amount</th>
          </tr>
        </thead>
        <tbody>
          <tr style={{ borderTop: "1px solid var(--border-subtle)" }}>
            <th scope="row" className="py-2 pr-4 text-left font-medium" style={{ color: "var(--text-3)" }}>Revenue (excluding output GST)</th>
            <td className="py-2 text-right tabular-nums" style={{ color: "var(--text-2)" }}>{money(view.revenue)}</td>
          </tr>
          {LEDGER_BLOCKS.map((block) => {
            const lines = view.lines.filter((l) => (block.groups as readonly string[]).includes(l.group));
            if (lines.length === 0) return null;
            return [
              <tr key={`h-${block.title}`} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                <th scope="colgroup" colSpan={2} className="px-2 py-1.5 text-left t-label" style={{ color: "var(--text-5)", background: "var(--fill-hover)" }}>{block.title}</th>
              </tr>,
              ...lines.map((l) => (
                <tr key={l.id}>
                  <th scope="row" className="py-1.5 pr-4 text-left font-normal" style={{ color: "var(--text-4)" }}>{l.label}</th>
                  <td className="py-1.5 text-right tabular-nums" style={{ color: l.amount.startsWith("-") ? "var(--accent)" : "var(--text-3)" }}>{money(l.amount)}</td>
                </tr>
              )),
            ];
          })}
          {view.lines.filter((l) => !KNOWN_GROUPS.has(l.group)).map((l) => (
            <tr key={l.id}>
              <th scope="row" className="py-1.5 pr-4 text-left font-normal" style={{ color: "var(--text-4)" }}>{l.label}</th>
              <td className="py-1.5 text-right tabular-nums" style={{ color: "var(--text-3)" }}>{money(l.amount)}</td>
            </tr>
          ))}
          <tr style={{ borderTop: "1px solid var(--border-default)" }}>
            <th scope="row" className="py-2 pr-4 text-left font-semibold" style={{ color: "var(--text-2)" }}>Contribution profit</th>
            <td className="py-2 text-right font-semibold tabular-nums" style={{ color: view.contribution.startsWith("-") ? "var(--negative)" : "var(--accent)" }}>{money(view.contribution)}</td>
          </tr>
          {view.operatingProfit != null && (
            <>
              <tr style={{ borderTop: "1px solid var(--border-subtle)" }}>
                <th scope="row" className="py-2 pr-4 text-left font-normal" style={{ color: "var(--text-4)" }}>Operating expenses</th>
                <td className="py-2 text-right tabular-nums" style={{ color: "var(--text-3)" }}>{money(view.operatingExpenses)}</td>
              </tr>
              <tr style={{ borderTop: "1px solid var(--border-default)" }}>
                <th scope="row" className="py-2 pr-4 text-left font-semibold" style={{ color: "var(--text-2)" }}>Operating profit</th>
                <td className="py-2 text-right font-semibold tabular-nums" style={{ color: view.operatingProfit.startsWith("-") ? "var(--negative)" : "var(--accent)" }}>{money(view.operatingProfit)}</td>
              </tr>
            </>
          )}
        </tbody>
      </table>
    </div>
  );
}

const SOLVE_UNAVAILABLE: Record<string, string> = {
  incomplete: "Fill in the required inputs first.",
  no_kept_orders: "No orders are kept at these return rates, so there is no price to solve for.",
  operating_unavailable: "Enter operating expenses to solve on operating profit.",
};

function Solution({ s, onUsePrice }: { s: PnlSolution; onUsePrice?: (paise: string) => void }) {
  const name = s.target.kind === "breakeven" ? "Break-even price" : `Price for a ${formatBps(s.target.bps)} margin`;
  let body: string;
  if (s.outcome === "price" && s.price) {
    body = `Lowest selling price: ${money(s.price)}`;
  } else if (s.outcome === "always") body = "Profit is not negative at any price with these costs and fees.";
  else if (s.outcome === "unreachable") body = s.reason ?? "No selling price reaches this target.";
  else body = SOLVE_UNAVAILABLE[s.reason ?? ""] ?? "Not available.";
  return (
    <li className="rounded-xl p-4" style={{ border: "1px solid var(--border-default)" }}>
      <div className="t-label" style={{ color: "var(--text-5)" }}>{name}</div>
      <div className="mt-1.5 t-headline font-semibold" style={{ color: s.outcome === "price" ? "var(--text-1)" : "var(--text-4)" }}>{body}</div>
      {s.outcome === "price" && s.ranges.length > 1 && (
        <p className="mt-2 t-meta" style={{ color: "var(--text-5)" }}>
          Fee bands make profit jump, so it works in these ranges: {s.ranges.map((r) => (r.to === null ? `${money(r.from)} and above` : r.from === r.to ? money(r.from) : `${money(r.from)} to ${money(r.to)}`)).join("; ")}.
        </p>
      )}
      {s.outcome === "price" && s.price && onUsePrice && (
        <button type="button" onClick={() => onUsePrice(s.price as string)} className="mt-btn mt-focus mt-3 min-h-10 rounded-lg px-3 t-body-sm font-semibold" style={{ border: "1px solid var(--accent-border-strong)", color: "var(--accent)" }}>
          Use this price
        </button>
      )}
      {s.excludesMissingCosts && (
        <p className="mt-2 t-meta" style={{ color: "var(--warning)" }}>This price leaves out the costs listed as not entered, so the real price is higher.</p>
      )}
    </li>
  );
}

const tone = (v: string) => (v.startsWith("-") ? "var(--negative)" : "var(--accent)");

/** The headline: contribution profit per order kept, its margin on revenue, and the two other ways to read the same profit. Every figure is the server's. */
function Hero({ result, beforeMissing }: { result: PnlScenarioResponse; beforeMissing?: string }) {
  const kept = result.perKept;
  const margin = result.metrics?.contributionMarginBps ?? null;
  const tile = (label: string, v: PnlView | null, note: string, unavailable: string) => (
    <div className="rounded-xl p-4" style={{ border: "1px solid var(--border-default)" }}>
      <div className="t-label" style={{ color: "var(--text-5)" }}>{label}</div>
      {v ? (
        <>
          <div className="mt-1.5 t-headline font-semibold tabular-nums" style={{ color: tone(v.contribution) }}>{money(v.contribution)}</div>
          <div className="mt-1 t-meta" style={{ color: "var(--text-5)" }}>{beforeMissing ?? note}</div>
        </>
      ) : (
        <>
          <div className="mt-1.5 t-headline font-semibold" style={{ color: "var(--text-6)" }}>Not available</div>
          <div className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{unavailable}</div>
        </>
      )}
    </div>
  );
  return (
    <div className="flex flex-col gap-3 rounded-2xl p-5" style={{ ...CARD, borderTop: `3px solid ${kept ? tone(kept.contribution) : "var(--border-default)"}` }}>
      <div className="t-label" style={{ color: "var(--text-5)" }}>Contribution profit per order kept</div>
      {kept ? (
        <>
          <div className="t-metric-lg tabular-nums" style={{ color: tone(kept.contribution) }}>{money(kept.contribution)}</div>
          <div className="t-body-sm" style={{ color: "var(--text-4)" }}>
            {margin !== null ? `${formatBps(margin)} margin on revenue of ${money(kept.revenue)}` : `Revenue ${money(kept.revenue)}`}
          </div>
          {beforeMissing && <div className="t-meta font-semibold" style={{ color: "var(--warning)" }}>{beforeMissing}</div>}
        </>
      ) : (
        <>
          <div className="t-headline font-semibold" style={{ color: "var(--text-6)" }}>Not available</div>
          <div className="t-meta" style={{ color: "var(--text-6)" }}>No orders are kept at these return rates.</div>
        </>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {tile("Monthly contribution profit", result.monthly, "Across all orders placed", "Enter orders per month to see monthly totals.")}
        {tile("Profit per order placed", result.perPlaced, "Includes losses on returns", "Not available.")}
      </div>
    </div>
  );
}

export function PnlResults({ result, stale, busy, onUsePrice }: { result: PnlScenarioResponse | null; stale: boolean; busy: boolean; onUsePrice?: (paise: string) => void }) {
  const [view, setView] = useState("kept");
  if (!result) {
    return (
      <div className="flex flex-col gap-4">
        <EstimateBanner />
        <EmptyState icon="finance" title={busy ? "Working it out…" : "No estimate yet"} description="Enter your price, cost and fees, then choose Calculate. Anything you leave blank is shown as missing, never counted as zero." />
      </div>
    );
  }
  const st = STATUS[result.status];
  const views: { id: string; label: string; v: PnlView | null }[] = [
    { id: "kept", label: "Per order kept", v: result.perKept },
    { id: "placed", label: "Per order placed", v: result.perPlaced },
    { id: "monthly", label: "Monthly", v: result.monthly },
  ];
  const tabs = views.filter((x) => x.v !== null).map((x) => ({ id: x.id, label: x.label }));
  const activeId = tabs.some((t) => t.id === view) ? view : (tabs[0]?.id ?? "kept");
  const m = result.metrics;
  const beforeMissing = result.status === "provisional" ? "Before missing costs" : undefined;
  const blocking = result.issues.filter((i) => i.severity === "blocking");
  const info = result.issues.filter((i) => i.severity === "info");
  const blankAssumptions = result.assumptions.filter((a) => BLANK_INPUT_ASSUMPTIONS.has(a.code));
  const ruleAssumptions = result.assumptions.filter((a) => !BLANK_INPUT_ASSUMPTIONS.has(a.code));

  return (
    <div className="flex flex-col gap-6" aria-busy={busy}>
      <EstimateBanner />
      {result.isExample && (
        <p role="note" className="m-0 rounded-xl px-4 py-2.5 t-body-sm" style={{ background: "var(--warning-fill)", border: "1px solid var(--warning-border)", color: "var(--warning)" }} data-testid="example-result-note">
          <strong>Example data — not real marketplace rates.</strong> These numbers are made up to show how the calculator works. Replace them with your own.
        </p>
      )}
      {stale && (
        <p role="status" className="rounded-xl px-4 py-2.5 t-body-sm" style={{ background: "var(--warning-fill)", border: "1px solid var(--warning-border)", color: "var(--warning)" }}>
          You changed an input after this was worked out. Choose Calculate to refresh it.
        </p>
      )}
      <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:gap-3">
        <StatusBadge tone={st.tone} dot>{st.label}</StatusBadge>
        <p className="min-w-0 flex-1 t-body-sm" style={{ color: "var(--text-4)" }}>{st.detail}</p>
      </div>
      {result.scopeNote && <p className="t-body-sm" style={{ color: "var(--text-5)" }}>{result.scopeNote}</p>}

      {blocking.length > 0 && (
        <ul className="flex flex-col gap-1.5" role="alert">
          {blocking.map((i) => <li key={i.code + (i.field ?? "")} className="t-body-sm" style={{ color: "var(--negative)" }}>{i.message}</li>)}
        </ul>
      )}
      {result.missingCosts.length > 0 && (
        <Section title="Not entered, so left out" hint={result.status === "incomplete" ? "These have not been entered. None of them is counted as zero." : "These are excluded from the profit below. They are not counted as zero."} panel={false}>
          <ul className="list-disc pl-5 t-body-sm" style={{ color: "var(--warning)" }}>
            {result.missingCosts.map((c) => <li key={c}>{c}</li>)}
          </ul>
        </Section>
      )}

      {result.perKept || result.perPlaced ? (
        <div className="grid gap-6 xl:grid-cols-2 xl:items-start">
          <div className="flex min-w-0 flex-col gap-6">
            <Hero result={result} beforeMissing={beforeMissing} />
            {result.breakdown && <WhereEachRupeeGoes breakdown={result.breakdown} marginBps={m?.contributionMarginBps ?? null} beforeMissing={beforeMissing !== undefined} />}
            {result.breakdown && <WhatIsKillingYourMargin costs={result.breakdown.topCosts} beforeMissing={beforeMissing !== undefined} />}
          </div>
          <div className="flex min-w-0 flex-col gap-6">
            <Section title="Profit and loss statement" hint={result.orders ? `${result.orders.placed.text} placed, ${result.orders.kept.text} kept (${result.orders.rto.text} RTO, ${result.orders.returned.text} returned).` : undefined} panel={false}>
              <div className="rounded-2xl p-4" style={CARD}>
                {tabs.length > 1 && <Tabs tabs={tabs} active={activeId} onChange={setView} label="Profit view" idPrefix="pnl-view" />}
                {views.map((x) => x.v && (
                  <TabPanel key={x.id} id={x.id} active={activeId} idPrefix="pnl-view">
                    <Ledger view={x.v} label={x.label} />
                  </TabPanel>
                ))}
              </div>
            </Section>
            {m && (
              <Section title="Ratios" hint="Each shows Not available until its inputs are entered." panel={false}>
                <div className="grid gap-4 sm:grid-cols-2">
                  <MetricCard label="Fees as a share of revenue" value={formatBps(m.effectiveFeeBps)} unavailableReason="Needs revenue." />
                  <MetricCard label="GST recovered per order kept" value={m.gstRecoveredPerKept != null ? money(m.gstRecoveredPerKept) : null} unavailableReason="Only when claiming input tax credit." />
                  <MetricCard label="ACOS" value={m.acosBps != null ? formatBps(m.acosBps) : null} unavailableReason="Needs ad spend and sales attributed to ads." />
                  <MetricCard label="TACoS" value={m.tacosBps != null ? formatBps(m.tacosBps) : null} unavailableReason="Needs ad spend." />
                  <MetricCard label="ROAS" value={m.roasBps != null ? formatRoas(m.roasBps) : null} unavailableReason="Needs ad spend and sales attributed to ads." />
                  <MetricCard label="Break-even ROAS" value={m.breakEvenRoasBps != null ? formatRoas(m.breakEvenRoasBps) : null} unavailableReason="Needs ad spend and a positive profit before ads." />
                  <MetricCard label="Highest ad cost per order kept" value={m.maxCac != null ? money(m.maxCac) : null} unavailableReason="Needs ad spend and a positive profit before ads." />
                  <MetricCard label="Operating margin" value={m.operatingMarginBps != null ? formatBps(m.operatingMarginBps) : null} unavailableReason="Enter operating expenses and orders per month." />
                </div>
              </Section>
            )}
            {blankAssumptions.length > 0 && (
              <Section title="Assumed because an input was left blank" hint="Enter the real value to replace each one." panel={false}>
                <ul className="m-0 list-disc rounded-2xl py-4 pl-9 pr-4 t-body-sm" style={{ ...CARD, color: "var(--text-4)" }}>
                  {blankAssumptions.map((a) => <li key={a.code}>{a.label}</li>)}
                </ul>
              </Section>
            )}
            {ruleAssumptions.length > 0 && (
              <Section title="How this estimate treats fees and GST" hint="Rules the calculation applies. They do not come from a blank input." panel={false}>
                <ul className="m-0 list-disc rounded-2xl py-4 pl-9 pr-4 t-body-sm" style={{ ...CARD, color: "var(--text-4)" }}>
                  {ruleAssumptions.map((a) => <li key={a.code}>{a.label}</li>)}
                </ul>
              </Section>
            )}
          </div>
        </div>
      ) : (
        <>
          {result.breakdown && <WhatIsKillingYourMargin costs={result.breakdown.topCosts} beforeMissing={beforeMissing !== undefined} />}
          {blankAssumptions.length > 0 && (
            <Section title="Assumed because an input was left blank" hint="Enter the real value to replace each one." panel={false}>
              <ul className="list-disc pl-5 t-body-sm" style={{ color: "var(--text-4)" }}>{blankAssumptions.map((a) => <li key={a.code}>{a.label}</li>)}</ul>
            </Section>
          )}
          {ruleAssumptions.length > 0 && (
            <Section title="How this estimate treats fees and GST" hint="Rules the calculation applies. They do not come from a blank input." panel={false}>
              <ul className="list-disc pl-5 t-body-sm" style={{ color: "var(--text-4)" }}>{ruleAssumptions.map((a) => <li key={a.code}>{a.label}</li>)}</ul>
            </Section>
          )}
        </>
      )}

      {result.solutions.length > 0 && (
        <Section title="Price targets" hint="The lowest selling price that reaches each target, using the same costs and fees." panel={false}>
          <ul className="grid gap-3 sm:grid-cols-2">{result.solutions.map((s) => <Solution key={s.target.kind + s.target.bps} s={s} onUsePrice={onUsePrice} />)}</ul>
        </Section>
      )}

      {info.length > 0 && <ul className="t-meta" style={{ color: "var(--text-5)" }}>{info.map((i) => <li key={i.code}>{i.message}</li>)}</ul>}
      <p className="t-meta" style={{ color: "var(--text-6)" }}>
        GST and input-tax-credit treatment is informational and still to be reviewed by a chartered accountant. TCS and TDS are cash items and are not in profit. Reference {result.estimateRef}.
      </p>
    </div>
  );
}
