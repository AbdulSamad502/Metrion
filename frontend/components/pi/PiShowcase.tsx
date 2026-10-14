"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  evidenceOf, explainPiError, formatPaise, imageDomain, safeHref, SOURCE_LABEL,
  type PiCase, type PiClient, type PiHistoryItem, type PiProduct,
} from "@/lib/piShowcase";

/** The read-only Product Intelligence showcase (docs/specs/ceo-pi-research-flow.md §5.4; layout: docs/design/Design-Overviews/PI-Dashboard.svg).
 * It shows research the CEO already ran and saved. There is no form, no input and no control that starts research, saves a brief or looks up suppliers: the only
 * buttons switch what is shown, expand a block, or pin/unpin a saved report. Every figure is stored by the backend; where something is missing the cell says so and
 * why, never a zero or a guess. */

const card = { background: "var(--bg-card)", border: "1px solid var(--border-subtle)" } as const;
const panel = { background: "var(--bg-card)", border: "1px solid var(--accent-border-subtle)" } as const;
const sortDesc = (a: PiHistoryItem, b: PiHistoryItem) => (b.completedAt ?? "").localeCompare(a.completedAt ?? "");
const fmtDate = (iso: string | null | undefined) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "date not stated";
};
const score = (s: string | null) => (s ? `${s}/100` : "no score");

