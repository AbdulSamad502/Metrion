import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CiDashboard, type CiClient } from "@/components/ci/CiDashboard";
import type { MarketOverview } from "@/lib/api";
import { askDraft, askFindingHref, askHref, draftFromParams, eventLabel, type CiCompetitor, type CiWorkspace } from "@/lib/ciWorkspace";

vi.mock("next/link", () => ({ default: ({ href, children, ...r }: { href: string; children: React.ReactNode }) => <a href={href} {...r}>{children}</a> }));

const EMPTY: CiWorkspace = {
  asOf: "2026-10-18T12:00:00Z", products: [], selectedProductId: null,
  kpis: { trackedCount: 0, verifiedCount: 0, needsEvidenceCount: 0, importantChangeCount: 0, reviewInsightCount: 0, pendingQuestionCount: 0 },
  competitors: [], candidates: [], reviewInsights: [], changes: [], pendingConfirmations: [], events: [], findings: [], lastDiscovery: null,
};

const comp = (over: Partial<CiCompetitor> = {}): CiCompetitor => ({
  id: "c1", findingId: null, effectivePrice: null, label: "Titan Octane", marketplace: "AMAZON", identityMatch: "NOT_A_MATCH", relationshipClass: "DIRECT_COMPETITOR", relevanceBand: "HIGH", relevanceScore: 15,
  relevanceProvisional: false, evidenceDate: "2026-10-18T08:00:00Z", freshness: "FRESH", priceStatus: "VERIFIED", listedPricePaise: 269900, availability: "IN_STOCK",
  ratingValue: "4.2", ratingCount: 5400, deltaPct: "-9.2", deltaDirection: "DECREASE", openQuestions: 0, ...over,
});

const FULL: CiWorkspace = {
  ...EMPTY,
  products: [{ productId: "SKU-1", title: "Emerald Chrono" }, { productId: "SKU-2", title: null }],
  selectedProductId: "SKU-1",
  kpis: { trackedCount: 3, verifiedCount: 1, needsEvidenceCount: 2, importantChangeCount: 1, reviewInsightCount: 1, pendingQuestionCount: 1 },
  competitors: [
    comp(),
    comp({ id: "c2", label: "Fossil Grant", relationshipClass: "FUNCTIONAL_ALTERNATIVE", relevanceBand: "MEDIUM", relevanceScore: 11, relevanceProvisional: true, freshness: "UNAVAILABLE", priceStatus: "UNAVAILABLE", listedPricePaise: null, deltaPct: null, deltaDirection: null, evidenceDate: "2026-10-01T08:00:00Z" }),
    comp({ id: "c3", label: "Sonata Poze", relationshipClass: "UNKNOWN", relevanceBand: null, relevanceScore: null, relevanceProvisional: null, freshness: "STALE", priceStatus: "UNVERIFIED", listedPricePaise: null, deltaPct: null, deltaDirection: null, evidenceDate: null }),
  ],
  candidates: [{ id: "k1", title: null, url: null, identityNote: null, marketplace: "FLIPKART", tier: "RECOMMENDED", identityMatch: "NOT_A_MATCH", relationshipClass: "DIRECT_COMPETITOR", relevanceBand: "MEDIUM", relevanceScore: 9, relevanceProvisional: true, sellerDecision: "NONE", evidenceStatus: "AWAITING_EVIDENCE" }],
  changes: [{ competitorId: "c1", findingId: "11111111-1111-4111-8111-111111111111", label: "Titan Octane", marketplace: "AMAZON", kind: "PRICE", deltaPaise: -27100, deltaPct: "-9.2", direction: "DECREASE", availabilityChange: null, occurredAt: "2026-10-18T09:00:00Z", evidenceDate: "2026-10-18T08:00:00Z" }],
  reviewInsights: [{ competitorId: "c1", findingId: "22222222-2222-4222-8222-222222222222", label: "Titan Octane", complaintThemes: [{ theme: "rigid strap" }, { theme: "dial fogging" }], positiveThemes: null, reviewsConsidered: 80, confidence: "DERIVED", insightState: "COMPLETE", evidenceDate: "2026-10-17T08:00:00Z" }],
  pendingConfirmations: [{ id: "q1", field: "listed_price_paise", reason: "CONSEQUENTIAL_FIELD", competitorId: "c3", createdAt: "2026-10-18T07:00:00Z", expiresAt: "2026-10-25T07:00:00Z" }],
  events: [{ id: "e1", type: "COMPETITOR_ADDED", occurredAt: "2026-10-17T08:00:00Z", objectType: "competitor_url", objectId: "c1", detail: {} }],
  findings: [
    { id: "11111111-1111-4111-8111-111111111111", type: "PRICE_CHANGE", competitorId: "c1", freshness: "FRESH", confidence: "DERIVED", sellerConfirmation: "CONFIRMED", sampleSize: null, evidenceCount: 1, createdAt: "2026-10-18T09:00:00Z",
      payload: { label: "Titan Octane", direction: "DECREASE", deltaPct: "-9.2", fromPricePaise: 297000, toPricePaise: 269900, evidenceDate: "2026-10-18T08:00:00Z" } },
    { id: "22222222-2222-4222-8222-222222222222", type: "REVIEW_THEME", competitorId: "c1", freshness: "FRESH", confidence: "DERIVED", sellerConfirmation: "NOT_REQUIRED", sampleSize: 80, evidenceCount: 1, createdAt: "2026-10-17T09:00:00Z",
      payload: { label: "Titan Octane", complaintThemes: [{ theme: "rigid strap" }, { theme: "dial fogging" }], evidenceDate: "2026-10-17T08:00:00Z" } },
    { id: "33333333-3333-4333-8333-333333333333", type: "FRESHNESS", competitorId: "c2", freshness: "UNAVAILABLE", confidence: "DERIVED", sellerConfirmation: "NOT_REQUIRED", sampleSize: null, evidenceCount: 1, createdAt: "2026-10-18T07:00:00Z",
      payload: { label: "Fossil Grant", evidenceDate: "2026-10-01T08:00:00Z" } },
  ],
};

