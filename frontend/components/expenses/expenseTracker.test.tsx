import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExpenseTracker } from "@/components/expenses/ExpenseTracker";

// The Expense Tracker dashboard (kickoff S3c). Totals are the backend's (engine feed, with an engineResultRef, AC17) and are only displayed; the review state and
// the payment status are two separate fields; a 403 on a write is handled in place; amounts are sent as integer-paise strings parsed by rupeesToPaise.

const META = {
  categories: [
    { id: "advertising", label: "Advertising", costClass: "ADVERTISING", treatment: "incremental" },
    { id: "operating_overhead", label: "Operating overhead (rent, utilities)", costClass: "OVERHEAD", treatment: "incremental" },
    { id: "software", label: "Software", costClass: "OVERHEAD", treatment: "incremental" },
  ],
  costClasses: ["ADVERTISING", "DIRECT", "OVERHEAD", "STORAGE"], treatments: ["already_in_settlement", "incremental", "informational"],
  channelTags: ["AMAZON", "FLIPKART", "MEESHO", "OTHER"], reviewStates: ["draft", "pending_review", "confirmed", "voided"],
  paymentStatuses: ["unpaid", "partially_paid", "paid", "unknown"],
  limits: { amountMaxPaise: 9999999999999, vendorMax: 120, descriptionMax: 500, reasonMax: 500, pageSizeDefault: 50, pageSizeMax: 200 },
};

const fig = (paise: number, ref: string) => ({ paise, engineResultRef: ref, asOfDate: "2026-09-30" });
const SUMMARY = {
  periodStart: "2026-09-01", periodEnd: "2026-09-30", asOfDate: "2026-09-30", watermark: "ledger:9:abc",
  expenseTotal: fig(17500000, "ref-total"), includingUnresolved: fig(19500000, "ref-unres"), recurringTotal: fig(12500000, "ref-rec"),
  reviewQueue: { amountPaise: 2000000, engineResultRef: "ref-queue", asOfDate: "2026-09-30", items: [{ expenseId: "e-3", reason: "PENDING_REVIEW", amountPaise: 2000000 }] },
  byCostClass: [{ costClass: "OVERHEAD", ...fig(12500000, "ref-ovh") }, { costClass: "ADVERTISING", ...fig(5000000, "ref-adv") }, { costClass: "STORAGE", ...fig(0, "ref-sto") }],
  byCategory: [{ category: "operating_overhead", label: "Operating overhead (rent, utilities)", ...fig(12500000, "ref-c1") }, { category: "advertising", label: "Advertising", ...fig(5000000, "ref-c2") }],
  notEntered: ["DIRECT"], gaps: ["direct costs: not entered"],
};

const rec = (o: Record<string, unknown>) => ({
  id: "e-1", effectiveDate: "2026-09-10", vendor: "Acme Realty", description: "September rent", category: "operating_overhead", categoryLabel: "Operating overhead (rent, utilities)",
  costClass: "OVERHEAD", treatment: "incremental", amountPaise: 12500000, channelScope: null, sku: null, origin: "MANUAL", sourceValidated: false, identifier: null,
  sourceReference: "manual", correctsExpenseId: null, refundOfExpenseId: null, recurring: false, createdAt: "2026-09-10T00:00:00Z", reviewState: "confirmed",
  reviewReason: null, paymentStatus: "unknown", paidAmountPaise: null, ...o,
});
const RECORDS = [
  rec({}),
  rec({ id: "e-2", vendor: "Acme Realty", description: "Refund", amountPaise: -4000000, effectiveDate: "2026-10-03", refundOfExpenseId: "e-1", paymentStatus: "paid" }),
  rec({ id: "e-3", vendor: "Tool Co", category: "software", categoryLabel: "Software", amountPaise: 2000000, reviewState: "pending_review", paymentStatus: "unpaid" }),
];

type Call = { method: string; url: string; body: unknown };
let calls: Call[];
let overrides: Record<string, () => Response>;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  calls = [];
  overrides = {};
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    const method = init?.method ?? "GET";
    calls.push({ method, url: path, body: init?.body ? JSON.parse(String(init.body)) : null });
    const key = `${method} ${path.split("?")[0]}`;
    if (overrides[key]) return overrides[key]();
    if (key === "GET /api/v1/cfo/expense-ledger/categories") return json(META);
    if (key === "POST /api/v1/cfo/expense-ledger/summary") return json(SUMMARY);
    if (key === "GET /api/v1/cfo/expense-ledger") return json({ records: RECORDS, total: 3, limit: 50, offset: 0 });
    if (key.startsWith("POST /api/v1/cfo/expense-ledger")) return json({ expenseId: "e-new", replayed: false }, 201);
    return json({ detail: "unexpected" }, 500);
  }));
});
afterEach(() => vi.unstubAllGlobals());

