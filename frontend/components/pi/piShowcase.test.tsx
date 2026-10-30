import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PiShowcase } from "@/components/pi/PiShowcase";
import { ToastProvider } from "@/components/ui/Toast";
import { formatPaise, type PiCase, type PiClient, type PiHistoryItem, type PiProduct } from "@/lib/piShowcase";

vi.mock("next/link", () => ({ default: ({ href, children, ...r }: { href: string; children: React.ReactNode }) => <a href={href} {...r}>{children}</a> }));

const RUN_A = "11111111-1111-4111-8111-111111111111";
const RUN_B = "22222222-2222-4222-8222-222222222222";

const product = (rank: number, over: Partial<PiProduct["candidate"]> = {}, rec: Partial<PiProduct["recommendation"]> = {}): PiProduct => ({
  rank,
  candidate: {
    id: `c${rank}`, candidate_title: `Watch ${rank}`, observed_category: "Watches", image_url: rank === 1 ? "https://cdn.shop.example/w1.jpg" : null,
    image_source_url: "https://shop.example/w1", proxy_score: "50.00", web_price_signal: null, candidate_marketplaces: ["AMAZON"], source_urls: [],
    feasibility_status: "UNAVAILABLE", feasibility_low_paise: null, feasibility_high_paise: null, feasibility_cogs_basis: null, feasibility_unavailable_reason: "seller has not stated a budget", ...over,
  },
  reviewInsights: [], supplierLeads: [], bestSupplierLeadId: null, financials: [], finalScore: `${90 - rank}.00`, finalScoreState: "COMPUTED",
  recommendation: { candidate_id: `c${rank}`, rank, title: `Watch ${rank}`, final_score: `${90 - rank}.00`, final_score_state: "COMPUTED", why_ranked: [], pros: ["comfortable strap"], cons: ["strap is stiff"], supplier_option: null, gaps: ["no supplier lead was found for this product"], note: "x", ...rec },
});

const caseOf = (runId: string, over: Partial<PiCase> = {}): PiCase => ({
  runId, status: "COMPLETE", pinned: false, pinnedAt: null, completedAt: "2026-10-10T00:00:00Z", caseSaved: true,
  brief: { category: "mens watches", budgetPaise: 35000000, targetPriceMinPaise: 199900, targetPriceMaxPaise: 349900, marketplaces: ["AMAZON"] },
  products: [1, 2, 3, 4, 5].map((n) => product(n)), overall: { candidate_id: "c1", title: "Watch 1", final_score: "89.00", reason: "highest combined score (89.00/100)", note: "x" },
  cfoRefs: [], gaps: [], unavailable: [{ field: "verified_buyer_reviews", reason: "no marketplace access in V1" }], investigationId: null, ...over,
});

const hist = (runId: string, over: Partial<PiHistoryItem> = {}): PiHistoryItem => ({
  runId, status: "COMPLETE", pinned: false, pinnedAt: null, completedAt: "2026-10-10T00:00:00Z", category: "mens watches", budgetPaise: 35000000,
  targetPriceMinPaise: null, targetPriceMaxPaise: null, marketplaces: ["AMAZON"], caseSaved: true, topProducts: [{ candidateId: "c1", title: "Watch 1", finalScore: "89.00" }], ...over,
});

function fake(over: Partial<PiClient> = {}): PiClient {
  return {
    history: async () => ({ items: [hist(RUN_A), hist(RUN_B, { completedAt: "2026-09-01T00:00:00Z", category: "jars" })] }),
    report: async (id) => caseOf(id),
    pin: vi.fn(async (id) => ({ runId: id, pinned: true })),
    unpin: vi.fn(async (id) => ({ runId: id, pinned: false })),
    ...over,
  };
}

describe("formatPaise", () => {
  it("groups Indian-style from integer paise and never invents a zero", () => {
    expect(formatPaise(15600000)).toBe("₹1,56,000");
    expect(formatPaise(129900)).toBe("₹1,299");
    expect(formatPaise(129950)).toBe("₹1,299.50");
    expect(formatPaise(5)).toBe("₹0.05");
    expect(formatPaise(null)).toBe("Unavailable");
    expect(formatPaise(undefined)).toBe("Unavailable");
  });
});