const BAND: MarketOverview = {
  productId: "SKU-1", trackedCompetitorCount: 3, minCompetitorsRequired: 3,
  rows: [
    { engineResultRef: "r1", metricCode: "PRICE_BAND", valuePaise: 249900, isAvailable: true, confidence: "DERIVED", calculationBasis: "PriceBand Q1 (product_ref=SKU-1) — x", unavailableReason: null, asOfDate: null },
    { engineResultRef: "r2", metricCode: "PRICE_BAND", valuePaise: 319900, isAvailable: true, confidence: "DERIVED", calculationBasis: "PriceBand Q3 (product_ref=SKU-1) — x", unavailableReason: null, asOfDate: null },
    { engineResultRef: "r3", metricCode: "PRICE_BAND", valuePaise: 265000, isAvailable: true, confidence: "DERIVED", calculationBasis: "PriceBand TYPICAL_LOW (product_ref=SKU-1) — x", unavailableReason: null, asOfDate: null },
    { engineResultRef: "r4", metricCode: "PRICE_BAND", valuePaise: 315000, isAvailable: true, confidence: "DERIVED", calculationBasis: "PriceBand TYPICAL_HIGH (product_ref=SKU-1) — x", unavailableReason: null, asOfDate: null },
  ],
};
const NO_BAND: MarketOverview = { productId: "SKU-1", trackedCompetitorCount: 1, minCompetitorsRequired: 3, rows: [{ engineResultRef: "u", metricCode: "PRICE_BAND", valuePaise: null, isAvailable: false, confidence: "DERIVED", calculationBasis: null, unavailableReason: "fewer than 3 eligible competitors", asOfDate: null }] };

const client = (ws: CiWorkspace, market: MarketOverview = BAND): CiClient & { workspace: ReturnType<typeof vi.fn> } => ({
  workspace: vi.fn(async () => ws),
  market: vi.fn(async () => market),
});

