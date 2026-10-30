import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "session-token" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({ DashboardShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import PnlCalculatorPage from "@/app/dashboard/pnl-calculator/page";
import type { PnlCompareResponse, PnlScenarioResponse } from "@/lib/pnlScenario";

// Parity with the public calculator: example numbers, Expected/Detailed, fee bands and basis, margin type, what-if, print. Every figure below is a fixture the browser must
// render as given; nothing here is computed by the page.

const view = (revenue: string, contribution: string) => ({
  revenue, contribution, operatingExpenses: null, operatingProfit: null,
  lines: [
    { id: "product", label: "Product cost", group: "product", amount: "30000" },
    { id: "fee_referral", label: "Referral fee", group: "commission", amount: "11800" },
    { id: "packaging", label: "Packaging", group: "packaging", amount: "2000" },
  ],
});
const response = (over: Partial<PnlScenarioResponse> = {}): PnlScenarioResponse => ({
  kind: "hypothetical_estimate", verification: "unverified_estimate", persisted: false, estimateRef: "pnl-scenario:11111111-1111-1111-1111-111111111111",
  formulaVersion: "PNL_SCENARIO.v1", status: "estimate", isExample: false, issues: [], missingCosts: [], assumptions: [], scopeNote: null, noKeptOrders: false,
  orders: null, perKept: view("100000", "49200"), perPlaced: view("100000", "49200"), monthly: view("10000000", "4920000"),
  metrics: { contributionMarginBps: "4920", operatingMarginBps: null, effectiveFeeBps: "1380", acosBps: null, tacosBps: null, roasBps: null, breakEvenRoasBps: null, maxCac: null, gstRecoveredPerKept: null, gstRecoveredMonthly: null },
  breakdown: null, solutions: [], ...over,
});
const comparison = (over: Partial<PnlCompareResponse> = {}): PnlCompareResponse => ({
  kind: "hypothetical_comparison", persisted: false,
  base: response(), whatIf: response({ estimateRef: "pnl-scenario:11111111-1111-1111-1111-111111111111:what-if", perKept: view("127119", "61000"), metrics: { ...response().metrics!, contributionMarginBps: "4800" } }),
  comparison: { perKeptChange: "11800", perPlacedChange: "11800", monthlyChange: "1180000", marginChangeBps: "-120" }, ...over,
});

let calls: { url: string; init: RequestInit }[] = [];
type Router = (url: string) => object;
const serve = (body: object | Router) =>
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(typeof body === "function" ? body(url) : body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
const sent = (i = 0) => JSON.parse(calls[i].init.body as string);
const compareCalls = () => calls.filter((c) => c.url.endsWith("/pnl-scenario-compare"));

beforeEach(() => { calls = []; });
afterEach(() => vi.unstubAllGlobals());

async function fillBasics(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Selling price per unit"), "1180");
  await user.type(screen.getByLabelText("Product GST rate"), "18");
  await user.type(screen.getByLabelText("Product cost per unit"), "354");
}

describe("example numbers and reset", () => {
  it("fills the example, labels it as made-up, sends the flag, and keeps the label on the result", async () => {
    serve(response({ isExample: true }));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    expect(screen.queryByTestId("example-note")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Try with example numbers" }));
    expect(screen.getByTestId("example-note")).toHaveTextContent("Example data — not real marketplace rates.");
    expect(screen.getByLabelText("Selling price per unit")).toHaveValue("1199");
    expect(screen.getByRole("radio", { name: "Expected" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(await screen.findByTestId("example-result-note")).toHaveTextContent("not real marketplace rates");
    const body = sent();
    expect(body.is_example).toBe(true);
    expect(body.fees.referral.amount.value).toEqual({ kind: "single", amount: "1000" });
    expect(body.rto_bps).toEqual({ state: "set", value: "800" });
  });

  it("does not claim a normal calculation is an example", async () => {
    serve(response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    expect(sent().is_example).toBe(false);
    expect(screen.queryByTestId("example-result-note")).toBeNull();
  });

  it("switching marketplace while the example is showing loads that marketplace example; Reset clears everything", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await user.click(screen.getByRole("button", { name: "Try with example numbers" }));
    await user.click(screen.getByRole("radio", { name: "Flipkart" }));
    expect(screen.getByLabelText("Commission")).toHaveValue("9");
    expect(screen.getByTestId("example-note")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.queryByTestId("example-note")).toBeNull();
    expect(screen.getByLabelText("Selling price per unit")).toHaveValue("");
    expect(screen.getByLabelText("Commission")).toHaveValue("");
  });

  it("switching marketplace without an example clears the fee fields instead of carrying them over", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await user.type(screen.getByLabelText("Referral fee"), "10");
    await user.click(screen.getByRole("radio", { name: "Meesho" }));
    expect(screen.getByLabelText("Commission")).toHaveValue("");
  });
});

describe("Expected and Detailed", () => {
  it("Expected leaves out packaging, advertising, return handling and the detail choices; Detailed adds them", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await user.click(screen.getByRole("radio", { name: "Expected" }));
    expect(screen.getByText(/Expected: only the key numbers/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Packaging per order")).toBeNull();
    expect(screen.queryByLabelText("Advertising spend per month")).toBeNull();
    expect(screen.queryByLabelText("Return / RTO handling fee")).toBeNull();
    await user.click(screen.getByRole("radio", { name: "Detailed" }));
    expect(screen.getByLabelText("Packaging per order")).toBeInTheDocument();
    expect(screen.getByLabelText("Advertising spend per month")).toBeInTheDocument();
    expect(screen.getByLabelText("Return / RTO handling fee")).toBeInTheDocument();
  });

  it("shows completion as a progress bar and All set once every step is entered", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await user.click(screen.getByRole("button", { name: "Try with example numbers" }));
    const bar = screen.getByRole("progressbar", { name: "Steps entered" });
    expect(bar).toHaveAttribute("aria-valuenow", "3");
    expect(bar).toHaveAttribute("aria-valuemax", "3");
    expect(screen.getByTestId("progress")).toHaveTextContent("All set: choose Calculate to see your result.");
  });
});

describe("fee price bands and charge basis", () => {
  it("collects bands and sends them as integer strings with the last band open-ended", async () => {
    serve(response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    const referral = screen.getByTestId("fee-referral");
    await user.click(within(referral).getByRole("checkbox", { name: "This fee changes with the selling price" }));
    expect(within(referral).queryByLabelText("Referral fee")).toBeNull();
    await user.type(within(referral).getByLabelText("Band 1: up to"), "500");
    await user.type(within(referral).getByLabelText("Band 1: rate"), "5");
    await user.type(within(referral).getByLabelText("Band 2: rate"), "12.5");
    await user.selectOptions(within(referral).getByLabelText("Band type"), "marginal");
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    expect(sent().fees.referral.amount).toEqual({ state: "set", value: { kind: "tiers", mode: "marginal", bands: [{ up_to: "50000", amount: "500" }, { up_to: null, amount: "1250" }] } });
  });

  it("names a band that was left blank and sends nothing", async () => {
    serve(response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    const referral = screen.getByTestId("fee-referral");
    await user.click(within(referral).getByRole("checkbox", { name: "This fee changes with the selling price" }));
    await user.type(within(referral).getByLabelText("Band 1: rate"), "5");
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    expect(await screen.findByText("Enter the price this band goes up to.")).toBeInTheDocument();
    expect(screen.getByText("Enter the rate for this band.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("adds and removes bands, and only a percent fee can be progressive", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    const closing = screen.getByTestId("fee-closing");
    await user.click(within(closing).getByRole("checkbox", { name: "This fee changes with the selling price" }));
    expect(within(closing).queryByRole("option", { name: /Progressive/ })).toBeNull();
    await user.click(within(closing).getByRole("button", { name: "Add band" }));
    expect(within(closing).getByLabelText("Band 3: amount")).toBeInTheDocument();
    await user.click(within(closing).getByRole("button", { name: "Remove first band" }));
    expect(within(closing).queryByLabelText("Band 3: amount")).toBeNull();
    expect(within(screen.getByTestId("fee-referral")).getByRole("checkbox", { name: "This fee changes with the selling price" })).not.toBeChecked();
  });

  it("offers price bands only for the fees the engine allows them on", () => {
    render(<PnlCalculatorPage />);
    expect(within(screen.getByTestId("fee-referral")).getByRole("checkbox", { name: "This fee changes with the selling price" })).toBeInTheDocument();
    expect(within(screen.getByTestId("fee-shipping")).queryByRole("checkbox", { name: "This fee changes with the selling price" })).toBeNull();
  });

  it("sends the charge basis only when the seller chose one, and only for a percentage fee", async () => {
    serve(response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.type(screen.getByLabelText("Referral fee"), "10");
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    expect(sent().fees.referral.basis).toBeUndefined();
    expect(screen.queryByLabelText("Closing fee: charged on")).toBeNull();
    await user.selectOptions(screen.getByLabelText("Referral fee: charged on"), "price_excl_gst");
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findAllByText("Contribution profit per order kept");
    expect(sent(1).fees.referral.basis).toBe("price_excl_gst");
  });
});

describe("price targets", () => {
  it("sends the chosen margin type with a target margin and none for break-even", async () => {
    serve(response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.type(screen.getByLabelText("Find the price for a target margin"), "20");
    await user.click(screen.getByRole("radio", { name: "Operating" }));
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    expect(sent().targets).toEqual([{ kind: "breakeven" }, { kind: "margin", bps: "2000", basis: "operating" }]);
  });
});

describe("what-if comparison", () => {
  const withResult = async () => {
    serve((url) => (url.endsWith("/pnl-scenario-compare") ? comparison() : response()));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    return user;
  };

  it("needs a current result first", () => {
    render(<PnlCalculatorPage />);
    expect(screen.getByRole("button", { name: "Compare" })).toBeDisabled();
    expect(screen.getByText(/Choose Calculate first/)).toBeInTheDocument();
  });

  it("asks for a value instead of sending an empty comparison", async () => {
    const user = await withResult();
    await user.click(screen.getByRole("button", { name: "Compare" }));
    expect(screen.getByText("Type a new value for at least one box.")).toBeInTheDocument();
    expect(compareCalls()).toHaveLength(0);
  });

  it("sends the base and a variant that differs only in what was typed, and does not change the current inputs", async () => {
    const user = await withResult();
    await user.type(screen.getByLabelText("New selling price"), "1500");
    await user.click(screen.getByRole("button", { name: "Compare" }));
    const box = await screen.findByTestId("what-if-result");
    const body = JSON.parse(compareCalls()[0].init.body as string);
    expect(body.base.selling_price).toEqual({ state: "set", value: "118000" });
    expect(body.what_if.selling_price).toEqual({ state: "set", value: "150000" });
    const strip = (x: Record<string, unknown>) => Object.fromEntries(Object.entries(x).filter(([k]) => k !== "selling_price"));
    expect(strip(body.what_if)).toEqual(strip(body.base));
    expect(JSON.stringify(body)).not.toMatch(/tenant/i);
    expect(screen.getByLabelText("Selling price per unit")).toHaveValue("1180");
    expect(within(box).getByText("Now")).toBeInTheDocument();
    expect(within(box).getByText("What if")).toBeInTheDocument();
    expect(within(box).getByText("+₹118.00")).toBeInTheDocument();
    expect(box).toHaveTextContent("hypothetical estimates");
    expect(box).toHaveTextContent(":what-if");
  });

  it("shows a falling profit as a negative change", async () => {
    serve((url) => (url.endsWith("/pnl-scenario-compare") ? comparison({ comparison: { perKeptChange: "-5000", perPlacedChange: null, monthlyChange: null, marginChangeBps: null } }) : response()));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    await user.type(screen.getByLabelText("New product cost"), "400");
    await user.click(screen.getByRole("button", { name: "Compare" }));
    expect(await screen.findByText("−₹50.00")).toBeInTheDocument();
  });

  it("says so when the changed values are not enough for a result", async () => {
    serve((url) => (url.endsWith("/pnl-scenario-compare") ? comparison({ whatIf: response({ status: "incomplete", perKept: null, issues: [{ code: "x", severity: "blocking", message: "Enter a selling price.", field: null }] }) }) : response()));
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    await user.type(screen.getByLabelText("New RTO rate"), "5");
    await user.click(screen.getByRole("button", { name: "Compare" }));
    expect(await screen.findByText(/not enough for a result yet/)).toBeInTheDocument();
  });

  it("flags a comparison as out of date after an input changes, and Clear removes it", async () => {
    const user = await withResult();
    await user.type(screen.getByLabelText("New selling price"), "1500");
    await user.click(screen.getByRole("button", { name: "Compare" }));
    await screen.findByTestId("what-if-result");
    await user.type(screen.getByLabelText("Product cost per unit"), "1");
    expect(screen.getByText(/You changed an input after this comparison/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByTestId("what-if-result")).toBeNull();
    expect(screen.getByLabelText("New selling price")).toHaveValue("");
  });

  it("names an unreadable what-if value and sends nothing", async () => {
    const user = await withResult();
    await user.type(screen.getByLabelText("New selling price"), "abc");
    await user.click(screen.getByRole("button", { name: "Compare" }));
    expect(await screen.findAllByRole("alert")).not.toHaveLength(0);
    expect(compareCalls()).toHaveLength(0);
  });

  it("hides the ad spend box in Expected mode", async () => {
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    expect(screen.getByLabelText("New ad spend / month")).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Expected" }));
    expect(screen.queryByLabelText("New ad spend / month")).toBeNull();
  });
});

describe("the statement, the result bar and print", () => {
  it("groups the statement into cost of goods, marketplace charges, and packaging and advertising", async () => {
    serve(response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    for (const heading of ["Cost of goods", "Marketplace charges", "Packaging and advertising"]) expect(screen.getAllByText(heading).length).toBeGreaterThan(0);
  });

  it("shows the quick-glance bar only once there is a result, linking to it", async () => {
    serve(response());
    const user = userEvent.setup();
    render(<PnlCalculatorPage />);
    expect(screen.queryByTestId("glance-bar")).toBeNull();
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    const bar = await screen.findByTestId("glance-bar");
    expect(bar).toHaveAttribute("href", "#pnl-results");
    expect(bar).toHaveTextContent("₹492.00");
  });

  it("prints only the result area, with the not-verified label and a header naming marketplace and mode, and the button needs a result", async () => {
    serve(response());
    const print = vi.fn();
    vi.stubGlobal("print", print);
    const user = userEvent.setup();
    const { container } = render(<PnlCalculatorPage />);
    const button = screen.getByRole("button", { name: "Print or save as PDF" });
    expect(button).toBeDisabled();
    await fillBasics(user);
    await user.click(screen.getByRole("button", { name: "Calculate" }));
    await screen.findByText("Contribution profit per order kept");
    const area = container.querySelector(".mt-print-area")!;
    expect(area).toContainElement(screen.getByTestId("estimate-banner"));
    expect(area.querySelector(".mt-print-only")).toHaveTextContent("Metrion profit & loss estimate · Amazon India · Detailed · hypothetical estimate, not verified");
    expect(button.closest(".mt-no-print")).not.toBeNull();
    await user.click(button);
    expect(print).toHaveBeenCalledTimes(1);
  });

  it("keeps the inputs and the what-if panel out of the printed page", () => {
    const { container } = render(<PnlCalculatorPage />);
    expect(container.querySelector(".mt-print-area")!.contains(screen.getByLabelText("Selling price per unit"))).toBe(false);
    expect(screen.getByTestId("what-if").closest(".mt-no-print")).not.toBeNull();
    expect(screen.getByLabelText("Selling price per unit").closest(".mt-no-print")).not.toBeNull();
  });
});

describe("the print stylesheet", () => {
  it("hides everything except the result area and keeps the warnings in it", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
    const print = css.slice(css.indexOf("@media print"));
    expect(print).toMatch(/:where\(body:has\(\.mt-print-area\)\) \* \{ visibility: hidden; \}/); // only a page that has a print area hides the rest (the PI report has none)
    expect(print).toMatch(/\.mt-print-area, \.mt-print-area \* \{ visibility: visible; \}/);
    expect(print).toMatch(/\.mt-no-print[^}]*display: none !important/);
    expect(print).toMatch(/--text-1: #111/);
  });
});
