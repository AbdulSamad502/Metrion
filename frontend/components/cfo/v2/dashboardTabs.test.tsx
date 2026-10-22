import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CashTaxTab } from "@/components/cfo/v2/cash/CashTaxTab";
import { HeldRows } from "@/components/cfo/v2/data/HeldRows";
import { ManualMapping } from "@/components/cfo/v2/data/ManualMapping";
import { ExpensesTab } from "@/components/cfo/v2/expenses/ExpensesTab";
import { IntelligenceTab } from "@/components/cfo/v2/intelligence/IntelligenceTab";
import { LeakShieldTab } from "@/components/cfo/v2/leak/LeakShieldTab";
import { OverviewTab } from "@/components/cfo/v2/overview/OverviewTab";
import { ProfitabilityTab } from "@/components/cfo/v2/profitability/ProfitabilityTab";
import { fig } from "@/test-support/cfoV2Fixtures";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "tok" }) }));
vi.mock("@/components/cfo/sections/ExpenseTrackerSection", () => ({ ExpenseTrackerSection: () => <div>expense tracker</div> }));

const PERIOD = { start: "2026-07-01", end: "2026-09-30" };
const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

type Handler = (url: string, init?: RequestInit) => unknown;
/** A fetch that answers by route; `can` sets what /access says. Every call is recorded. */
function serve(routes: Record<string, Handler | unknown>, can = true) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.includes("/cfo/access")) return json({ canAdjust: can });
      const key = Object.keys(routes).find((k) => url.includes(k));
      if (!key) return json({ detail: `unexpected ${url}` }, 404);
      const h = routes[key];
      return json(typeof h === "function" ? (h as Handler)(url, init) : h);
    }),
  );
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

const BANNED = [/recoverable/i, /recovered/i, /ready to dispute/i, /autonomous/i, /auto-generated/i, /cash in bank/i, /liquid cash/i, /runway/i, /\bLive\b/];
const noBanned = (el: HTMLElement) => BANNED.forEach((b) => expect(el.textContent ?? "").not.toMatch(b));

const overview = {
  status: "ANSWERED", dataVersion: 3, cached: false, generatedAt: "2026-10-22T10:00:00+00:00", operatingProfitState: "UNAVAILABLE", canAdjust: true,
  kpis: [fig({ label: "Contribution Profit" }), fig({ label: "Operating Profit", valueDisplay: null, completeness: "UNAVAILABLE", register: "UNAVAILABLE", unavailableReason: "no expenses recorded" })],
  urgentActions: [{ text: "Provide a cost per unit for SKU B" }],
  coverage: [{ metricId: "NET_REALIZED_REVENUE", marketplace: "AMAZON", included: false, sharePct: "40.0", thresholdPct: "95.0", reason: "return status is missing on too many lines", excludedLineCount: 4, excludedBasis: "GROSS_SALES_OF_EXCLUDED_MARKETPLACE", excludedAmountDisplay: "₹800.00" }],
  labels: [],
};

describe("Overview", () => {
  it("draws each figure through FigureView, explains what is missing and what was left out of a total", async () => {
    serve({ "/cfo/overview": overview });
    const { container } = render(<OverviewTab period={PERIOD} />);
    expect(await screen.findByText("₹1,23,456.00")).toBeInTheDocument();
    expect(screen.getByLabelText("Operating Profit: not available")).toHaveTextContent("—");
    expect(screen.getByText("no expenses recorded")).toBeInTheDocument();
    expect(screen.getByText(/Operating Profit needs your expenses first/)).toBeInTheDocument();
    expect(screen.getByText("Provide a cost per unit for SKU B")).toBeInTheDocument();
    expect(screen.getByText(/AMAZON · net realized revenue: left out: return status is missing/)).toHaveTextContent("₹800.00 of gross sales not counted");
    noBanned(container);
  });

  it("asks for the chosen period and marketplace, and shows a refusal or a failure in words", async () => {
    const calls = serve({ "/cfo/overview": { status: "REFUSED", code: "X", message: "That period has no data." } });
    render(<OverviewTab period={PERIOD} />);
    expect(await screen.findByText("That period has no data.")).toBeInTheDocument();
    expect(calls.find((c) => c.url.includes("/cfo/overview"))?.url).toContain("period_start=2026-07-01&period_end=2026-09-30");
    await userEvent.selectOptions(screen.getByLabelText("Marketplace"), "MEESHO");
    await screen.findByText("That period has no data.");
    expect(calls.at(-1)?.url).toContain("marketplace=MEESHO");
  });

  it("a failing section shows a plain error with a retry, not a payload", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json({ detail: "boom at /srv/x.py:9" }, 500)));
    render(<OverviewTab period={PERIOD} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/went wrong on our side/);
    expect(screen.queryByText(/x\.py/)).toBeNull();
  });
});

