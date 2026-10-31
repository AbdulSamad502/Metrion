"use client";

import { FRESH_WORD, LEVEL_WORD, STRENGTH_WORD, type Freshness, type NewsItem, type Opportunity, type Step } from "@/lib/cmoMarket";

/** News items and opportunities as the backend sent them (CMO 3.0 M10). Presentation only: nothing is computed, estimated or added. Every item shows its source links with publication dates, how fresh it is,
 * how strongly it relates to the seller's products and why, the evidence strength, what was reported (verified as reported, not as true) separately from a possible explanation (not measured), demand as
 * UNAVAILABLE, and next steps. Status is a word with a mark, never colour alone. Styles: the `cw-*` item language in cmo.css, on the Overview's theme tokens. */

const freshClass = (f: Freshness) => (f === "FRESH" ? "ov-pill ov-pill--good" : f === "RECENT" ? "ov-pill" : "ov-pill ov-pill--warn");
const levelClass = (l: string) => (l === "HIGH" ? "ov-pill ov-pill--brand" : "ov-pill");

function Sources({ list }: { list: { url: string; title: string | null; publishedAt: string | null; sourceClass: string | null }[] }) {
  if (list.length === 0) return <p className="cw-note">No citable source is stored.</p>;
  return (
    <ul className="cw-sources" aria-label="Sources">
      {list.map((s) => (
        <li key={s.url}>
          <a href={s.url} target="_blank" rel="noopener noreferrer" className="cw-link">{s.title || s.url}</a>{" "}
          <span>· {s.publishedAt ? s.publishedAt.slice(0, 10) : "date unknown"}{s.sourceClass === "OFFICIAL_MARKETPLACE" ? " · official marketplace source" : ""}</span>
        </li>
      ))}
    </ul>
  );
}

function Steps({ steps, onAsk }: { steps: Step[]; onAsk?: (text: string) => void }) {
  return (
    <div className="cw-block cw-quiet">
      <p className="cw-label">What you can do next</p>
      <ul className="cw-steps" aria-label="Next steps">
        {steps.map((s, i) => (
          <li key={i} className="cw-step" data-testid="step" data-agent={s.agent}>
            <span className="ov-pill">{s.agent === "YOU" ? "You" : s.agent}</span>
            <span>{s.text}</span>
            {s.ask && (onAsk
              ? <button type="button" className="mt-focus cw-ask" onClick={() => onAsk(s.ask as string)}>Ask: “{s.ask}”</button>
              : <span className="cw-note">Ask me: “{s.ask}”.</span>)}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function NewsList({ items, onAsk, focusId }: { items: NewsItem[]; onAsk?: (text: string) => void; focusId?: string }) {
  return (
    <ol className="cw-list" aria-label="Marketplace news">
      {items.map((n) => (
        <li key={n.id} className="cw-item" data-focus={focusId === n.id ? "true" : undefined} data-testid="news-item" data-freshness={n.freshness} data-relevance={n.relevance.level}>
          <div className="cw-head">
            <h3 className="cw-title">{n.headline}</h3>
            <div className="cw-pills">
              <span className={freshClass(n.freshness)} data-testid="freshness">{FRESH_WORD[n.freshness]}{n.ageDays !== null ? ` · ${n.ageDays} days old` : ""}</span>
              <span className={levelClass(n.relevance.level)} data-testid="relevance">Relevance to your products: {LEVEL_WORD[n.relevance.level]}</span>
            </div>
            <p className="cw-meta">
              {n.marketplaces.length ? n.marketplaces.join(", ") : "Marketplace not stated"} · published {n.publishedAt ?? "date unknown"} · {n.newsKind ?? "kind not stated"} · from your report of {n.reportDate}
              {n.seenInReports > 1 ? ` (seen in ${n.seenInReports} reports, shown once)` : ""}
            </p>
          </div>
          <div className="cw-block">
            <p className="cw-text">{n.summary}</p>
            <Sources list={n.sources} />
            <p className="cw-note">{n.sourceNote}</p>
          </div>
          <div className="cw-block">
            <p className="cw-label">What it could mean for a seller</p>
            <p className="cw-text">{n.impact}</p>
          </div>
          <div className="cw-block">
            <p className="cw-label">For your products</p>
            <p className="cw-text">{n.relevance.reason}</p>
            {n.relevance.affects.length > 0 && (
              <ul className="cw-sources" aria-label="Products it may affect">{n.relevance.affects.map((a) => <li key={a.sku} data-testid="affects">{a.name}: {LEVEL_WORD[a.level]}. {a.reason}</li>)}</ul>
            )}
          </div>
          {n.isStale && <p className="cw-caution" role="status" data-testid="stale-note">◆ This item is old or undated. Check that it is still current.</p>}
          {n.limitation && <p className="cw-note">{n.limitation}</p>}
          <Steps steps={n.recommendations} onAsk={onAsk} />
        </li>
      ))}
    </ol>
  );
}

export function OpportunityList({ items, onAsk }: { items: Opportunity[]; onAsk?: (text: string) => void }) {
  return (
    <ol className="cw-list" aria-label="Opportunities, most relevant first">
      {items.map((o) => (
        <li key={o.id} className="cw-item" data-testid="opportunity" data-strength={o.evidenceStrength} data-relevance={o.relevance.level}>
          <div className="cw-head">
            <h3 className="cw-title">{o.rank}. {o.title}</h3>
            <div className="cw-pills">
              <span className="ov-pill">{o.kind}</span>
              <span className={levelClass(o.relevance.level)} data-testid="relevance">Relevance: {LEVEL_WORD[o.relevance.level]}</span>
              <span className="ov-pill" data-testid="strength">Evidence: {STRENGTH_WORD[o.evidenceStrength]}</span>
              <span className={freshClass(o.observed.freshness)}>{FRESH_WORD[o.observed.freshness]}</span>
            </div>
          </div>
          <div className="cw-block">
            <p className="cw-label">Why it is relevant to you</p>
            <p className="cw-text">{o.relevance.reason}</p>
          </div>
          <div className="cw-block" data-testid="observed">
            <p className="cw-label">{o.observed.label}</p>
            <p className="cw-text">{o.observed.summary}</p>
            <p className="cw-note">{o.observed.independentSources ?? "?"} independent source(s) · freshest {o.observed.freshestPublishedAt ?? "date unknown"} · from your report of {o.observed.reportDate}</p>
            <Sources list={o.observed.sources} />
          </div>
          <div className="cw-block" data-testid="possible">
            <p className="cw-label">{o.possible.label}</p>
            <p className="cw-text">{o.possible.text}</p>
          </div>
          <div className="cw-block">
            <p className="cw-label">How strong the evidence is</p>
            <p className="cw-text">{STRENGTH_WORD[o.evidenceStrength]}. {o.evidenceStrengthWhy}</p>
          </div>
          <p className="cw-unavail" data-testid="demand"><span className="ov-pill">? Demand {o.demand.state}</span><span>{o.demand.note}</span></p>
          <p className="cw-note">{o.rankedBecause}</p>
          <Steps steps={o.recommendations} onAsk={onAsk} />
        </li>
      ))}
    </ol>
  );
}
