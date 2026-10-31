"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { CompareView } from "@/components/ceo/hub/ListingCompareView";
import type { HistoryApi, HistoryList, HistoryRecommendations, HistoryVersion, HistoryVersionDetail, ListingHistoryCard as Card, HistoryCompare } from "@/lib/ceo";

/** Listing history in the CEO chat (CMO 3.0 M7): every saved version of a listing, one version in full, the exact differences between two versions, and evidence-based suggestions. Read-only and
 * free: it never generates, edits, approves or publishes anything. "Approved for use" is shown as exactly that, a decision recorded in Metrion; the latest version is never assumed to be
 * approved and no version is ever called published or live. Every status is a word with a mark, never colour alone. */

const MP: Record<string, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };
const chip = (on: boolean): React.CSSProperties => ({ border: `1px solid ${on ? "var(--accent)" : "var(--border-subtle)"}`, background: on ? "var(--fill-hover)" : "transparent", color: on ? "var(--accent)" : "var(--text-3)" });
const day = (iso: string) => iso.slice(0, 10);
const PRIORITY: Record<string, string> = { HIGH: "✗ Fix first", MEDIUM: "! Worth a look", LOW: "○ Minor" };
const VERDICT: Record<string, string> = { BLOCKED: "Blocked", NEEDS_ATTENTION: "Needs attention", CHECKED_NOT_VERIFIED: "Checked, not verified" };

function messageFor(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401 || e.status === 403) return "You do not have access to this listing history.";
    if (e.status === 404) return "That version is no longer available. Nothing was changed.";
    if (e.status === 422) {
      const d = e.detail as { detail?: { detail?: string } } | undefined;
      return d?.detail?.detail ?? "Those versions cannot be compared.";
    }
  }
  return "I could not load that just now. Nothing was changed or used up.";
}

type Props = { card: Card; api?: HistoryApi; disabled?: boolean; onSend: (text: string) => void };

