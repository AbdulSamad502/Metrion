"use client";

import Link from "next/link";
import { NewsList, OpportunityList } from "@/components/cmo/market/MarketItems";
import type { MarketCard } from "@/lib/cmoMarket";

/** Market opportunities and marketplace news in the CEO chat (CMO 3.0 M10). It shows only what the backend sent, read from the seller's saved reports, with sources, dates, freshness and relevance; a
 * step's suggested question is sent as a normal message only when the seller presses its button. It searches nothing, invents nothing and changes nothing on a marketplace. */

const box: React.CSSProperties = { border: "1px solid var(--border-subtle)" };

export function MarketIntelligenceCard({ card, disabled = false, onSend }: { card: MarketCard; disabled?: boolean; onSend: (text: string) => void }) {
  const ask = disabled ? undefined : onSend;
  if (card.view === "CLARIFY") {
    return (
      <div className="flex flex-wrap gap-2" data-testid="market-clarify" role="group" aria-label={card.question}>
        {(card.options ?? []).map((o) => <button key={o.label} type="button" disabled={disabled} onClick={() => onSend(o.label)} className="mt-focus rounded-md px-2.5 py-1 t-meta font-bold" style={{ border: "1px solid var(--accent)", color: "var(--accent)", background: "transparent" }}>{o.label}</button>)}
      </div>
    );
  }
  if (card.view === "REFUSED" || card.view === "NO_REPORT") {
    return (
      <div className="rounded-lg p-3 t-meta" style={box} data-testid="market-empty" data-view={card.view}>
        <p className="m-0" style={{ color: "var(--text-3)" }}>{card.message}</p>
        <p className="m-0 mt-1 t-meta-sm" style={{ color: "var(--text-6)" }}>Nothing is invented to fill the gap.</p>
      </div>
    );
  }
  const news = card.news ?? [];
  const opps = card.opportunities ?? [];
  return (
    <div className="flex flex-col gap-2.5" data-testid="market-card" data-view={card.view}>
      {card.state === "STALE_REPORTS" && card.message && <p role="status" className="m-0 t-meta" style={{ color: "var(--warning)" }} data-testid="market-stale">◆ {card.message}</p>}
      <p className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>From your {card.reportCount} saved report(s); newest {card.latestReportAt}. Nothing new was searched.</p>
      {opps.length > 0 && <OpportunityList items={opps} onAsk={ask} />}
      {card.view.startsWith("OPPORT") || card.view === "FOCUS" ? (opps.length === 0 && <p className="m-0 t-meta" style={{ color: "var(--text-3)" }} data-testid="no-opportunities">No saved finding relates to your products.</p>) : null}
      {news.length > 0 && <NewsList items={news} onAsk={ask} focusId={card.focusId} />}
      {["NEWS", "CHANGED", "AFFECTS", "ACTION"].includes(card.view) && news.length === 0 && <p className="m-0 t-meta" style={{ color: "var(--text-3)" }} data-testid="no-news">No marketplace news is stored{card.filter?.marketplace ? ` for ${card.filter.marketplace}` : ""}.</p>}
      {((card.moreNews ?? 0) > 0 || (card.moreOpportunities ?? 0) > 0) && <p className="m-0 t-meta-sm" style={{ color: "var(--text-6)" }}>More on the market page: {card.moreNews ?? 0} news, {card.moreOpportunities ?? 0} opportunities.</p>}
      <Link href={card.page} className="mt-focus self-start t-meta font-bold" style={{ color: "var(--accent)" }}>Open the market page →</Link>
    </div>
  );
}
