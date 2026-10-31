"use client";

import { useState } from "react";
import type { BuyerQuestion, MarketReadiness, PreviewMarketplace, ReadinessCard as Card, ReadinessItem } from "@/lib/ceo";

/** Buyer questions and the listing-readiness checklist in the CEO chat (CMO 3.0 M5). It shows only what the backend sent: each question with the seller's own answer and its source (or NOT
 * CONFIRMED), each requirement with its status and points, the score with the points it rests on, and what to do next. Switching view or marketplace changes what is shown and makes no
 * request. A seller's answer to a question is sent as the one fixed sentence the CEO understands ("For my <product>, <topic> is: <answer>"), exactly as if they had typed it, so the same
 * checks run. Every status is a word with a mark, never colour alone; unknown requirements are shown as NOT ASSESSED and never as passed. */

const NAMES: Record<PreviewMarketplace, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
const ITEM_WORD: Record<ReadinessItem["status"], string> = { DONE: "✓ DONE", MISSING: "○ MISSING", BLOCKED: "✗ BLOCKED", NOT_ASSESSED: "? NOT ASSESSED" };
const ITEM_COLOR: Record<ReadinessItem["status"], string> = { DONE: "var(--positive)", MISSING: "var(--warning)", BLOCKED: "var(--negative, #E5484D)", NOT_ASSESSED: "var(--text-6)" };
const VERDICT_WORD: Record<MarketReadiness["verdict"], string> = { BLOCKED: "BLOCKED", NOT_READY: "NOT READY", DRAFT_READY_NOT_VERIFIED: "DRAFT READY, NOT VERIFIED", READY: "READY" };
const Q_WORD: Record<BuyerQuestion["status"], string> = { CONFIRMED: "✓ Answered from your facts", NOT_CONFIRMED: "? NOT CONFIRMED", SELLER_UNKNOWN: "○ You said it is not confirmed" };
const IMPORTANCE: Record<BuyerQuestion["importance"], string> = { ESSENTIAL: "essential detail", LIKELY: "commonly asked", COMPETITOR_RELEVANT: "a tracked competitor emphasises this" };
const chip = (on: boolean): React.CSSProperties => ({ border: `1px solid ${on ? "var(--accent)" : "var(--border-subtle)"}`, background: on ? "var(--fill-hover)" : "transparent", color: on ? "var(--accent)" : "var(--text-3)" });

function Question({ q, product, disabled, onSend }: { q: BuyerQuestion; product: string; disabled: boolean; onSend: (text: string) => void }) {
  const [draft, setDraft] = useState("");
  const open = q.status !== "CONFIRMED";
  const id = `answer-${q.id}`;
  return (
    <li data-testid={`question-${q.id}`} className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
      <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>{q.question}</div>
      <div className="t-meta-sm" style={{ color: "var(--text-6)" }}>{IMPORTANCE[q.importance]}</div>
      <div className="mt-1 t-meta" style={{ color: q.status === "CONFIRMED" ? "var(--positive)" : "var(--warning)", fontWeight: 700 }}>{Q_WORD[q.status]}</div>
      {q.status === "CONFIRMED" && q.answer && (
        <p className="m-0 mt-1 t-meta" style={{ color: "var(--text-3)" }}>
          You told me: “{q.answer}” <span className="t-meta-sm" style={{ color: "var(--text-6)" }}>({q.source?.origin}, {q.source?.at}; not checked by Metrion)</span>
        </p>
      )}
      {open && q.ask && <p className="m-0 mt-1 t-meta" style={{ color: "var(--text-3)" }}>{q.ask}</p>}
      <p className="m-0 mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>{q.listingUse}</p>
      {open && (
        <form className="mt-2 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (draft.trim() && !disabled) { onSend(`For my ${product}, ${q.topic.toLowerCase()} is: ${draft.trim()}`); setDraft(""); } }}>
          <label htmlFor={id} className="sr-only">Your answer about {q.topic.toLowerCase()}</label>
          <input id={id} value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={200} disabled={disabled} placeholder="Your answer (say “not tested” if you do not know)"
            className="mt-focus rounded-md px-2 py-1 t-meta" style={{ border: "1px solid var(--border-subtle)", background: "transparent", color: "var(--text-2)", minWidth: 220, flex: 1 }} />
          <button type="submit" disabled={disabled || !draft.trim()} className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(false)}>Save answer</button>
        </form>
      )}
    </li>
  );
}