const cell = (display: string | null, status = "COMPLETE") => ({ display, status });
describe("Profitability", () => {
  const mp = { status: "ANSWERED", dataVersion: 1, generatedAt: "t", coverage: [{ metricId: "X", marketplace: "AMAZON", included: false, sharePct: null, thresholdPct: null, reason: "r", excludedLineCount: 1, excludedBasis: null, excludedAmountDisplay: null }],
    items: [{ key: "MEESHO", marketplace: "MEESHO", grossSales: cell("₹10.00"), nrr: cell("₹9.00"), contributionProfit: cell("₹4.00", "PROVISIONAL"), margin: cell("40%") },
      { key: "AMAZON", marketplace: "AMAZON", grossSales: cell(null, "UNAVAILABLE"), nrr: cell(null, "UNAVAILABLE"), contributionProfit: cell(null, "UNAVAILABLE"), margin: cell(null, "UNAVAILABLE") }] };
  const sku = { status: "ANSWERED", items: [{ key: "A", sku: "A", grossSales: cell("₹8.00"), nrr: cell("₹7.00"), contributionProfit: cell("₹3.00") }], page: 1, pageSize: 25, total: 60, pageCount: 3, dataVersion: 1, generatedAt: "t", truncated: false };

  it("shows unavailable marketplaces as a dash (never 0), a provisional badge, and asks the server to sort and page", async () => {
    const calls = serve({
      "/profitability/marketplaces": mp, "/profitability/skus": sku,
      "/profitability/trend": { status: "ANSWERED", points: [{ label: "2026-08", plot: 3, display: "₹30.00", status: "COMPLETE" }, { label: "2026-09", plot: null, display: null, status: "UNAVAILABLE" }], dataVersion: 1, generatedAt: "t" },
    });
    render(<ProfitabilityTab period={PERIOD} />);
    const table = await screen.findByRole("table", { name: "Profit by marketplace" });
    expect(within(table).getAllByLabelText("not available").length).toBe(4);
    expect(within(table).getByText("Provisional")).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "Contribution Profit by month as a table" })).toBeInTheDocument();
    await screen.findByRole("table", { name: "Profit by SKU" });
    expect(screen.getByText(/Page 1 of 3 · 60 rows/)).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("navigation", { name: "Profit by SKU pages" })).getByRole("button", { name: "Next" }));
    await userEvent.click(await screen.findByRole("button", { name: /^SKU/ }));
    const urls = calls.map((c) => c.url);
    expect(urls.some((u) => u.includes("/profitability/skus") && u.includes("page=2"))).toBe(true);
    expect(urls.some((u) => u.includes("/profitability/skus") && u.includes("sort=key"))).toBe(true);
  });

  it("the bridge waits for a second period, then shows drivers plus Other and flags a bridge that does not reconcile", async () => {
    serve({
      "/profitability/marketplaces": { ...mp, items: [] }, "/profitability/skus": { ...sku, items: [], total: 0, pageCount: 1 }, "/profitability/trend": { status: "ANSWERED", points: [], dataVersion: 1, generatedAt: "t" },
      "/profitability/bridge": { status: "ANSWERED", reconciles: false, bridge: { deltaDisplay: "-₹4.50", otherDisplay: "₹0.00", otherRef: null, drivers: [{ metricId: "MARKETPLACE_FEES", deltaDisplay: "-₹1.00", ref: "r" }] } },
    });
    render(<ProfitabilityTab period={PERIOD} />);
    expect(await screen.findByText(/Choose a second period/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Compare against from"), "2026-04-01");
    await userEvent.type(screen.getByLabelText("to"), "2026-06-30");
    expect(await screen.findByText(/marketplace fees: -₹1.00/)).toBeInTheDocument();
    expect(screen.getByText("Total change: -₹4.50")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/do not add up/);
  });
});

