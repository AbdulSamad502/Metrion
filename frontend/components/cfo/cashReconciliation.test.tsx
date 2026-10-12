import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CashReconciliationSection } from "@/components/cfo/sections/ReportingSections";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const metric = (code: string, over: Record<string, unknown> = {}) => ({ engineResultRef: "11111111-1111-1111-1111-111111111111", metricCode: code, valuePaise: null, isAvailable: false, confidence: "UNAVAILABLE", calculationBasis: null, unavailableReason: "no adapter maps this", asOfDate: "2026-09-30", ...over });
let calls: { url: string; body: unknown }[];
let response: () => Promise<Response>;

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : null });
    return response();
  }));
});
afterEach(() => vi.unstubAllGlobals());

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Marketplace"), "FLIPKART");
  await user.type(screen.getByLabelText("Period start"), "2026-09-01");
  await user.type(screen.getByLabelText("Period end"), "2026-09-30");
  await user.type(screen.getByLabelText("As-of date"), "2026-09-30");
}

describe("Cash reconciliation", () => {
  it("asks for the inputs first and calls nothing without them", async () => {
    render(<CashReconciliationSection getToken={async () => "t"} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Check cash received" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Fill in marketplace and all three dates first.");
    expect(calls).toHaveLength(0);
  });

  it("posts the period to the real route and shows what is available and what is not, never a made-up expected figure", async () => {
    response = async () => reply({
      cashReceived: metric("CASH_RECEIVED", { valuePaise: 123400, isAvailable: true, confidence: "VERIFIED", unavailableReason: null }),
      cashExpected: metric("CASH_EXPECTED"), cashVariance: metric("CASH_VARIANCE"), tcsCollected: metric("TCS_COLLECTED", { valuePaise: 500, isAvailable: true, confidence: "VERIFIED", unavailableReason: null }), tdsDeducted: metric("TDS_DEDUCTED"),
      settledWithinLagCount: 7, unsettledBeyondLagCount: 2, datesMissingCount: 1,
    });
    render(<CashReconciliationSection getToken={async () => "t"} />);
    const user = userEvent.setup();
    await fill(user);
    await user.click(screen.getByRole("button", { name: "Check cash received" }));
    expect(await screen.findByText(/Settled within the usual lag: 7/)).toBeInTheDocument();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain("/api/v1/cfo/cash-reconciliation");
    expect(calls[0].body).toEqual({ marketplace: "FLIPKART", period_start: "2026-09-01", period_end: "2026-09-30", as_of_date: "2026-09-30" });
    expect(screen.getAllByText(/Unavailable/i).length).toBeGreaterThanOrEqual(3); // expected, variance and TDS
    expect(screen.getByText("+₹1234.00")).toBeInTheDocument();
  });

  it("a refused request is plain words and shows no result", async () => {
    response = async () => reply({ detail: { code: "ENTITLEMENT", trace: "x" } }, 402);
    render(<CashReconciliationSection getToken={async () => "t"} />);
    const user = userEvent.setup();
    await fill(user);
    await user.click(screen.getByRole("button", { name: "Check cash received" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/Settled within/)).toBeNull();
  });
});
