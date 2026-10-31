"use client";

import { useState } from "react";
import { SectionCard } from "@/components/cmo/showcaseUi";
import { useLoad } from "@/components/cmo/performance/useLoad";
import { performanceError, type MappingItem, type PerformanceApi, type SkuCandidate } from "@/lib/cmoPerformance";

/** The seller's own statements that make a before/after view possible: which SKU in their reports is each product, the date each saved version went live, and how many days each comparison covers.
 * Metrion cannot see a marketplace, so none of this is ever assumed (not from when a listing was written, approved or copied). Statements are only added; changing an earlier one asks first and the earlier
 * one stays in the history. */

const MP: Record<string, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };
const today = () => new Date().toISOString().slice(0, 10);

function LinkRow({ item, api, onChanged }: { item: MappingItem; api: PerformanceApi; onChanged: () => void }) {
  const [cands, setCands] = useState<SkuCandidate[] | null>(null);
  const [pick, setPick] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [ask, setAsk] = useState<string | null>(null);
  const open = async () => { try { setCands((await api.candidates(item.marketplace)).candidates); } catch (e) { setMsg(performanceError(e).message); } };
  const save = async (replace: boolean) => {
    setMsg(null);
    try { const r = await api.linkSku({ sku: item.sku, marketplace: item.marketplace, reportSku: pick, replace }); setMsg(r.message); setAsk(null); setCands(null); onChanged(); } catch (e) {
      const err = performanceError(e);
      if (err.code === "LINK_EXISTS") setAsk(err.message); else setMsg(err.message);
    }
  };
  return (
    <div className="flex flex-col gap-1.5" data-testid="link-row">
      <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>
        {item.reportSku ? <>✓ Connected to <strong>{item.reportSku}</strong> in your reports (you confirmed it {item.linkConfirmedAt?.slice(0, 10)}).</> : <>✗ Not connected yet. Metrion does not guess which SKU in your reports is this product.</>}
        {" "}<button type="button" className="mt-focus rounded-md px-2 py-0.5 font-bold" style={box} onClick={() => void open()}>{item.reportSku ? "Change" : "Connect a SKU"}</button>
      </p>
      {cands && (
        <div className="flex flex-wrap items-center gap-2 t-meta">
          {cands.length === 0 ? <span style={{ color: "var(--text-4)" }}>No SKU found in your imported reports for {MP[item.marketplace]}. Import a report first.</span> : (
            <>
              <label>SKU in your reports <select aria-label={`SKU for ${item.product}`} className="mt-focus rounded-md px-2 py-1" style={box} value={pick} onChange={(e) => { setPick(e.target.value); setAsk(null); }}>
                <option value="">Choose…</option>{cands.map((c) => <option key={c.reportSku} value={c.reportSku}>{c.reportSku}{c.reportTitle ? ` — ${c.reportTitle}` : ""} ({c.rows} rows)</option>)}
              </select></label>
              <button type="button" disabled={!pick} className="mt-focus rounded-md px-2.5 py-1 font-bold" style={{ ...box, color: "var(--accent)" }} onClick={() => void save(false)}>Save</button>
            </>
          )}
        </div>
      )}
      {ask && (
        <p role="alert" className="m-0 t-meta" style={{ color: "var(--text-2)" }} data-testid="replace-ask">{ask}{" "}
          <button type="button" className="mt-focus rounded-md px-2 py-0.5 font-bold" style={{ ...box, color: "var(--accent)" }} onClick={() => void save(true)}>Replace it</button></p>
      )}
      {msg && <p role="status" className="m-0 t-meta" style={{ color: "var(--text-2)" }}>{msg}</p>}
      {item.history.links.length > 1 && (
        <details className="t-meta" style={{ color: "var(--text-4)" }}><summary className="mt-focus" style={{ cursor: "pointer" }}>History of this statement</summary>
          <ul className="m-0 list-none p-0">{item.history.links.map((h) => <li key={h.confirmedAt}>{h.confirmedAt.slice(0, 10)}: {h.reportSku}</li>)}</ul></details>
      )}
    </div>
  );
}

