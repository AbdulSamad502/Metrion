import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CmoOverview } from "@/components/cmo/CmoOverview";
import { ApiError } from "@/lib/api";
import { demoRespond } from "@/lib/demo/respond";
import type { ImagesApi } from "@/lib/cmoImages";
import type { MarketApi } from "@/lib/cmoMarket";
import type { PerformanceApi } from "@/lib/cmoPerformance";

const sample = <T,>(path: string): Promise<T> => {
  const out = demoRespond<T>(path);
  return out.handled ? Promise.resolve(out.body) : Promise.reject(new Error("unhandled"));
};
const filled = () => ({
  performance: { dashboard: vi.fn(() => sample("/api/v1/cmo/performance/dashboard?")) } as unknown as PerformanceApi,
  images: { products: vi.fn(() => sample("/api/v1/cmo/product-images/products")), page: vi.fn((s: string, m: string) => sample(`/api/v1/cmo/product-images?sku=${s}&marketplace=${m}`)) } as unknown as ImagesApi,
  market: { overview: vi.fn(() => sample("/api/v1/cmo/market-intelligence?")) } as unknown as MarketApi,
});

describe("the CMO overview", () => {
  it("shows the three lanes with their source, period and status, and the figures exactly as served", async () => {
    const a = filled();
    render(<CmoOverview {...a} />);
    expect(await screen.findByTestId("perf-sales")).toHaveTextContent("₹1,12,640.00");
    expect(screen.getByTestId("lane-performance-status")).toHaveTextContent("CURRENT");
    expect(screen.getByTestId("lane-performance")).toHaveTextContent("30 of 30 days covered");
    expect(await screen.findByTestId("images-score")).toHaveTextContent("78 / 100");
    expect(screen.getByTestId("lane-images")).toHaveTextContent("marketplace requirements NOT ASSESSED");
    expect(await screen.findByTestId("market-top-opportunity")).toHaveTextContent("relevance HIGH");
    expect(screen.getByTestId("lane-market")).toHaveTextContent("Demand is UNAVAILABLE");
    expect(screen.getAllByRole("link").map((l) => l.getAttribute("href"))).toEqual(expect.arrayContaining(["/dashboard/cmo/performance", "/dashboard/cmo/images", "/dashboard/cmo/market"]));
  });

  it("says what is missing in each lane instead of showing a zero", async () => {
    render(<CmoOverview
      performance={{ dashboard: vi.fn(async () => ({ ...(await sample<object>("/api/v1/cmo/performance/dashboard?")), dataSpan: { lastImportAt: null, first: null, last: null } })) } as unknown as PerformanceApi}
      images={{ products: vi.fn(async () => ({ products: [{ sku: "a", name: "A", sets: [{ marketplace: "AMAZON", images: 0 }] }], marketplaces: ["AMAZON"], shotTypes: [], limits: { maxImages: 12, maxFilesPerRequest: 6 } })), page: vi.fn() } as unknown as ImagesApi}
      market={{ overview: vi.fn(async () => ({ state: "NO_REPORT", message: "You have no saved market-trend report yet.", news: [], opportunities: [] })) } as unknown as MarketApi} />);
    expect(await screen.findByTestId("performance-empty")).toHaveTextContent("Nothing is estimated");
    expect(await screen.findByTestId("images-empty")).toHaveTextContent("never counted as a pass");
    expect(await screen.findByTestId("market-lane-empty")).toHaveTextContent("no saved market-trend report");
  });

  it("shows a plain failure in one lane without breaking the others", async () => {
    const a = filled();
    (a.market.overview as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(500, { detail: "x" }));
    render(<CmoOverview {...a} />);
    expect(await screen.findByTestId("perf-sales")).toBeInTheDocument();
    expect(await screen.findByText(/Your saved market reports could not be read/)).toBeInTheDocument();
  });
});
