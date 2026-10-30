import fs from "node:fs";
import path from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnomalyCheckSection, CfoPreviewSection, PeriodComparisonSection, ReconcileSection } from "@/components/cfo/sections/ReportingSections";
import { FinancialHealthSection, SellerGoalSection, StrategicBriefingSection } from "@/components/cfo/sections/ImportAndGoalSections";
import { BatchSizeSection, FundingReadinessSection, LandedCostSection, PricingCurveSection, SupplierRankingSection } from "@/components/cfo/sections/PricingSections";
import { ExpenseTrackerSection } from "@/components/cfo/sections/ExpenseTrackerSection";
import { PeriodPnlSection } from "@/components/cfo/sections/PeriodPnlSection";

// Each Profit & Finance form is filled in the way a seller would and submitted; the request the component really builds is (1) checked against the backend's schema by the
// guard in test-support/setup.ts, values included, and (2) recorded in test-support/fixtures/requestSamples.json. backend/tests/integration/test_frontend_request_samples.py
// replays those exact bodies against the real routes. With CAPTURE_REQUEST_SAMPLES=1 the file is rewritten; without it the test fails when a form's request no longer
// has the recorded shape, so the backend never replays bodies the frontend has stopped sending.
const SAMPLES = path.resolve(__dirname, "../../test-support/fixtures/requestSamples.json");
const captured: Record<string, unknown> = {};
let calls: { method: string; url: string; body: unknown }[];

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ method: init?.method ?? "GET", url: String(url).replace(/^https?:\/\/[^/]+/, ""), body: init?.body ? JSON.parse(String(init.body)) : null });
    return new Response(JSON.stringify({ detail: "not computed in this test" }), { status: 503, headers: { "Content-Type": "application/json" } });
  }));
});
afterEach(() => vi.unstubAllGlobals());

const user = () => userEvent.setup();
const token = async () => "t";
const D = { start: "2026-09-01", end: "2026-09-30", asOf: "2026-09-30" };

async function typeInto(u: ReturnType<typeof user>, label: string | RegExp, value: string, nth = 0) {
  const el = screen.getAllByLabelText(label)[nth];
  if (el.tagName === "SELECT") {
    await u.selectOptions(el, value); // the marketplace is a choice of the three supported ids; the value sent is the same id the text box used to take
    return;
  }
  await u.clear(el);
  await u.type(el, value);
}

async function submit(ui: ReactElement, fills: ([string | RegExp, string] | [string | RegExp, string, number])[], button: string) {
  render(ui);
  const u = user();
  for (const [label, value, nth] of fills) await typeInto(u, label, value, nth ?? 0);
  await u.click(screen.getByRole("button", { name: button }));
  await waitFor(() => expect(calls.length).toBe(1));
  const sent = calls[0];
  // the guard rejects a request the backend would refuse, which surfaces as a CONTRACT error instead of a call
  const query = sent.url.includes("?") ? Object.fromEntries(new URL(sent.url, "http://x").searchParams) : null;
  captured[`${sent.method} ${sent.url.split("?")[0]}`] = sent.body ?? { __query: query };
  return sent;
}

const dates = (): [string, string][] => [["Period start", D.start], ["Period end", D.end], ["As-of date", D.asOf]];