const mount = () => render(<ExpenseTracker getToken={async () => "t"} />);
const posts = () => calls.filter((c) => c.method === "POST" && !c.url.endsWith("/summary"));

describe("overview", () => {
  it("shows the engine's totals, each with its result reference, and says 'Not entered' for a class with no rows", async () => {
    mount();
    expect(await screen.findByText("₹1,75,000.00")).toBeInTheDocument();
    expect(screen.getByText(/ref-total/)).toBeInTheDocument();
    expect(screen.getByText("₹1,95,000.00")).toBeInTheDocument();      // including unresolved
    expect(screen.getByText("₹20,000.00")).toBeInTheDocument();        // review queue amount
    const notEntered = screen.getByTestId("not-entered");
    expect(within(notEntered).getByText(/Direct costs/)).toBeInTheDocument();
    expect(notEntered).toHaveTextContent("Not entered");
    expect(notEntered).not.toHaveTextContent("₹0.00");
  });

  it("shows an explicit zero as ₹0.00 and keeps it apart from 'Not entered'", async () => {
    mount();
    await screen.findByText("₹1,75,000.00");
    const storage = screen.getByTestId("class-STORAGE");
    expect(storage).toHaveTextContent("₹0.00");
    expect(storage).not.toHaveTextContent("Not entered");
  });

  it("asks the backend for the period, never adds anything itself", async () => {
    mount();
    await screen.findByText("₹1,75,000.00");
    const summary = calls.find((c) => c.url.endsWith("/summary"))!;
    expect(Object.keys(summary.body as object).sort()).toEqual(["period_end", "period_start"]);
  });
});

describe("expense list", () => {
  it("shows the review state and the payment status as two separate fields, and a refund as a negative amount", async () => {
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Expenses/ }));
    const rows = await screen.findAllByTestId("expense-row");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByTestId("review-state")).toHaveTextContent("Confirmed");
    expect(within(rows[0]).getByTestId("payment-status")).toHaveTextContent("Payment unknown");
    expect(within(rows[1]).getByTestId("payment-status")).toHaveTextContent("Paid");
    expect(within(rows[1])).toBeTruthy();
    expect(rows[1]).toHaveTextContent("−₹40,000.00");
    expect(within(rows[2]).getByTestId("review-state")).toHaveTextContent("Pending review");
    expect(within(rows[2]).getByTestId("payment-status")).toHaveTextContent("Unpaid");
  });

  it("filters by category on the server", async () => {
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Expenses/ }));
    await screen.findAllByTestId("expense-row");
    await u.selectOptions(screen.getByLabelText("Category"), "software");
    await waitFor(() => expect(calls.some((c) => c.method === "GET" && c.url.includes("category=software"))).toBe(true));
  });
});

describe("review queue", () => {
  it("lists what waits for review and confirms an item through the backend", async () => {
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Review queue/ }));
    expect(await screen.findByText(/Waiting for review/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(posts().some((c) => c.url.endsWith("/e-3/review"))).toBe(true));
    expect(posts().find((c) => c.url.endsWith("/e-3/review"))!.body).toEqual({ state: "confirmed" });
  });
});

describe("review queue wording", () => {
  it("says an unknown-SKU entry stays in the total and only its SKU allocation is pending", async () => {
    overrides["POST /api/v1/cfo/expense-ledger/summary"] = () => json({ ...SUMMARY, reviewQueue: { ...SUMMARY.reviewQueue, items: [{ expenseId: "e-9", reason: "UNMAPPED_IDENTIFIER", amountPaise: 125050 }] } });
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Review queue/ }));
    const panel = await screen.findByText(/SKU not found in your catalog/);
    expect(panel).toHaveTextContent("still in the total");
    expect(panel).toHaveTextContent("only the SKU allocation is pending");
    expect(screen.queryByText(/^These are not counted in the total until you confirm them\.$/)).toBeNull();
    expect(screen.getByText(/An entry whose SKU is not found stays in the total/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();   // nothing to confirm: only the allocation is pending
  });
});

describe("history", () => {
  it("loads the record's review and payment events from the server when History is opened", async () => {
    overrides["GET /api/v1/cfo/expense-ledger/e-2"] = () => json({ ...RECORDS[1], history: [
      { seq: 1, kind: "REVIEW", reviewState: "confirmed", paymentStatus: null, paidAmountPaise: null, reason: null, createdAt: "2026-10-03T00:00:00Z" },
      { seq: 2, kind: "PAYMENT", reviewState: null, paymentStatus: "paid", paidAmountPaise: 125050, reason: null, createdAt: "2026-10-04T00:00:00Z" },
    ] });
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: "Expenses" }));
    await screen.findAllByTestId("expense-row");
    await u.click(screen.getAllByRole("button", { name: "History" })[1]);
    const events = await screen.findAllByTestId("history-event");
    expect(events).toHaveLength(2);
    expect(events[1]).toHaveTextContent("Payment status: Paid (₹1,250.50 paid)");
    expect(calls.some((c) => c.method === "GET" && c.url.endsWith("/expense-ledger/e-2"))).toBe(true);
  });
});