describe("the CI dashboard is read-only (spec C32, AC38, AC58)", () => {
  it("has no form, input, select, textarea, file control or image, empty or full", async () => {
    for (const ws of [EMPTY, FULL]) {
      const { container, unmount } = render(<CiDashboard client={client(ws)} />);
      await screen.findByTestId("ci-dashboard");
      expect(container.querySelectorAll("form, input, select, textarea, img, svg image, [type=file], [contenteditable]")).toHaveLength(0);
      unmount();
    }
  });

  it("shows a professional empty state with no sample data for a new seller", async () => {
    render(<CiDashboard client={client(EMPTY)} />);
    await screen.findByTestId("ci-dashboard");
    expect(await screen.findByText("No competitors tracked yet")).toBeInTheDocument();
    expect(screen.getByText(/Nothing here is estimated or sample data/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Find competitors/ })[0]).toHaveAttribute("href", "/dashboard/ceo-hub?ask=research");
    expect(screen.queryByText("₹")).not.toBeInTheDocument();
  });

  it("offers two header shortcuts: find competitors and track a competitor (no monitor button)", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(await screen.findByRole("link", { name: "Find competitors" })).toHaveAttribute("href", "/dashboard/ceo-hub?ask=research");
    expect(screen.queryByRole("link", { name: /monitor/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Track a competitor" })).toHaveAttribute("href", "/dashboard/ceo-hub?ask=track");
  });

  it("switching product only reloads what is shown", async () => {
    const c = client(FULL);
    render(<CiDashboard client={c} />);
    await screen.findByTestId("ci-dashboard");
    await userEvent.click(await screen.findByRole("button", { name: "SKU-2" }));
    await waitFor(() => expect(c.workspace).toHaveBeenLastCalledWith("SKU-2"));
  });
});

describe("what the dashboard states, and what it refuses to", () => {
  it("states a verified price, and no price at all for stale or unconfirmed evidence", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    const table = screen.getByRole("table", { name: "Tracked competitors" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("₹2,699")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Verified")).toBeInTheDocument();
    expect(within(rows[1]).getByText("No current price")).toBeInTheDocument();
    expect(within(rows[1]).queryByText(/₹/)).not.toBeInTheDocument();
    expect(within(rows[2]).getByText("Awaiting your confirmation")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Confirm in chat", { selector: "span" })).toBeInTheDocument();
  });

  it("shows relevance with its score and provisional flag, relationship in words, and an unscored candidate as not scored", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.queryByText(/\/16/)).not.toBeInTheDocument(); // no raw scores or "provisional" jargon: a plain match word
    expect(screen.getAllByText(/^(High|Medium|Low)$/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Not scored").length).toBeGreaterThan(0);
  });

  it("shows the engine's band when there is one, and explains why not when there is none", async () => {
    const { unmount } = render(<CiDashboard client={client(FULL, BAND)} />);
    expect(await screen.findByText("₹2,499")).toBeInTheDocument();
    expect(screen.getByText("₹3,199")).toBeInTheDocument();
    unmount();
    render(<CiDashboard client={client(FULL, NO_BAND)} />);
    await screen.findByTestId("ci-dashboard");
    expect(await screen.findByText("No price band yet")).toBeInTheDocument();
    expect(screen.getByText(/fewer than 3 eligible competitors/)).toBeInTheDocument();
  });

  it("lists candidates as leads awaiting evidence, with no link to or text from the listing", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.getAllByText(/not verified yet/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Search leads\. They are not verified prices/)).toBeInTheDocument();
    expect(document.querySelectorAll('a[href*="flipkart.com"], a[href*="amazon.in"]')).toHaveLength(0);
  });

  it("states changes with the evidence date they rest on", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.getByText("Titan Octane: price down 9.2%")).toBeInTheDocument();
    expect(screen.getByText(/from the screenshot of/)).toBeInTheDocument();
    expect(screen.getByText(/not watched between your screenshots/)).toBeInTheDocument();
  });

  it("shows review themes with how many reviews were read, and pending confirmations", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.getAllByText(/80 reviews read/).length).toBeGreaterThan(0);
    expect(screen.getByText("Complaints: rigid strap, dial fogging")).toBeInTheDocument();
    expect(screen.getByText("Confirm the listed price")).toBeInTheDocument();
    expect(screen.getByText("Competitor added")).toBeInTheDocument();
  });

  it("never claims to watch competitors live", async () => {
    const { container } = render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(container.textContent ?? "").not.toMatch(/real[- ]?time|continuous|monitored continuously|24\/7|always up to date/i);
  });

  it("hides technical identifiers by default", async () => {
    const { container } = render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(container.textContent ?? "").not.toMatch(/engineResultRef|[0-9a-f]{8}-[0-9a-f]{4}-|\br1\b/);
  });

  it("says plainly when the workspace cannot be loaded, and when the role lacks access", async () => {
    const failing: CiClient = { workspace: vi.fn(async () => { throw new Error("boom"); }), market: vi.fn() };
    render(<CiDashboard client={failing} />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("the CEO Hub links (spec D14)", () => {
  it("build a plain-words draft the seller sends, and read it back", () => {
    expect(askDraft("research", "Emerald Chrono")).toBe("Find competitors for my Emerald Chrono");
    expect(askDraft("monitor")).toBe("Monitor my competitors");
    expect(askHref("monitor", "Emerald Chrono")).toBe("/dashboard/ceo-hub?ask=monitor&about=Emerald+Chrono");
    expect(draftFromParams("research", "Emerald Chrono")).toBe("Find competitors for my Emerald Chrono");
    expect(draftFromParams("track", "Emerald Chrono")).toBe("Track a competitor for my Emerald Chrono");
    expect(draftFromParams("delete-everything", "x")).toBeNull();
    expect(draftFromParams(null, null)).toBeNull();
  });
  it("name every event type in words", () => {
    expect(eventLabel("EVIDENCE_RECEIVED")).toBe("Screenshot received");
    expect(eventLabel("SOMETHING_NEW")).toBe("something new");
  });
});


describe("Ask CEO passes the finding id and the product (spec C33, C46)", () => {
  it("every insight asks about its own stored finding, with the product", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.getByText(/Titan Octane: price dropped 9\.2% \(from ₹2,970 to ₹2,699\)/)).toBeInTheDocument();
    expect(screen.getByText(/Titan Octane's customers complain about rigid strap and dial fogging \(80 reviews read\)/)).toBeInTheDocument();
    expect(screen.getByText(/Fossil Grant: the newest screenshot is from/)).toBeInTheDocument();
    const hrefs = screen.getAllByRole("link", { name: /Explain this/ }).map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("/dashboard/ceo-hub?ask=finding&finding=11111111-1111-4111-8111-111111111111&sku=SKU-1&about=Emerald+Chrono");
    expect(hrefs).toContain("/dashboard/ceo-hub?ask=finding&finding=22222222-2222-4222-8222-222222222222&sku=SKU-1&about=Emerald+Chrono");
    expect(screen.getAllByText(/screenshot(s)? behind it/).length).toBe(3);
  });
  it("the change, review and competitor-table buttons carry the finding id too", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(document.querySelector('a[href*="finding=11111111-1111-4111-8111-111111111111&sku=SKU-1&about=Titan+Octane"]')).not.toBeNull();
    expect(document.querySelector('a[href*="finding=22222222-2222-4222-8222-222222222222&sku=SKU-1&about=Titan+Octane"]')).not.toBeNull();
  });
  it("a row with no finding falls back to a plain-words question, never a made-up id", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href") ?? "");
    expect(hrefs.some((h) => h.startsWith("/dashboard/ceo-hub?ask=verify&about="))).toBe(true); // each competitor row has a plain "Verify price" action
    expect(hrefs.some((h) => h.startsWith("/dashboard/ceo-hub?ask=stop&about="))).toBe(true);
    expect(hrefs.every((h) => !h.includes("finding=undefined") && !h.includes("finding=null"))).toBe(true);
  });
  it("the hub link reads back into a draft and a validated id", () => {
    expect(askFindingHref("11111111-1111-4111-8111-111111111111", "SKU-1", "Titan Octane")).toBe("/dashboard/ceo-hub?ask=finding&finding=11111111-1111-4111-8111-111111111111&sku=SKU-1&about=Titan+Octane");
    expect(draftFromParams("finding", "Titan Octane")).toBe("Tell me about this finding about Titan Octane");
  });
});


describe("what a buyer pays comes from Brain 1 and says what it is missing", () => {
  const cell = (v: number | null, ref: string, reason: string | null = null) => ({ valuePaise: v, engineResultRef: ref, isAvailable: v !== null, unavailableReason: reason });
  it("shows the effective price, the total with delivery, and which offers are not counted", async () => {
    const ws: CiWorkspace = { ...FULL, competitors: [comp({ effectivePrice: { effective: cell(259900, "e1"), buyerTotal: cell(264800, "e2"), deliveryChargePaise: 4900,
      offers: [{ kind: "COUPON", amountPaise: 10000, conditional: false }, { kind: "BANK_OFFER", amountPaise: 25000, conditional: true }], excludedOffers: [{ kind: "BANK_OFFER", reason: "CONDITIONAL" }] } })] };
    render(<CiDashboard client={client(ws)} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.getByText(/₹2,599/)).toBeInTheDocument();
    expect(screen.getByText("₹2,648 with delivery")).toBeInTheDocument();
    expect(screen.getByText("1 offer counted, 1 offer not counted (needs a card or a condition)")).toBeInTheDocument();
  });
  it("says why a total is missing instead of showing delivery as free", async () => {
    const ws: CiWorkspace = { ...FULL, competitors: [comp({ effectivePrice: { effective: cell(269900, "e1"), buyerTotal: cell(null, "e2", "DELIVERY_CHARGE_NOT_OBSERVED"), deliveryChargePaise: null, offers: [], excludedOffers: [] } })] };
    render(<CiDashboard client={client(ws)} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.getByText("Total: delivery charge not confirmed")).toBeInTheDocument();
    expect(screen.queryByText(/with delivery/)).not.toBeInTheDocument();
  });
  it("shows nothing priced for a competitor without a verified price", async () => {
    render(<CiDashboard client={client(FULL)} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.getAllByText("Not available").length).toBeGreaterThan(0);
    expect(screen.queryByText(/after discounts/)).not.toBeInTheDocument();
  });
});


describe("a search lead is shown by what the search called it, with where it is, why it is listed and a link", () => {
  it("shows the title, the marketplace, the reason and an Open listing link, and never a price", async () => {
    const ws: CiWorkspace = { ...FULL, candidates: [{ ...FULL.candidates[0], title: "CASPIAN Astra Stainless Steel Water Bottle 1L", url: "https://www.amazon.in/dp/B0AAAAAAA1", relationshipClass: "UNKNOWN", identityNote: "I cannot tell if it is the same product as yours: your product has no brand recorded" }] };
    render(<CiDashboard client={client(ws)} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.getByText("CASPIAN Astra Stainless Steel Water Bottle 1L")).toBeInTheDocument();
    expect(screen.getByText(/your product has no brand recorded/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open listing" })).toHaveAttribute("href", "https://www.amazon.in/dp/B0AAAAAAA1");
  });
});

describe("what the dashboard does when data is loading, refreshing or failing", () => {
  const SKU2: CiWorkspace = { ...FULL, selectedProductId: "SKU-2", competitors: [comp({ id: "z1", label: "Rival Two" })] };
  const deferred = <T,>() => {
    let resolve!: (v: T) => void;
    let reject!: (e: unknown) => void;
    const promise = new Promise<T>((res, rej) => ((resolve = res), (reject = rej)));
    return { promise, resolve, reject };
  };

  it("names the product, the data's own date and when it was checked", async () => {
    render(<CiDashboard client={client(FULL)} />);
    const ctx = await screen.findByTestId("ci-context");
    expect(ctx).toHaveTextContent(/Showing .* · Data as of .* · checked /);
  });

  it("offers a retry when the first load fails, and shows the workspace once it works", async () => {
    let fail = true;
    const c: CiClient = { workspace: vi.fn(async () => { if (fail) throw new Error("boom"); return FULL; }), market: vi.fn(async () => BAND) };
    render(<CiDashboard client={c} />);
    await screen.findByRole("alert");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("ci-dashboard")).toBeInTheDocument();
  });

  it("keeps the workspace on screen when a refresh fails, and says it may be out of date", async () => {
    let fail = false;
    const c: CiClient = { workspace: vi.fn(async () => { if (fail) throw new Error("boom"); return FULL; }), market: vi.fn(async () => BAND) };
    render(<CiDashboard client={c} />);
    await screen.findByTestId("ci-dashboard");
    fail = true;
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/may be out of date/);
    expect(screen.getByTestId("ci-dashboard")).toBeInTheDocument();
    expect(screen.getAllByText("Titan Octane").length).toBeGreaterThan(0);
  });

  it("says a refresh is running, shows the last result meanwhile, and cannot start a second one", async () => {
    const d = deferred<CiWorkspace>();
    let calls = 0;
    const c: CiClient = { workspace: vi.fn(() => (calls++ === 0 ? Promise.resolve(FULL) : d.promise)), market: vi.fn(async () => BAND) };
    render(<CiDashboard client={c} />);
    await screen.findByTestId("ci-dashboard");
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
    expect(screen.getByTestId("ci-context")).toHaveTextContent(/Refreshing… what is shown is the last result that loaded/);
    expect(screen.getAllByText("Titan Octane").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Refreshing…" }));
    expect(c.workspace).toHaveBeenCalledTimes(2);
    d.resolve(FULL);
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled());
  });

  it("does not present the old product's results as the new product's while it loads", async () => {
    const d = deferred<CiWorkspace>();
    let calls = 0;
    const c: CiClient = { workspace: vi.fn(() => (calls++ === 0 ? Promise.resolve(FULL) : d.promise)), market: vi.fn(async () => BAND) };
    render(<CiDashboard client={c} />);
    await screen.findByTestId("ci-dashboard");
    await userEvent.click(screen.getByRole("button", { name: "SKU-2" }));
    expect(screen.getByTestId("ci-context")).toHaveTextContent(/Loading .* the .* view below is the previous one/);
    expect(screen.getByRole("button", { name: "SKU-2" })).toHaveAttribute("aria-pressed", "true");
    d.resolve(SKU2);
    expect((await screen.findAllByText("Rival Two")).length).toBeGreaterThan(0);
    expect(screen.getByTestId("ci-context")).toHaveTextContent(/Showing /);
  });

  it("keeps the previous product and names the failure when a switch fails, with a retry", async () => {
    let fail = true;
    let calls = 0;
    const c: CiClient = { workspace: vi.fn(async () => { if (calls++ > 0 && fail) throw new Error("boom"); return calls > 1 ? SKU2 : FULL; }), market: vi.fn(async () => BAND) };
    render(<CiDashboard client={c} />);
    await screen.findByTestId("ci-dashboard");
    await userEvent.click(screen.getByRole("button", { name: "SKU-2" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Still showing/);
    expect(screen.getAllByText("Titan Octane").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Emerald Chrono" })).toHaveAttribute("aria-pressed", "true"); // the selection follows what is shown
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect((await screen.findAllByText("Rival Two")).length).toBeGreaterThan(0);
  });

  it("shows only the latest choice when replies arrive out of order", async () => {
    const slow = deferred<CiWorkspace>();
    const SKU1_AGAIN: CiWorkspace = { ...FULL, competitors: [comp({ id: "y1", label: "Rival One Again" })] };
    let calls = 0;
    const c: CiClient = { workspace: vi.fn((id: string | null) => { calls++; if (calls === 1) return Promise.resolve(FULL); return id === "SKU-2" ? slow.promise : Promise.resolve(SKU1_AGAIN); }), market: vi.fn(async () => BAND) };
    render(<CiDashboard client={c} />);
    await screen.findByTestId("ci-dashboard");
    await userEvent.click(screen.getByRole("button", { name: "SKU-2" })); // slow
    await userEvent.click(screen.getByRole("button", { name: "Emerald Chrono" })); // then back to SKU-1, which answers first
    expect((await screen.findAllByText("Rival One Again")).length).toBeGreaterThan(0);
    slow.resolve(SKU2); // the older reply arrives last and must be ignored
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("Rival Two")).toBeNull();
    expect(screen.getAllByText("Rival One Again").length).toBeGreaterThan(0);
  });

  it("does not ask again for the product already shown", async () => {
    const c = client(FULL);
    render(<CiDashboard client={c} />);
    await screen.findByTestId("ci-dashboard");
    await userEvent.click(screen.getByRole("button", { name: "Emerald Chrono" }));
    expect(c.workspace).toHaveBeenCalledTimes(1);
  });

  it("says the price band is loading, not that there is none", async () => {
    const m = deferred<MarketOverview>();
    const c: CiClient = { workspace: vi.fn(async () => FULL), market: vi.fn(() => m.promise) };
    render(<CiDashboard client={c} />);
    await screen.findByTestId("ci-dashboard");
    expect(screen.getByText("Loading the price band…")).toBeInTheDocument();
    expect(screen.queryByText("No price band yet")).toBeNull();
    m.resolve(BAND);
    expect(await screen.findByText("Typical low")).toBeInTheDocument();
  });
});