describe("PI showcase (read-only)", () => {
  it("opens the newest report with the five-product carousel and the design's sections", async () => {
    render(<PiShowcase client={fake()} />);
    expect(await screen.findByRole("heading", { name: /Recent Investigation: mens watches/ })).toBeInTheDocument();
    expect(screen.getByText("Rank #1")).toBeInTheDocument();
    expect(screen.getByText(/Budget: ₹3,50,000 · Target Price: ₹1,999 – ₹3,499 · Amazon · Top 5 Shortlist/)).toBeInTheDocument();
    expect(screen.getByText("Product Information")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Top picks/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Old Investigation\s+Historical/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+ New Discovery" })).toHaveAttribute("href", "/dashboard/ceo-hub");
    expect(screen.getByRole("link", { name: /Print \/ Export PDF/ })).toHaveAttribute("href", `/reports/pi/${RUN_A}/print`);
  });

  it("has no form, input or control that starts research", async () => {
    const { container } = render(<PiShowcase client={fake()} />);
    await screen.findByText("Rank #1");
    expect(container.querySelectorAll("input, textarea, select, form")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /run|discover|supplier lookup|generate|start research/i })).toBeNull();
  });

  it("shows missing cost, margin and units as Unavailable with the reason, never as zero", async () => {
    render(<PiShowcase client={fake()} />);
    await screen.findByText("Rank #1");
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText(/Needs your supplier quote/)).toBeInTheDocument();
    expect(screen.getByText(/Needs your cost and selling price/)).toBeInTheDocument();
    expect(screen.getByText(/Missing evidence: no supplier lead was found/)).toBeInTheDocument();
    expect(screen.queryByText("₹0")).toBeNull();
  });

  it("labels commentary honestly and never as verified buyer reviews", async () => {
    render(<PiShowcase client={fake()} />);
    await screen.findByText("Rank #1");
    expect(screen.getByText(/Viewer and web commentary, not verified buyer reviews/)).toBeInTheDocument();
    expect(screen.getAllByText(/comfortable strap/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/strap is stiff/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/trending|bestseller/i)).toBeNull();
  });

  it("shows an image with its source, a plain placeholder when there is none, and falls back when it fails to load", async () => {
    const { container } = render(<PiShowcase client={fake()} />);
    await screen.findByText("Rank #1");
    const img = container.querySelector('img:not([alt=""])') as HTMLImageElement; // the detail picture (the small list thumbnails are decorative)
    expect(img.getAttribute("src")).toBe("https://cdn.shop.example/w1.jpg");
    expect(screen.getByText("image from shop.example")).toBeInTheDocument();
    img.dispatchEvent(new Event("error"));
    expect((await screen.findAllByText("No clear product image found")).length).toBeGreaterThan(0);
  });

  it("moves between the five products and shows that product's own details", async () => {
    render(<PiShowcase client={fake()} />);
    await screen.findByText("Rank #1");
    await userEvent.click(screen.getByRole("button", { name: "Rank 3" }));
    expect(screen.getByText("Rank #3")).toBeInTheDocument();
    expect(screen.getByLabelText("Product information: Watch 3")).toBeInTheDocument();
  });

  it("renders the supplier lead with its honest source label and a safe link only", async () => {
    const lead = { id: "l1", supplier_name: "Siddhi Instruments", source: "TAVILY", contact: { phone: null, website: "javascript:alert(1)" }, locality: null, source_url: "https://supplier.example/p", fetched_at: "2026-10-09T00:00:00Z" };
    const withLead = caseOf(RUN_A, { products: [product(1, {}, { supplier_option: lead })].map((p) => ({ ...p, supplierLeads: [lead], bestSupplierLeadId: "l1" })) });
    render(<PiShowcase client={fake({ report: async () => withLead })} />);
    await screen.findAllByText("Siddhi Instruments");
    expect(screen.getByText(/Web search lead \(not verified\)/)).toBeInTheDocument();
    expect(screen.getByText(/Phone: not published · MOQ: not published/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Supplier Link/ })).toBeNull(); // a javascript: website is refused, never rendered as a link
  });

  it("shows the CFO's figures from the seller's confirmed quote in the tiles, and a published price as a labelled fact, not a quote", async () => {
    const lead = { id: "l1", supplier_name: "Siddhi", source: "TAVILY", contact: { phone: null, website: null, published_price: { low_paise: 45000, high_paise: 52000, sample_count: 2, unit: "piece", source_url: "https://s.example/p", captured_at: "2026-10-09T00:00:00Z", disclaimer: "x" } }, locality: null, source_url: "https://s.example/p" };
    const financials = [
      { kind: "ENGINE" as const, authoritative: true, leg_key: "cfo.landed_cost", label: "Landed cost per unit (Siddhi)", display: "₹255", status: "COMPLETE" as const },
      { kind: "ENGINE" as const, authoritative: true, leg_key: "cfo.batch_size", label: "Most units your budget allows", display: "380 units", status: "COMPLETE" as const },
    ];
    const withFin = caseOf(RUN_A, { products: [{ ...product(1, {}, { supplier_option: lead }), supplierLeads: [lead], bestSupplierLeadId: "l1", financials }] });
    render(<PiShowcase client={fake({ report: async () => withFin })} />);
    await screen.findAllByText("Siddhi");
    expect(screen.getAllByText("₹255").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("380 units").length).toBeGreaterThanOrEqual(1); // in the ledger row and in the product tile
    expect(screen.getAllByText(/From your quote/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/a ceiling, not a forecast/)).toBeInTheDocument();
    expect(screen.getByText(/Published price: ₹450 - ₹520 per piece \(their own page, .*; not a quote\)/)).toBeInTheDocument();
  });

  it("names why a CFO result is missing instead of showing zero", async () => {
    const financials = [{ kind: "GAP" as const, authoritative: true, leg_key: "cfo.landed_cost", label: "Landed cost per unit", display: null, status: "UNAVAILABLE" as const, reason: "no supplier quote is stored for this product" }];
    const gap = caseOf(RUN_A, { products: [{ ...product(1), financials }] });
    render(<PiShowcase client={fake({ report: async () => gap })} />);
    expect(await screen.findByText("no supplier quote is stored for this product")).toBeInTheDocument();
  });

  it("shows the research evidence: independent sources with links, video engagement, and what could not be obtained", async () => {
    const withEvidence = caseOf(RUN_A, { products: [product(1, {
      source_diversity: 3, source_urls: [{ url: "https://a.example/review", source: "tavily" }, { url: "https://a.example/other", source: "tavily" }, { url: "https://www.youtube.com/watch?v=x", source: "youtube" }, { url: "javascript:alert(1)", source: "tavily" }],
      engagement_signal: { status: "AVAILABLE", video_count: 2, view_count: 150000, comment_count: 900 }, demand_signal: { status: "UNAVAILABLE", reason: "Google Ads API access pending brand verification" },
      score_explanation: { signals: [{ signal: "source_diversity", status: "AVAILABLE", points: 3, max_points: 4, reason: "3 independent domains" }, { signal: "demand_signal", status: "UNAVAILABLE", points: 0, max_points: 0, reason: "pending" }] },
    })] });
    render(<PiShowcase client={fake({ report: async () => withEvidence })} />);
    const panel = await screen.findByLabelText("Research evidence and trend signals");
    expect(within(panel).getByText(/3 websites or videos mention it/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "a.example" })).toHaveAttribute("href", "https://a.example/review"); // one link per independent domain
    expect(within(panel).getAllByRole("link")).toHaveLength(2); // a.example and youtube.com; the javascript: URL is never a link
    expect(within(panel).getByText(/2 video\(s\), 150,000 views, 900 comments|2 video\(s\), 1,50,000 views, 900 comments/)).toBeInTheDocument();
    expect(within(panel).getByText(/unavailable - Google Ads API access pending brand verification/)).toBeInTheDocument();
    expect(within(panel).getByText(/3\/4 points - 3 independent domains/)).toBeInTheDocument();
  });

  it("names missing engagement instead of showing zero", async () => {
    render(<PiShowcase client={fake({ report: async () => caseOf(RUN_A, { products: [product(1, { engagement_signal: { status: "UNAVAILABLE", reason: "no YouTube video matched this product" } })] }) })} />);
    const panel = await screen.findByLabelText("Research evidence and trend signals");
    expect(within(panel).getByText(/no YouTube video matched this product/)).toBeInTheDocument();
  });

  it("pins a saved report through the client", async () => {
    const client = fake();
    render(<PiShowcase client={client} />);
    await screen.findByText("Rank #1");
    const current = screen.getByRole("region", { name: /Investigation: mens watches/ });
    await userEvent.click(within(current).getByRole("button", { name: "Pin" }));
    await waitFor(() => expect(client.pin).toHaveBeenCalledWith(RUN_A));
  });

  it("opens the report named by the CEO link, and loads an older investigation on expand", async () => {
    const report = vi.fn(async (id: string) => caseOf(id, { brief: { category: id === RUN_B ? "jars" : "mens watches", budgetPaise: null } }));
    render(<PiShowcase client={fake({ report })} initialRunId={RUN_B} />);
    expect(await screen.findByRole("heading", { name: /Investigation: jars/ })).toBeInTheDocument();
    expect(report).toHaveBeenCalledWith(RUN_B);
    await userEvent.click(screen.getByRole("button", { name: "Expand Window" }));
    expect(await screen.findByText(/Recommendation summary:/)).toBeInTheDocument();
    expect(report).toHaveBeenCalledWith(RUN_A);
    expect(screen.getByRole("link", { name: /Full Audit Report/ })).toHaveAttribute("href", `/reports/pi/${RUN_A}/print`);
  });

  it("shows an honest empty state that points to the CEO when nothing is saved", async () => {
    render(<PiShowcase client={fake({ history: async () => ({ items: [] }) })} />);
    expect(await screen.findByText("No saved research yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ask the CEO to research products/ })).toHaveAttribute("href", "/dashboard/ceo-hub");
  });

  it("shows an error with retry when history fails", async () => {
    const history = vi.fn().mockRejectedValueOnce(Object.assign(new Error("x"), { status: 500 })).mockResolvedValue({ items: [hist(RUN_A)] });
    render(<PiShowcase client={fake({ history })} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load/i);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Rank #1")).toBeInTheDocument();
  });

  it("states a 404 for a report that left history", async () => {
    render(<PiShowcase client={fake({ report: async () => { throw Object.assign(new Error("x"), { status: 404 }); } })} />);
    expect(await screen.findByText("This report is no longer in your history.")).toBeInTheDocument();
  });
});