describe("entry form", () => {
  it("parses the typed rupees to an integer-paise string and sends the category and date", async () => {
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Add expense/ }));
    await u.type(screen.getByLabelText("Date"), "2026-09-15");
    await u.selectOptions(screen.getByLabelText("Category"), "software");
    await u.type(screen.getByLabelText("Amount (₹)"), "1,250.50");
    await u.type(screen.getByLabelText("Vendor"), "Tool Co");
    await u.click(screen.getByRole("button", { name: "Save expense" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0].url).toBe("/api/v1/cfo/expense-ledger");
    expect(posts()[0].body).toMatchObject({ effective_date: "2026-09-15", category: "software", amount_paise: "125050", vendor: "Tool Co" });
    expect(typeof (posts()[0].body as { amount_paise: unknown }).amount_paise).toBe("string");
  });

  it("refuses an unparsable amount before sending anything", async () => {
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Add expense/ }));
    await u.type(screen.getByLabelText("Date"), "2026-09-15");
    await u.selectOptions(screen.getByLabelText("Category"), "software");
    await u.type(screen.getByLabelText("Amount (₹)"), "12.345");
    await u.click(screen.getByRole("button", { name: "Save expense" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/two decimals/i);
    expect(posts()).toHaveLength(0);
  });

  it("shows the server's reason when the vendor looks like an amount", async () => {
    overrides["POST /api/v1/cfo/expense-ledger"] = () => json({ detail: [{ loc: ["body", "vendor"], msg: "Value error, The vendor looks like an amount. Enter the vendor's name only; amounts go in the amount field." }] }, 422);
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Add expense/ }));
    await u.type(screen.getByLabelText("Date"), "2026-09-15");
    await u.selectOptions(screen.getByLabelText("Category"), "software");
    await u.type(screen.getByLabelText("Amount (₹)"), "100");
    await u.type(screen.getByLabelText("Vendor"), "Acme 1,200.50");
    await u.click(screen.getByRole("button", { name: "Save expense" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/vendor/i);
  });

  it("handles a 403 in place: a plain message, the form stays usable", async () => {
    overrides["POST /api/v1/cfo/expense-ledger"] = () => json({ detail: "financials.adjust permission required" }, 403);
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Add expense/ }));
    await u.type(screen.getByLabelText("Date"), "2026-09-15");
    await u.selectOptions(screen.getByLabelText("Category"), "software");
    await u.type(screen.getByLabelText("Amount (₹)"), "100");
    await u.click(screen.getByRole("button", { name: "Save expense" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/permission/i);
    expect(screen.getByRole("button", { name: "Save expense" })).toBeEnabled();
    expect(screen.getByLabelText("Amount (₹)")).toHaveValue("100");   // nothing the seller typed is lost
  });
});

describe("void and correct", () => {
  it("voids with a reason (never a delete) through the backend", async () => {
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Expenses/ }));
    const rows = await screen.findAllByTestId("expense-row");
    await u.click(within(rows[0]).getByRole("button", { name: "Void" }));
    await u.click(screen.getByRole("button", { name: "Void expense" }));            // no reason typed: refused in place
    expect(await screen.findByRole("alert")).toHaveTextContent(/reason/i);
    expect(posts()).toHaveLength(0);
    await u.type(screen.getByLabelText("Reason"), "entered twice");
    await u.click(screen.getByRole("button", { name: "Void expense" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0].url).toBe("/api/v1/cfo/expense-ledger/e-1/void");
    expect(posts()[0].body).toEqual({ reason: "entered twice" });
  });

  it("an edit is sent as a linked correction, prefilled from the record", async () => {
    mount();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: /Expenses/ }));
    const rows = await screen.findAllByTestId("expense-row");
    await u.click(within(rows[0]).getByRole("button", { name: "Correct" }));
    expect(screen.getByLabelText("Amount (₹)")).toHaveValue("125000");
    await u.clear(screen.getByLabelText("Amount (₹)"));
    await u.type(screen.getByLabelText("Amount (₹)"), "1,300");
    await u.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0].url).toBe("/api/v1/cfo/expense-ledger/e-1/correct");
    expect(posts()[0].body).toMatchObject({ amount_paise: "130000", category: "operating_overhead" });
  });
});
