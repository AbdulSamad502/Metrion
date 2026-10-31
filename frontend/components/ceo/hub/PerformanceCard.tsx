"use client";

import Link from "next/link";
import { useState } from "react";
import { performanceError, type PerformanceApi, type PerformanceCard as Card, type VersionAnalysis } from "@/lib/cmoPerformance";

/** Listing performance in the CEO chat (CMO 3.0 M8). The figures are the ones on the performance page, read from the seller's own imported reports; nothing is estimated and no difference is called an
 * effect of a change. A SKU link, go-live date or comparison length the seller states in chat appears here as a proposal with a Save button: typing "yes" saves nothing, and replacing an earlier
 * statement asks first. Reading and saving cost no AI credit. */

const MP: Record<string, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };
const chip: React.CSSProperties = { border: "1px solid var(--border-subtle)", color: "var(--text-3)" };
const act: React.CSSProperties = { border: "1px solid var(--accent)", color: "var(--accent)", background: "var(--fill-hover)" };

function Confirm({ card, api, disabled }: { card: Card; api?: PerformanceApi; disabled: boolean }) {
  const [state, setState] = useState<"idle" | "busy" | "saved">("idle");
  const [msg, setMsg] = useState<string | null>(null);
  const [ask, setAsk] = useState<string | null>(null);
  const p = card.proposal as Record<string, string | number>;
  const save = async (replace: boolean) => {
    if (!api || state === "busy") return;
    setState("busy"); setMsg(null);
    try {
      const r = card.view === "CONFIRM_LINK" ? await api.linkSku({ sku: String(p.sku), marketplace: String(p.marketplace), reportSku: String(p.reportSku), replace })
        : card.view === "CONFIRM_GOLIVE" ? await api.confirmGoLive({ generationId: String(p.generationId), wentLiveOn: String(p.wentLiveOn), replace })
        : await api.setWindow(p.days as number);
      setMsg(r.message); setAsk(null); setState("saved");
    } catch (e) {
      const err = performanceError(e);
      setState("idle");
      if (err.code === "LINK_EXISTS" || err.code === "GOLIVE_EXISTS") setAsk(err.message); else setMsg(err.message);
    }
  };
  return (
    <div className="flex flex-col gap-2" data-testid="performance-confirm">
      {state !== "saved" && <button type="button" disabled={!api || disabled || state === "busy"} className="mt-focus self-start rounded-md px-3 py-1.5 t-meta font-bold" style={act} onClick={() => void save(false)}>{state === "busy" ? "Saving…" : "Save"}</button>}
      {ask && <p role="alert" className="m-0 t-meta" style={{ color: "var(--text-2)" }}>{ask} <button type="button" className="mt-focus rounded-md px-2 py-0.5 font-bold" style={act} onClick={() => void save(true)}>Replace it</button></p>}
      <p role="status" className="m-0 t-meta" style={{ color: "var(--text-2)" }}>{state === "saved" ? "✓ " : ""}{msg}</p>
    </div>
  );
}

