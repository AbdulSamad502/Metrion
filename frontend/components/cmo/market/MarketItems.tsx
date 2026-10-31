"use client";

import { FRESH_WORD, LEVEL_WORD, STRENGTH_WORD, type NewsItem, type Opportunity, type Step } from "@/lib/cmoMarket";

/** News items and opportunities as the backend sent them (CMO 3.0 M10). Presentation only: nothing is computed, estimated or added. Every item shows its source links with publication dates, how fresh it is,
 * how strongly it relates to the seller's products and why, the evidence strength, what was reported (verified as reported, not as true) separately from a possible explanation (not measured), demand as
 * UNAVAILABLE, and next steps. Status is a word with a mark, never colour alone. */

const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };
const chip: React.CSSProperties = { border: "1px solid var(--border-subtle)", color: "var(--text-3)" };

function Sources({ list }: { list: { url: string; title: string | null; publishedAt: string | null; sourceClass: string | null }[] }) {
  if (list.length === 0) return <p className="m-0 t-meta" style={{ color: "var(--text-4)" }}>No citable source is stored.</p>;
  return (
    <ul className="m-0 list-none p-0 t-meta" aria-label="Sources">
      {list.map((s) => (
        <li key={s.url}>
          <a href={s.url} target="_blank" rel="noopener noreferrer" className="mt-focus font-bold" style={{ color: "var(--accent)" }}>{s.title || s.url}</a>{" "}
          <span style={{ color: "var(--text-4)" }}>· {s.publishedAt ? s.publishedAt.slice(0, 10) : "date unknown"}{s.sourceClass === "OFFICIAL_MARKETPLACE" ? " · official marketplace source" : ""}</span>
        </li>
      ))}
    </ul>
  );
}

function Steps({ steps, onAsk }: { steps: Step[]; onAsk?: (text: string) => void }) {
  return (
    <ul className="m-0 list-none p-0 t-meta" style={{ color: "var(--text-3)" }} aria-label="Next steps">
      {steps.map((s, i) => (
        <li key={i} data-testid="step" data-agent={s.agent}>
          <strong>{s.agent === "YOU" ? "You" : s.agent}:</strong> {s.text}
          {s.ask && (onAsk
            ? <> <button type="button" className="mt-focus rounded-md px-2 py-0.5 font-bold" style={chip} onClick={() => onAsk(s.ask as string)}>Ask: “{s.ask}”</button></>
            : <span style={{ color: "var(--text-4)" }}> Ask me: “{s.ask}”.</span>)}
        </li>
      ))}
    </ul>
  );
}

export function NewsList({ items, onAsk, focusId }: { items: NewsItem[]; onAsk?: (text: string) => void; focusId?: string }) {
  return (
    <ol className="m-0 flex list-none flex-col gap-2.5 p-0" aria-label="Marketplace news">
      {items.map((n) => (
        <li key={n.id} className="flex flex-col gap-1.5 rounded-xl p-3 t-meta" style={{ ...box, ...(focusId === n.id ? { borderColor: "var(--accent)" } : {}) }} data-testid="news-item" data-freshness={n.freshness} data-relevance={n.relevance.level}>
          <div className="flex flex-wrap items-center gap-2">
            <strong className="t-body-sm" style={{ color: "var(--text-1)" }}>{n.headline}</strong>
            <span className="rounded-md px-1.5 py-0.5 font-bold" style={chip} data-testid="freshness">{FRESH_WORD[n.freshness]}{n.ageDays !== null ? ` · ${n.ageDays} days old` : ""}</span>
            <span className="rounded-md px-1.5 py-0.5 font-bold" style={chip} data-testid="relevance">Relevance to your products: {LEVEL_WORD[n.relevance.level]}</span>
          </div>
          <div style={{ color: "var(--text-3)" }}>
            {n.marketplaces.length ? n.marketplaces.join(", ") : "Marketplace not stated"} · published {n.publishedAt ?? "date unknown"} · {n.newsKind ?? "kind not stated"} · from your report of {n.reportDate}
            {n.seenInReports > 1 ? ` (seen in ${n.seenInReports} reports, shown once)` : ""}
          </div>
          <p className="m-0" style={{ color: "var(--text-2)" }}>{n.summary}</p>
          <Sources list={n.sources} />
          <p className="m-0" style={{ color: "var(--text-4)" }}>{n.sourceNote}</p>
          <p className="m-0" style={{ color: "var(--text-3)" }}><strong>What it could mean for a seller:</strong> {n.impact}</p>
          <p className="m-0" style={{ color: "var(--text-3)" }}><strong>For your products:</strong> {n.relevance.reason}</p>
          {n.relevance.affects.length > 0 && (
            <ul className="m-0 list-none p-0" style={{ color: "var(--text-3)" }} aria-label="Products it may affect">{n.relevance.affects.map((a) => <li key={a.sku} data-testid="affects">{a.name}: {LEVEL_WORD[a.level]}. {a.reason}</li>)}</ul>
          )}
          {n.isStale && <p className="m-0" role="status" style={{ color: "var(--warning)" }} data-testid="stale-note">◆ This item is old or undated. Check that it is still current.</p>}
          {n.limitation && <p className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>{n.limitation}</p>}
          <Steps steps={n.recommendations} onAsk={onAsk} />
        </li>
      ))}
    </ol>
  );
}

