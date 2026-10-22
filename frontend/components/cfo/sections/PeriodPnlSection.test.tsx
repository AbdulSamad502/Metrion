import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PeriodPnlSection } from "@/components/cfo/sections/PeriodPnlSection";

// ST-01 (docs/specs/expense-tracker.md Appendix D): the result says whether advertising was entered in THIS calculation. Absent is "Not entered in this
// calculation" and never ₹0.00; an entered amount (including an explicit zero) is shown as money. The wording says "in this calculation" because rows saved
// in the legacy expense tracker (PUT /cfo/expenses) are not read by this P&L; they only count when the caller supplies them.

const metric = (code: string, valuePaise: number | null, valueFraction: string | null = null) => ({
  engineResultRef: "00000000-0000-4000-8000-000000000001",
  metricCode: code,
  valuePaise,
  valueFraction,
  isAvailable: true,
  confidence: "PROVISIONAL",
  calculationBasis: "test",
  unavailableReason: null,
  asOfDate: "2026-09-30",
});

const response = (advertisingEntered: boolean, advertisingCostsPaise: number | null) => ({
  nrr: metric("NET_REALIZED_REVENUE", 99900),
  contributionProfit: metric("CONTRIBUTION_PROFIT", 50000),
  marginPct: metric("CONTRIBUTION_MARGIN_PCT", null, "50.05"),
  feeRatioPct: metric("FEE_RATIO_PCT", null, "5.00"),
  returnRatePct: metric("RETURN_RATE_PCT", null, "0.00"),
  marketplaceFeeFlags: [],
  dataRequestId: null,
  advertisingEntered,
  advertisingCostsPaise,
});

async function compute(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })));
  render(<PeriodPnlSection getToken={async () => "t"} />);
  const u = userEvent.setup();
  const fill = async (label: string, value: string) => {
    const el = screen.getAllByLabelText(label)[0];
    await u.clear(el);
    await u.type(el, value);
  };
  await fill("Marketplace", "AMAZON");
  await fill("Gross item amount (₹)", "999");
  await fill("Sales line id (UUID)", "7c1d3e50-0000-4000-8000-000000000003");
  await fill("Period start", "2026-09-01");
  await fill("Period end", "2026-09-30");
  await fill("As-of date", "2026-09-30");
  await u.click(screen.getByRole("button", { name: "Compute period P&L" }));
  await waitFor(() => expect(screen.getByText("Contribution Profit")).toBeInTheDocument());
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe("Period P&L advertising line (ST-01)", () => {
  it("shows 'Not entered in this calculation' when advertising was not entered, never ₹0.00", async () => {
    await compute(response(false, null));
    const row = screen.getByTestId("pnl-advertising");
    expect(row).toHaveTextContent("Advertising: Not entered in this calculation");
    expect(row).not.toHaveTextContent("₹0.00");
  });

  it("shows ₹0.00 for an explicit zero entry", async () => {
    await compute(response(true, 0));
    expect(screen.getByTestId("pnl-advertising")).toHaveTextContent("Advertising: ₹0.00");
    expect(screen.getByTestId("pnl-advertising")).not.toHaveTextContent("Not entered");
  });

  it("shows the entered amount", async () => {
    await compute(response(true, 4500));
    expect(screen.getByTestId("pnl-advertising")).toHaveTextContent("Advertising: ₹45.00");
  });
});