function GoLiveRow({ item, api, onChanged }: { item: MappingItem; api: PerformanceApi; onChanged: () => void }) {
  const [dates, setDates] = useState<Record<string, string>>({});
  const [msgs, setMsgs] = useState<Record<string, string>>({});
  const [asks, setAsks] = useState<Record<string, string>>({});
  const save = async (id: string, replace: boolean) => {
    try { const r = await api.confirmGoLive({ generationId: id, wentLiveOn: dates[id], replace }); setMsgs({ ...msgs, [id]: r.message }); setAsks({ ...asks, [id]: "" }); onChanged(); } catch (e) {
      const err = performanceError(e);
      if (err.code === "GOLIVE_EXISTS") setAsks({ ...asks, [id]: err.message }); else setMsgs({ ...msgs, [id]: err.message });
    }
  };
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0" aria-label={`Go-live dates for ${item.product}`}>
      {item.versions.map((v) => (
        <li key={v.versionId} className="t-meta" style={{ color: "var(--text-3)" }} data-testid="golive-row">
          <strong>Version {v.number}</strong> (written {v.createdAt}): {v.wentLiveOn ? <>✓ you said it went live on <strong>{v.wentLiveOn}</strong>.</> : <>✗ no go-live date confirmed. It is not assumed from when it was written, approved or copied.</>}
          <span className="ml-2 inline-flex flex-wrap items-center gap-1.5">
            <input aria-label={`Go-live date of version ${v.number}`} type="date" min={v.createdAt} max={today()} className="mt-focus rounded-md px-1.5 py-1" style={box} value={dates[v.versionId] ?? ""} onChange={(e) => setDates({ ...dates, [v.versionId]: e.target.value })} />
            <button type="button" disabled={!dates[v.versionId]} className="mt-focus rounded-md px-2.5 py-1 font-bold" style={{ ...box, color: "var(--accent)" }} onClick={() => void save(v.versionId, false)}>{v.wentLiveOn ? "Change date" : "Confirm date"}</button>
          </span>
          {asks[v.versionId] && <span role="alert" className="ml-1" style={{ color: "var(--text-2)" }}>{asks[v.versionId]} <button type="button" className="mt-focus rounded-md px-2 py-0.5 font-bold" style={{ ...box, color: "var(--accent)" }} onClick={() => void save(v.versionId, true)}>Replace it</button></span>}
          {msgs[v.versionId] && <span role="status" className="ml-1" style={{ color: "var(--text-2)" }}>{msgs[v.versionId]}</span>}
        </li>
      ))}
    </ul>
  );
}

export function ConfirmationsPanel({ api, onChanged }: { api: PerformanceApi; onChanged: () => void }) {
  const [tick, setTick] = useState(0);
  const { data, last, error: err } = useLoad(() => api.mappings(), `maps#${tick}`);
  const m = data ?? last; // a re-read after a save keeps the rows (and their confirmation messages) on screen
  const [days, setDays] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const changed = () => { setTick((n) => n + 1); onChanged(); };
  const saveWindow = async () => { setMsg(null); try { const r = await api.setWindow(Number(days)); setMsg(r.message); changed(); } catch (e) { setMsg(performanceError(e).message); } };
  if (err) return <SectionCard title="What I still need from you"><p role="alert" className="m-0 t-body-sm">{err}</p></SectionCard>;
  if (!m) return <SectionCard title="What I still need from you"><p role="status" className="m-0 t-meta" style={{ color: "var(--text-4)" }}>Loading…</p></SectionCard>;
  const [lo, hi] = m.windowBounds;
  return (
    <SectionCard title="What I still need from you" hint="To compare a listing version before and after it went live I need three statements only you can make. You can also tell me any of them in the CEO chat.">
      <div className="flex flex-col gap-3">
        {m.missing.length > 0 ? (
          <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--text-2)" }} data-testid="missing-list" aria-label="Still missing">{m.missing.map((x) => <li key={x}>✗ {x}</li>)}</ul>
        ) : <p className="m-0 t-meta" style={{ color: "var(--text-2)" }} data-testid="nothing-missing">✓ Nothing is missing: every product has a confirmed SKU and every version a go-live date.</p>}
        <div className="rounded-xl p-3" style={box} data-testid="window-box">
          <strong className="t-body-sm" style={{ color: "var(--text-1)" }}>Comparison period</strong>
          <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>{m.windowDays ? <>Each version is compared over {m.windowDays} days before and {m.windowDays} days after its go-live date (set by {m.windowSetBy === "YOU" ? "you" : "your administrator"}).</> : "Not set yet. There is no default: choose how many days each period covers."}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2 t-meta">
            <label>Days ({lo} to {hi}) <input aria-label="Comparison period in days" type="number" inputMode="numeric" min={lo} max={hi} step={1} className="mt-focus ml-1 w-20 rounded-md px-2 py-1" style={box} value={days} onChange={(e) => setDays(e.target.value)} /></label>
            <button type="button" disabled={!/^\d+$/.test(days) || Number(days) < lo || Number(days) > hi} className="mt-focus rounded-md px-2.5 py-1 font-bold" style={{ ...box, color: "var(--accent)" }} onClick={() => void saveWindow()}>Save</button>
            {msg && <span role="status" style={{ color: "var(--text-2)" }}>{msg}</span>}
          </div>
        </div>
        {m.items.length === 0 ? <p className="m-0 t-meta" style={{ color: "var(--text-3)" }} data-testid="no-listings">You have no saved listing yet. Ask the CEO to “write my complete listing”, then come back here.</p> : m.items.map((item) => (
          <div key={`${item.sku}|${item.marketplace}`} className="flex flex-col gap-2 rounded-xl p-3" style={box} data-testid="mapping-item" data-status={item.status}>
            <strong className="t-body-sm" style={{ color: "var(--text-1)" }}>{item.product} · {MP[item.marketplace]} · {item.status === "COMPLETE" ? "✓ Complete" : "! Needs your confirmation"}</strong>
            <LinkRow item={item} api={api} onChanged={changed} />
            <GoLiveRow item={item} api={api} onChanged={changed} />
          </div>
        ))}
      </div>
    </SectionCard>
  );
}