describe("what the Profit & Finance forms send", () => {
  it("add expense", async () => {
    const s = await submit(<ExpenseTrackerSection getToken={token} />, [["Amount (₹)", "500"]], "Add expense");
    expect(s.method).toBe("PUT");
  });

  it("set expense budget", async () => {
    await submit(<ExpenseTrackerSection getToken={token} />, [["Budget ceiling (₹)", "20000"], ["Period start", D.start, 0], ["Period end", D.end, 0]], "Set budget");
  });

  it("check budget status (a query, no body)", async () => {
    const s = await submit(<ExpenseTrackerSection getToken={token} />, [["Period start", D.start, 1], ["Period end", D.end, 1]], "Check status");
    expect(s.method).toBe("GET");
  });

  it("pricing curve, with every cost answered explicitly", async () => {
    render(<PricingCurveSection getToken={token} />);
    const u = user();
    for (const [label, value] of [["SKU", "SKU-1"], ["Marketplace", "AMAZON"], ["Category", "Home"], ["Fee type", "referral"], ["As-of date", D.asOf]] as [string, string][]) await typeInto(u, label, value);
    await u.type(screen.getByPlaceholderText("e.g. 999"), "999");
    for (const radio of screen.getAllByRole("radio", { name: "None (0), I confirm" })) await u.click(radio);
    await u.click(screen.getByRole("button", { name: "Compute pricing curve" }));
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].body).toMatchObject({ sku: "SKU-1", candidate_prices_paise: [99900], basis: "INCLUSIVE", shipping_logistics_paise: 0, advertising_costs_paise: 0, other_allocated_costs_paise: 0 });
    captured[`${calls[0].method} ${calls[0].url}`] = calls[0].body;
  });

  it("period P&L (single line)", async () => {
    await submit(<PeriodPnlSection getToken={token} />, [["Marketplace", "AMAZON"], ["Gross item amount (₹)", "999"], ["Sales line id (UUID)", "7c1d3e50-0000-4000-8000-000000000003"], ...dates()], "Compute period P&L");
  });

  it("reconciliation", async () => {
    const s = await submit(<ReconcileSection getToken={token} />, [["Marketplace", "FLIPKART"], ...dates()], "Run reconciliation");
    expect(s.body).toEqual({ marketplace: "FLIPKART", period_start: D.start, period_end: D.end, as_of_date: D.asOf });
  });

  it("preview", async () => {
    await submit(<CfoPreviewSection getToken={token} />, [["Marketplace", "AMAZON"], ...dates()], "Load preview");
  });

  it("anomaly check", async () => {
    await submit(<AnomalyCheckSection getToken={token} />, [[/target ref/i, "TENANT"], ...dates()], "Run anomaly check");
  });

  it("period comparison", async () => {
    await submit(
      <PeriodComparisonSection getToken={token} />,
      [[/First result reference/, "7c1d3e50-0000-4000-8000-000000000001"], [/Second result reference/, "7c1d3e50-0000-4000-8000-000000000002"], ["As-of date", D.asOf]],
      "Compare periods",
    );
  });

  it("financial health", async () => {
    await submit(<FinancialHealthSection getToken={token} />, dates(), "Compute");
  });

  it("strategic briefing", async () => {
    await submit(<StrategicBriefingSection getToken={token} />, dates(), "Build briefing");
  });

  it("seller goal", async () => {
    // The section also reads the saved goal when it mounts (a GET), so wait for the PUT specifically.
    render(<SellerGoalSection getToken={token} />);
    const u = user();
    await typeInto(u, /Target margin/, "15.00");
    await typeInto(u, /Priority category/, "reduce_fees");
    await u.click(screen.getByRole("button", { name: "Save goal" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    captured[`PUT ${put.url}`] = put.body;
  });

  it("landed cost", async () => {
    await submit(<LandedCostSection getToken={token} />, [["SKU", "SKU-1"], ["Supplier quote target ref", "SKU-1"], ["Quantity", "100"]], "Compute landed cost");
  });

  it("supplier ranking", async () => {
    await submit(<SupplierRankingSection getToken={token} />, [["SKU", "SKU-1"], ["Quantity", "100"]], "Rank suppliers");
  });

  it("batch size", async () => {
    await submit(<BatchSizeSection getToken={token} />, [["SKU", "SKU-1"], ["Supplier quote target ref", "SKU-1"], ["Budget target ref", "tenant"], ...dates()], "Estimate batch size");
  });

  it("funding readiness", async () => {
    await submit(<FundingReadinessSection getToken={token} />, dates(), "Assemble funding readiness");
  });
});

afterAll(() => {
  const text = JSON.stringify(Object.fromEntries(Object.entries(captured).sort(([a], [b]) => a.localeCompare(b))), null, 1) + "\n";
  if (process.env.CAPTURE_REQUEST_SAMPLES) fs.writeFileSync(SAMPLES, text, "utf8");
  else if (Object.keys(captured).length === 16) {
    const shape = (v: unknown): unknown => (v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort().map(([k, x]) => [k, shape(x)])) : Array.isArray(v) ? v.map(shape) : typeof v);
    const committed = JSON.parse(fs.readFileSync(SAMPLES, "utf8"));
    expect(shape(JSON.parse(text))).toEqual(shape(committed)); // stale: rerun with CAPTURE_REQUEST_SAMPLES=1
  }
});
