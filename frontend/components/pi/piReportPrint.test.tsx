import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PiReportPrint } from "@/components/pi/PiReportPrint";
import type { PiCase, PiClient, PiProduct } from "@/lib/piShowcase";

const RUN = "11111111-1111-4111-8111-111111111111";

const product = (rank: number, over: Partial<PiProduct> = {}): PiProduct => ({
  rank,
  candidate: { id: `c${rank}`, candidate_title: `Watch ${rank}`, observed_category: "Watches", image_url: rank === 1 ? "https://cdn.shop.example/w1.jpg" : null, image_source_url: "https://shop.example/w1", proxy_score: "50.00", web_price_signal: { status: "AVAILABLE", average_paise: 299900 }, candidate_marketplaces: ["AMAZON"], source_urls: [], feasibility_status: "UNAVAILABLE", feasibility_low_paise: null, feasibility_high_paise: null, feasibility_cogs_basis: null, feasibility_unavailable_reason: null },
  reviewInsights: [], supplierLeads: [], bestSupplierLeadId: null, finalScore: `${90 - rank}.00`, finalScoreState: "COMPUTED", financials: [],
  recommendation: { candidate_id: `c${rank}`, rank, title: `Watch ${rank}`, final_score: `${90 - rank}.00`, final_score_state: "COMPUTED", why_ranked: ["Stage 1 proxy score was 50.00/100"], pros: ["comfortable strap"], cons: ["strap is stiff"], supplier_option: null, gaps: ["no supplier lead was found for this product"], note: "x" },
  ...over,
});

const report = (over: Partial<PiCase> = {}): PiCase => ({
  runId: RUN, status: "COMPLETE", pinned: false, pinnedAt: null, completedAt: "2026-10-10T00:00:00Z", caseSaved: true,
  brief: { category: "mens watches", budgetPaise: 35000000, targetPriceMinPaise: 199900, targetPriceMaxPaise: 349900, marketplaces: ["AMAZON"] },
  products: [1, 2, 3, 4, 5].map((n) => product(n)), overall: { candidate_id: "c1", title: "Watch 1", final_score: "89.00", reason: "highest combined score (89.00/100)", note: "x" },
  cfoRefs: [], gaps: ["only 5 candidates had signal"], unavailable: [{ field: "verified_buyer_reviews", reason: "no marketplace access in V1" }], investigationId: null, ...over,
});

const client = (r: PiCase | Error): PiClient => ({
  history: async () => ({ items: [] }),
  report: async () => { if (r instanceof Error) throw r; return r; },
  pin: vi.fn(), unpin: vi.fn(),
});

describe("PI print / PDF report", () => {
  it("prints the brief, all five products with findings, suppliers, financial status and recommendations", async () => {
    render(<PiReportPrint client={client(report())} runId={RUN} />);
    expect(await screen.findByRole("heading", { name: "mens watches" })).toBeInTheDocument();
    for (let n = 1; n <= 5; n++) expect(screen.getByRole("region", { name: new RegExp(`Rank ${n}: Watch ${n}`) })).toBeInTheDocument();
    expect(screen.getByText(/Budget ₹3,50,000 · Target price ₹1,999 - ₹3,499/)).toBeInTheDocument();
    expect(screen.getByText(/Strongest opportunity: Watch 1/)).toBeInTheDocument();
    expect(screen.getAllByText(/comfortable strap/).length).toBe(5);
    expect(screen.getAllByText("No supplier lead was found.").length).toBe(5);
    expect(screen.getAllByText(/Not calculated: they need a supplier quote you confirm with the CEO/).length).toBe(5);
    expect(screen.getByText("image from shop.example")).toBeInTheDocument();
    expect(screen.getByText(/What this research could not provide/)).toBeInTheDocument();
    expect(screen.getByText(/verified buyer reviews:/)).toBeInTheDocument();
    expect(screen.getByText("only 5 candidates had signal")).toBeInTheDocument();
    expect(screen.getByText(/not verified as selling well/)).toBeInTheDocument();
  });

  it("prints CFO results labelled as coming from the confirmed quote, and a missing one with its reason; supplier price is not a quote", async () => {
    const lead = { id: "l", supplier_name: "Siddhi", source: "TAVILY", contact: { published_price: { low_paise: 45000, high_paise: 45000, sample_count: 1, unit: "piece", source_url: null, captured_at: "2026-10-09T00:00:00Z", disclaimer: "x" } }, locality: null, source_url: "https://s.example" };
    const financials = [
      { kind: "ENGINE" as const, authoritative: true, leg_key: "cfo.landed_cost", label: "Landed cost per unit", display: "₹255", status: "COMPLETE" as const },
      { kind: "GAP" as const, authoritative: true, leg_key: "cfo.batch_size", label: "Most units your budget allows", display: null, status: "UNAVAILABLE" as const, reason: "no budget stored" },
    ];
    render(<PiReportPrint client={client(report({ products: [product(1, { supplierLeads: [lead], bestSupplierLeadId: "l", financials })] }))} runId={RUN} />);
    expect(await screen.findByText(/Landed cost per unit: ₹255 \(from your confirmed supplier quote\)/)).toBeInTheDocument();
    expect(screen.getByText(/Most units your budget allows: Unavailable \(no budget stored\)/)).toBeInTheDocument();
    expect(screen.getByText(/Published price ₹450 per piece \(the supplier's own page, .*; not a quote\)/)).toBeInTheDocument();
  });

  it("has a print button that calls the browser print and nothing that starts research", async () => {
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    const { container } = render(<PiReportPrint client={client(report())} runId={RUN} />);
    await userEvent.click(await screen.findByRole("button", { name: "Print / Save as PDF" }));
    expect(print).toHaveBeenCalledOnce();
    expect(container.querySelectorAll("input, textarea, select, form")).toHaveLength(0);
    expect(container.querySelector(".pi-no-print")).not.toBeNull(); // the button is hidden in the printout
  });

  it("says plainly when the report is no longer available", async () => {
    render(<PiReportPrint client={client(Object.assign(new Error("x"), { status: 404 }))} runId={RUN} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This report is no longer in your history.");
  });
});