describe("PI page contracts", () => {
  it("the page source never calls a research-starting route", () => {
    const src = [join(__dirname, "../../app/dashboard/pi/page.tsx"), join(__dirname, "../../lib/piShowcase.ts"), join(__dirname, "PiShowcase.tsx")].map((f) => readFileSync(f, "utf8")).join("\n");
    expect(src).not.toMatch(/\/pi\/discover|\/pi\/supplier-lookup|\/pi\/niche-briefs/);
    expect(src).not.toMatch(/dangerouslySetInnerHTML/);
  });
});

const deferred = <T,>() => {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => ((resolve = res), (reject = rej)));
  return { promise, resolve, reject };
};
const current = () => screen.getByRole("region", { name: /Investigation: mens watches/ });

describe("PI pinning keeps the open report in place", () => {
  it("never blanks the report while the pin is confirmed, shows the backend's answer at once, and confirms it with the toast", async () => {
    const reload = deferred<PiCase>();
    let reports = 0;
    const client = fake({ report: vi.fn(async (id: string) => (++reports === 1 ? caseOf(id) : reload.promise)) });
    render(<ToastProvider><PiShowcase client={client} /></ToastProvider>);
    await screen.findByText("Rank #1");
    await userEvent.click(within(current()).getByRole("button", { name: "Pin" }));
    expect(await within(current()).findByRole("button", { name: "Pinned" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Report pinned.")).toBeInTheDocument();
    expect(screen.getByText("Rank #1")).toBeInTheDocument(); // the report is still there while it is re-read
    expect(screen.queryByLabelText("Loading investigation")).toBeNull();
    expect(within(current()).getByText("Updating…")).toBeInTheDocument();
    reload.resolve(caseOf(RUN_A, { pinned: true }));
    await waitFor(() => expect(within(current()).queryByText("Updating…")).toBeNull());
    expect(within(current()).getByRole("button", { name: "Pinned" })).toBeInTheDocument();
  });

  it("sends one request for a double press", async () => {
    const gate = deferred<{ runId: string; pinned: boolean }>();
    const client = fake({ pin: vi.fn(() => gate.promise) });
    render(<PiShowcase client={client} />);
    await screen.findByText("Rank #1");
    const pin = within(current()).getByRole("button", { name: "Pin" });
    fireEvent.click(pin);
    fireEvent.click(pin);
    expect(client.pin).toHaveBeenCalledTimes(1);
    gate.resolve({ runId: RUN_A, pinned: true });
    await within(current()).findByRole("button", { name: "Pinned" });
  });

  it("says why a pin failed and stays unpinned, with no success toast", async () => {
    const client = fake({ pin: vi.fn(async () => { throw Object.assign(new Error("x"), { status: 500 }); }) });
    render(<ToastProvider><PiShowcase client={client} /></ToastProvider>);
    await screen.findByText("Rank #1");
    await userEvent.click(within(current()).getByRole("button", { name: "Pin" }));
    expect(await within(current()).findByRole("alert")).toHaveTextContent(/could not load/i);
    expect(within(current()).getByRole("button", { name: "Pin" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText("Report pinned.")).toBeNull();
  });

  it("keeps the report and says so when re-reading it fails", async () => {
    let reports = 0;
    const client = fake({ report: vi.fn(async (id: string) => { if (++reports > 1) throw Object.assign(new Error("x"), { status: 500 }); return caseOf(id); }) });
    render(<PiShowcase client={client} />);
    await screen.findByText("Rank #1");
    await userEvent.click(within(current()).getByRole("button", { name: "Pin" }));
    expect(await within(current()).findByText(/Showing the last copy of this report that loaded/)).toBeInTheDocument();
    expect(screen.getByText("Rank #1")).toBeInTheDocument();
    await userEvent.click(within(current()).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(client.report).toHaveBeenCalledTimes(3));
  });
});

describe("PI saved-research list refreshes without losing what loaded", () => {
  it("names how many reports it shows and when it was checked", async () => {
    render(<PiShowcase client={fake()} />);
    expect(await screen.findByTestId("pi-context")).toHaveTextContent(/2 saved reports · checked /);
  });

  it("keeps the list and says it is the last one that loaded when a refresh fails", async () => {
    let fail = false;
    const client = fake({ history: async () => { if (fail) throw Object.assign(new Error("x"), { status: 500 }); return { items: [hist(RUN_A), hist(RUN_B, { category: "jars" })] }; } });
    render(<PiShowcase client={client} />);
    await screen.findByText("Rank #1");
    fail = true;
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Showing the last list that loaded/);
    expect(screen.getByText("Rank #1")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Old investigation: jars/ })).toBeInTheDocument();
  });

  it("shows a refresh in progress, keeps the list, and cannot start a second refresh", async () => {
    const slow = deferred<{ items: PiHistoryItem[] }>();
    let calls = 0;
    const client = fake({ history: vi.fn(() => (++calls === 1 ? Promise.resolve({ items: [hist(RUN_A)] }) : slow.promise)) });
    render(<PiShowcase client={client} />);
    await screen.findByText("Rank #1");
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
    expect(screen.getByTestId("pi-context")).toHaveTextContent(/Refreshing… what is shown is the last list that loaded/);
    expect(screen.getByText("Rank #1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Refreshing…" }));
    expect(client.history).toHaveBeenCalledTimes(2);
    slow.resolve({ items: [hist(RUN_A)] });
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled());
  });

  it("ignores an older list that arrives after a newer one", async () => {
    const slow = deferred<{ items: PiHistoryItem[] }>();
    let calls = 0;
    const client = fake({
      history: vi.fn(() => {
        calls++;
        if (calls === 1) return Promise.resolve({ items: [hist(RUN_A)] });
        if (calls === 2) return slow.promise; // the manual refresh: slow, and old
        return Promise.resolve({ items: [hist(RUN_A), hist(RUN_B, { category: "jars" })] }); // the re-read after the pin: newer
      }),
    });
    render(<PiShowcase client={client} />);
    await screen.findByText("Rank #1");
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await userEvent.click(within(current()).getByRole("button", { name: "Pin" }));
    await waitFor(() => expect(screen.getByTestId("pi-context")).toHaveTextContent(/2 saved reports/));
    slow.resolve({ items: [hist(RUN_A)] }); // arrives last, and is dropped
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByTestId("pi-context")).toHaveTextContent(/2 saved reports/);
    expect(screen.getByRole("region", { name: /Old investigation: jars/ })).toBeInTheDocument();
  });

  it("offers a retry when the first load fails, which cannot be pressed twice", async () => {
    const gate = deferred<{ items: PiHistoryItem[] }>();
    let calls = 0;
    const client = fake({ history: vi.fn(() => (++calls === 1 ? Promise.reject(Object.assign(new Error("x"), { status: 500 })) : gate.promise)) });
    render(<PiShowcase client={client} />);
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByRole("button", { name: "Try again" })).toBeDisabled();
    gate.resolve({ items: [hist(RUN_A)] });
    expect(await screen.findByText("Rank #1")).toBeInTheDocument();
    expect(client.history).toHaveBeenCalledTimes(2);
  });
});

