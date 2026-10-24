import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "session-token" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({ DashboardShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import PnlCalculatorPage from "@/app/dashboard/pnl-calculator/page";
import type { PnlScenarioResponse } from "@/lib/pnlScenario";

const view = (revenue: string, contribution: string) => ({
  revenue,
  contribution,
  operatingExpenses: null,
  operatingProfit: null,
  lines: [
    { id: "product", label: "Product cost", group: "product", amount: "30000" },
    { id: "fee_referral", label: "Referral fee", group: "commission", amount: "11800" },
    { id: "fee_refunds", label: "Fees refunded on returns", group: "fee_refund", amount: "-500" },
  ],
});
const share = (id: string, label: string, group: string, amount: string, shareBps: string) => ({ id, label, group, amount, shareBps });
/** Fixture A1 as the engine returns it: revenue 1,000 per order kept, product 300, packaging 20, referral 118, closing 20, shipping 50, profit 492. */
const breakdown = (): NonNullable<PnlScenarioResponse["breakdown"]> => ({
  lines: [
    share("product", "Product cost", "product", "30000", "3000"), share("stock_loss", "Stock lost on returns and RTO", "stock_loss", "0", "0"), share("packaging", "Packaging", "packaging", "2000", "200"),
    share("fee_referral", "Referral fee", "commission", "11800", "1180"), share("fee_closing", "Closing fee", "other_fee", "2000", "200"), share("fee_shipping", "Shipping / weight-handling fee", "shipping", "5000", "500"),
  ],
  profitShareBps: "4920",
  segments: [
    { ...share("product", "Product cost", "product", "30000", "3000"), startBps: "0", endBps: "3000" }, { ...share("packaging", "Packaging", "packaging", "2000", "200"), startBps: "3000", endBps: "3200" },
    { ...share("fee_referral", "Referral fee", "commission", "11800", "1180"), startBps: "3200", endBps: "4380" }, { ...share("fee_closing", "Closing fee", "other_fee", "2000", "200"), startBps: "4380", endBps: "4580" },
    { ...share("fee_shipping", "Shipping / weight-handling fee", "shipping", "5000", "500"), startBps: "4580", endBps: "5080" }, { ...share("profit", "Left as profit", "profit", "49200", "4920"), startBps: "5080", endBps: "10000" },
  ],
  chartUnavailableReason: null,
  topCosts: [share("product", "Product cost", "product", "30000", "3000"), share("fee_referral", "Referral fee", "commission", "11800", "1180"), share("fee_shipping", "Shipping / weight-handling fee", "shipping", "5000", "500")],
});
const count = (text: string) => ({ num: text, den: "1", text, exact: true });

/** A server answer as the API sends it. These strings are fixtures: the browser must render them as given and compute nothing. */
const response = (over: Partial<PnlScenarioResponse> = {}): PnlScenarioResponse => ({
  kind: "hypothetical_estimate", verification: "unverified_estimate", persisted: false, estimateRef: "pnl-scenario:11111111-1111-1111-1111-111111111111",
  formulaVersion: "PNL_SCENARIO.v1", status: "estimate", isExample: false, issues: [], missingCosts: [], assumptions: [], scopeNote: null, noKeptOrders: false,
  orders: { placed: count("100"), kept: count("100"), rto: count("0"), returned: count("0") },
  perKept: view("100000", "49200"), perPlaced: view("100000", "49200"), monthly: view("10000000", "4920000"),
  metrics: {
    contributionMarginBps: "4920", operatingMarginBps: null, effectiveFeeBps: "1380", acosBps: null, tacosBps: null, roasBps: null, breakEvenRoasBps: null,
    maxCac: null, gstRecoveredPerKept: "9144", gstRecoveredMonthly: "914400",
  },
  breakdown: breakdown(),
  solutions: [{ target: { kind: "breakeven", bps: "0", basis: "contribution" }, outcome: "price", price: "14014", ranges: [{ from: "14014", to: null }], excludesMissingCosts: false, reason: null }],
  ...over,
});

let calls: { url: string; init: RequestInit }[] = [];
const serve = (status: number, body: unknown) =>
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
  }));

beforeEach(() => { calls = []; });
afterEach(() => vi.unstubAllGlobals());

async function fillBasics(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Selling price per unit"), "1180");
  await user.type(screen.getByLabelText("Product GST rate"), "18");
  await user.type(screen.getByLabelText("Product cost per unit"), "354");
}

