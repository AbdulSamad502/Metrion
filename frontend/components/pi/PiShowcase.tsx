"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Pill, RefreshButton } from "@/components/overview/parts";
import { Donut, toneAt } from "@/components/overview/charts";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Spinner } from "@/components/ui/LoadingState";
import { useToast } from "@/components/ui/Toast";
import {
  evidenceOf, explainPiError, formatPaise, imageDomain, safeHref, SOURCE_LABEL,
  type PiCase, type PiClient, type PiHistoryItem, type PiProduct,
} from "@/lib/piShowcase";
import "@/components/overview/overview.css";
import "./pi.css";

/** The read-only Product Intelligence showcase (docs/specs/ceo-pi-research-flow.md §5.4; layout: docs/design/Design-Overviews/PI-Dashboard.svg).
 * It shows research the CEO already ran and saved. There is no form, no input and no control that starts research, saves a brief or looks up suppliers: the only
 * buttons switch what is shown, expand a block, or pin/unpin a saved report. Every figure is stored by the backend; where something is missing the cell says so and
 * why, never a zero or a guess. */

const sortDesc = (a: PiHistoryItem, b: PiHistoryItem) => (b.completedAt ?? "").localeCompare(a.completedAt ?? "");
const fmtDate = (iso: string | null | undefined) => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "date not stated";
};
const score = (s: string | null) => (s ? `${s}/100` : "no score");

function Badge({ children, tone = "accent" }: { children: ReactNode; tone?: "accent" | "neutral" }) {
  return <Pill tone={tone === "accent" ? "brand" : undefined}>{children}</Pill>;
}