describe("PI showcase: one strong action, and the research stays read-only", () => {
  const solid = (el: Element) => el.classList.contains("ov-btn--brand") && el.tagName === "A"; // the pinned toggle is a button; only a link can be the solid next step

  it("leaves '+ New Discovery' as the one solid control; batch size and supplier links are calm", async () => {
    const lead = { id: "l1", candidate_id: "c1", supplier_name: "Acme Supply", source: "TAVILY", source_url: "https://acme.example/p", locality: "Delhi", contact_email: null, contact_phone: null, contact_website: null, published_price: null, moq: null, fetched_at: "2026-10-10T00:00:00Z" } as never;
    const withLead = caseOf(RUN_A, { products: [1, 2, 3, 4, 5].map((n) => (n === 1 ? { ...product(n), supplierLeads: [lead], bestSupplierLeadId: "l1" } : product(n))) });
    render(<PiShowcase client={fake({ report: async () => withLead })} />);
    await screen.findByRole("heading", { name: /Recent Investigation/ });
    const strong = [...document.querySelectorAll("a, button")].filter((e) => solid(e) && !e.hasAttribute("aria-current")); // the active carousel dot marks position, it is not an action
    expect(strong.map((e) => e.textContent)).toEqual(["+ New Discovery"]);
    expect(solid(screen.getByRole("link", { name: /Ask for batch size/ }))).toBe(false);
  });

  it("shows the saved score as plain text, not as a positive state", async () => {
    render(<PiShowcase client={fake()} />);
    await screen.findByRole("heading", { name: /Recent Investigation/ });
    const topScore = screen.getAllByText(/^Score 89.00\/100$/)[0];
    expect(topScore.getAttribute("style") ?? "").not.toContain("var(--accent)");
    expect(screen.getByText("Rank #1").getAttribute("style") ?? "").not.toContain("var(--accent)");
  });

  it("puts the product's name first in its information card and keeps the section heading", async () => {
    render(<PiShowcase client={fake()} />);
    const card = await screen.findByLabelText("Product information: Watch 1");
    expect(within(card).getByRole("heading", { name: "Product Information" })).toBeInTheDocument();
    expect(within(card).getByText("Watch 1", { selector: "p" })).toBeInTheDocument();
    expect(card).toHaveTextContent(/from public web signals/);
  });
});

