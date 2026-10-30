"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { PreviewCard, PreviewMarketplace, PreviewMode, PreviewOption, PreviewStatus } from "@/lib/ceo";

/** The visual listing preview in the CEO chat (CMO 3.0 M4). An illustrative simulation of a search-result card for Amazon, Flipkart and Meesho: it is NOT the real marketplace page and
 * says so on the card. Everything it shows was sent in the card by the backend (the title text, the cut-off, the M3 score and the points it rests on, the compliance status); switching
 * marketplace, title or screen only changes what is shown, so it makes no request and calls no model. The product picture is the seller's own photo (fetched through the authenticated
 * image route) or a neutral placeholder; a picture is never generated. Price, rating and reviews are NOT simulated: the card shows plain grey bars where a real page would have them. */

const NAMES: Record<PreviewMarketplace, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
// The simulated page has its own fixed light palette (it stands for a marketplace page, not for Metrion): dark text on white, AA contrast.
const THEME: Record<PreviewMarketplace, { accent: string; link: string; layout: string }> = {
  AMAZON: { accent: "#C45500", link: "#0B5C6B", layout: "Amazon-style layout" },
  FLIPKART: { accent: "#1F5FD0", link: "#111827", layout: "Flipkart-style layout" },
  MEESHO: { accent: "#8B1E7A", link: "#111827", layout: "Meesho-style layout" },
};
const STATUS_WORD: Record<PreviewStatus, string> = { VISIBLE: "visible", CUT_OFF: "cut off", NOT_IN_TITLE: "not in this title" };
const STATUS_MARK: Record<PreviewStatus, string> = { VISIBLE: "✓", CUT_OFF: "…", NOT_IN_TITLE: "✗" };
const COMPLIANCE_WORD = { PASS: "PASS", FAIL: "FAIL", NOT_ASSESSED: "NOT ASSESSED" } as const;

