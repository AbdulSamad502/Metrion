import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MarketDashboard } from "@/components/cmo/market/MarketDashboard";
import { MarketIntelligenceCard } from "@/components/ceo/hub/MarketIntelligenceCard";
import { ApiError } from "@/lib/api";
import { isMarketCard, marketDraftFromParams, marketError } from "@/lib/cmoMarket";
import type { MarketApi, MarketCard, MarketOverview, NewsItem, Opportunity } from "@/lib/cmoMarket";

// Written with M10; see the docs for whether this file has been run.
const news = (over: Partial<NewsItem> = {}): NewsItem => ({
  id: "r1:f1", headline: "Amazon India updates return policy", summary: "The returns window changes.", newsKind: "POLICY", marketplaces: ["AMAZON"], publishedAt: "2026-10-20", ageDays: 12, freshness: "FRESH", isStale: false, officialSource: true,
  sources: [{ url: "https://sell.amazon.in/a", title: "Return policy", publishedAt: "2026-10-20T00:00:00", retrievedAt: "2026-10-30T00:00:00", sourceClass: "OFFICIAL_MARKETPLACE" }],
  sourceNote: "From an official marketplace source.", impact: "A policy or rules update. It may change what you can list or how.", reportId: "r1", reportDate: "2026-10-30", seenInReports: 2, independentSources: 1, corroboration: "SINGLE_SOURCE", limitation: null,
  relevance: { level: "HIGH", reason: "It mentions “steel” from your product and it concerns Amazon.", affects: [{ sku: "aqua", name: "AquaNest steel bottle", level: "HIGH", sharedTerms: ["steel"], marketplaces: ["AMAZON"], reason: "It mentions steel." }] },
  recommendations: [{ agent: "YOU", text: "Open the source and read it yourself." }, { agent: "CMO", text: "Check your listing.", ask: "Show my latest AquaNest steel bottle listing" }], ...over,
});
const opp = (over: Partial<Opportunity> = {}): Opportunity => ({
  id: "r1:f2", title: "Insulated steel bottle gifting", section: "ADJACENT", kind: "Adjacent topic", rank: 1, rankedBecause: "Ranked by those three in that order, with no score or forecast.", evidenceStrength: "MODERATE", evidenceStrengthWhy: "Reported by more than one independent source.",
  limitation: null, relevance: { level: "HIGH", reason: "It mentions steel.", affects: [] },
  observed: { label: "What the saved sources reported (verified as reported, not as true)", summary: "Gifting searches are discussed.", sources: [{ url: "https://news.example/g", title: "Gifting", publishedAt: "2026-10-25T00:00:00", retrievedAt: null, sourceClass: "THIRD_PARTY" }], independentSources: 2, freshestPublishedAt: "2026-10-25", freshness: "FRESH", ageDays: 7, reportId: "r1", reportDate: "2026-10-30", seenInReports: 1 },
  possible: { label: "A possible explanation (not measured)", text: "Corroboration describes how widely attention is reported. It is not evidence of demand, sales or profit." }, demand: { state: "UNAVAILABLE", note: "Metrion holds no search-volume, sales or demand data for this topic, so none is shown." },
  recommendations: [{ agent: "PI", text: "Research it.", ask: "Find product ideas I could sell" }, { agent: "CFO", text: "Check the margin.", ask: "What is my profit by product?" }], ...over,
});
const overview = (over: Partial<MarketOverview> = {}): MarketOverview => ({
  state: "OK", message: null, latestReportAt: "2026-10-30", reportCount: 2, news: [news()], opportunities: [opp()], newsWithoutMarketplace: 0, filters: { sku: null, marketplace: null },
  products: [{ sku: "aqua", name: "AquaNest steel bottle", marketplaces: ["AMAZON"] }], marketplaces: ["AMAZON", "FLIPKART", "MEESHO"], today: "2026-11-01", freshnessRules: { freshDays: 14, recentDays: 60, reportStaleDays: 30 },
  notes: ["Everything here comes from your own saved market-trend reports."], aiCredits: 0, ...over,
});
const api = (ov: MarketOverview | (() => Promise<MarketOverview>) = overview()): MarketApi => ({ overview: vi.fn(typeof ov === "function" ? ov : async () => ov) }) as unknown as MarketApi;