export function PerformanceCard({ card, api, disabled = false, onSend }: { card: Card; api?: PerformanceApi; disabled?: boolean; onSend: (text: string) => void }) {
  const v = card.view;
  const body = (() => {
    if (v === "CLARIFY") {
      const opts = (card.options ?? []) as { label: string }[];
      return (
        <>
          <p className="m-0 t-body-sm" style={{ color: "var(--text-2)" }}>{String(card.question)}</p>
          <div className="flex flex-wrap gap-2">{opts.map((o) => <button key={o.label} type="button" disabled={disabled} className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip} onClick={() => onSend(o.label)}>{o.label}</button>)}</div>
        </>
      );
    }
    if (v === "OVERVIEW") {
      const tiles = card.tiles ?? [];
      const per = card.period;
      return (
        <>
          {per && <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>{per.start} to {per.end} · {per.covered} of {per.days} days covered · {per.source}</p>}
          {tiles.length ? (
            <ul className="m-0 grid list-none gap-2 p-0" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
              {tiles.map((t) => <li key={t.key} className="rounded-md p-2 t-meta" style={box}><span style={{ color: "var(--text-3)" }}>{t.label}</span><br /><strong style={{ color: "var(--text-1)" }}>{t.value}</strong><br />
                <span style={{ color: "var(--text-4)" }}>{t.change}</span></li>)}
            </ul>
          ) : <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>No figure can be shown for this period yet (NOT ASSESSED).</p>}
          {(card.notShown ?? []).length > 0 && <p className="m-0 t-meta" style={{ color: "var(--text-4)" }}>Not shown: {(card.notShown ?? []).join(", ")} (not assessed or unavailable).</p>}
        </>
      );
    }
    if (v === "RANK") {
      const r = card.ranking as { label: string; ranked: { product: string; marketplace: string; text: string }[]; notAssessed: { product: string; reason: string }[]; note: string };
      return (
        <>
          {r.ranked.length > 0 && <ol className="m-0 list-decimal pl-5 t-meta" style={{ color: "var(--text-2)" }} aria-label={`Lowest ${r.label.toLowerCase()} first`}>{r.ranked.map((x) => <li key={`${x.product}${x.marketplace}`}>{x.product} · {MP[x.marketplace]} · {x.text}</li>)}</ol>}
          {r.notAssessed.map((x) => <p key={x.product} className="m-0 t-meta" style={{ color: "var(--text-4)" }}>○ {x.product}: not assessed. {x.reason}</p>)}
          <p className="m-0 t-meta" style={{ color: "var(--text-4)" }}>{r.note}</p>
        </>
      );
    }
    if (v === "VERSIONS") {
      const a = card.analysis as VersionAnalysis;
      return (
        <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--text-3)" }}>
          {a.versions.map((x) => <li key={x.versionId}>Version {x.number}: {x.state === "OBSERVED_COMPARABLE" ? "✓ compared" : x.state === "INCOMPARABLE" ? "✗ cannot compare" : "○ not assessed"}{x.wentLiveOn ? ` (live ${x.wentLiveOn})` : ""}</li>)}
        </ul>
      );
    }
    if (v === "MISSING") {
      const m = (card.missing ?? []) as string[];
      return m.length ? <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--text-2)" }} aria-label="Still missing">{m.map((x) => <li key={x}>✗ {x}</li>)}</ul> : <p className="m-0 t-meta" style={{ color: "var(--text-2)" }}>✓ Nothing is missing.</p>;
    }
    if (v === "CONFIRM_LINK" || v === "CONFIRM_GOLIVE" || v === "CONFIRM_WINDOW") {
      const p = card.proposal as Record<string, string | number>;
      return (
        <>
          <p className="m-0 t-body-sm" style={{ color: "var(--text-2)" }}>
            {v === "CONFIRM_LINK" && <>Connect <strong>{String(card.product)}</strong> ({MP[String(p.marketplace)]}) to the SKU <strong>{String(p.reportSku)}</strong> in your reports{card.replaces ? <>, replacing <strong>{String(card.replaces)}</strong></> : null}.</>}
            {v === "CONFIRM_GOLIVE" && <>Version <strong>{String(p.number)}</strong> of <strong>{String(card.product)}</strong> went live on <strong>{String(p.wentLiveOn)}</strong>{card.replaces ? <>, replacing {String(card.replaces)}</> : null}. Metrion cannot verify this date.</>}
            {v === "CONFIRM_WINDOW" && <>Compare listing versions over <strong>{String(p.days)}</strong>-day periods{card.current ? <> (now {String(card.current)})</> : null}.</>}
          </p>
          <Confirm card={card} api={api} disabled={disabled} />
        </>
      );
    }
    return <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>{String(card.message ?? "")}</p>;
  })();
  return (
    <div className="mt-2 flex flex-col gap-2 rounded-xl p-3" style={box} data-testid="listing-performance" data-view={v} role="group" aria-label="Listing performance">
      {body}
      <Link href={card.page} className="mt-focus self-start t-meta font-bold" style={{ color: "var(--accent)" }}>Open the performance page →</Link>
    </div>
  );
}