describe("Profit Calculator page", () => {
  it("opens empty with the 'not verified' label already showing, and no figure", () => {
    render(<PnlCalculatorPage />);
    expect(screen.getByTestId("estimate-banner")).toHaveTextContent("Hypothetical estimate — not verified");
    expect(screen.getByText("No estimate yet")).toBeInTheDocument();
    expect(screen.queryByText(/₹/, { selector: "td, .t-metric" })).toBeNull();
  });

  it("sends the typed numbers as exact integer strings, with the session token and no tenant", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.type(screen.getByLabelText("Referral fee"), "10");
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toMatch(/\/api\/v1\/cfo\/pnl-scenario$/);
    expect((calls[0].init.headers as Record<string, string>).Authorization).toBe("Bearer session-token");
    const body = JSON.parse(calls[0].init.body as string);
    expect(body.selling_price).toEqual({ state: "set", value: "118000" });
    expect(body.gst_rate_bps).toEqual({ state: "set", value: "1800" });
    expect(body.fees.referral.amount).toEqual({ state: "set", value: { kind: "single", amount: "1000" } });
    expect(body.packaging_cost).toEqual({ state: "empty" }); // untouched fields are 'not entered', never zero
    expect(JSON.stringify(body)).not.toMatch(/tenant/i);
  });

  it("renders exactly what the server returned, labelled an estimate, with no 'verified' wording", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(await screen.findAllByText("₹492.00")).not.toHaveLength(0);
    expect(screen.getByText("49.20% margin on revenue of ₹1,000.00")).toBeInTheDocument();
    expect(screen.getByText("₹49,200.00")).toBeInTheDocument(); // monthly
    expect(screen.getByText("Lowest selling price: ₹140.14")).toBeInTheDocument();
    expect(screen.getByTestId("estimate-banner")).toBeInTheDocument();
    expect(screen.getByText(/pnl-scenario:1111/)).toBeInTheDocument();
    expect(screen.queryByText(/verified result|engine result/i)).toBeNull();
    expect(screen.getByText("Estimate")).toBeInTheDocument();
  });

  it("shows a credit line as a negative amount and a loss in the negative tone", async () => {
    serve(200, response({ perKept: view("100000", "-250") }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(await screen.findAllByText("−₹2.50")).not.toHaveLength(0);
    expect(screen.getAllByText("−₹5.00").length).toBeGreaterThan(0);
  });

  it("prints a figure above 2^53 paise exactly (the browser never turns it into a number)", async () => {
    serve(200, response({ monthly: view("9007199254740993", "9007199254740993") }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect((await screen.findAllByText("₹9,00,71,99,25,47,409.93")).length).toBeGreaterThan(0);
  });

  it("names missing costs as left out and calls the result provisional", async () => {
    serve(200, response({ status: "provisional", missingCosts: ["Referral fee", "Closing fee"], assumptions: [{ code: "recovery_default", label: "80% of returned and RTO units assumed resellable; the rest treated as lost" }] }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(await screen.findByText("Provisional")).toBeInTheDocument();
    const missing = screen.getByText("Not entered, so left out").closest("section")!;
    expect(within(missing).getByText("Referral fee")).toBeInTheDocument();
    expect(within(missing).getByText("Closing fee")).toBeInTheDocument();
    expect(screen.getByText(/80% of returned and RTO units assumed resellable/)).toBeInTheDocument();
  });

  it("an incomplete answer shows the reasons and no profit figure at all", async () => {
    serve(200, response({
      status: "incomplete", perKept: null, perPlaced: null, monthly: null, metrics: null, orders: null, breakdown: null, solutions: [],
      issues: [{ code: "price_missing", severity: "blocking", message: "Enter the selling price", field: "selling_price" }],
    }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(await screen.findByText("Incomplete")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter the selling price");
    expect(screen.queryByText("Contribution profit per order kept")).toBeNull();
  });

  it("marks the result out of date when an input changes afterwards", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    expect(screen.queryByText(/You changed an input/)).toBeNull();
    await user.type(screen.getByLabelText("Product cost per unit"), "1");
    expect(screen.getByRole("status")).toHaveTextContent(/You changed an input/);
  });

  it("does not call the server when a number cannot be read, and says which field", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await user.type(screen.getByLabelText("Selling price per unit"), "12.345");
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(calls).toHaveLength(0);
    const field = screen.getByLabelText("Selling price per unit");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(screen.getAllByRole("alert").some((a) => /at most two decimals/.test(a.textContent ?? ""))).toBe(true);
  });

  it("explains a refusal in plain words and keeps the estimate label", async () => {
    serve(403, { code: "NOT_PERMITTED" });
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.some((a) => /permission/i.test(a.textContent ?? ""))).toBe(true);
    expect(screen.queryByText(/NOT_PERMITTED/)).toBeNull();
    expect(screen.getByTestId("estimate-banner")).toBeInTheDocument();
  });

  it("offers Doesn't apply as a separate, explicit choice from leaving a field blank", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    const packagingRow = screen.getByLabelText("Packaging per order").closest("div")!.parentElement!;
    await user.click(within(packagingRow).getByRole("checkbox", { name: /Doesn't apply/ }));
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    expect(JSON.parse(calls[0].init.body as string).packaging_cost).toEqual({ state: "na" });
  });

  it("hides the Amazon fulfilment choice for other marketplaces and shows the matching fee fields", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    expect(screen.getByText("Amazon fulfilment")).toBeInTheDocument();
    expect(screen.getByLabelText("Referral fee")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Meesho" }));
    expect(screen.queryByText("Amazon fulfilment")).toBeNull();
    expect(screen.queryByLabelText("Referral fee")).toBeNull();
    expect(screen.getByLabelText("Commission")).toBeInTheDocument();
  });
  it("labels the headline figures 'Before missing costs' when the result is provisional, and only then", async () => {
    serve(200, response({ status: "provisional", missingCosts: ["Referral fee"] }));
    const user = userEvent.setup();
    const { unmount } = render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Provisional");
    expect(screen.getAllByText("Before missing costs")).toHaveLength(3); // the headline and its two tiles; the margin is part of the headline
    unmount();
    serve(200, response());
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Estimate");
    expect(screen.queryByText("Before missing costs")).toBeNull();
  });

  it("does not talk about 'the profit below' when an incomplete result shows no profit", async () => {
    serve(200, response({ status: "incomplete", perKept: null, perPlaced: null, monthly: null, metrics: null, orders: null, breakdown: null, solutions: [], missingCosts: ["Referral fee"],
      issues: [{ code: "price_missing", severity: "blocking", message: "Enter the selling price", field: "selling_price" }] }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Incomplete");
    expect(screen.getByText(/None of them is counted as zero/)).toBeInTheDocument();
    expect(screen.queryByText(/excluded from the profit below/)).toBeNull();
  });

  it("keeps 'excluded from the profit below' for a provisional result, where a profit is shown", async () => {
    serve(200, response({ status: "provisional", missingCosts: ["Referral fee"] }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(await screen.findByText(/excluded from the profit below/)).toBeInTheDocument();
  });

  it("describes blank-input assumptions and calculation rules separately, and never calls a rule a blank input", async () => {
    serve(200, response({ assumptions: [
      { code: "recovery_default", label: "80% of returned and RTO units assumed resellable; the rest treated as lost" },
      { code: "fee_basis", label: "Percentage fees applied to the selling price including GST (change per fee in Detailed mode)" },
      { code: "itc_written_off", label: "No ITC taken on stock written off through returns or RTO (to be confirmed with your CA)" },
      { code: "some_future_rule", label: "A rule added later" },
    ] }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    const blank = (await screen.findByText("Assumed because an input was left blank")).closest("section")!;
    const rules = screen.getByText("How this estimate treats fees and GST").closest("section")!;
    expect(within(blank).getByText(/80% of returned and RTO units/)).toBeInTheDocument();
    expect(within(blank).queryByText(/Percentage fees applied/)).toBeNull();
    expect(within(rules).getByText(/Percentage fees applied to the selling price including GST/)).toBeInTheDocument();
    expect(within(rules).getByText(/No ITC taken/)).toBeInTheDocument();
    expect(within(rules).getByText("A rule added later")).toBeInTheDocument(); // an unknown code is a rule, not a blank input
    expect(screen.queryByText(/Applied because the input was left blank/)).toBeNull();
  });

  it("shows no assumptions heading at all when there are none", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Estimate");
    expect(screen.queryByText("Assumed because an input was left blank")).toBeNull();
    expect(screen.queryByText("How this estimate treats fees and GST")).toBeNull();
  });

  it("gives the Doesn't apply checkbox a 40px target, with its label still clickable, keyboard-operable and named", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    const cost = screen.getByLabelText("Product cost per unit") as HTMLInputElement;
    const box = within(cost.closest("div")!.parentElement!).getByRole("checkbox", { name: /Doesn't apply/ });
    expect(box.closest("label")!.className).toMatch(/(^| )min-h-10( |$)/); // the whole pill is a 40px target around a small box
    expect(box.closest("label")).toHaveTextContent("Doesn't apply (₹0)"); // the whole label is the click target
    await user.click(within(cost.closest("div")!.parentElement!).getByText("Doesn't apply (₹0)"));
    expect(box).toBeChecked();
    expect(cost).toBeDisabled();
    box.focus();
    await user.keyboard(" ");
    expect(box).not.toBeChecked();
  });

  it("groups each fee with its own refund and charged-on choices in Detailed mode, and shows only the key fee in Expected mode", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    const referral = screen.getByTestId("fee-referral");
    expect(within(referral).getByLabelText("Referral fee")).toBeInTheDocument();
    expect(within(referral).getByLabelText("Referral fee: share refunded on returns")).toBeInTheDocument();
    expect(within(referral).getByLabelText("Referral fee: charged on")).toBeInTheDocument();
    expect(within(referral).getByRole("checkbox", { name: "This fee changes with the selling price" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Expected" }));
    const quick = screen.getByTestId("fee-referral");
    expect(within(quick).queryByLabelText("Referral fee: share refunded on returns")).toBeNull();
    expect(within(quick).queryByRole("checkbox", { name: "This fee changes with the selling price" })).toBeNull();
  });
  it("shows numbered steps that tick only when everything in them was entered, and counts them", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    const progress = screen.getByTestId("progress");
    expect(progress).toHaveTextContent("0 of 4 steps entered");
    await user.type(screen.getByLabelText("Selling price per unit"), "1199");
    await user.type(screen.getByLabelText("Product cost per unit"), "450");
    await user.type(screen.getByLabelText("Product GST rate"), "18");
    expect(within(screen.getByTestId("step-1")).queryByText("Entered")).toBeNull(); // packaging (Detailed) is still blank
    await user.click(within(screen.getByTestId("step-1")).getAllByRole("checkbox", { name: /Doesn't apply/ }).at(-1)!); // packaging: confirmed not applicable
    expect(within(screen.getByTestId("step-1")).getByText("Entered")).toBeInTheDocument();
    expect(progress).toHaveTextContent("1 of 4 steps entered");
  });

  it("collapses and re-opens a step from its header, with the state announced", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    const header = within(screen.getByTestId("step-3")).getByRole("button", { name: /Orders and returns/ });
    expect(header).toHaveAttribute("aria-expanded", "true");
    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("RTO rate")).not.toBeVisible();
    await user.click(header);
    expect(screen.getByLabelText("RTO rate")).toBeVisible();
  });

  it("GST rate buttons type the rate for the seller, show which is chosen, and 'Other' leaves a custom rate alone", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    const rate = screen.getByLabelText("Product GST rate") as HTMLInputElement;
    const group = screen.getByRole("group", { name: "Common GST rates" });
    await user.click(within(group).getByRole("button", { name: "5%" }));
    expect(rate.value).toBe("5");
    expect(within(group).getByRole("button", { name: "5%" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(group).getByRole("button", { name: "Other" }));
    expect(rate.value).toBe("");
    await user.type(rate, "12");
    expect(within(group).getByRole("button", { name: "Other" })).toHaveAttribute("aria-pressed", "true");
    expect(within(group).getByRole("button", { name: "5%" })).toHaveAttribute("aria-pressed", "false");
  });

  it("offers the three GST situations as cards with a plain-words description, and hides the product GST rate when not registered", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    expect(screen.getByRole("radio", { name: /Registered \+ ITC/ })).toBeChecked();
    expect(screen.getByText("GST is not income; GST you pay is recovered.")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Not registered/ }));
    expect(screen.queryByLabelText("Product GST rate")).toBeNull();
    expect(screen.getByText("No GST collected; GST you pay is a cost.")).toBeInTheDocument();
  });

  it("Reset clears every field and any result, and says nothing is saved", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    expect(screen.getByText(/Not saved\. Sent to Metrion only to work out the estimate\./)).toBeInTheDocument();
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect((screen.getByLabelText("Selling price per unit") as HTMLInputElement).value).toBe("");
    expect(screen.getByText("No estimate yet")).toBeInTheDocument();
  });

  it("'Use this price' puts the solved price in the selling-price field and marks the result out of date", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Lowest selling price: ₹140.14");
    await user.click(screen.getByRole("button", { name: "Use this price" }));
    expect((screen.getByLabelText("Selling price per unit") as HTMLInputElement).value).toBe("140.14");
    expect(screen.getByRole("status")).toHaveTextContent(/You changed an input/);
    expect(calls).toHaveLength(1); // nothing is recalculated until the seller chooses Calculate
  });
  it("ticks the fees step once the key fees are entered; optional extras do not hold it back", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    const step2 = screen.getByTestId("step-2");
    await user.type(screen.getByLabelText("Referral fee"), "10");
    await user.type(screen.getByLabelText("Closing fee"), "20");
    expect(within(step2).queryByText("Entered")).toBeNull(); // shipping still blank
    await user.type(screen.getByLabelText("Shipping / weight-handling fee"), "55");
    expect(within(step2).getByText("Entered")).toBeInTheDocument();
    expect((screen.getByLabelText("Other per-order fee") as HTMLInputElement).value).toBe(""); // never filled in for the seller
  });
  it("draws the donut from the server's slice positions, with a written description, and shows each line's server share beside its bar", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    const donut = await screen.findByTestId("donut");
    expect(donut.style.background).toContain("conic-gradient");
    expect(donut.style.background).toContain("0.00%");
    expect(donut.style.background).toContain("50.80%"); // 5080 bps, the server's cumulative position, written as text
    expect(donut.style.background).toContain("100.00%");
    expect(donut).toHaveAttribute("aria-label", expect.stringContaining("Referral fee 11.80%"));
    expect(donut).toHaveAttribute("aria-label", expect.stringContaining("Left as profit 49.20%"));
    const section = screen.getByText("Where each ₹ of the sale goes").closest("section")!;
    expect(within(section).getByText("₹118.00 · 11.80%")).toBeInTheDocument();
    expect(within(section).getAllByText("49.20%", { selector: "span.tabular-nums" })).toHaveLength(2); // the donut centre and the profit row
    expect(within(section).queryByText(/Stock lost/)).toBeNull(); // a zero line is not drawn
  });

  it("ranks the three biggest costs as the server gave them", async () => {
    serve(200, response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    const list = (await screen.findByText("What's killing your margin?")).closest("section")!;
    const rows = within(list).getAllByRole("listitem").map((r) => r.textContent);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toMatch(/Product cost.*₹300\.00.*30\.00%/);
    expect(rows[1]).toMatch(/Referral fee.*₹118\.00.*11\.80%/);
    expect(rows[2]).toMatch(/Shipping.*₹50\.00.*5\.00%/);
  });

  it("says why there is no donut when the server could not draw one, and still lists the shares and top costs", async () => {
    const b = breakdown();
    serve(200, response({ breakdown: { ...b, segments: null, chartUnavailableReason: "Costs are higher than revenue, so there is no profit slice to draw. See the ledger.", profitShareBps: "-1500" } }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(await screen.findByTestId("chart-unavailable")).toHaveTextContent("no profit slice to draw");
    expect(screen.queryByTestId("donut")).toBeNull();
    const section = screen.getByText("Where each ₹ of the sale goes").closest("section")!;
    expect(within(section).getByText("−15.00%")).toBeInTheDocument();
    expect(screen.getByText("What's killing your margin?")).toBeInTheDocument();
  });

  it("marks the breakdown 'before the costs not entered' on a provisional result", async () => {
    serve(200, response({ status: "provisional", missingCosts: ["Referral fee"] }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(await screen.findByText(/Before the costs listed as not entered\. Shares are of revenue/)).toBeInTheDocument();
    expect(screen.getByText(/before the costs not entered/)).toBeInTheDocument();
  });

  it("shows neither the donut nor the top costs for an incomplete result", async () => {
    serve(200, response({ status: "incomplete", perKept: null, perPlaced: null, monthly: null, metrics: null, orders: null, breakdown: null, solutions: [] }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Incomplete");
    expect(screen.queryByTestId("donut")).toBeNull();
    expect(screen.queryByText("What's killing your margin?")).toBeNull();
  });
});