function Note({ children }: { children: ReactNode }) {
  return <p role="status" className="pi-soft ov-body">{children}</p>;
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

  const [refreshing, setRefreshing] = useState(false);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const seq = useRef(0); // only the latest history request may change the screen
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const loadHistory = useCallback(async () => {
    const mine = ++seq.current;
    setRefreshing(true);
    try {
      const { items } = await client.history();
      if (!mounted.current || mine !== seq.current) return;
      setHistory(items);
      setHistoryError(null);
      setCheckedAt(new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }));
      setCurrentId((cur) => cur ?? [...items].sort(sortDesc)[0]?.runId ?? null);
    } catch (e) {
      // A failed refresh keeps the last list that loaded; the notice below says so.
      if (mounted.current && mine === seq.current) setHistoryError(explainPiError(e).message);
    } finally {
      if (mounted.current && mine === seq.current) setRefreshing(false);
    }
  }, [client]);
  useEffect(() => {
    (async () => {
      await loadHistory();
    })();
  }, [loadHistory]);

  const open = (runId: string, wantedRank = 1) => {
    setCurrentId(runId);
    setRank(wantedRank);
    window.history.replaceState(null, "", `?run=${encodeURIComponent(runId)}`);
    window.scrollTo?.({ top: 0 });
  };

  const others = (history ?? []).filter((h) => h.runId !== currentId).sort(sortDesc);
  return (
    <div className="ov mt-content">
      <header className="ov-head ov-rise">
        <div className="min-w-0">
          <h2 className="ov-h">What to sell next</h2>
          <p className="ov-body" style={{ marginTop: 4 }}>Saved research · read-only</p>
        </div>
        <Link href="/dashboard/ceo-hub" className="ov-btn ov-btn--brand min-h-10">
          + New Discovery
        </Link>
      </header>

      {history !== null && (
        <div className="ov-head-r ov-rise" style={{ justifyContent: "space-between", ["--i" as string]: 1 }} data-testid="pi-context">
          <p role="status" className="ov-meta" style={{ margin: 0 }}>
            {refreshing ? "Refreshing… what is shown is the last list that loaded." : `${history.length} saved ${history.length === 1 ? "report" : "reports"}${checkedAt ? ` · checked ${checkedAt}` : ""}`}
          </p>
          <RefreshButton spinning={refreshing} onClick={() => void loadHistory()} />
        </div>
      )}

      {historyError && (
        <div role="alert" className="ov-note ov-note--bad">
          <span>{history !== null ? "Could not refresh your saved research. Showing the last list that loaded." : historyError}</span>
          <button type="button" onClick={() => void loadHistory()} disabled={refreshing} className="ov-btn min-h-10">Try again</button>
        </div>
      )}

      {history === null && !historyError && (
        <div role="status" aria-label="Loading research history" className="ov-card">
          <span className="ov-skel" style={{ height: 24, width: 240 }} />
          <span className="ov-skel" style={{ height: 160 }} />
          <p className="ov-meta">Loading your saved research…</p>
        </div>
      )}

      {history !== null && history.length === 0 && !currentId && (
        <section className="ov-card ov-rise" aria-label="No saved research yet">
          <div className="ov-empty">
            <span className="ov-badge-circle"><Icon name="products" size={24} /></span>
            <div>
              <h3 className="ov-h">No saved research yet</h3>
              <p className="ov-body" style={{ marginTop: 8, maxWidth: "52ch" }}>Product research starts in a conversation with the CEO. Ask it to find products to sell, and the full report is saved here.</p>
            </div>
            <Link href="/dashboard/ceo-hub" className="ov-btn ov-btn--brand min-h-10">Ask the CEO to research products</Link>
          </div>
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

      {others.length > 0 && (
        <div className="ov-card ov-rise pi-history" role="group" aria-label="Earlier research">
          {others.map((h) => <OldInvestigation key={h.runId} item={h} client={client} cache={cache} onOpen={open} onPinChanged={loadHistory} />)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------- top picks from older investigations
function TopPicks({ items, onOpen }: { items: PiHistoryItem[]; onOpen: (runId: string, rank?: number) => void }) {
  const picks = items.filter((i) => i.topProducts[0]).slice(0, 3);
  return (
    <section className="ov-card ov-rise" aria-label="Top products from your earlier investigations">
      <h3 className="ov-title" style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", columnGap: 12 }}>
        <span>Top picks</span>
        
      </h3>
      {picks.length === 0 ? (
        <p className="ov-body">No earlier investigations yet.</p>
      ) : (
        <ul className="pi-picks">
          {picks.map((i) => (
            <li key={i.runId}>
              <button type="button" onClick={() => onOpen(i.runId, 1)} className="pi-pick mt-focus">
                <span className="pi-pick-n" aria-hidden>1</span>
                <span className="pi-pick-main">
                  <span className="ov-title">{i.topProducts[0].title ?? "Untitled product"}</span>
                  <span className="ov-meta">{i.category ?? "Investigation"} · {fmtDate(i.completedAt)}</span>
                  <span className="ov-title" style={{ color: "var(--ov-brand-ink)" }}>Score {score(i.topProducts[0].finalScore)}</span>
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
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What the backend itself answered to the last pin or unpin, kept only while the list still carries the value it was asked about, so the button never
  // flips back to the old state in the gap before the list is re-read, and never shows a state the backend has not confirmed.
  const [confirmed, setConfirmed] = useState<{ base: boolean; value: boolean } | null>(null);
  const inFlight = useRef(false); // a second press in the same instant is dropped, before any re-render
  const shown = confirmed && confirmed.base === pinned ? confirmed.value : pinned;
  const toggle = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const res = await (shown ? client.unpin(runId) : client.pin(runId));
      setConfirmed({ base: pinned, value: res.pinned });
      toast.success(res.pinned ? "Report pinned." : "Report unpinned.");
      onChanged();
    } catch (e) {
      setError(explainPiError(e).message);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <button type="button" aria-pressed={shown} disabled={busy} onClick={() => void toggle()} className={`ov-btn min-h-10${shown ? " ov-btn--brand" : ""}`}>
        {busy && <Spinner size={12} />}
        {shown ? "Pinned" : "Pin"}
      </button>
      {error && <span role="alert" className="ov-meta" style={{ color: "var(--ov-warn)" }}>{error}</span>}
    </span>
  );
}

function useCase(client: PiClient, cache: Map<string, PiCase>, runId: string, enabled = true) {
  const [state, setState] = useState<{ status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: PiCase }>(() => {
    const hit = cache.get(runId);
    return hit ? { status: "ready", data: hit } : { status: "loading" };
  });
  const [tick, setTick] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const alive = useRef(true);
  const reloading = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    client.report(runId).then(
      (data) => { cache.set(runId, data); if (live) setState({ status: "ready", data }); },
      (e) => { if (live) setState({ status: "error", message: explainPiError(e).message }); },
    );
    return () => { live = false; };
  }, [client, cache, runId, enabled, tick]);
  // A background re-read of a report that is already on screen: it stays visible, a failure leaves it in place and says so, and only one runs at a time.
  const reload = useCallback(async () => {
    if (reloading.current) return;
    reloading.current = true;
    setRefreshing(true);
    setRefreshError(null);
    try {
      const data = await client.report(runId);
      cache.set(runId, data);
      if (alive.current) setState({ status: "ready", data });
    } catch (e) {
      if (alive.current) setRefreshError(explainPiError(e).message);
    } finally {
      reloading.current = false;
      if (alive.current) setRefreshing(false);
    }
  }, [client, cache, runId]);
  return { state, refreshing, refreshError, reload, retry: () => { setState({ status: "loading" }); setTick((n) => n + 1); } };
}

// ---------------------------------------------------------------------------------------------------- current investigation
function CurrentInvestigation({ runId, client, cache, rank, setRank, isLatest, onPinChanged }: {
  runId: string; client: PiClient; cache: Map<string, PiCase>; rank: number; setRank: (n: number) => void; isLatest: boolean; onPinChanged: () => void;
}) {
  const { state, retry, reload, refreshing, refreshError } = useCase(client, cache, runId);
  const refresh = () => { void reload(); onPinChanged(); }; // re-read in place: the open report stays on screen while its pinned state is confirmed
  if (state.status === "loading") return (
    <section className="ov-card" aria-label="Loading investigation">
      <span className="ov-skel" style={{ height: 24, width: 280 }} />
      <span className="ov-skel" style={{ height: 240 }} />
      <p role="status" className="ov-meta">Loading this investigation…</p>
    </section>
  );
  if (state.status === "error") return (
    <section className="ov-card" aria-label="Investigation unavailable">
      <p role="alert" className="ov-body" style={{ color: "var(--ov-ink)" }}>{state.message}</p>
      <span><button type="button" onClick={retry} className="ov-btn min-h-10">Try again</button></span>
    </section>
  );
  const c = state.data;
  const products = c.products;
  const idx = Math.min(Math.max(rank - 1, 0), Math.max(products.length - 1, 0));
  const product = products[idx];
  return (
    <section className="ov-card ov-rise" style={{ gap: 24 }} aria-label={`Investigation: ${c.brief.category ?? "saved research"}`}>
      <header className="ov-head" style={{ alignItems: "flex-start" }}>
        <div className="min-w-0">
          <h3 className="ov-h" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
            {isLatest ? "Recent Investigation" : "Investigation"}: {c.brief.category ?? "Saved research"}
            <Badge tone={isLatest ? "accent" : "neutral"}>{isLatest ? "Current" : "Selected"}</Badge>
            {c.status === "PARTIAL" && <Badge tone="neutral">Partial</Badge>}
          </h3>
          <p className="ov-meta" style={{ marginTop: 8 }}>{briefLine(c.brief, `Top ${products.length} Shortlist`)} · saved {fmtDate(c.completedAt)}</p>
        </div>
        <div className="ov-head-r" style={{ flexWrap: "wrap" }}>
          {refreshing && <span role="status" className="ov-meta" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><Spinner size={12} /> Updating…</span>}
          <PinButton pinned={c.pinned} runId={runId} client={client} onChanged={refresh} />
          <Link href={`/reports/pi/${encodeURIComponent(runId)}/print`} target="_blank" rel="noopener noreferrer" className="ov-btn min-h-10">
            Print / Export PDF
          </Link>
        </div>
      </header>

      {refreshError && (
        <div role="alert" className="ov-note">
          <span>{refreshError} Showing the last copy of this report that loaded.</span>
          <button type="button" onClick={() => void reload()} className="ov-btn min-h-10">Try again</button>
        </div>
      )}

      {products.length === 0 ? (
        <Note>This report has no shortlisted products{c.gaps.length ? `: ${c.gaps.join("; ")}` : ""}.</Note>
      ) : (
        <>
          {c.overall && (
            <div className="ov-card ov-hero pi-hero">
              {products[0] && products[0].candidate.candidate_title === c.overall.title && <Thumb product={products[0]} size={112} />}
              <div className="pi-hero-main">
                <p className="ov-meta">Best bet</p>
                <p className="ov-h"><strong>{c.overall.title}</strong></p>
                <p className="ov-meta">{c.overall.reason}</p>
              </div>
              <div className="pi-hero-side">
                {products[0] && products[0].candidate.candidate_title === c.overall.title && products[0].finalScore && (
                  <div className="pi-hero-score"><span className="ov-fig-lg">{products[0].finalScore}</span><span className="ov-meta">/100 score</span></div>
                )}
                <Link href="/dashboard/ceo-hub" className="ov-btn ov-btn--glass min-h-10">Ask for batch size →</Link>
              </div>
            </div>
          )}
          <Ledger products={products} idx={idx} onSelect={(n) => setRank(n + 1)} />
          <ProductInformation product={product} brief={c.brief} />
          <Recommendation c={c} />
          {c.unavailable.length > 0 && (
            <details className="ov-meta">
              <summary style={{ cursor: "pointer", minHeight: 40, display: "flex", alignItems: "center" }}>What this research could not provide</summary>
              <ul className="pi-list" style={{ listStyle: "disc", paddingLeft: 20, marginTop: 8 }}>{c.unavailable.map((u) => <li key={u.field}><strong>{u.field.replace(/_/g, " ")}:</strong> {u.reason}</li>)}</ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}

/** A small square picture for a list row or banner. Nothing is drawn when the product has no usable image (the row keeps its words). */
function Thumb({ product, size }: { product: PiProduct; size: number }) {
  const [failed, setFailed] = useState(false);
  const url = safeHref(product.candidate.image_url);
  if (!url || failed) return null;
  return (
    <span className="pi-thumb-sm" style={{ width: size, height: size }} aria-hidden>
      {/* eslint-disable-next-line @next/next/no-img-element -- hotlinked from arbitrary hosts, attributed in the detail view */}
      <img src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    </span>
  );
}

function ProductImage({ product, large = false }: { product: PiProduct; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  const url = safeHref(product.candidate.image_url);
  if (!url || failed) {
    return (
      <div className="grid h-full w-full place-items-center text-center" style={{ minHeight: large ? 220 : 96 }}>
        <span className="ov-meta">No clear product image found</span>
      </div>
    );
  }
  return (
    // A light backing so dark or transparent product photos (a black case on a dark card) are always visible. Hotlinked from arbitrary hosts, attributed below (PI spec C8).
    <div className="pi-photo-frame">
      {/* eslint-disable-next-line @next/next/no-img-element -- hotlinked from arbitrary hosts, attributed below */}
      <img src={url} alt={product.candidate.candidate_title} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} className="h-full w-full object-contain" style={{ maxHeight: large ? 300 : 120 }} />
    </div>
  );
}

/** The shortlist as a ledger: one row per product, the biggest block on the screen because choosing between them is the question. Picking a row shows its detail below. */
function Ledger({ products, idx, onSelect }: { products: PiProduct[]; idx: number; onSelect: (i: number) => void }) {
  const positive = (p: PiProduct) => {
    const split = p.reviewInsights.find((i) => i.sentiment_split)?.sentiment_split ?? null;
    const hit = split && Object.entries(split).find(([k]) => k.toLowerCase() === "positive");
    return hit ? String(hit[1]) : null;
  };
  const best = Math.max(1, ...products.map((p) => Number.parseFloat(p.finalScore ?? "0") || 0));
  /** "78%" read only to size a bar; the written percentage is the backend's. */
  const posShare = (t: string) => {
    const n = Number.parseFloat(t);
    return Number.isFinite(n) && n >= 0 && n <= 100 ? n : null;
  };
  return (
    <div className="pi-ledger-wrap">
      <table className="pi-ledger" aria-label="Shortlisted products">
        <thead>
          <tr>
            <th scope="col"><span className="sr-only">Rank</span></th>
            <th scope="col">Product</th>
            <th scope="col" className="num">Score</th>
            <th scope="col">Customers say</th>
            <th scope="col">Supplier</th>
            <th scope="col" className="num">Landed cost</th>
            <th scope="col" className="num">Units</th>
          </tr>
        </thead>
        <tbody>
          {products.map((q, i) => {
            const fin = (rx: RegExp) => q.financials?.find((f) => rx.test(f.label) && f.display)?.display ?? null;
            const sel = i === idx;
            const pos = positive(q);
            const num = Number.parseFloat(q.finalScore ?? "");
            return (
              <tr key={q.candidate.id} aria-selected={sel} className={sel ? "is-selected" : undefined}>
                <td>
                  <button type="button" onClick={() => onSelect(i)} aria-label={`Rank ${q.rank}`} aria-current={sel} className="pi-rank mt-focus">{q.rank}</button>
                </td>
                <td className="pi-name">
                  <button type="button" onClick={() => onSelect(i)} className="pi-pickname mt-focus" tabIndex={-1}>
                    <Thumb product={q} size={56} />
                    <span className="pi-pickname-text">
                      <span className="ov-title">{q.candidate.candidate_title}</span>
                      {q.candidate.observed_category && <span className="ov-meta">{q.candidate.observed_category}</span>}
                    </span>
                  </button>
                </td>
                <td className="num">
                  <span className="pi-score"><b>{q.finalScore ?? "—"}</b>{!Number.isNaN(num) && <span className="pi-bar" aria-hidden><i style={{ width: `${(num / best) * 100}%` }} /></span>}</span>
                </td>
                <td>{pos ? <span className="pi-pos"><span className="ov-body" style={{ color: "var(--ov-ink)" }}>{pos} positive</span>{posShare(pos) !== null && <span className="pi-bar pi-bar--good" aria-hidden><i style={{ width: `${posShare(pos)}%` }} /></span>}</span> : <span className="ov-meta">No commentary</span>}</td>
                <td>{q.recommendation.supplier_option ? <span className="ov-body" style={{ color: "var(--ov-ink)" }}>{q.recommendation.supplier_option.supplier_name}</span> : <span className="ov-meta">None found</span>}</td>
                <td className="num">{fin(/landed cost/i) ?? <span className="ov-meta">Needs quote</span>}</td>
                <td className="num">{fin(/units/i) ?? <span className="ov-meta">Needs quote</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function f2(margin: { display: string | null; reason?: string } | undefined, spread: string): { value: string; sub: string; missing: boolean } {
  return margin?.display ? { value: margin.display, sub: "From your quote", missing: false } : { value: "Unavailable", sub: margin?.reason ?? spread, missing: true };
}

function Tile({ label, value, sub, missing, icon, tone }: { label: string; value: string; sub?: string; missing?: boolean; icon?: IconName; tone?: string }) {
  return (
    <div className="pi-tile">
      <div className="pi-tile-top">
        {icon && <span className="pi-tile-ico" style={{ color: tone, background: `color-mix(in srgb, ${tone} 14%, transparent)` }} aria-hidden><Icon name={icon} size={16} /></span>}
        <span className="ov-meta">{label}</span>
      </div>
      <div className={missing ? "ov-title" : "ov-fig"} style={missing ? { color: "var(--ov-ink-3)" } : undefined}>{value}</div>
      {sub && <div className="ov-meta">{sub}</div>}
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
  const tile = (f: ReturnType<typeof find>, fallback: string) => (f?.display ? { value: f.display, sub: "From your quote", missing: false } : { value: "Unavailable", sub: f?.reason ?? fallback, missing: true });
  const costT = tile(cost, "Needs your supplier quote");
  const marginT = f2(margin, "Needs your cost and selling price");
  const unitsT = tile(units, "Needs your confirmed quote");
  const imgUrl = safeHref(c.image_url);
  const scoreNum = product.finalScore !== null ? Number(product.finalScore) : NaN;
  const ringScore = Number.isFinite(scoreNum) && scoreNum >= 0 && scoreNum <= 100 ? scoreNum : null; // only to size the ring; the written score is the backend's
  const sentimentParts = (product.reviewInsights.find((i) => i.sentiment_split)?.sentiment_split ? Object.entries(product.reviewInsights.find((i) => i.sentiment_split)!.sentiment_split!) : []).map(([k, v], i) => ({ key: k, label: k.toLowerCase(), raw: v, share: Number.parseFloat(v) / 100, color: /pos/i.test(k) ? "var(--ov-good)" : /neg/i.test(k) ? "var(--ov-warn)" : toneAt(i + 3) })).filter((p) => Number.isFinite(p.share) && p.share > 0);
  return (
    <section className="pi-detail" aria-label={`Product information: ${c.candidate_title}`}>
      <header className="pi-detail-head">
        {imgUrl && (
          <div className="pi-thumb"><ProductImage product={product} large /></div>
        )}
        {ringScore !== null && (
          <Donut size={96} parts={[{ key: "score", label: "Score", share: ringScore / 100, color: "var(--ov-brand)" }]} summary={`Score ${score(product.finalScore)}`} center={<span className="ov-title">{product.finalScore}</span>} />
        )}
        <div className="min-w-0">
          <div className="ov-meta" style={{ display: "flex", alignItems: "center", gap: 8 }}><Badge tone="neutral">Rank #{product.rank}</Badge><h4 style={{ margin: 0, font: "inherit" }}>Product Information</h4></div>
          <p className="ov-h" style={{ marginTop: 8 }}>{c.candidate_title}</p>
          <p className="ov-meta" style={{ marginTop: 4 }}>{c.observed_category ? `${c.observed_category} · ` : ""}score {score(product.finalScore)} · from public web signals</p>
          {imgUrl && <p className="ov-meta">image from {imageDomain(c.image_source_url)}</p>}
        </div>
      </header>

      <div className="pi-facts">
        <Tile icon="tag" tone="var(--ov-c1)" label="Selling price" value={band ?? (web?.average_paise != null ? formatPaise(web.average_paise) : "Unavailable")} sub={band ? (web?.average_paise != null ? `Web ref: ${formatPaise(web.average_paise)} (not verified)` : "Your target band") : web ? "Web reference, not verified" : "No target price stated"} missing={!band && !web} />
        <Tile icon="cart" tone="var(--ov-c3)" label="Cost price" value={costT.value} sub={costT.sub} missing={costT.missing} />
        <Tile icon="reports" tone="var(--ov-c2)" label="Net margin" value={marginT.value} sub={marginT.sub} missing={marginT.missing} />
        <Tile icon="orders" tone="var(--ov-c4)" label="Units to buy" value={unitsT.value} sub={unitsT.sub ? `${unitsT.sub}${units?.display ? " · a ceiling, not a forecast" : ""}` : undefined} missing={unitsT.missing} />
      </div>

      <div className="pi-cols">
        <div className="pi-panel pi-panel--people">
          <h5 className="ov-title">What viewers say</h5>
          <p className="ov-meta">Viewer and web commentary, not verified buyer reviews{splits[0] ? ` · ${splits[0]}` : ""}</p>
          {sentimentParts.length >= 2 && (
            <div className="ov-chart">
              <Donut size={104} parts={sentimentParts} summary={`Commentary: ${sentimentParts.map((p) => `${p.label} ${p.raw}`).join(", ")}`} />
              <ul className="ov-chart-key">{sentimentParts.map((p) => <li key={p.key}><i style={{ background: p.color }} aria-hidden />{p.label}<b>{p.raw}</b></li>)}</ul>
            </div>
          )}
          <div className="pi-halves">
            <div>
              <div className="ov-meta pi-liked"><Icon name="check" size={12} strokeWidth={2.5} /> Liked</div>
              {positives.length ? <ul className="pi-list" style={{ marginTop: 8 }}>{positives.map((t) => <li key={t} className="ov-body" style={{ color: "var(--ov-ink)" }}>{t}</li>)}</ul> : <p className="ov-meta" style={{ marginTop: 8 }}>No commentary themes were available.</p>}
            </div>
            <div>
              <div className="ov-meta pi-fix"><Icon name="alert" size={12} strokeWidth={2.5} /> To fix</div>
              {defects.length ? <ul className="pi-list" style={{ marginTop: 8 }}>{defects.map((t) => <li key={t} className="ov-body" style={{ color: "var(--ov-ink)" }}>{t}</li>)}</ul> : <p className="ov-meta" style={{ marginTop: 8 }}>No complaint themes were found.</p>}
            </div>
          </div>

        </div>
        <div className="pi-panel">
          <EvidencePanel product={product} />
        </div>
        <div className="pi-panel pi-panel--wide">
          <h5 className="ov-title">Supplier lead</h5>
          {lead ? (
            <div className="pi-supplier">
              <div className="min-w-0 ov-body">
                <div className="ov-title">{href ? <a href={href} target="_blank" rel="noopener noreferrer" className="pi-link">{lead.supplier_name}</a> : lead.supplier_name}</div>
                <div className="ov-meta">{lead.locality ?? "Location not stated"} · {SOURCE_LABEL[lead.source] ?? lead.source}</div>
                <div className="ov-meta">Phone: {lead.contact?.phone ?? "not published"} · MOQ: {lead.contact?.moq ? "published by the supplier" : "not published"}</div>
                {published && <div className="ov-body" style={{ fontWeight: 800, color: "var(--ov-ink)", marginTop: 8 }}>Published price: {published.low_paise === published.high_paise ? formatPaise(published.low_paise) : `${formatPaise(published.low_paise)} - ${formatPaise(published.high_paise)}`} per {published.unit} (their own page, {fmtDate(published.captured_at)}; not a quote)</div>}
                {lead.fetched_at && <div className="ov-meta">Found {fmtDate(lead.fetched_at)} · not checked by Metrion</div>}
              </div>
              {href && <a href={href} target="_blank" rel="noopener noreferrer" className="ov-btn min-h-10" style={{ flex: "none" }}>Supplier Link ↗</a>}
            </div>
          ) : <p className="ov-meta">No supplier lead was found for this product.</p>}
        </div>
      </div>

      {rec.gaps.length > 0 && <p className="ov-meta">Missing evidence: {rec.gaps.join("; ")}.</p>}
    </section>
  );
}

function EvidencePanel({ product }: { product: PiProduct }) {
  const ev = evidenceOf(product.candidate);
  const n = (v: number | null) => (v === null ? "n/a" : v.toLocaleString("en-IN"));
  const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);
  return (
    <div className="pi-evidence" aria-label="Research evidence and trend signals">
      <h5 className="ov-title">Research evidence and trend signals</h5>
      <dl className="pi-facts-list">
        <div>
          <dt className="ov-meta">Sources</dt>
          <dd className="ov-body">
            {ev.independentSources === null ? "not recorded" : `${ev.independentSources} website${ev.independentSources === 1 ? "" : "s"} or video${ev.independentSources === 1 ? "" : "s"} mention it`}
            {ev.sources.length > 0 && (
              <span className="pi-sources">{ev.sources.slice(0, 6).map((s) => (
                <span key={s.url}><a href={s.url} target="_blank" rel="noopener noreferrer" className="pi-link">{s.domain}</a> <span className="ov-meta">({s.kind})</span></span>
              ))}</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="ov-meta">Video views</dt>
          <dd className="ov-body">{ev.engagement ? `${n(ev.engagement.videos)} video(s), ${n(ev.engagement.views)} views, ${n(ev.engagement.comments)} comments` : ev.engagementMissing}</dd>
        </div>
        {ev.demandMissing && (
          <div>
            <dt className="ov-meta">Search demand</dt>
            <dd className="ov-body">unavailable - {ev.demandMissing}</dd>
          </div>
        )}
      </dl>
      <h5 className="ov-title pi-sub">Score signals</h5>
      <ul className="pi-list pi-signals">
        {ev.signals.map((s, si) => (
          <li key={s.signal} className="pi-signal">
            <span className="ov-body" style={{ color: "var(--ov-ink)", fontWeight: 700 }}>{cap(s.signal)}</span>
            {s.status === "AVAILABLE" && s.max > 0 && <span className="pi-bar" aria-hidden><i style={{ width: `${Math.min(100, (Number(s.points) / Number(s.max)) * 100)}%`, background: toneAt(si) }} /></span>}
            <span className="ov-meta">{s.status === "AVAILABLE" ? `${s.points}/${s.max} points - ${s.reason}` : `unavailable (${s.reason})`}</span>
          </li>
        ))}
      </ul>
      <p className="ov-meta">Attention, not demand or sales.</p>
    </div>
  );
}

function Recommendation({ c }: { c: PiCase }) {
  // One recommendation for the whole investigation: the order to consider the products in, each with its best supplier (name and link), the CFO's units figure when the seller has
  // confirmed a quote (otherwise the exact thing to say to the CEO), and what to improve from the commentary. Every value is a saved PI field or a stored CFO result.
  return (
    <details className="pi-rec" aria-label="Recommendation from the saved research">
      <summary className="ov-title"><Badge tone="neutral">PI</Badge> Recommendation for this investigation{c.brief.category ? ` (${c.brief.category})` : ""}<Icon name="chevron" size={16} className="pi-chev" /></summary>
      <p className="ov-meta">In this order. Not a purchase instruction.</p>
      <ol className="pi-rec-list">
        {c.products.map((p) => {
          const lead = p.recommendation.supplier_option;
          const href = safeHref(lead?.contact?.website ?? lead?.source_url);
          const published = lead?.contact?.published_price ?? null;
          const landed = p.financials?.find((f) => /landed cost/i.test(f.label) && f.display)?.display;
          const units = p.financials?.find((f) => /units/i.test(f.label) && f.display)?.display;
          const pros = p.recommendation.pros;
          const cons = p.recommendation.cons;
          return (
            <li key={p.candidate.id}>
              <div className="ov-title">{p.rank}. {p.candidate.candidate_title} <span className="ov-meta">· score {score(p.finalScore)}</span></div>
              <dl className="pi-dl ov-body">
                <div><dt>Supplier: </dt><dd>{lead ? (href ? <a href={href} target="_blank" rel="noopener noreferrer" className="pi-link">{lead.supplier_name} ↗</a> : lead.supplier_name) : "no supplier lead found"}{published ? <strong style={{ color: "var(--ov-brand-ink)" }}> · published price {published.low_paise === published.high_paise ? formatPaise(published.low_paise) : `${formatPaise(published.low_paise)} - ${formatPaise(published.high_paise)}`} per {published.unit} (not a quote)</strong> : ""}</dd></div>
                <div><dt>Landed cost: </dt><dd>{landed ?? "not calculated yet"}</dd></div>
                <div><dt>Units / batch size: </dt><dd>{units ? `${units} at most with your budget (a ceiling)` : `not calculated yet. Ask the CEO: “how many units of #${p.rank}?”`}</dd></div>
                <div><dt>Improve / watch: </dt><dd>{cons.length ? `customers complain about ${cons.slice(0, 3).join(", ")}.` : pros.length ? `no complaints found. Customers like ${pros.slice(0, 3).join(", ")}.` : "no review commentary found for this product."}</dd></div>
              </dl>
            </li>
          );
        })}
      </ol>
      
    </details>
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
    <section className="pi-old" aria-label={`Old investigation: ${item.category ?? "saved research"}`}>
      <header className="ov-head" style={{ alignItems: "center" }}>
        <div className="min-w-0">
          <h3 className="ov-title" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
            Old Investigation <Badge tone="neutral">Historical</Badge> {item.pinned && <Badge tone="neutral">Pinned</Badge>}
          </h3>
          <p className="ov-meta" style={{ marginTop: 4 }}>{item.category ?? "Saved research"} · {fmtDate(item.completedAt)} · {briefLine(item)}</p>
        </div>
        <div className="ov-head-r">
          <PinButton pinned={item.pinned} runId={item.runId} client={client} onChanged={() => { cache.delete(item.runId); onPinChanged(); }} />
          <button type="button" aria-expanded={expanded} aria-controls={panelId} onClick={() => setExpanded((v) => !v)} className="ov-btn min-h-10">
            {expanded ? "Collapse" : "Expand Window"}
          </button>
        </div>
      </header>
      {expanded && (
        <div id={panelId} className="pi-stack">
          {state.status === "loading" && <p role="status" className="ov-meta">Loading…</p>}
          {state.status === "error" && (
            <p role="alert" className="ov-body">{state.message} <button type="button" onClick={retry} className="pi-link" style={{ background: "none", border: 0, padding: 0, font: "inherit", cursor: "pointer" }}>Try again</button></p>
          )}
          {state.status === "ready" && (
            <>
              <ul className="pi-picks">
                {state.data.products.slice(0, 3).map((p) => (
                  <li key={p.candidate.id} className="pi-soft" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <div style={{ display: "grid", placeItems: "center", height: 96, overflow: "hidden", borderRadius: 12 }}><ProductImage product={p} /></div>
                    <div className="ov-title" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.candidate.candidate_title}</div>
                    <div className="ov-meta">Score {score(p.finalScore)} · Supplier: {p.recommendation.supplier_option?.supplier_name ?? "no lead found"}</div>
                    <span><button type="button" onClick={() => onOpen(item.runId, p.rank)} className="ov-btn min-h-10" style={{ background: "var(--ov-card)" }}>View Details ↗</button></span>
                  </li>
                ))}
              </ul>
              <div className="pi-soft" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
                <p className="ov-body" style={{ color: "var(--ov-ink)" }}><strong>Recommendation summary:</strong> {state.data.overall ? `${state.data.overall.title} - ${state.data.overall.reason}.` : "No product had enough signal for an overall pick."}</p>
                <Link href={`/reports/pi/${encodeURIComponent(item.runId)}/print`} target="_blank" rel="noopener noreferrer" className="ov-btn ov-btn--ghost min-h-10">Full Audit Report ↗</Link>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