export function ListingHistoryCard({ card, api, disabled = false, onSend }: Props) {
  const [view, setView] = useState<Card>(card);
  const [list, setList] = useState<HistoryList | null>(card.view === "HISTORY" ? card : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; retry: () => void } | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [sku, setSku] = useState<string | null>(card.view === "HISTORY" ? card.filters.sku : null);
  const [mp, setMp] = useState<string | null>(card.view === "HISTORY" ? card.filters.marketplace : null);

  const run = async <T extends Card>(fn: () => Promise<T>, then: (r: T) => void) => {
    if (!api || busy) return;
    setBusy(true);
    setError(null);
    try { then(await fn()); } catch (e) { setError({ message: messageFor(e), retry: () => void run(fn, then) }); } finally { setBusy(false); }
  };
  const loadList = (nextSku: string | null, nextMp: string | null, append = false) =>
    run(() => api!.history({ sku: nextSku, marketplace: nextMp, offset: append && list ? list.offset + list.limit : 0 }), (r) => {
      const merged = append && list ? { ...r, versions: [...list.versions, ...r.versions], offset: list.offset + list.limit } : r;
      setList(merged); setView(merged); setSku(nextSku); setMp(nextMp); setPicked([]);
    });
  const open = (id: string) => run(() => api!.version(id), setView);
  const advice = (id: string) => run(() => api!.recommendations(id), setView);
  const compare = (a: string, b: string) => run(() => api!.compare(a, b), setView);
  const back = () => { setError(null); if (list) setView(list); };
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= 2 ? [p[1], id] : [...p, id]));

  const frame = (title: string, children: React.ReactNode, canGoBack = true) => (
    <div className="mt-2 flex flex-col gap-3 rounded-xl p-3" style={box} data-testid="listing-history" data-view={view.view} aria-label={title} role="group">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="m-0 t-body-sm font-bold" style={{ color: "var(--text-2)" }}>{title}</h3>
        {canGoBack && view.view !== "HISTORY" && list && <button type="button" className="mt-focus rounded-md px-2 py-1 t-meta font-bold" style={chip(false)} onClick={back}>← Back to history</button>}
      </div>
      <div role="status" aria-live="polite" className="sr-only">{busy ? "Loading" : ""}</div>
      {busy && <p className="m-0 t-meta" style={{ color: "var(--text-4)" }} data-testid="history-loading">Loading…</p>}
      {error && (
        <div role="alert" className="rounded-md p-2 t-meta" style={{ border: "1px solid var(--negative, #E5484D)", color: "var(--text-2)" }} data-testid="history-error">
          {error.message} <button type="button" className="mt-focus ml-1 rounded-md px-2 py-0.5 font-bold" style={chip(false)} onClick={error.retry}>Try again</button>
        </div>
      )}
      {children}
    </div>
  );

  if (view.view === "CLARIFY") {
    return frame("A quick question", (
      <>
        <p className="m-0 t-body-sm" style={{ color: "var(--text-2)" }}>{view.question}</p>
        <div className="flex flex-wrap gap-2">
          {view.options.map((o) => <button key={o.label} type="button" disabled={disabled} className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(false)} onClick={() => onSend(o.label)}>{o.label}</button>)}
        </div>
      </>
    ), false);
  }

  if (view.view === "HISTORY") {
    const h = view;
    const products = Array.from(new Map(h.groups.map((g) => [g.sku, g.product ?? g.sku])).entries());
    const mps = Array.from(new Set(h.groups.map((g) => g.marketplace)));
    const total = h.groups.reduce((n, g) => n + g.versionCount, 0);
    return frame("Listing history", (
      <>
        {api && (products.length > 1 || mps.length > 1 || sku || mp) && (
          <div className="flex flex-wrap items-center gap-2 t-meta" style={{ color: "var(--text-4)" }}>
            <label>Product <select aria-label="Filter by product" value={sku ?? ""} disabled={busy} className="mt-focus rounded-md px-1.5 py-1" style={box} onChange={(e) => void loadList(e.target.value || null, mp)}><option value="">All products</option>{products.map(([s, n]) => <option key={s} value={s}>{n}</option>)}</select></label>
            <label>Marketplace <select aria-label="Filter by marketplace" value={mp ?? ""} disabled={busy} className="mt-focus rounded-md px-1.5 py-1" style={box} onChange={(e) => void loadList(sku, e.target.value || null)}><option value="">All marketplaces</option>{mps.map((m) => <option key={m} value={m}>{MP[m]}</option>)}</select></label>
          </div>
        )}
        {h.empty ? (
          <p className="m-0 t-body-sm" style={{ color: "var(--text-3)" }} data-testid="history-empty">No saved listing versions{sku || mp ? " match this filter" : " yet"}. Ask me to “write my complete listing” and I will plan it for your approval first.</p>
        ) : (
          <>
            {total === 1 && <p className="m-0 t-meta" style={{ color: "var(--text-4)" }} data-testid="history-one">There is one version so far. When you edit or rewrite a section, the new version is saved next to it and the original stays.</p>}
            <ol className="m-0 flex list-none flex-col gap-2 p-0" aria-label="Versions, newest first" data-testid="history-timeline">
              {h.versions.map((v: HistoryVersion) => (
                <li key={v.id} className="rounded-md p-2.5 t-meta" style={box} data-testid="history-version">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <strong style={{ color: "var(--text-2)" }}>Version {v.number}{v.isLatest ? " (latest)" : ""} · {v.product ?? v.sku} · {MP[v.marketplace]}</strong>
                    <span style={{ color: "var(--text-4)" }}>{day(v.createdAt)}</span>
                  </div>
                  <div style={{ color: "var(--text-3)" }}>{v.sourceText}{v.parentNumber ? ` · built from version ${v.parentNumber}` : v.source === "ORIGINAL" ? "" : " · earlier version not available"}</div>
                  {v.title && <div style={{ color: "var(--text-4)" }}>{v.title}</div>}
                  <div style={{ color: "var(--text-3)" }}>
                    {v.states.approvedForUse.done ? "✓ Approved for use in Metrion" : "○ Not approved for use"} · {v.states.audited.done ? `Audit: ${VERDICT[v.states.audited.verdict ?? ""] ?? v.states.audited.verdict}` : "Not audited yet"} · Published: unknown to Metrion
                  </div>
                  {api && (
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <button type="button" className="mt-focus rounded-md px-2 py-1 font-bold" style={chip(false)} disabled={busy} onClick={() => void open(v.id)} aria-label={`Open version ${v.number}`}>Open</button>
                      <button type="button" className="mt-focus rounded-md px-2 py-1 font-bold" style={chip(false)} disabled={busy} onClick={() => void advice(v.id)} aria-label={`Suggestions for version ${v.number}`}>Suggestions</button>
                      <label className="flex items-center gap-1" style={{ color: "var(--text-3)" }}><input type="checkbox" checked={picked.includes(v.id)} onChange={() => toggle(v.id)} aria-label={`Select version ${v.number} to compare`} /> Compare</label>
                    </div>
                  )}
                </li>
              ))}
            </ol>
            {api && (
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(picked.length === 2)} disabled={busy || picked.length !== 2} onClick={() => void compare(picked[0], picked[1])} data-testid="compare-selected">Compare selected versions</button>
                {picked.length < 2 && <span className="t-meta" style={{ color: "var(--text-5)" }}>Tick two versions (they can be any two).</span>}
                {h.hasMore && <button type="button" className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(false)} disabled={busy} onClick={() => void loadList(sku, mp, true)}>Show more</button>}
              </div>
            )}
          </>
        )}
        <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>{h.notice} {h.published}</p>
      </>
    ), false);
  }

  if (view.view === "VERSION") {
    const d: HistoryVersionDetail = view;
    const s = d.sections;
    const a = d.audit;
    return frame(`Version ${d.version.number} of ${d.versionCount} · ${d.version.product ?? d.version.sku} · ${MP[d.version.marketplace]}`, (
      <>
        <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>{d.version.sourceText} · {day(d.version.createdAt)}{d.parent ? ` · built from version ${d.parent.number}` : ""}. {d.whyRevised.note}</p>
        <ul className="m-0 flex list-none flex-col gap-1 p-0 t-meta" style={{ color: "var(--text-3)" }}>
          <li><strong style={{ color: "var(--text-2)" }}>Title:</strong> {s.title}</li>
          {s.bullets.map((b, i) => <li key={i}><strong style={{ color: "var(--text-2)" }}>Bullet {i + 1}:</strong> {b}</li>)}
          <li><strong style={{ color: "var(--text-2)" }}>Description:</strong> {s.description}</li>
          <li><strong style={{ color: "var(--text-2)" }}>Keywords:</strong> {s.keywords.join(", ") || "none"}</li>
          {s.backend_terms && <li><strong style={{ color: "var(--text-2)" }}>Backend search terms:</strong> {s.backend_terms.join(", ") || "none"}</li>}
          {s.hashtags && <li><strong style={{ color: "var(--text-2)" }}>Hashtags:</strong> {s.hashtags.join(" ")}</li>}
        </ul>
        <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>{d.version.states.approvedForUse.done ? "✓ Approved for use in Metrion." : "○ Not approved for use."} Published: unknown to Metrion.</p>
        <section aria-label="Audit of this version" className="flex flex-col gap-1">
          <h4 className="m-0 mt-eyebrow">This version&apos;s own audit</h4>
          {!a ? <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>This version has no saved audit.</p> : (
            <>
              <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>Verdict: {VERDICT[a.verdict] ?? a.verdict} · saved {day(a.createdAt)}</p>
              {a.findings.length === 0 ? <p className="m-0 t-meta" style={{ color: "var(--text-4)" }}>No findings.</p> : a.findings.map((f, i) => <div key={i} className="t-meta" style={{ color: "var(--text-3)" }}>{f.severity === "BLOCKER" ? "✗" : f.severity === "WARNING" ? "!" : "○"} {f.section.toLowerCase()}: {f.explanation}</div>)}
            </>
          )}
        </section>
        {api && (
          <div className="flex flex-wrap gap-2">
            {d.parent && <button type="button" className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(false)} disabled={busy} onClick={() => void compare(d.parent!.id, d.version.id)}>What changed from version {d.parent.number}</button>}
            <button type="button" className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(false)} disabled={busy} onClick={() => void advice(d.version.id)}>What to improve</button>
          </div>
        )}
      </>
    ));
  }

  if (view.view === "COMPARE") {
    const c: HistoryCompare = view;
    return frame(`Version ${c.older.number} → version ${c.newer.number} · ${c.product ?? c.sku} · ${MP[c.marketplace]}`, <CompareView c={c} />);
  }

  const r: HistoryRecommendations = view;
  return frame(`What to look at next · version ${r.versionNumber} · ${r.product ?? ""} ${MP[r.marketplace] ?? ""}`, (
    <>
      {r.state !== "RECOMMENDATIONS" ? <p className="m-0 t-body-sm" style={{ color: "var(--text-3)" }} data-testid="recommend-none">{r.message}</p> : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0" data-testid="recommendations">
          {r.recommendations.map((x, i) => (
            <li key={i} className="rounded-md p-2.5 t-meta" style={box}>
              <strong style={{ color: "var(--text-2)" }}>{PRIORITY[x.priority]} · {x.recommendation}</strong> <span style={{ color: "var(--text-5)" }}>({x.section.toLowerCase().replace(/_/g, " ")}, version {x.versionNumber})</span>
              <div style={{ color: "var(--text-3)" }}>Why: {x.reason}</div>
              <ul className="m-0 pl-4" style={{ color: "var(--text-4)" }}>{x.evidence.map((e, j) => <li key={j}>{e}</li>)}</ul>
              <div style={{ color: "var(--text-3)" }}>Next: {x.nextAction}</div>
              <div style={{ color: "var(--text-5)" }}>Limits: {x.limitations}</div>
            </li>
          ))}
        </ul>
      )}
      <p className="m-0 t-meta" style={{ color: "var(--text-5)" }}>{r.notice ?? r.limitations} {r.performance.never}</p>
    </>
  ));
}