function useProductImage(card: PreviewCard, loader?: (investigationId: string, attachmentId: string) => Promise<string>) {
  const loaderRef = useRef(loader); // read through a ref so a new function identity on every render never refetches the photo
  loaderRef.current = loader;
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const id = card.image?.attachmentId ?? null;
  useEffect(() => {
    if (!id || !loaderRef.current) return; // no photo, or no way to load it: the neutral placeholder stays
    let alive = true;
    let url: string | null = null;
    (async () => {
      try {
        url = await (loaderRef.current as (inv: string, a: string) => Promise<string>)(card.investigationId, id);
        if (alive) setSrc(url);
      } catch {
        if (alive) setFailed(true);
      }
    })();
    return () => {
      alive = false;
      if (url && url.startsWith("blob:") && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
    };
  }, [id, card.investigationId]);
  return { src, failed };
}

function Placeholder({ note }: { note: string }) {
  return (
    <div data-testid="preview-image-placeholder" role="img" aria-label="No product photo: neutral placeholder" title={note}
      className="flex h-full w-full flex-col items-center justify-center gap-1 text-center" style={{ background: "#E5E7EB", color: "#374151", fontSize: 11 }}>
      <svg aria-hidden width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#6B7280" strokeWidth="1.5"><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="9" cy="11" r="2" /><path d="M21 17l-5-5-6 6" /></svg>
      <span>No product photo</span>
    </div>
  );
}

function SearchResult({ card, option, marketplace, mode, image }: { card: PreviewCard; option: PreviewOption; marketplace: PreviewMarketplace; mode: PreviewMode; image: { src: string | null; failed: boolean } }) {
  const t = THEME[marketplace];
  const screen = option.modes[mode];
  const mobile = mode === "mobile";
  return (
    <div data-testid="preview-stage" data-mode={mode} data-marketplace={marketplace} className="mx-auto" style={{ width: "100%", maxWidth: mobile ? 340 : 720 }}>
      <div className="mb-1.5 flex items-center justify-between" style={{ fontSize: 11, color: "var(--text-6)" }}>
        <span>{t.layout} · {mobile ? "phone" : "desktop"} view</span>
        <span style={{ fontWeight: 700, color: "var(--warning)" }}>ILLUSTRATIVE SIMULATION</span>
      </div>
      <div style={{ background: "#FFFFFF", color: "#111827", border: `1px solid #D1D5DB`, borderTop: `4px solid ${t.accent}`, borderRadius: 8, padding: mobile ? 10 : 14, boxShadow: "0 1px 2px rgba(0,0,0,.12)" }}>
        <div className="flex gap-3" style={{ flexDirection: "row" }}>
          <div style={{ width: mobile ? 96 : 150, height: mobile ? 96 : 150, flex: "none", borderRadius: 6, overflow: "hidden", border: "1px solid #E5E7EB", background: "#F3F4F6" }}>
            {image.src && !image.failed ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img data-testid="preview-image" src={image.src} alt={card.image ? `Your product photo ${card.image.filename}` : "Your product photo"} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
            ) : (
              <Placeholder note={card.imageNote} />
            )}
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <p data-testid="preview-title" style={{ margin: 0, fontSize: mobile ? 14 : 17, lineHeight: 1.35, color: t.link, wordBreak: "break-word" }}>
              <span data-testid="preview-visible">{screen.visible}</span>
              {screen.truncated && <span aria-label="cut off here" style={{ color: "#4B5563" }}>…</span>}
            </p>
            <div aria-hidden className="mt-2 flex flex-col gap-1.5">
              <span style={{ height: 8, width: "38%", background: "#E5E7EB", borderRadius: 4 }} />
              <span style={{ height: 8, width: "55%", background: "#E5E7EB", borderRadius: 4 }} />
            </div>
            <p className="mt-1.5" style={{ margin: 0, marginTop: 6, fontSize: 10.5, color: "#4B5563" }}>Price, rating and reviews are not simulated.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

const chip = (on: boolean): React.CSSProperties => ({ border: `1px solid ${on ? "var(--accent)" : "var(--border-subtle)"}`, background: on ? "var(--fill-hover)" : "transparent", color: on ? "var(--accent)" : "var(--text-3)" });

export function ListingPreviewCard({ card, loadImage }: { card: PreviewCard; loadImage?: (investigationId: string, attachmentId: string) => Promise<string> }) {
  const available = card.sets.map((s) => s.marketplace);
  const [marketplace, setMarketplace] = useState<PreviewMarketplace>(available[0] ?? "AMAZON");
  const [mode, setMode] = useState<PreviewMode>(card.defaultMode ?? "mobile");
  const set = card.sets.find((s) => s.marketplace === marketplace) ?? card.sets[0];
  const [optionId, setOptionId] = useState<string>(set?.recommendedOptionId ?? set?.options[0]?.optionId ?? "");
  const option = set?.options.find((o) => o.optionId === optionId) ?? set?.options[0];
  const image = useProductImage(card, loadImage);
  const pick = useMemo(() => (m: PreviewMarketplace) => {
    setMarketplace(m);
    const s = card.sets.find((x) => x.marketplace === m);
    setOptionId(s?.recommendedOptionId ?? s?.options[0]?.optionId ?? "");
  }, [card.sets]);
  if (!set || !option) return null;
  const screen = option.modes[mode];
  const sc = option.score;
  const hard = option.hardFailures.length > 0;
  const comp = option.compliance;

  return (
    <section data-testid="listing-preview" aria-label="Listing preview" className="mt-2 flex w-full flex-col gap-3 rounded-2xl px-4 py-3.5" style={{ border: "1px solid var(--accent-border-subtle)", background: "var(--surface-2, transparent)" }}>
      <div>
        <div className="t-body font-semibold" style={{ color: "var(--text-2)" }}>Listing preview{card.product.name ? ` · ${card.product.name}` : ""}</div>
        <p className="mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }} data-testid="preview-notice">{card.notice}</p>
      </div>

      <div className="flex flex-wrap items-center gap-2" aria-label="Preview controls">
        <div role="tablist" aria-label="Marketplace" className="flex gap-1.5">
          {(["AMAZON", "FLIPKART", "MEESHO"] as PreviewMarketplace[]).map((m) => {
            const has = available.includes(m);
            return (
              <button key={m} type="button" role="tab" aria-selected={marketplace === m} disabled={!has} onClick={() => pick(m)} title={has ? undefined : `No saved ${NAMES[m]} titles yet. Ask the CEO to write them.`}
                className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={{ ...chip(marketplace === m && has), opacity: has ? 1 : 0.5 }}>
                {NAMES[m]}{has ? "" : " (no titles yet)"}
              </button>
            );
          })}
        </div>
        <div role="group" aria-label="Screen" className="flex gap-1.5">
          {(["mobile", "desktop"] as PreviewMode[]).map((m) => (
            <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)} className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(mode === m)}>
              {m === "mobile" ? "Mobile" : "Desktop"}
            </button>
          ))}
        </div>
      </div>

      <div role="tablist" aria-label="Title options" className="flex flex-wrap gap-1.5">
        {set.options.map((o) => {
          const label = `Option ${o.rank}`;
          const bad = o.hardFailures.length > 0;
          return (
            <button key={o.optionId} type="button" role="tab" aria-selected={o.optionId === option.optionId} onClick={() => setOptionId(o.optionId)} className="mt-focus rounded-md px-2.5 py-1 t-meta" style={chip(o.optionId === option.optionId)}>
              {label}
              {bad ? " · HARD FAIL" : o.score.status === "ASSESSED" ? ` · ${o.score.score}/100` : " · no score"}
              {o.optionId === set.recommendedOptionId ? " · recommended" : ""}
            </button>
          );
        })}
      </div>

      <SearchResult card={card} option={option} marketplace={marketplace} mode={mode} image={image} />

      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        <div data-testid="preview-score" className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
          <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Quality score (internal)</div>
          {hard ? (
            <p className="mt-1 t-meta" style={{ color: "var(--negative, #E5484D)" }} role="alert">HARD FAIL: never recommended whatever its score. {option.hardFailures.join(" ")}</p>
          ) : null}
          {sc.status === "ASSESSED" ? (
            <p className="mt-1 t-body" data-testid="preview-score-line" style={{ color: "var(--text-2)" }}>
              <strong>{sc.score}/100</strong> ({String(sc.band ?? "").replace("_", " ").toLowerCase()}) · {sc.assessablePoints} of 100 points assessable
            </p>
          ) : (
            <p className="mt-1 t-meta" data-testid="preview-score-line" style={{ color: "var(--warning)" }}>No overall score: {sc.note ?? "not enough confirmed evidence"}</p>
          )}
          <p className="mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>An internal listing-quality assessment, not a marketplace ranking, search position, conversion or sales prediction.</p>
          <div className="mt-2 t-meta" data-testid="preview-compliance" style={{ color: "var(--text-3)" }}>
            Marketplace rule (separate from the score): <strong style={{ color: comp.status === "PASS" ? "var(--positive)" : comp.status === "FAIL" ? "var(--negative, #E5484D)" : "var(--warning)" }}>{comp.status === "PASS" ? "✓ " : comp.status === "FAIL" ? "✗ " : "? "}{COMPLIANCE_WORD[comp.status]}</strong>
            {comp.detail ? <span> · {comp.detail}</span> : null}
          </div>
        </div>

        <div data-testid="preview-truncation" className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
          <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>What shows on {mode === "mobile" ? "mobile" : "desktop"}</div>
          <p className="mt-1 t-meta" style={{ color: "var(--text-3)" }}>
            {screen.truncated ? `Shows ${screen.visibleChars} of ${screen.totalChars} characters; the rest is hidden.` : `All ${screen.totalChars} characters show.`}
            {" "}Cut-off {screen.limit} characters, <strong>{screen.limitBasis === "VERIFIED" ? "VERIFIED display rule" : "ILLUSTRATIVE (not an official limit)"}</strong>.
          </p>
          {screen.truncated && (
            <p className="mt-1 t-meta" data-testid="preview-hidden" style={{ color: "var(--text-3)" }}>
              <span style={{ fontWeight: 700 }}>Hidden: </span><span style={{ textDecoration: "line-through", textDecorationStyle: "dotted" }}>{screen.hidden}</span>
            </p>
          )}
          <p className="mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>{screen.limitNote}</p>
        </div>
      </div>

      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
        <div data-testid="preview-keywords" className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
          <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Keywords for the title</div>
          {screen.keywords.length === 0 ? <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>Not assessed: no title-worthy keywords yet.</p> : (
            <ul className="m-0 mt-1 flex list-none flex-col gap-0.5 p-0">
              {screen.keywords.map((k) => <li key={k.keyword} className="t-meta" style={{ color: "var(--text-3)" }}><span aria-hidden>{STATUS_MARK[k.status]} </span>{k.keyword}: <strong>{STATUS_WORD[k.status]}</strong></li>)}
            </ul>
          )}
        </div>
        <div data-testid="preview-details" className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
          <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Your confirmed details</div>
          {screen.details.length === 0 ? <p className="mt-1 t-meta" style={{ color: "var(--text-6)" }}>Not assessed: no confirmed details yet.</p> : (
            <ul className="m-0 mt-1 flex list-none flex-col gap-0.5 p-0">
              {screen.details.map((d) => <li key={d.label} className="t-meta" style={{ color: "var(--text-3)" }}><span aria-hidden>{STATUS_MARK[d.status]} </span>{d.label} ({d.value}): <strong>{STATUS_WORD[d.status]}</strong></li>)}
            </ul>
          )}
        </div>
      </div>

      <div data-testid="preview-suggestions" className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
        <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Suggestions</div>
        <ul className="m-0 mt-1 flex list-disc flex-col gap-0.5 pl-4">{screen.suggestions.map((s) => <li key={s} className="t-meta" style={{ color: "var(--text-3)" }}>{s}</li>)}</ul>
      </div>

      {set.recommendation && <p className="m-0 t-meta" data-testid="preview-recommendation" style={{ color: "var(--text-3)" }}>{set.recommendation}</p>}
      <p className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>{card.imageNote}</p>
      <ul className="m-0 flex list-none flex-col gap-0.5 p-0">{card.limits.map((l) => <li key={l} className="t-meta-sm" style={{ color: "var(--text-6)" }}>{l}</li>)}</ul>
    </section>
  );
}