function Badge({ children, tone = "accent" }: { children: ReactNode; tone?: "accent" | "neutral" }) {
  return (
    <span className="t-micro inline-block whitespace-nowrap rounded px-1.5 py-0.5 font-bold uppercase" style={{ color: tone === "accent" ? "var(--accent)" : "var(--text-5)", border: `1px solid ${tone === "accent" ? "var(--accent-border-default)" : "var(--border-default)"}`, background: tone === "accent" ? "var(--accent-fill-subtle)" : "transparent" }}>
      {children}
    </span>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <p role="status" className="rounded-lg px-3 py-3 t-body-sm" style={{ color: "var(--text-6)", background: "var(--fill-hover)", border: "1px dashed var(--border-default)" }}>{children}</p>;
}

function briefLine(b: { budgetPaise?: number | null; targetPriceMinPaise?: number | null; targetPriceMaxPaise?: number | null; marketplaces?: string[] | null }, tail?: string): string {
  const parts: string[] = [];
  if (b.budgetPaise != null) parts.push(`Budget: ${formatPaise(b.budgetPaise)}`);
  if (b.targetPriceMinPaise != null && b.targetPriceMaxPaise != null) parts.push(`Target Price: ${formatPaise(b.targetPriceMinPaise)} – ${formatPaise(b.targetPriceMaxPaise)}`);
  if (b.marketplaces?.length) parts.push(b.marketplaces.map((m) => m[0] + m.slice(1).toLowerCase()).join(", "));
  if (tail) parts.push(tail);
  return parts.join(" · ");
}

export function PiShowcase({ client, initialRunId = null }: { client: PiClient; initialRunId?: string | null }) {
  const [history, setHistory] = useState<PiHistoryItem[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [currentId, setCurrentId] = useState<string | null>(initialRunId);
  const [rank, setRank] = useState(1);
  const [cache] = useState(() => new Map<string, PiCase>());

  const loadHistory = useCallback(async () => {
    try {
      const { items } = await client.history();
      setHistory(items);
      setHistoryError(null);
      setCurrentId((cur) => cur ?? [...items].sort(sortDesc)[0]?.runId ?? null);
    } catch (e) {
      setHistoryError(explainPiError(e).message);
    }
  }, [client]);
  useEffect(() => {
    let live = true;
    client.history().then(
      ({ items }) => { if (live) { setHistory(items); setHistoryError(null); setCurrentId((cur) => cur ?? [...items].sort(sortDesc)[0]?.runId ?? null); } },
      (e) => { if (live) setHistoryError(explainPiError(e).message); },
    );
    return () => { live = false; };
  }, [client]);

  const open = (runId: string, wantedRank = 1) => {
    setCurrentId(runId);
    setRank(wantedRank);
    window.history.replaceState(null, "", `?run=${encodeURIComponent(runId)}`);
    window.scrollTo?.({ top: 0 });
  };

  const others = (history ?? []).filter((h) => h.runId !== currentId).sort(sortDesc);
  return (
    <div className="mt-content flex flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="t-headline font-bold" style={{ color: "var(--text-1)" }}>Product Intelligence Workspace</h2>
          <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>Opportunity discovery and supplier leads from your saved research · read-only</p>
        </div>
        <Link href="/dashboard/ceo-hub" className="mt-btn mt-focus rounded-lg px-4 py-2 t-body-sm font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>
          + New Discovery
        </Link>
      </header>

      {historyError && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl px-4 py-3 t-body-sm" style={{ ...card, color: "var(--text-3)" }}>
          {historyError}
          <button type="button" onClick={() => void loadHistory()} className="mt-btn mt-focus rounded-lg px-3 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>Try again</button>
        </div>
      )}

      {history === null && !historyError && <p role="status" aria-label="Loading research history" className="t-body-sm" style={{ color: "var(--text-6)" }}>Loading your saved research…</p>}

      {history !== null && history.length === 0 && !currentId && (
        <section className="rounded-2xl p-6" style={panel} aria-label="No saved research yet">
          <h3 className="t-card-title font-bold" style={{ color: "var(--text-1)" }}>No saved research yet</h3>
          <p className="mt-2 t-body-sm" style={{ color: "var(--text-5)" }}>Product research starts in a conversation with the CEO. Ask it to find products to sell, and the full report is saved here.</p>
          <Link href="/dashboard/ceo-hub" className="mt-btn mt-focus mt-4 inline-block rounded-lg px-4 py-2 t-body-sm font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>Ask the CEO to research products</Link>
        </section>
      )}

      {(history?.length ?? 0) > 0 && <TopPicks items={others} onOpen={open} />}

      {currentId && (
        <CurrentInvestigation
          key={currentId} runId={currentId} client={client} cache={cache} rank={rank} setRank={setRank}
          isLatest={history ? [...history].sort(sortDesc)[0]?.runId === currentId : false}
          onPinChanged={loadHistory}
        />
      )}

      {others.map((h) => <OldInvestigation key={h.runId} item={h} client={client} cache={cache} onOpen={open} onPinChanged={loadHistory} />)}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------- top picks from older investigations
function TopPicks({ items, onOpen }: { items: PiHistoryItem[]; onOpen: (runId: string, rank?: number) => void }) {
  const picks = items.filter((i) => i.topProducts[0]).slice(0, 3);
  return (
    <section className="rounded-2xl p-4" style={panel} aria-label="Top products from your earlier investigations">
      <h3 className="flex flex-wrap items-baseline gap-x-3 t-body font-bold" style={{ color: "var(--text-1)" }}>
        <span><span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: "var(--accent)" }} aria-hidden />Top Products from your Old Investigations</span>
        <span className="t-meta font-normal" style={{ color: "var(--text-6)" }}>The best-scored pick of each earlier saved report</span>
      </h3>
      {picks.length === 0 ? (
        <p className="mt-3 t-body-sm" style={{ color: "var(--text-6)" }}>No earlier investigations yet.</p>
      ) : (
        <ul className="mt-3 grid gap-3 md:grid-cols-3">
          {picks.map((i) => (
            <li key={i.runId}>
              <button type="button" onClick={() => onOpen(i.runId, 1)} className="mt-btn mt-focus flex w-full items-center gap-3 rounded-xl p-3 text-left" style={card}>
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full t-body font-bold" style={{ border: "1px solid var(--accent-border-default)", color: "var(--accent)" }} aria-hidden>1</span>
                <span className="min-w-0">
                  <span className="block truncate t-body-sm font-bold" style={{ color: "var(--text-1)" }}>{i.topProducts[0].title ?? "Untitled product"}</span>
                  <span className="block truncate t-meta" style={{ color: "var(--text-5)" }}>{i.category ?? "Investigation"} · {fmtDate(i.completedAt)}</span>
                  <span className="block t-meta font-bold" style={{ color: "var(--accent)" }}>Score {score(i.topProducts[0].finalScore)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------------------------------- pin control
function PinButton({ pinned, runId, client, onChanged }: { pinned: boolean; runId: string; client: PiClient; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      await (pinned ? client.unpin(runId) : client.pin(runId));
      onChanged();
    } catch (e) {
      setError(explainPiError(e).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex items-center gap-2">
      <button type="button" aria-pressed={pinned} disabled={busy} onClick={() => void toggle()} className="mt-btn mt-focus min-h-[32px] rounded-lg px-3 py-1 t-meta font-bold" style={pinned ? { background: "var(--accent-fill-subtle)", border: "1px solid var(--accent-border-strong)", color: "var(--accent)" } : { border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>
        {pinned ? "Pinned" : "Pin"}
      </button>
      {error && <span role="alert" className="t-micro" style={{ color: "var(--warning)" }}>{error}</span>}
    </span>
  );
}

function useCase(client: PiClient, cache: Map<string, PiCase>, runId: string, enabled = true) {
  const [state, setState] = useState<{ status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: PiCase }>(() => {
    const hit = cache.get(runId);
    return hit ? { status: "ready", data: hit } : { status: "loading" };
  });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    client.report(runId).then(
      (data) => { cache.set(runId, data); if (live) setState({ status: "ready", data }); },
      (e) => { if (live) setState({ status: "error", message: explainPiError(e).message }); },
    );
    return () => { live = false; };
  }, [client, cache, runId, enabled, tick]);
  return { state, retry: () => { setState({ status: "loading" }); setTick((n) => n + 1); } };
}

// ---------------------------------------------------------------------------------------------------- current investigation
function CurrentInvestigation({ runId, client, cache, rank, setRank, isLatest, onPinChanged }: {
  runId: string; client: PiClient; cache: Map<string, PiCase>; rank: number; setRank: (n: number) => void; isLatest: boolean; onPinChanged: () => void;
}) {
  const { state, retry } = useCase(client, cache, runId);
  const refresh = () => { cache.delete(runId); retry(); onPinChanged(); };
  if (state.status === "loading") return <section className="rounded-2xl p-6" style={panel} aria-label="Loading investigation"><p role="status" className="t-body-sm" style={{ color: "var(--text-6)" }}>Loading this investigation…</p></section>;
  if (state.status === "error") return (
    <section className="rounded-2xl p-6" style={panel} aria-label="Investigation unavailable">
      <p role="alert" className="t-body-sm" style={{ color: "var(--text-3)" }}>{state.message}</p>
      <button type="button" onClick={retry} className="mt-btn mt-focus mt-3 rounded-lg px-3 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>Try again</button>
    </section>
  );
  const c = state.data;
  const products = c.products;
  const idx = Math.min(Math.max(rank - 1, 0), Math.max(products.length - 1, 0));
  const product = products[idx];
  return (
    <section className="rounded-2xl p-5" style={{ ...panel, border: "1px solid var(--accent-border-strong)" }} aria-label={`Investigation: ${c.brief.category ?? "saved research"}`}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 t-card-title font-bold" style={{ color: "var(--text-1)" }}>
            <span className="h-2 w-2 rounded-full" style={{ background: "var(--accent)" }} aria-hidden />
            {isLatest ? "Recent Investigation" : "Investigation"}: {c.brief.category ?? "Saved research"}
            <Badge>{isLatest ? "Current" : "Selected"}</Badge>
            {c.status === "PARTIAL" && <Badge tone="neutral">Partial</Badge>}
          </h3>
          <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{briefLine(c.brief, `Top ${products.length} Shortlist`)} · saved {fmtDate(c.completedAt)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PinButton pinned={c.pinned} runId={runId} client={client} onChanged={refresh} />
          <Link href={`/reports/pi/${encodeURIComponent(runId)}/print`} target="_blank" rel="noopener noreferrer" className="mt-btn mt-focus min-h-[32px] rounded-lg px-3 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>
            Print / Export PDF
          </Link>
        </div>
      </header>

      {products.length === 0 ? (
        <Note>This report has no shortlisted products{c.gaps.length ? `: ${c.gaps.join("; ")}` : ""}.</Note>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
            <Carousel products={products} idx={idx} onSelect={(n) => setRank(n + 1)} />
            <ProductInformation product={product} brief={c.brief} />
          </div>
          <Recommendation c={c} />
          {c.unavailable.length > 0 && (
            <details className="mt-3 t-meta" style={{ color: "var(--text-6)" }}>
              <summary className="cursor-pointer">What this research could not provide</summary>
              <ul className="mt-2 list-disc pl-5">{c.unavailable.map((u) => <li key={u.field}><strong>{u.field.replace(/_/g, " ")}:</strong> {u.reason}</li>)}</ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}

function ProductImage({ product, large = false }: { product: PiProduct; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  const url = safeHref(product.candidate.image_url);
  if (!url || failed) {
    return (
      <div className="grid h-full w-full place-items-center text-center" style={{ minHeight: large ? 220 : 96 }}>
        <span className="t-meta" style={{ color: "var(--text-6)" }}>No clear product image found</span>
      </div>
    );
  }
  return (
    // A light backing so dark or transparent product photos (a black case on a dark card) are always visible. Hotlinked from arbitrary hosts, attributed below (PI spec C8).
    <div className="grid h-full w-full place-items-center overflow-hidden rounded-lg" style={{ background: "#f3f3f0" }}>
      {/* eslint-disable-next-line @next/next/no-img-element -- hotlinked from arbitrary hosts, attributed below */}
      <img src={url} alt={product.candidate.candidate_title} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} className="h-full w-full object-contain" style={{ maxHeight: large ? 300 : 120 }} />
    </div>
  );
}

function Carousel({ products, idx, onSelect }: { products: PiProduct[]; idx: number; onSelect: (i: number) => void }) {
  const p = products[idx];
  const prev = products[idx - 1];
  const next = products[idx + 1];
  const neighbour = (q: PiProduct | undefined, to: number, side: string) => q ? (
    <button type="button" onClick={() => onSelect(to)} aria-label={`Show ${side} product, rank ${q.rank}: ${q.candidate.candidate_title}`} className="mt-btn mt-focus hidden w-16 shrink-0 self-center overflow-hidden rounded-xl p-1 sm:block" style={{ ...card, opacity: 0.55 }}>
      <ProductImage product={q} />
      <span className="mt-1 block truncate t-micro" style={{ color: "var(--text-6)" }}>Prod #{q.rank}</span>
    </button>
  ) : <span className="hidden w-16 shrink-0 sm:block" aria-hidden />;
  return (
    <div>
      <div className="flex items-stretch gap-3">
        {neighbour(prev, idx - 1, "previous")}
        <figure className="relative min-w-0 flex-1 rounded-2xl p-3" style={{ ...card, border: "1px solid var(--accent-border-default)" }} aria-label={`Rank ${p.rank}: ${p.candidate.candidate_title}`}>
          <span className="absolute left-3 top-3 z-10"><Badge>Rank #{p.rank}</Badge></span>
          <div className="grid place-items-center pt-6" style={{ minHeight: 240 }}><ProductImage product={p} large /></div>
          <figcaption className="mt-2">
            <span className="block truncate t-body-sm font-bold" style={{ color: "var(--accent)" }}>{p.candidate.candidate_title}</span>
            {safeHref(p.candidate.image_url) && <span className="block t-micro" style={{ color: "var(--text-7)" }}>image from {imageDomain(p.candidate.image_source_url)}</span>}
          </figcaption>
        </figure>
        {neighbour(next, idx + 1, "next")}
      </div>
      <div className="mt-3 flex items-center justify-center gap-2" role="group" aria-label="Shortlisted products">
        <button type="button" onClick={() => onSelect(idx - 1)} disabled={idx === 0} aria-label="Previous product" className="mt-btn mt-focus rounded px-2 py-0.5 t-meta" style={{ color: "var(--text-3)" }}>‹</button>
        {products.map((q, i) => (
          <button key={q.candidate.id} type="button" onClick={() => onSelect(i)} aria-label={`Rank ${q.rank}`} aria-current={i === idx} className="mt-focus h-2 rounded-full" style={{ width: i === idx ? 22 : 8, background: i === idx ? "var(--accent)" : "var(--border-hover)" }} />
        ))}
        <button type="button" onClick={() => onSelect(idx + 1)} disabled={idx === products.length - 1} aria-label="Next product" className="mt-btn mt-focus rounded px-2 py-0.5 t-meta" style={{ color: "var(--text-3)" }}>›</button>
      </div>
    </div>
  );
}

function f2(margin: { display: string | null; reason?: string } | undefined, spread: string): { value: string; sub: string; missing: boolean } {
  return margin?.display ? { value: margin.display, sub: "From your confirmed supplier quote (CFO result)", missing: false } : { value: "Unavailable", sub: margin?.reason ?? spread, missing: true };
}

function Tile({ label, value, sub, missing }: { label: string; value: string; sub?: string; missing?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="t-micro font-bold uppercase" style={{ color: "var(--text-6)" }}>{label}</div>
      <div className="t-card-title font-bold" style={{ color: missing ? "var(--text-5)" : "var(--text-1)" }}>{value}</div>
      {sub && <div className="t-micro" style={{ color: "var(--text-6)" }}>{sub}</div>}
    </div>
  );
}

function ProductInformation({ product, brief }: { product: PiProduct; brief: PiCase["brief"] }) {
  const c = product.candidate;
  const rec = product.recommendation;
  const lead = product.supplierLeads.find((l) => l.id === product.bestSupplierLeadId) ?? rec.supplier_option;
  const web = c.web_price_signal && c.web_price_signal.status !== "UNAVAILABLE" ? c.web_price_signal : null;
  const band = brief.targetPriceMinPaise != null && brief.targetPriceMaxPaise != null ? `${formatPaise(brief.targetPriceMinPaise)} – ${formatPaise(brief.targetPriceMaxPaise)}` : null;
  const positives = rec.pros;
  const defects = rec.cons;
  const splits = product.reviewInsights.filter((i) => i.sentiment_split).map((i) => `${i.insight_source_type === "YOUTUBE_COMMENTARY" ? "Viewer" : "Web"} commentary ${Object.entries(i.sentiment_split ?? {}).map(([k, v]) => `${k.toLowerCase()} ${v}`).join(", ")}`);
  const spread = c.feasibility_status === "COMPUTED" && c.feasibility_low_paise != null && c.feasibility_high_paise != null
    ? `Price-and-fee spread ${formatPaise(c.feasibility_low_paise)} – ${formatPaise(c.feasibility_high_paise)} (estimate, before product cost)` : (c.feasibility_unavailable_reason ?? "Needs a supplier quote");
  const href = safeHref(lead?.contact?.website ?? lead?.source_url);
  const published = lead?.contact?.published_price ?? null;
  const fin = product.financials ?? [];
  const find = (rx: RegExp) => fin.find((f) => rx.test(f.label));
  const cost = find(/landed cost/i);
  const units = find(/units/i);
  const margin = find(/margin/i);
  const tile = (f: ReturnType<typeof find>, fallback: string) => (f?.display ? { value: f.display, sub: "From your confirmed supplier quote (CFO result)", missing: false } : { value: "Unavailable", sub: f?.reason ?? fallback, missing: true });
  const costT = tile(cost, `Needs your supplier quote - say "how many units should I buy of #${product.rank}?" in the CEO chat`);
  const marginT = f2(margin, "Needs your cost and a selling price after fees and tax");
  const unitsT = tile(units, `Needs your confirmed quote (with minimum order or delivery time) - say "how many units should I buy of #${product.rank}?" in the CEO chat`);
  return (
    <div className="rounded-2xl p-4" style={{ ...card, border: "1px solid var(--accent-border-default)" }} aria-label={`Product information: ${c.candidate_title}`}>
      <h4 className="t-body font-bold" style={{ color: "var(--text-1)" }}>Product Information</h4>
      <p className="t-meta" style={{ color: "var(--text-5)" }}>{c.candidate_title}{c.observed_category ? ` · ${c.observed_category}` : ""} · score {score(product.finalScore)} · opportunity candidate from public web signal</p>

      <div className="mt-3 grid grid-cols-2 gap-3 border-y py-3 md:grid-cols-4" style={{ borderColor: "var(--border-subtle)" }}>
        <Tile label="Selling price" value={band ?? (web?.average_paise != null ? formatPaise(web.average_paise) : "Unavailable")} sub={band ? (web?.average_paise != null ? `Web ref: ${formatPaise(web.average_paise)} (not verified)` : "Your target band") : web ? "Web-mentioned reference, not verified" : "No target price stated"} missing={!band && !web} />
        <Tile label="Cost price" value={costT.value} sub={costT.sub} missing={costT.missing} />
        <Tile label="Net margin" value={marginT.value} sub={marginT.sub} missing={marginT.missing} />
        <Tile label="Units to buy" value={unitsT.value} sub={unitsT.sub ? `${unitsT.sub}${units?.display ? " - a budget ceiling, not a forecast" : ""}` : undefined} missing={unitsT.missing} />
      </div>

      <h5 className="mt-3 t-micro font-bold uppercase" style={{ color: "var(--text-6)" }}>Viewer / web commentary insights (not verified buyer reviews)</h5>
      <div className="mt-1 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg p-2" style={{ background: "var(--accent-fill-subtle)", border: "1px solid var(--accent-border-default)" }}>
          <div className="t-meta font-bold" style={{ color: "var(--accent)" }}>Positive{splits[0] ? ` · ${splits[0]}` : ""}</div>
          {positives.length ? <ul className="t-meta" style={{ color: "var(--text-3)" }}>{positives.map((t) => <li key={t}>• {t}</li>)}</ul> : <p className="t-meta" style={{ color: "var(--text-6)" }}>No commentary themes were available.</p>}
        </div>
        <div className="rounded-lg p-2" style={{ background: "var(--fill-hover)", border: "1px solid var(--border-default)" }}>
          <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Defects to address</div>
          {defects.length ? <ul className="t-meta" style={{ color: "var(--text-3)" }}>{defects.map((t) => <li key={t}>• {t}</li>)}</ul> : <p className="t-meta" style={{ color: "var(--text-6)" }}>No complaint themes were found.</p>}
        </div>
      </div>

      <EvidencePanel product={product} />

      <h5 className="mt-3 t-micro font-bold uppercase" style={{ color: "var(--text-6)" }}>Supplier lead</h5>
      {lead ? (
        <div className="mt-1 flex flex-wrap items-center justify-between gap-3 rounded-lg p-3" style={{ border: "1px solid var(--border-default)" }}>
          <div className="min-w-0 t-body-sm" style={{ color: "var(--text-3)" }}>
            <div className="t-body font-bold" style={{ color: "var(--text-1)" }}>{href ? <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2" style={{ color: "var(--accent)" }}>{lead.supplier_name}</a> : lead.supplier_name}</div>
            <div>{lead.locality ?? "Location not stated"} · {SOURCE_LABEL[lead.source] ?? lead.source}</div>
            <div>Phone: {lead.contact?.phone ?? "not published"} · MOQ: {lead.contact?.moq ? "published by the supplier" : "not published"}</div>
            {published && <div className="font-bold" style={{ color: "var(--accent)" }}>Published price: {published.low_paise === published.high_paise ? formatPaise(published.low_paise) : `${formatPaise(published.low_paise)} - ${formatPaise(published.high_paise)}`} per {published.unit} (the supplier&apos;s own page, {fmtDate(published.captured_at)}; not a quote)</div>}
            {lead.fetched_at && <div style={{ color: "var(--text-6)" }}>Found {fmtDate(lead.fetched_at)}. Contact and price details are not checked by Metrion.</div>}
          </div>
          {href && <a href={href} target="_blank" rel="noopener noreferrer" className="mt-btn mt-focus rounded-lg px-3 py-1.5 t-meta font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>Supplier Link ↗</a>}
        </div>
      ) : <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>No supplier lead was found for this product.</p>}

      {rec.gaps.length > 0 && <p className="mt-3 t-micro" style={{ color: "var(--text-6)" }}>Missing evidence: {rec.gaps.join("; ")}.</p>}
    </div>
  );
}

function EvidencePanel({ product }: { product: PiProduct }) {
  const ev = evidenceOf(product.candidate);
  const n = (v: number | null) => (v === null ? "n/a" : v.toLocaleString("en-IN"));
  return (
    <div aria-label="Research evidence and trend signals">
      <h5 className="mt-3 t-micro font-bold uppercase" style={{ color: "var(--text-6)" }}>Research evidence and trend signals</h5>
      <ul className="mt-1 flex flex-col gap-1 t-meta" style={{ color: "var(--text-4)" }}>
        <li>
          <strong style={{ color: "var(--text-2)" }}>Independent sources:</strong> {ev.independentSources === null ? "not recorded" : `${ev.independentSources} website${ev.independentSources === 1 ? "" : "s"} or video${ev.independentSources === 1 ? "" : "s"} mention it`}
          {ev.sources.length > 0 && (
            <span> - {ev.sources.slice(0, 6).map((s, i) => (
              <span key={s.url}>{i > 0 && ", "}<a href={s.url} target="_blank" rel="noopener noreferrer" className="underline">{s.domain}</a> ({s.kind})</span>
            ))}</span>
          )}
        </li>
        <li>
          <strong style={{ color: "var(--text-2)" }}>Video engagement (YouTube):</strong>{" "}
          {ev.engagement ? `${n(ev.engagement.videos)} video(s), ${n(ev.engagement.views)} views, ${n(ev.engagement.comments)} comments` : ev.engagementMissing}
        </li>
        {ev.demandMissing && <li><strong style={{ color: "var(--text-2)" }}>Search demand:</strong> unavailable - {ev.demandMissing}</li>}
        {ev.signals.map((s) => (
          <li key={s.signal}><strong style={{ color: "var(--text-2)" }}>Score signal, {s.signal}:</strong> {s.status === "AVAILABLE" ? `${s.points}/${s.max} points` : `unavailable (${s.reason})`}{s.status === "AVAILABLE" ? ` - ${s.reason}` : ""}</li>
        ))}
      </ul>
      <p className="mt-1 t-micro" style={{ color: "var(--text-7)" }}>Signals from public web and video content: attention, not verified demand or sales.</p>
    </div>
  );
}

function Recommendation({ c }: { c: PiCase }) {
  // One recommendation for the whole investigation: the order to consider the products in, each with its best supplier (name and link), the CFO's units figure when the seller has
  // confirmed a quote (otherwise the exact thing to say to the CEO), and what to improve from the commentary. Every value is a saved PI field or a stored CFO result.
  return (
    <div className="mt-4 rounded-xl p-4" style={{ ...card, border: "1px solid var(--accent-border-default)" }} aria-label="Recommendation from the saved research">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h4 className="t-body font-bold" style={{ color: "var(--text-1)" }}><Badge>PI</Badge> Recommendation for this investigation{c.brief.category ? ` (${c.brief.category})` : ""}</h4>
        <Link href="/dashboard/ceo-hub" className="mt-btn mt-focus rounded-lg px-3 py-1.5 t-meta font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>Ask the CEO for batch size →</Link>
      </div>
      {c.overall && <p className="mt-2 t-body-sm" style={{ color: "var(--text-2)" }}><strong>Strongest opportunity: {c.overall.title}</strong> - {c.overall.reason}.</p>}
      <p className="mt-1 t-meta" style={{ color: "var(--text-5)" }}>Consider them in this order. Nothing here is a purchase instruction.</p>
      <ol className="mt-3 flex flex-col gap-3">
        {c.products.map((p) => {
          const lead = p.recommendation.supplier_option;
          const href = safeHref(lead?.contact?.website ?? lead?.source_url);
          const published = lead?.contact?.published_price ?? null;
          const landed = p.financials?.find((f) => /landed cost/i.test(f.label) && f.display)?.display;
          const units = p.financials?.find((f) => /units/i.test(f.label) && f.display)?.display;
          const pros = p.recommendation.pros;
          const cons = p.recommendation.cons;
          return (
            <li key={p.candidate.id} className="rounded-lg p-3" style={{ border: "1px solid var(--border-default)" }}>
              <div className="t-body font-bold" style={{ color: "var(--text-1)" }}>{p.rank}. {p.candidate.candidate_title} <span className="t-meta" style={{ color: "var(--accent)" }}>· score {score(p.finalScore)}</span></div>
              <dl className="mt-1 grid gap-1 t-body-sm" style={{ color: "var(--text-3)" }}>
                <div><dt className="inline font-bold" style={{ color: "var(--text-2)" }}>Supplier: </dt><dd className="inline">{lead ? (href ? <a href={href} target="_blank" rel="noopener noreferrer" className="font-bold underline underline-offset-2" style={{ color: "var(--accent)" }}>{lead.supplier_name} ↗</a> : lead.supplier_name) : "no supplier lead found"}{published ? <strong style={{ color: "var(--accent)" }}> · published price {published.low_paise === published.high_paise ? formatPaise(published.low_paise) : `${formatPaise(published.low_paise)} - ${formatPaise(published.high_paise)}`} per {published.unit} (not a quote)</strong> : ""}</dd></div>
                <div><dt className="inline font-bold" style={{ color: "var(--text-2)" }}>Landed cost: </dt><dd className="inline">{landed ?? "not calculated yet"}</dd></div>
                <div><dt className="inline font-bold" style={{ color: "var(--text-2)" }}>Units / batch size: </dt><dd className="inline">{units ? `${units} at most with your budget (a ceiling, not a recommendation)` : `not calculated yet. In the CEO chat say “how many units should I buy of #${p.rank}?”; the CFO works it out from your confirmed quote.`}</dd></div>
                <div><dt className="inline font-bold" style={{ color: "var(--text-2)" }}>Improve / watch: </dt><dd className="inline">{cons.length ? `customers complain about ${cons.slice(0, 3).join(", ")}; address this in your listing and sourcing.` : pros.length ? `no complaints found in the commentary; lean on what customers like (${pros.slice(0, 3).join(", ")}).` : "no review commentary found for this product."}</dd></div>
              </dl>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 t-micro" style={{ color: "var(--text-6)" }}>Estimates from public web signal, not a purchase instruction. Profit and loss also needs a selling price after fees and tax.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------- older investigations
function OldInvestigation({ item, client, cache, onOpen, onPinChanged }: {
  item: PiHistoryItem; client: PiClient; cache: Map<string, PiCase>; onOpen: (runId: string, rank?: number) => void; onPinChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const { state, retry } = useCase(client, cache, item.runId, expanded);
  const panelId = `old-${item.runId}`;
  return (
    <section className="rounded-2xl p-5" style={panel} aria-label={`Old investigation: ${item.category ?? "saved research"}`}>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 t-card-title font-bold" style={{ color: "var(--text-1)" }}>
            Old Investigation <Badge tone="neutral">Historical</Badge> {item.pinned && <Badge>Pinned</Badge>}
          </h3>
          <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>{item.category ?? "Saved research"} · {fmtDate(item.completedAt)} · {briefLine(item)}</p>
        </div>
        <div className="flex items-center gap-2">
          <PinButton pinned={item.pinned} runId={item.runId} client={client} onChanged={() => { cache.delete(item.runId); onPinChanged(); }} />
          <button type="button" aria-expanded={expanded} aria-controls={panelId} onClick={() => setExpanded((v) => !v)} className="mt-btn mt-focus min-h-[32px] rounded-lg px-3 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>
            {expanded ? "Collapse" : "Expand Window"}
          </button>
        </div>
      </header>
      {expanded && (
        <div id={panelId} className="mt-4">
          {state.status === "loading" && <p role="status" className="t-body-sm" style={{ color: "var(--text-6)" }}>Loading…</p>}
          {state.status === "error" && (
            <p role="alert" className="t-body-sm" style={{ color: "var(--text-3)" }}>{state.message} <button type="button" onClick={retry} className="underline">Try again</button></p>
          )}
          {state.status === "ready" && (
            <>
              <ul className="grid gap-3 md:grid-cols-3">
                {state.data.products.slice(0, 3).map((p) => (
                  <li key={p.candidate.id} className="rounded-xl p-3" style={card}>
                    <div className="grid h-24 place-items-center overflow-hidden rounded-lg" style={{ background: "var(--fill-hover)" }}><ProductImage product={p} /></div>
                    <div className="mt-2 truncate t-body-sm font-bold" style={{ color: "var(--text-1)" }}>{p.candidate.candidate_title}</div>
                    <div className="t-meta" style={{ color: "var(--text-5)" }}>Score {score(p.finalScore)} · Supplier: {p.recommendation.supplier_option?.supplier_name ?? "no lead found"}</div>
                    <button type="button" onClick={() => onOpen(item.runId, p.rank)} className="mt-btn mt-focus mt-2 rounded-lg px-2 py-1 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}>View Details ↗</button>
                  </li>
                ))}
              </ul>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl p-3" style={card}>
                <p className="t-meta" style={{ color: "var(--text-3)" }}><strong>Recommendation summary:</strong> {state.data.overall ? `${state.data.overall.title} - ${state.data.overall.reason}.` : "No product had enough signal for an overall pick."}</p>
                <Link href={`/reports/pi/${encodeURIComponent(item.runId)}/print`} target="_blank" rel="noopener noreferrer" className="t-meta font-bold" style={{ color: "var(--accent)" }}>Full Audit Report ↗</Link>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