describe("the market page", () => {
  it("shows opportunities and news with sources, dates, freshness, relevance, evidence and demand as unavailable", async () => {
    render(<MarketDashboard api={api()} />);
    const o = await screen.findByTestId("opportunity");
    expect(o).toHaveAttribute("data-strength", "MODERATE");
    expect(within(o).getByTestId("observed")).toHaveTextContent("verified as reported, not as true");
    expect(within(o).getByTestId("possible")).toHaveTextContent("A possible explanation (not measured)");
    expect(within(o).getByTestId("demand")).toHaveTextContent("Demand UNAVAILABLE");
    expect(within(o).getByRole("link", { name: "Gifting" })).toHaveAttribute("href", "https://news.example/g");
    const n = screen.getByTestId("news-item");
    expect(within(n).getByTestId("freshness")).toHaveTextContent("FRESH · 12 days old");
    expect(within(n).getByTestId("relevance")).toHaveTextContent("Relevance to your products: HIGH");
    expect(n).toHaveTextContent("published 2026-10-20");
    expect(n).toHaveTextContent("seen in 2 reports, shown once");
    expect(within(n).getByRole("link", { name: "Return policy" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(n).getAllByTestId("step").map((s) => s.getAttribute("data-agent"))).toEqual(["YOU", "CMO"]);
  });

  it("says nothing is saved yet and invents nothing", async () => {
    render(<MarketDashboard api={api(overview({ state: "NO_REPORT", message: "You have no saved market-trend report yet.", news: [], opportunities: [], reportCount: 0, latestReportAt: null }))} />);
    expect(await screen.findByTestId("market-empty")).toHaveTextContent("no saved market-trend report");
    expect(screen.queryByTestId("opportunity")).not.toBeInTheDocument();
  });

  it("warns when the newest report is old and marks a stale item", async () => {
    render(<MarketDashboard api={api(overview({ state: "STALE_REPORTS", message: "Your newest market-trend report is 90 days old.", news: [news({ freshness: "STALE", isStale: true, ageDays: 120 })] }))} />);
    expect(await screen.findByTestId("market-stale")).toHaveTextContent("90 days old");
    expect(screen.getByTestId("stale-note")).toHaveTextContent("old or undated");
  });

  it("shows loading, then an error in plain words", async () => {
    const never = new Promise<MarketOverview>(() => undefined);
    const { unmount } = render(<MarketDashboard api={api(() => never)} />);
    expect(screen.getByTestId("market-loading")).toBeInTheDocument();
    unmount();
    render(<MarketDashboard api={api(async () => { throw new ApiError(500, { detail: "Trouble." }); })} />);
    expect(await screen.findByTestId("market-error")).toBeInTheDocument();
  });

  it("filters by product and marketplace through the API and shows an empty selection honestly", async () => {
    const a = api(overview({ news: [], opportunities: [], newsWithoutMarketplace: 2 }));
    render(<MarketDashboard api={a} />);
    expect(await screen.findByTestId("no-news")).toHaveTextContent("2 item(s) name no marketplace");
    expect(screen.getByTestId("no-opportunities")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Marketplace"), "FLIPKART");
    await waitFor(() => expect(a.overview).toHaveBeenLastCalledWith({ sku: null, marketplace: "FLIPKART" }));
    await userEvent.selectOptions(screen.getByLabelText("Product"), "aqua");
    await waitFor(() => expect(a.overview).toHaveBeenLastCalledWith({ sku: "aqua", marketplace: "FLIPKART" }));
    expect(screen.getByTestId("ask-ceo")).toHaveAttribute("href", expect.stringContaining("ask=market"));
  });
});

describe("the CEO chat market card", () => {
  const card = (over: Partial<MarketCard> = {}): MarketCard => ({ kind: "MARKET_INTELLIGENCE", view: "NEWS", page: "/dashboard/cmo/market", aiCredits: 0, state: "OK", latestReportAt: "2026-10-30", reportCount: 2, news: [news()], opportunities: [], ...over });

  it("shows news and sends a suggested question only when its button is pressed", async () => {
    const onSend = vi.fn();
    render(<MarketIntelligenceCard card={card()} onSend={onSend} />);
    expect(screen.getByTestId("market-card")).toHaveAttribute("data-view", "NEWS");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Ask: “Show my latest AquaNest steel bottle listing”/ }));
    expect(onSend).toHaveBeenCalledWith("Show my latest AquaNest steel bottle listing");
  });

  it("shows opportunities and the no-report, clarify and refused states", async () => {
    const onSend = vi.fn();
    const { unmount } = render(<MarketIntelligenceCard card={card({ view: "FOCUS", news: [], opportunities: [opp()] })} onSend={onSend} />);
    expect(screen.getByTestId("opportunity")).toBeInTheDocument();
    unmount();
    const r2 = render(<MarketIntelligenceCard card={card({ view: "NO_REPORT", message: "You have no saved market-trend report yet." })} onSend={onSend} />);
    expect(screen.getByTestId("market-empty")).toHaveTextContent("Nothing is invented");
    r2.unmount();
    render(<MarketIntelligenceCard card={card({ view: "CLARIFY", question: "Which marketplace do you mean?", options: [{ label: "Amazon", marketplace: "AMAZON" }, { label: "Flipkart", marketplace: "FLIPKART" }] })} onSend={onSend} />);
    await userEvent.click(screen.getByRole("button", { name: "Flipkart" }));
    expect(onSend).toHaveBeenCalledWith("Flipkart");
  });

  it("disables the suggested questions while the chat is busy", () => {
    render(<MarketIntelligenceCard card={card()} disabled onSend={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Ask:/ })).not.toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("recognises only the market card and builds only fixed hand-off sentences", () => {
    expect(isMarketCard({ kind: "MARKET_INTELLIGENCE", view: "NEWS" })).toBe(true);
    expect(isMarketCard({ kind: "IMAGE_QUALITY", view: "REPORT" })).toBe(false);
    expect(marketDraftFromParams("market", "OPPORTUNITIES", null)).toBe("Find opportunities for my products");
    expect(marketDraftFromParams("market", "CHANGED", "AMAZON")).toBe("What has changed on Amazon?");
    expect(marketDraftFromParams("market", "CHANGED", "EBAY")).toBeNull();
    expect(marketDraftFromParams("market", "<script>", null)).toBeNull();
    expect(marketDraftFromParams("cmo", "NEWS", null)).toBeNull();
    expect(marketError(new ApiError(404, { detail: "That product is not one of yours yet." }))).toBe("That product is not one of yours yet.");
  });
});
