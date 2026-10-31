"use client";

import Link from "next/link";
import { useState } from "react";
import { SectionCard } from "@/components/cmo/showcaseUi";
import { NewsList, OpportunityList } from "@/components/cmo/market/MarketItems";
import { useLoad } from "@/components/cmo/performance/useLoad";
import { marketHandoff, MP_LABEL, type MarketApi, type Marketplace } from "@/lib/cmoMarket";

/** Market opportunities and marketplace news (CMO 3.0 M10). Everything here is read from market-trend reports the seller already saved, related to their own products and marketplaces by fixed rules.
 * Nothing is searched, estimated or invented; demand is always UNAVAILABLE; reading costs no AI credit. With no saved report the page says so. Filter by product and marketplace; hand any question to the CEO. */

const box: React.CSSProperties = { border: "1px solid var(--ov-line)" };

export function MarketDashboard({ api }: { api: MarketApi }) {
  const [sku, setSku] = useState("");
  const [mp, setMp] = useState("");
  const [tick, setTick] = useState(0);
  const { data, last, error } = useLoad(() => api.overview({ sku: sku || null, marketplace: mp || null }), `${sku}|${mp}#${tick}`);
  const products = (data ?? last)?.products ?? [];
  return (
    <div className="cw-page flex flex-col gap-5" data-testid="market-dashboard">
      <SectionCard title="Market opportunities and news" hint="From the market-trend reports you saved, related to your own products. Nothing new is searched and nothing is invented. Reading it uses no AI credit.">
        <div className="flex flex-wrap items-end gap-3 t-meta">
          <label className="flex flex-col gap-1">Product
            <select aria-label="Product" className="mt-focus rounded-md px-2 py-1.5" style={box} value={sku} onChange={(e) => setSku(e.target.value)}>
              <option value="">All my products</option>{products.map((p) => <option key={p.sku} value={p.sku}>{p.name}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">Marketplace
            <select aria-label="Marketplace" className="mt-focus rounded-md px-2 py-1.5" style={box} value={mp} onChange={(e) => setMp(e.target.value)}>
              <option value="">All marketplaces</option>{(Object.keys(MP_LABEL) as Marketplace[]).map((m) => <option key={m} value={m}>{MP_LABEL[m]}</option>)}
            </select>
          </label>
          <button type="button" className="mt-focus rounded-md px-3 py-1.5 font-bold" style={box} onClick={() => setTick((n) => n + 1)}>Reload</button>
          <Link href={marketHandoff(mp ? "CHANGED" : "OPPORTUNITIES", mp || null)} className="mt-focus font-bold" style={{ color: "var(--ov-brand-ink)" }} data-testid="ask-ceo">Ask the CEO about this →</Link>
        </div>
      </SectionCard>

      {error && !data && <p role="alert" className="m-0 t-body-sm" data-testid="market-error">{error}</p>}
      {!data && !error && <p role="status" className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="market-loading">Loading what your saved reports hold…</p>}

      {data && data.state === "NO_REPORT" && (
        <SectionCard title="Nothing saved yet">
          <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="market-empty">{data.message}</p>
          <p className="m-0 mt-1 t-meta" style={{ color: "var(--ov-ink-3)" }}>Metrion shows no news or opportunity it has not researched for you, and invents none.</p>
        </SectionCard>
      )}

      {data && data.state !== "NO_REPORT" && (
        <>
          {data.state === "STALE_REPORTS" && <p role="status" className="m-0 t-meta" style={{ color: "var(--ov-warn)" }} data-testid="market-stale">◆ {data.message}</p>}
          <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }}>Based on {data.reportCount} saved report{data.reportCount === 1 ? "" : "s"}; the newest is from {data.latestReportAt}. Fresh means published within {data.freshnessRules.freshDays} days, recent within {data.freshnessRules.recentDays}, as of {data.today}.</p>
          <SectionCard title={`Opportunities for your products (${data.opportunities.length})`} hint="Strongest relevance and evidence first. These are leads to check, not predictions: Metrion has no demand, search-volume or sales data.">
            {data.opportunities.length === 0 ? <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="no-opportunities">No saved finding relates to {sku || mp ? "this selection" : "your products"}. Nothing is made up to fill the space.</p> : <OpportunityList items={data.opportunities} />}
          </SectionCard>
          <SectionCard title={`Marketplace news (${data.news.length})`} hint="Newest first. Each item shows its source and date; anything old or undated is marked.">
            {data.news.length === 0 ? <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid="no-news">Your saved reports hold no marketplace news for this selection.{data.newsWithoutMarketplace > 0 ? ` ${data.newsWithoutMarketplace} item(s) name no marketplace.` : ""}</p> : <NewsList items={data.news} />}
          </SectionCard>
          <ul className="m-0 list-none p-0 t-meta-sm" style={{ color: "var(--ov-ink-3)" }}>{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </>
      )}
    </div>
  );
}
