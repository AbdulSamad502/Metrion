import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PiReportPrint } from "@/components/pi/PiReportPrint";
import type { PiCase, PiClient } from "@/lib/piShowcase";

const LONG = "https://www.example-supplier-domain.com/products/very/long/path/that/never/breaks/in/any/natural/place/abcdefghijklmnopqrstuvwxyz0123456789";
const report = (): PiCase => ({
  runId: "11111111-1111-4111-8111-111111111111", status: "COMPLETE", pinned: false, pinnedAt: null, completedAt: "2026-10-10T00:00:00Z", caseSaved: true,
  brief: { category: "kitchen", budgetPaise: null, targetPriceMinPaise: null, targetPriceMaxPaise: null, marketplaces: [] },
  products: [{
    rank: 1, candidate: { id: "c1", candidate_title: "Container", observed_category: "Kitchen", image_url: null, image_source_url: null, proxy_score: "50.00", web_price_signal: { status: "UNAVAILABLE", average_paise: null }, candidate_marketplaces: [], source_urls: [], feasibility_status: "UNAVAILABLE", feasibility_low_paise: null, feasibility_high_paise: null, feasibility_cogs_basis: null, feasibility_unavailable_reason: null },
    reviewInsights: [], supplierLeads: [], bestSupplierLeadId: null, finalScore: "80.00", finalScoreState: "COMPUTED", financials: [],
    recommendation: { candidate_id: "c1", rank: 1, title: "Container", final_score: "80.00", final_score_state: "COMPUTED", why_ranked: [], pros: [], cons: [], gaps: [], note: "x",
      supplier_option: { id: "l1", supplier_name: "Acme Traders", locality: null, source: "INDIAMART", source_url: LONG, contact: { phone: null, website: null, published_price: null } } },
  } as never],
  overall: null, cfoRefs: [], gaps: [], unavailable: [], investigationId: null,
});
const client: PiClient = { history: async () => ({ items: [] }), report: async () => report(), pin: async () => ({ runId: "x", pinned: true }), unpin: async () => ({ runId: "x", pinned: false }) };

describe("PI report layout (jsdom: inline styles only; real wrapping checked in Chromium)", () => {
  it("lets a long unbroken supplier URL wrap inside its value cell and keeps the value column shrinkable", async () => {
    const { container } = render(<PiReportPrint client={client} runId="11111111-1111-4111-8111-111111111111" />);
    const cell = (await screen.findByText(new RegExp(LONG.slice(0, 40)))).closest("div") as HTMLElement;
    expect(cell.style.overflowWrap).toBe("anywhere");
    expect((cell.parentElement as HTMLElement).style.gridTemplateColumns).toBe("9.5rem minmax(0, 1fr)");
    expect(container.textContent).toContain(LONG); // the URL itself is printed whole, not truncated
  });

  it("forces a white page canvas and light colour scheme for print, and still hides the print button there", async () => {
    const { container } = render(<PiReportPrint client={client} runId="11111111-1111-4111-8111-111111111111" />);
    await screen.findByText(/Acme Traders/);
    const css = container.querySelector("style")!.textContent!;
    expect(css).toMatch(/@media print \{[^}]*html:root \{ background: #fff !important; color-scheme: light !important; \}/);
    expect(css).toMatch(/\.pi-no-print \{ display: none !important; \}/);
    expect(screen.getByRole("button", { name: "Print / Save as PDF" })).toHaveClass("pi-no-print");
  });
});