const leak = (over: object = {}) => ({
  id: "f1", marketplace: "MEESHO", category: "MISSING_REFUND", severity: "HIGH", amount: cell("₹500.00", "PROVISIONAL"), affectedLines: 2, sku: null, ageDays: 5, claimWindowDays: 30, windowStatus: "CLOSING_SOON", claimState: "NEW",
  engineResultRef: "e1", withheld: false, withheldReason: null, ...over,
});
describe("Leak Shield", () => {
  const body = (items: object[]) => ({ status: "ANSWERED", items, page: 1, pageSize: 25, total: items.length, pageCount: 1, generatedAt: "t", note: "Seller-reported status only: Metrion never files a claim." });

  it("labels the amount as identified, withholds Amazon, and offers actions only to someone who may change data", async () => {
    serve({ "/leak/findings": body([leak(), leak({ id: "f2", marketplace: "AMAZON", withheld: true, withheldReason: "verify the match key" })]) }, false);
    const { container } = render(<LeakShieldTab />);
    expect(await screen.findByText("Discrepancy identified")).toBeInTheDocument();
    expect(screen.getByText("₹500.00")).toBeInTheDocument();
    expect(screen.getAllByText("Claim window closing soon").length).toBeGreaterThan(0);
    expect(screen.getByText("Provisional — withheld")).toBeInTheDocument();
    expect(screen.getByText(/never files a claim/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Draft claim text" })).toBeNull(); // read-only member
    noBanned(container);
  });

  it("drafts claim text (identifiers only, copy it yourself) and moves the status one allowed step", async () => {
    const calls = serve({
      "/claim/draft": { text: "Order O-1 was shipped and not paid.", state: "CLAIM_DRAFTED" }, "/claim/step": { state: "ACKNOWLEDGED" },
      "/leak/findings": body([leak()]),
    });
    render(<LeakShieldTab />);
    await userEvent.click(await screen.findByRole("button", { name: "Draft claim text" }));
    expect(await screen.findByLabelText("Draft claim text", { selector: "textarea" })).toHaveValue("Order O-1 was shipped and not paid.");
    expect(screen.getByText(/copy and paste it into the marketplace yourself/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mark: Acknowledged" }));
    const step = calls.find((c) => c.url.includes("/claim/step"));
    expect(JSON.parse(String(step?.init?.body))).toEqual({ to: "ACKNOWLEDGED" });
    expect(await screen.findByRole("button", { name: "Mark: Dismissed" })).toBeInTheDocument();
  });
});

describe("Cash & Tax", () => {
  const cash = { status: "ANSWERED", figures: [fig({ label: "Expected receipts", completeness: "ESTIMATED", register: "ESTIMATE", estimateRef: "est1", engineResultRef: null })], dataRequests: [], coverage: [], generatedAt: "t", note: "An estimate from your own settlement history. It is not your bank balance." };
  const payables = { status: "ANSWERED", items: [{ id: "p1", amount: cell("₹12,500.50"), dueDate: "2026-10-30", supplierRef: "S1", poRef: null }], generatedAt: "t" };

  it("an estimate is badged as one, GST is stated as unconfirmed, and the add form is hidden for a read-only member", async () => {
    serve({ "/cash/expected-receipts": cash, "/cash/payables": payables }, false);
    const { container } = render(<CashTaxTab period={PERIOD} />);
    expect(await screen.findByText("Estimated")).toBeInTheDocument();
    expect(screen.getByText(/not your bank balance/)).toBeInTheDocument();
    expect(await screen.findByText("₹12,500.50")).toBeInTheDocument();
    expect(screen.getByText(/GST treatment is not confirmed yet/)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Add a payable" })).toBeNull();
    noBanned(container);
  });

  it("sends the rupee text AS TYPED for the server to convert (no client money math)", async () => {
    const calls = serve({ "/cash/expected-receipts": cash, "/cash/payables": payables, "/api/v1/cfo/payables": { payableRef: "p2" } });
    render(<CashTaxTab period={PERIOD} />);
    await userEvent.type(await screen.findByLabelText("Amount in rupees"), "12500.50");
    await userEvent.click(screen.getByRole("button", { name: "Add payable" }));
    const post = calls.find((c) => c.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ amount_rupees: "12500.50" });
  });
});

describe("Intelligence", () => {
  it("lists recorded alerts with their trust label and gates the scan button", async () => {
    serve({ "/intelligence/alerts": { status: "ANSWERED", generatedAt: "t", items: [{ id: "a1", agent: "CFO", kind: "RISK", subject: "margin", text: "Contribution margin fell against the previous month.", trustLabel: "Calculated by Metrion", createdAt: "2026-10-21" }] } }, false);
    render(<IntelligenceTab period={PERIOD} />);
    expect(await screen.findByText("Contribution margin fell against the previous month.")).toBeInTheDocument();
    expect(screen.getByText(/Calculated by Metrion/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check my data now" })).toBeNull();
  });
  it("an empty list is said in words, and the scan sends the period end", async () => {
    const calls = serve({ "/intelligence/alerts": { status: "ANSWERED", generatedAt: "t", items: [] }, "/risk-scan": { signals: [] } });
    render(<IntelligenceTab period={PERIOD} />);
    expect(await screen.findByText(/Nothing to flag/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Check my data now" }));
    expect(JSON.parse(String(calls.find((c) => c.url.includes("/risk-scan"))?.init?.body))).toEqual({ as_of_date: "2026-09-30" });
  });
});

describe("Expenses", () => {
  const entry = (over: object) => ({ id: "e1", entryDate: "2026-09-05", amountDisplay: "₹1,180.00", category: "Software", vendor: null, description: null, gstAmountDisplay: "₹180.00", gstTreatmentUnconfirmed: true,
    allocatedComponent: null, hold: "NONE", confirmedClass: null, suggestedClass: "OVERHEAD", suggestionReason: "looks like a subscription", ...over });

  it("a suggestion is not counted until confirmed; GST sits beside the amount marked unconfirmed", async () => {
    const calls = serve({ "/ledger/classes": { classId: "c1" }, "/ledger/entries": { entries: [entry({})] } });
    render(<ExpensesTab period={PERIOD} getToken={async () => "t"} />);
    expect(await screen.findByText(/Suggested: Overhead/)).toHaveTextContent("not counted until you confirm");
    expect(screen.getByText(/GST treatment not confirmed/)).toBeInTheDocument();
    expect(screen.getByText("expense tracker")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(JSON.parse(String(calls.find((c) => c.url.includes("/ledger/classes"))?.init?.body))).toEqual({ class: "OVERHEAD", entry_id: "e1" });
  });

  it("an allocated cost must say which cost before it can be confirmed; a held entry says why it is not counted", async () => {
    serve({ "/ledger/entries": { entries: [entry({ id: "e2", suggestedClass: "ALLOCATED_COST", category: "Packaging" }), entry({ id: "e3", hold: "POSSIBLE_DUPLICATE", suggestedClass: null })] } });
    render(<ExpensesTab period={PERIOD} getToken={async () => "t"} />);
    const confirm = await screen.findByRole("button", { name: "Confirm" });
    expect(confirm).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Which cost"), "packaging");
    expect(confirm).toBeEnabled();
    expect(screen.getByText(/looks like a duplicate of another entry, so it is not counted/)).toBeInTheDocument();
  });
});

describe("Manual mapping and held rows", () => {
  const cols = { reportKind: "EXPENSE", canManuallyMap: true, columns: [{ index: 0, name: "Date" }, { index: 1, name: "Head" }, { index: 2, name: "Paid" }],
    canonicalFields: [{ name: "expense_date", valueType: "date" }, { name: "expense_category", valueType: "text" }, { name: "expense_amount", valueType: "money" }],
    requiredGroups: [["expense_date"], ["expense_category"], ["expense_amount"]], transforms: ["DATE_DMY", "IDENTITY", "RUPEES_TO_PAISE"], taxInclusion: ["EXCLUSIVE", "INCLUSIVE"], signConventions: ["AS_IS"], componentCodes: [] };

  it("the proposal is only sent once every required field is chosen, and names only the chosen columns", async () => {
    const calls = serve({ "/columns": cols, "/mapping/manual": { jobId: "j2", status: "AWAITING_MAPPING_CONFIRMATION" } });
    const onProposed = vi.fn();
    render(<ManualMapping jobId="j1" onProposed={onProposed} />);
    const send = await screen.findByRole("button", { name: "Use these columns" });
    expect(send).toBeDisabled();
    expect(screen.getByText(/Still needed: expense date; expense category; expense amount/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("What Date is"), "expense_date");
    await userEvent.selectOptions(screen.getByLabelText("What Head is"), "expense_category");
    await userEvent.selectOptions(screen.getByLabelText("What Paid is"), "expense_amount");
    await userEvent.selectOptions(screen.getByLabelText("How to read Paid"), "RUPEES_TO_PAISE");
    await userEvent.click(send);
    expect(JSON.parse(String(calls.find((c) => c.url.includes("/mapping/manual"))?.init?.body))).toEqual({
      fields: [{ index: 0, canonical_field: "expense_date" }, { index: 1, canonical_field: "expense_category" }, { index: 2, canonical_field: "expense_amount", transform: "RUPEES_TO_PAISE" }],
    });
    expect(onProposed).toHaveBeenCalledWith(expect.objectContaining({ jobId: "j2" }));
  });

  const held = (over: object = {}) => ({ id: "h1", rowNumber: 7, kind: "CONFLICT", rule: "V-DUP-003", reason: "Row 7 has the same order line as an earlier upload but different values.", earlierRow: null, values: { "Sub Order No": "ORD-1" }, resolution: null, resolutionNote: null, ...over });
  it("held rows are decided one by one (keep earlier or discard) and the unavailable actions are not offered", async () => {
    const calls = serve({ "/held/resolve": { resolved: 1, action: "DISCARD" }, "/held": { items: [held()], page: 1, pageSize: 20, total: 1, pageCount: 1, unresolved: 1 } });
    render(<HeldRows jobId="j1" />);
    expect(await screen.findByText(/Row 7 — Row 7 has the same order line/)).toBeInTheDocument();
    expect(screen.getByText("1 held — needs your decision. Held rows are not counted anywhere.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /replace|both/i })).toBeNull();
    expect(screen.getByText(/Replacing earlier data with this row, or keeping both, is not available yet/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Discard this row" }));
    expect(JSON.parse(String(calls.find((c) => c.url.includes("/held/resolve"))?.init?.body))).toEqual({ held_row_ids: ["h1"], action: "DISCARD" });
  });
  it("a read-only member sees the row and that it needs a decision from someone else", async () => {
    serve({ "/held": { items: [held()], page: 1, pageSize: 20, total: 1, pageCount: 1, unresolved: 1 } }, false);
    render(<HeldRows jobId="j1" />);
    expect(await screen.findByText(/needs a decision from someone who can change financial data/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard this row" })).toBeNull();
  });
});