export function OpportunityList({ items, onAsk }: { items: Opportunity[]; onAsk?: (text: string) => void }) {
  return (
    <ol className="m-0 flex list-none flex-col gap-2.5 p-0" aria-label="Opportunities, most relevant first">
      {items.map((o) => (
        <li key={o.id} className="flex flex-col gap-1.5 rounded-xl p-3 t-meta" style={box} data-testid="opportunity" data-strength={o.evidenceStrength} data-relevance={o.relevance.level}>
          <div className="flex flex-wrap items-center gap-2">
            <strong className="t-body-sm" style={{ color: "var(--text-1)" }}>{o.rank}. {o.title}</strong>
            <span className="rounded-md px-1.5 py-0.5 font-bold" style={chip}>{o.kind}</span>
            <span className="rounded-md px-1.5 py-0.5 font-bold" style={chip} data-testid="relevance">Relevance: {LEVEL_WORD[o.relevance.level]}</span>
            <span className="rounded-md px-1.5 py-0.5 font-bold" style={chip} data-testid="strength">Evidence: {STRENGTH_WORD[o.evidenceStrength]}</span>
            <span className="rounded-md px-1.5 py-0.5 font-bold" style={chip}>{FRESH_WORD[o.observed.freshness]}</span>
          </div>
          <p className="m-0" style={{ color: "var(--text-3)" }}><strong>Why it is relevant to you:</strong> {o.relevance.reason}</p>
          <div data-testid="observed">
            <strong style={{ color: "var(--text-2)" }}>{o.observed.label}</strong>
            <p className="m-0" style={{ color: "var(--text-2)" }}>{o.observed.summary}</p>
            <p className="m-0" style={{ color: "var(--text-4)" }}>{o.observed.independentSources ?? "?"} independent source(s) · freshest {o.observed.freshestPublishedAt ?? "date unknown"} · from your report of {o.observed.reportDate}</p>
            <Sources list={o.observed.sources} />
          </div>
          <p className="m-0" style={{ color: "var(--text-3)" }} data-testid="possible"><strong>{o.possible.label}:</strong> {o.possible.text}</p>
          <p className="m-0" style={{ color: "var(--text-3)" }}><strong>How strong the evidence is:</strong> {STRENGTH_WORD[o.evidenceStrength]}. {o.evidenceStrengthWhy}</p>
          <p className="m-0" style={{ color: "var(--warning)" }} data-testid="demand">? Demand {o.demand.state}: {o.demand.note}</p>
          <p className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>{o.rankedBecause}</p>
          <Steps steps={o.recommendations} onAsk={onAsk} />
        </li>
      ))}
    </ol>
  );
}