function Market({ m }: { m: MarketReadiness }) {
  const sc = m.score;
  return (
    <div data-testid="readiness-market" data-marketplace={m.marketplace} className="flex flex-col gap-2.5">
      <div className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
        <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Readiness for {NAMES[m.marketplace]}</div>
        <p data-testid="readiness-score" className="m-0 mt-1 t-body" style={{ color: "var(--text-2)" }}>
          {sc.status === "ASSESSED" ? <><strong>{sc.score}/100</strong> · {sc.assessablePoints} of 100 points assessable</> : <span style={{ color: "var(--warning)" }}>No readiness score: {sc.note}</span>}
        </p>
        <p className="m-0 mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>{sc.note}</p>
        <p data-testid="readiness-verdict" className="m-0 mt-1 t-meta" style={{ color: m.verdict === "BLOCKED" ? "var(--negative, #E5484D)" : "var(--text-3)" }}><strong>{VERDICT_WORD[m.verdict]}.</strong> {m.verdictText}</p>
        <p className="m-0 mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>{m.counts.done} done · {m.counts.missing} missing · {m.counts.blocked} blocked · {m.counts.notAssessed} not assessed</p>
      </div>
      {m.imageQuality && (
        <div data-testid="readiness-image-quality" data-state={m.imageQuality.state} className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
          <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>Image quality (shown beside readiness)</div>
          <p className="m-0 mt-1 t-meta" style={{ color: m.imageQuality.state === "REVIEWED" ? "var(--text-3)" : "var(--warning)" }}>{m.imageQuality.state === "NOT_ASSESSED" ? "? NOT ASSESSED. " : ""}{m.imageQuality.message}</p>
          <p className="m-0 mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }}>{m.imageQuality.note}</p>
        </div>
      )}
      {m.nextActions.length > 0 && (
        <div data-testid="readiness-actions" className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
          <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>What to do next</div>
          <ol className="m-0 mt-1 flex list-decimal flex-col gap-0.5 pl-5">{m.nextActions.map((a) => <li key={a.id} className="t-meta" style={{ color: "var(--text-3)" }}>{a.status === "BLOCKED" ? "Fix first: " : ""}{a.action}</li>)}</ol>
        </div>
      )}
      {m.categories.map((c) => (
        <div key={c.id} data-testid={`category-${c.id}`} className="rounded-lg p-3" style={{ border: "1px solid var(--border-subtle)" }}>
          <div className="t-meta font-bold" style={{ color: "var(--text-2)" }}>{c.label} · {c.status === "ASSESSED" ? `${c.earned}/${c.assessable} points` : "not assessed"}</div>
          <ul className="m-0 mt-1 flex list-none flex-col gap-1.5 p-0">
            {c.items.map((i) => (
              <li key={i.id} data-testid={`item-${i.id}`} className="t-meta" style={{ color: "var(--text-3)" }}>
                <span style={{ color: ITEM_COLOR[i.status], fontWeight: 700 }}>{ITEM_WORD[i.status]}</span> {i.label}
                {i.status === "NOT_ASSESSED" ? "" : i.max > 0 ? ` (${i.earned}/${i.max})` : ""}
                <div className="t-meta-sm" style={{ color: "var(--text-6)" }}>{i.detail}{i.action ? ` Next: ${i.action}` : ""}</div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function ReadinessCard({ card, disabled = false, onSend }: { card: Card; disabled?: boolean; onSend: (text: string) => void }) {
  const [view, setView] = useState<Card["view"]>(card.view);
  const marketplaces = card.readiness.marketplaces.map((m) => m.marketplace);
  const [mp, setMp] = useState<PreviewMarketplace>(card.defaultMarketplace);
  const market = card.readiness.marketplaces.find((m) => m.marketplace === mp) ?? card.readiness.marketplaces[0];
  const c = card.questions.counts;
  return (
    <section data-testid="readiness-card" aria-label="Buyer questions and listing readiness" className="mt-2 flex w-full flex-col gap-3 rounded-2xl px-4 py-3.5" style={{ border: "1px solid var(--accent-border-subtle)" }}>
      <div>
        <div className="t-body font-semibold" style={{ color: "var(--text-2)" }}>{card.product.name}: buyer questions and listing readiness</div>
        <p className="mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }} data-testid="readiness-notice">{card.notice}</p>
      </div>
      <div role="tablist" aria-label="View" className="flex gap-1.5">
        {([["questions", "Buyer questions"], ["readiness", "Listing readiness"]] as const).map(([v, label]) => (
          <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)} className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(view === v)}>{label}</button>
        ))}
      </div>
      {view === "questions" ? (
        <div className="flex flex-col gap-2.5">
          <p data-testid="questions-summary" className="m-0 t-meta" style={{ color: "var(--text-3)" }}>{c.CONFIRMED} of {card.questions.questions.length} answered from your facts · {c.NOT_CONFIRMED} NOT CONFIRMED · {c.SELLER_UNKNOWN} you said not confirmed</p>
          <ul className="m-0 flex list-none flex-col gap-2 p-0" aria-label="Buyer questions">
            {card.questions.questions.map((q) => <Question key={q.id} q={q} product={card.product.name} disabled={disabled} onSend={onSend} />)}
          </ul>
          {card.questions.limits.map((l) => <p key={l} className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>{l}</p>)}
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">
          <div role="tablist" aria-label="Marketplace" className="flex gap-1.5">
            {marketplaces.map((m) => <button key={m} type="button" role="tab" aria-selected={mp === m} onClick={() => setMp(m)} className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={chip(mp === m)}>{NAMES[m]}</button>)}
          </div>
          {market && <Market m={market} />}
          {card.readiness.limits.map((l) => <p key={l} className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>{l}</p>)}
        </div>
      )}
    </section>
  );
}
