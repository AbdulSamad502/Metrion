"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useLoad } from "@/components/cmo/performance/useLoad";
import { FRESH_WORD, MARKET_PAGE, type MarketApi } from "@/lib/cmoMarket";
import { IMAGES_PAGE, MARKETPLACE_LABEL, type ImagesApi } from "@/lib/cmoImages";
import { describeChange, formatMetric, PERFORMANCE_PAGE, type MetricKey, type PerformanceApi } from "@/lib/cmoPerformance";

/** The top of the CMO workspace: three lanes (listing performance, product images, market), each a short read-only summary of what its own page holds, with the source, the period and the status of
 * every figure, and a link in. Every value is read from the same routes as the full pages; nothing here adds, compares or estimates a figure. A lane that has nothing yet says so and what to do. */

function Lane({ id, title, status, source, href, cta, children }: { id: string; title: string; status: ReactNode; source: ReactNode; href: string; cta: string; children: ReactNode }) {
  return (
    <section className="ov-card ov-rise flex min-w-0 flex-col gap-3" aria-label={title} data-testid={`lane-${id}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="m-0 t-body-sm font-bold" style={{ color: "var(--ov-ink)" }}>{title}</h2>
        <span className="t-meta font-bold" style={{ color: "var(--ov-ink-2)" }} data-testid={`lane-${id}-status`}>{status}</span>
      </header>
      <div className="flex flex-1 flex-col gap-2">{children}</div>
      <p className="m-0 t-meta" style={{ color: "var(--ov-ink-3)" }}>{source}</p>
      <Link href={href} className="mt-focus self-start t-meta font-bold" style={{ color: "var(--ov-brand-ink)" }}>{cta} <span className="mt-arrow" aria-hidden="true">→</span></Link>
    </section>
  );
}

const Fact = ({ label, value, note, testid }: { label: string; value: ReactNode; note?: ReactNode; testid?: string }) => (
  <div className="flex flex-col" data-testid={testid}>
    <span className="t-meta" style={{ color: "var(--ov-ink-3)" }}>{label}</span>
    <strong style={{ color: "var(--ov-ink)", fontSize: 20, fontVariantNumeric: "tabular-nums" }}>{value}</strong>
    {note && <span className="t-meta" style={{ color: "var(--ov-ink-2)" }}>{note}</span>}
  </div>
);
const Muted = ({ children, testid }: { children: ReactNode; testid?: string }) => <p className="m-0 t-meta" style={{ color: "var(--ov-ink-2)" }} data-testid={testid}>{children}</p>;
const Failed = ({ what }: { what: string }) => <p role="alert" className="m-0 t-meta" style={{ color: "var(--ov-bad)" }}>✗ {what} could not be read just now. Nothing was changed.</p>;

const HEADLINE: MetricKey[] = ["sales", "orders", "ctr"];

function PerformanceLane({ api }: { api: PerformanceApi }) {
  const { data: d, error } = useLoad(() => api.dashboard({}), "overview");
  const open = { href: PERFORMANCE_PAGE, cta: "Open listing performance" };
  if (error && !d) return <Lane id="performance" title="Listing performance" status="UNAVAILABLE" source="Your imported performance reports." {...open}><Failed what="Your performance" /></Lane>;
  if (!d) return <Lane id="performance" title="Listing performance" status="Loading…" source="Your imported performance reports." {...open}><Muted>Loading…</Muted></Lane>;
  const none = !d.dataSpan.lastImportAt;
  return (
    <Lane id="performance" title="Listing performance" status={none ? "○ NO REPORT YET" : d.current.complete ? "● CURRENT" : "◐ PARTIAL"}
      source={none ? "Import a marketplace report to see this." : `Source: your imported reports. Period ${d.current.periodStart} to ${d.current.periodEnd}, ${d.current.coveredDays} of ${d.current.days} days covered. Last import ${d.dataSpan.lastImportAt?.slice(0, 10)}.`} {...open}>
      {none ? <Muted testid="performance-empty">No performance report is imported yet, so every figure stays unavailable. Nothing is estimated.</Muted> : (
        HEADLINE.map((k) => {
          const m = d.current.metrics[k];
          return <Fact key={k} testid={`perf-${k}`} label={k === "sales" ? "Sales" : k === "orders" ? "Orders" : "Click-through rate"}
            value={m.state === "AVAILABLE" && m.value !== null ? formatMetric(k, m.value) : "Unavailable"} note={m.state === "AVAILABLE" ? describeChange(k, d.comparison[k]) : m.reason} />;
        })
      )}
    </Lane>
  );
}

function ImagesLane({ api }: { api: ImagesApi }) {
  const { data, error } = useLoad(async () => {
    const list = await api.products();
    for (const p of list.products) {
      const set = p.sets.find((s) => s.images > 0);
      if (set) return { list, page: await api.page(p.sku, set.marketplace) };
    }
    return { list, page: null };
  }, "overview");
  const open = { href: IMAGES_PAGE, cta: "Open product images" };
  if (error && !data) return <Lane id="images" title="Product images" status="UNAVAILABLE" source="Your own uploaded pictures." {...open}><Failed what="Your pictures" /></Lane>;
  if (!data) return <Lane id="images" title="Product images" status="Loading…" source="Your own uploaded pictures." {...open}><Muted>Loading…</Muted></Lane>;
  const page = data.page;
  if (!page) return <Lane id="images" title="Product images" status="○ NO PICTURES YET" source="Upload your product pictures to see this." {...open}><Muted testid="images-empty">No pictures are attached to any product yet. Missing pictures are never counted as a pass.</Muted></Lane>;
  const r = page.review;
  const top = r?.report.findings[0];
  return (
    <Lane id="images" title="Product images" status={!r ? "○ NOT REVIEWED" : r.isCurrent ? "● CURRENT" : "◆ OUT OF DATE"}
      source={`Source: your own pictures of ${page.product.name} on ${MARKETPLACE_LABEL[page.marketplace]}, measured by fixed rules (no AI model). Image quality only; marketplace requirements ${page.compliance.status === "NOT_ASSESSED" ? "NOT ASSESSED" : "checked"}.`} {...open}>
      <Fact testid="images-score" label="Overall image quality" value={r ? (r.report.score === null ? "Score withheld" : `${r.report.score} / 100`) : "Not reviewed"} note={r ? `Reviewed ${r.createdAt.slice(0, 10)} · ${page.images.length} pictures` : `${page.images.length} pictures attached`} />
      {top && <Fact testid="images-top" label={`Most important to improve (${top.severity})`} value={<span style={{ fontSize: 14 }}>{top.problem}</span>} note={top.recommendation} />}
      {!r && <Muted>These pictures have not been reviewed yet. Open the page and press Review.</Muted>}
    </Lane>
  );
}

function MarketLane({ api }: { api: MarketApi }) {
  const { data: d, error } = useLoad(() => api.overview({}), "overview");
  const open = { href: MARKET_PAGE, cta: "Open market and news" };
  if (error && !d) return <Lane id="market" title="Market opportunities and news" status="UNAVAILABLE" source="Your saved market-trend reports." {...open}><Failed what="Your saved market reports" /></Lane>;
  if (!d) return <Lane id="market" title="Market opportunities and news" status="Loading…" source="Your saved market-trend reports." {...open}><Muted>Loading…</Muted></Lane>;
  if (d.state === "NO_REPORT") return <Lane id="market" title="Market opportunities and news" status="○ NO REPORT YET" source="Ask the CEO to research market trends; that is a separate paid step you approve first." {...open}><Muted testid="market-lane-empty">{d.message}</Muted></Lane>;
  const opp = d.opportunities[0];
  const news = d.news[0];
  return (
    <Lane id="market" title="Market opportunities and news" status={d.state === "STALE_REPORTS" ? "◆ OLD REPORTS" : "● CURRENT"}
      source={`Source: ${d.reportCount} saved market-trend report${d.reportCount === 1 ? "" : "s"}, newest ${d.latestReportAt}. Demand is UNAVAILABLE: Metrion holds no search or sales data.`} {...open}>
      <Fact testid="market-counts" label="Related to your products" value={`${d.opportunities.length} opportunities · ${d.news.length} news items`} />
      {opp && <Fact testid="market-top-opportunity" label={`Top opportunity (relevance ${opp.relevance.level}, evidence ${opp.evidenceStrength})`} value={<span style={{ fontSize: 14 }}>{opp.title}</span>} />}
      {news && <Fact testid="market-top-news" label={`Latest news · ${FRESH_WORD[news.freshness]}${news.publishedAt ? ` · ${news.publishedAt}` : ""}`} value={<span style={{ fontSize: 14 }}>{news.headline}</span>} note={news.sourceNote} />}
    </Lane>
  );
}

export function CmoOverview({ performance, images, market }: { performance: PerformanceApi; images: ImagesApi; market: MarketApi }) {
  return (
    <div className="cw-page mb-5 grid gap-4 lg:grid-cols-3" data-testid="cmo-overview">
      <PerformanceLane api={performance} />
      <ImagesLane api={images} />
      <MarketLane api={market} />
    </div>
  );
}
