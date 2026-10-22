import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssignPanel, ImportExportPanel, RecurringPanel } from "@/components/expenses/ExpenseTools";
import { ExpenseTable } from "@/components/expenses/ExpenseViews";
import { buildTemplateBody, buildTemplateRefundBody } from "@/lib/expenseTools";
import type { ExpenseRecord, LedgerMeta } from "@/lib/expenseLedger";

// Recurring templates, CSV import and the accountant export (kickoff S4b, S5a, S5b). Amounts are rupees typed by the seller and sent as integer-paise strings; every
// duplicate decision, spread and count is the backend's and is only shown; nothing is added up in the browser.

const META = {
  categories: [{ id: "software", label: "Software", costClass: "OVERHEAD", treatment: "incremental" }, { id: "packaging", label: "Packaging", costClass: "DIRECT", treatment: "incremental" }],
  costClasses: [], treatments: [], channelTags: [], reviewStates: [], paymentStatuses: [], limits: {},
} as unknown as LedgerMeta;

const tpl = (o: Record<string, unknown>) => ({
  templateKey: "k-1", version: 1, kind: "MONTHLY", vendor: "Acme SaaS", description: null, category: "software", categoryLabel: "Software", costClass: "OVERHEAD", treatment: "incremental",
  amountPaise: 50000, ratePaise: null, amortizationMonths: null, startMonth: null, channelScope: null, sku: null, effectiveFrom: "2026-01-01", effectiveTo: null, ended: false, ...o,
});

type Call = { method: string; url: string; body: unknown; headers: Record<string, string> };
let calls: Call[];
let handlers: Record<string, () => Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  calls = [];
  handlers = {};
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    const method = init?.method ?? "GET";
    const body = init?.body instanceof FormData ? "FORM" : init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, url: path, body, headers: (init?.headers ?? {}) as Record<string, string> });
    const key = `${method} ${path}`;
    const hit = handlers[key] ?? handlers[`${method} ${path.split("?")[0]}`];
    return hit ? hit() : json({ detail: "unexpected" }, 500);
  }));
});
afterEach(() => vi.unstubAllGlobals());

const BASE = "/api/v1/cfo/expense-ledger";

describe("buildTemplateBody", () => {
  const f = { kind: "MONTHLY", category: "software", vendor: " Acme ", amount: "500", rate: "", months: "", effectiveFrom: "2026-01-01" } as const;
  it("sends a monthly amount as integer paise and the typed text trimmed", () => {
    expect(buildTemplateBody({ ...f })).toEqual({ ok: true, body: { kind: "MONTHLY", category: "software", effective_from: "2026-01-01", vendor: "Acme", amount_paise: "50000" } });
  });
  it("sends an amortized total with a whole number of months", () => {
    expect(buildTemplateBody({ ...f, kind: "AMORTIZED", amount: "1200.50", months: "12" })).toEqual({
      ok: true, body: { kind: "AMORTIZED", category: "software", effective_from: "2026-01-01", vendor: "Acme", amount_paise: "120050", amortization_months: 12 },
    });
  });
  it("sends a per-order rate", () => {
    const r = buildTemplateBody({ ...f, kind: "PER_ORDER", rate: "5" });
    expect(r.ok && r.body.rate_paise).toBe("500");
    expect(r.ok && "amount_paise" in r.body).toBe(false);
  });
  it.each(["", "0", "-1", "2.5", "012", "1000", "abc"])("refuses months %j", (months) => {
    expect(buildTemplateBody({ ...f, kind: "AMORTIZED", months })).toMatchObject({ ok: false });
  });
  it("names what is missing instead of guessing", () => {
    expect(buildTemplateBody({ ...f, category: "" })).toEqual({ ok: false, error: "Choose a category." });
    expect(buildTemplateBody({ ...f, effectiveFrom: "" })).toEqual({ ok: false, error: "Choose when it starts." });
    expect(buildTemplateBody({ ...f, amount: "" })).toMatchObject({ ok: false });
    expect(buildTemplateBody({ ...f, amount: "abc" })).toMatchObject({ ok: false });
  });
});

describe("recurring entries", () => {
  const mount = (onChanged = vi.fn(async () => {})) => ({ onChanged, ...render(<RecurringPanel getToken={async () => "t"} meta={META} onChanged={onChanged} />) });

  it("lists the templates with their terms, and says why a per-order one cannot make an amount yet", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [tpl({}), tpl({ templateKey: "k-2", kind: "PER_ORDER", vendor: null, amountPaise: null, ratePaise: 500, category: "packaging", categoryLabel: "Packaging" })] });
    mount();
    const rows = await screen.findAllByTestId("template-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Acme SaaS · Every month");
    expect(rows[0]).toHaveTextContent("₹500.00");
    expect(rows[1]).toHaveTextContent("Packaging · Per order");
    expect(rows[1]).toHaveTextContent("Priced from your sales for each finished month: the rate times the order count.");
  });

  it("says so when there is nothing recurring", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [] });
    mount();
    expect(await screen.findByText("Nothing recurring yet")).toBeInTheDocument();
  });

  it("saves a monthly entry with integer paise and reloads the list", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [] });
    handlers[`POST ${BASE}/templates`] = () => json({ templateKey: "k-9", version: 1 }, 201);
    const user = userEvent.setup();
    mount();
    await screen.findByText("Nothing recurring yet");
    await user.selectOptions(screen.getByLabelText("Category"), "software");
    await user.type(screen.getByLabelText("Starts"), "2026-01-01");
    await user.type(screen.getByLabelText("Amount each month (₹)"), "500");
    await user.click(screen.getByRole("button", { name: "Save recurring entry" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === `${BASE}/templates`)).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ kind: "MONTHLY", category: "software", effective_from: "2026-01-01", amount_paise: "50000" });
    expect(calls.filter((c) => c.method === "GET" && c.url === `${BASE}/templates`).length).toBeGreaterThanOrEqual(2);
  });

  it("shows the amortization fields only for a spread-over-months entry", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [] });
    const user = userEvent.setup();
    mount();
    await screen.findByText("Nothing recurring yet");
    expect(screen.queryByLabelText("Spread over (months)")).toBeNull();
    await user.selectOptions(screen.getByLabelText("Kind"), "AMORTIZED");
    expect(screen.getByLabelText("Spread over (months)")).toBeInTheDocument();
    expect(screen.getByLabelText("Total amount (₹)")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Kind"), "PER_UNIT");
    expect(screen.getByLabelText("Rate per unit (₹)")).toBeInTheDocument();
  });

  it("does not send an invalid entry and names the problem", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [] });
    const user = userEvent.setup();
    mount();
    await screen.findByText("Nothing recurring yet");
    await user.click(screen.getByRole("button", { name: "Save recurring entry" }));
    expect(await screen.findByText("Choose a category.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("creates the entries up to a month and reports how many wait for review, and what was skipped and why", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [tpl({})] });
    handlers[`POST ${BASE}/templates/materialise`] = () => json({ created: ["a", "b"], alreadyMaterialised: 1, skipped: [{ templateKey: "k-2", reason: "NO_ORDERS_IN_PERIOD" }, { templateKey: "k-3", reason: "MONTH_NOT_FINISHED" }] });
    const user = userEvent.setup();
    const { onChanged } = mount();
    await screen.findByTestId("template-row");
    await user.clear(screen.getByLabelText("Create the entries up to"));
    await user.type(screen.getByLabelText("Create the entries up to"), "2026-03-01");
    await user.click(screen.getByRole("button", { name: "Create the entries" }));
    const box = await screen.findByTestId("materialise-result");
    expect(box).toHaveTextContent("2 new entries are waiting for review; 1 already existed.");
    expect(box).toHaveTextContent("There are no sales lines for that month");
    expect(box).toHaveTextContent("The month has not finished");
    expect(calls.find((c) => c.url.endsWith("/materialise"))!.body).toEqual({ through_month: "2026-03-01" });
    expect(onChanged).toHaveBeenCalled();
  });

  it("does not log a duplicate-key warning when one template is skipped for several months", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [tpl({})] });
    handlers[`POST ${BASE}/templates/materialise`] = () => json({ created: [], alreadyMaterialised: 0, skipped: [{ templateKey: "k-1", reason: "NO_ORDERS_IN_PERIOD" }, { templateKey: "k-1", reason: "NO_ORDERS_IN_PERIOD" }] });
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup();
    mount();
    await screen.findByTestId("template-row");
    await user.click(screen.getByRole("button", { name: "Create the entries" }));
    await screen.findByTestId("materialise-result");
    expect(spy.mock.calls.filter((c) => String(c[0]).includes("same key"))).toHaveLength(0);
    spy.mockRestore();
  });

  it("shows a server refusal in place", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [] });
    handlers[`POST ${BASE}/templates/materialise`] = () => json({ detail: "through_month may be at most next month" }, 422);
    const user = userEvent.setup();
    mount();
    await screen.findByText("Nothing recurring yet");
    await user.click(screen.getByRole("button", { name: "Create the entries" }));
    expect(await screen.findByText(/at most next month|Could not create/)).toBeInTheDocument();
  });

  it("ends a template with an end date and no delete", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [tpl({})] });
    handlers[`POST ${BASE}/templates/k-1/end`] = () => json({ templateKey: "k-1", version: 2 }, 201);
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "End" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/k-1/end"))).toBe(true));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    expect(Object.keys(calls.find((c) => c.url.endsWith("/k-1/end"))!.body as object)).toEqual(["effective_to"]);
  });
});

describe("CSV import", () => {
  const csv = () => new File(["date,vendor\n"], "expenses.csv", { type: "text/csv" });
  const ROWS = [
    { row: 1, status: "OK", errors: [], note: null, matchedExpenseIds: [], date: "2026-09-10", vendor: "Acme", description: null, category: "software", amountPaise: 120050, sourceId: "INV-1", channel: null },
    { row: 2, status: "PROBABLE_MATCH", errors: [], note: "Same date, vendor, amount and description as an existing entry.", matchedExpenseIds: ["e-1"], date: "2026-09-11", vendor: "Beta", description: null, category: "software", amountPaise: 5000, sourceId: null, channel: null },
    { row: 3, status: "DUPLICATE", errors: [], note: "This source id is already in the ledger.", matchedExpenseIds: ["e-2"], date: "2026-09-12", vendor: "Gamma", description: null, category: "software", amountPaise: 700, sourceId: "INV-9", channel: null },
    { row: 4, status: "ERROR", errors: ["Date must be a real date written YYYY-MM-DD."], note: null, matchedExpenseIds: [], date: null, vendor: null, description: null, category: null, amountPaise: null, sourceId: null, channel: null },
  ];
  const summary = (extra: Record<string, unknown> = {}) => ({ fileSha256: "abc", rowCount: 4, counts: { OK: 1, ERROR: 1, DUPLICATE: 1, PROBABLE_MATCH: 1 }, fileErrors: [], rows: ROWS, ...extra });
  const mount = () => render(<ImportExportPanel getToken={async () => "t"} onChanged={async () => {}} />);

  it("checks a file without saving, lists every row with its result, and the amounts as the server gave them", async () => {
    handlers[`POST ${BASE}/import/preview`] = () => json(summary());
    const user = userEvent.setup();
    mount();
    await user.upload(screen.getByLabelText("CSV file"), csv());
    await user.click(screen.getByRole("button", { name: "Check the file" }));
    const rows = await screen.findAllByTestId("import-row");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("Ready");
    expect(rows[0]).toHaveTextContent("₹1,200.50");
    expect(rows[1]).toHaveTextContent("Looks like an existing entry (kept, flagged)");
    expect(rows[2]).toHaveTextContent("Already in the ledger (skipped)");
    expect(rows[3]).toHaveTextContent("Date must be a real date written YYYY-MM-DD.");
    expect(screen.getByTestId("import-summary")).toHaveTextContent("Checked, nothing saved yet. 1 ready, 1 look like existing entries, 1 already in the ledger, 1 with a problem.");
    expect(calls.map((c) => c.url)).toEqual([`${BASE}/import/preview`]);
    expect(calls[0].body).toBe("FORM");
    expect(calls[0].headers.Authorization).toBe("Bearer t");
  });

  it("needs a file first", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(screen.getByRole("button", { name: "Check the file" }));
    expect(await screen.findByText("Choose a CSV file first.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("will not import while rows have problems unless the seller chooses to leave them out", async () => {
    handlers[`POST ${BASE}/import/preview`] = () => json(summary());
    handlers[`POST ${BASE}/import/commit`] = () => json(summary({ created: ["x", "y"], alreadyImported: 0, state: "pending_review" }));
    const user = userEvent.setup();
    mount();
    await user.upload(screen.getByLabelText("CSV file"), csv());
    await user.click(screen.getByRole("button", { name: "Check the file" }));
    await screen.findByTestId("import-summary");
    const importButton = screen.getByRole("button", { name: "Import" });
    expect(importButton).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /Import the good rows and leave the 1 with a problem/ }));
    expect(importButton).toBeEnabled();
    await user.click(importButton);
    await waitFor(() => expect(screen.getByTestId("import-summary")).toHaveTextContent("Imported."));
    expect(screen.getByTestId("import-summary")).toHaveTextContent("2 waiting for review; 0 had been imported before.");
    expect(calls.at(-1)!.url).toBe(`${BASE}/import/commit?skip_invalid=true`);
    expect(screen.queryByRole("button", { name: "Import" })).toBeNull(); // done: nothing more to send
  });

  it("imports a clean file without the skip flag", async () => {
    handlers[`POST ${BASE}/import/preview`] = () => json(summary({ counts: { OK: 1, ERROR: 0, DUPLICATE: 0, PROBABLE_MATCH: 0 }, rows: [ROWS[0]], rowCount: 1 }));
    handlers[`POST ${BASE}/import/commit`] = () => json(summary({ counts: { OK: 1, ERROR: 0, DUPLICATE: 0, PROBABLE_MATCH: 0 }, rows: [ROWS[0]], created: ["x"], alreadyImported: 0 }));
    const user = userEvent.setup();
    mount();
    await user.upload(screen.getByLabelText("CSV file"), csv());
    await user.click(screen.getByRole("button", { name: "Check the file" }));
    await screen.findByTestId("import-summary");
    expect(screen.queryByRole("checkbox")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(calls.at(-1)!.url).toBe(`${BASE}/import/commit`));
  });

  it("shows a refused file as an alert with no table", async () => {
    handlers[`POST ${BASE}/import/preview`] = () => json({ fileSha256: "x", rowCount: 0, counts: { OK: 0, ERROR: 0, DUPLICATE: 0, PROBABLE_MATCH: 0 }, fileErrors: ["The header must be exactly these columns (any order): date, vendor."], rows: [] });
    const user = userEvent.setup();
    mount();
    await user.upload(screen.getByLabelText("CSV file"), csv());
    await user.click(screen.getByRole("button", { name: "Check the file" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The header must be exactly these columns");
    expect(screen.queryByTestId("import-row")).toBeNull();
  });

  it("shows a 403 on import in place", async () => {
    handlers[`POST ${BASE}/import/preview`] = () => json(summary({ counts: { OK: 1, ERROR: 0, DUPLICATE: 0, PROBABLE_MATCH: 0 }, rows: [ROWS[0]] }));
    handlers[`POST ${BASE}/import/commit`] = () => json({ detail: "financials.adjust permission required" }, 403);
    const user = userEvent.setup();
    mount();
    await user.upload(screen.getByLabelText("CSV file"), csv());
    await user.click(screen.getByRole("button", { name: "Check the file" }));
    await screen.findByTestId("import-summary");
    await user.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByText(/permission|Could not import/i)).toBeInTheDocument();
  });
});

describe("downloads", () => {
  it("downloads the template and both exports with the session token and keeps nothing", async () => {
    const click = vi.fn();
    const created = vi.fn(() => "blob:x");
    const revoked = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked }));
    const original = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = original(tag);
      if (tag === "a") el.click = click;
      return el;
    });
    for (const path of ["/import/template", "/export", "/export?history=true"]) handlers[`GET ${BASE}${path}`] = () => new Response("a,b\r\n", { status: 200, headers: { "Content-Type": "text/csv" } });
    const user = userEvent.setup();
    render(<ImportExportPanel getToken={async () => "t"} onChanged={async () => {}} />);
    await user.click(screen.getByRole("button", { name: "Download the template" }));
    await user.click(screen.getByRole("button", { name: "Download the ledger (CSV)" }));
    await user.click(screen.getByRole("button", { name: "Download with full history" }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(3));
    expect(calls.map((c) => c.url)).toEqual([`${BASE}/import/template`, `${BASE}/export`, `${BASE}/export?history=true`]);
    expect(calls.every((c) => c.headers.Authorization === "Bearer t")).toBe(true);
    expect(revoked).toHaveBeenCalledTimes(3);
    vi.restoreAllMocks();
  });

  it("shows a refused download in place", async () => {
    handlers[`GET ${BASE}/export`] = () => json({ detail: "forbidden" }, 403);
    const user = userEvent.setup();
    render(<ImportExportPanel getToken={async () => "t"} onChanged={async () => {}} />);
    await user.click(screen.getByRole("button", { name: "Download the ledger (CSV)" }));
    expect(await screen.findByText(/Could not download|forbidden|permission/i)).toBeInTheDocument();
  });

  it("describes the export as every state, on demand, and not stored", () => {
    render(<ImportExportPanel getToken={async () => "t"} onChanged={async () => {}} />);
    const section = screen.getByText("Export for your accountant").closest("section") ?? document.body;
    expect(within(section as HTMLElement).getByText(/including voided ones/)).toBeInTheDocument();
    expect(within(section as HTMLElement).getByText(/not stored by Metrion/)).toBeInTheDocument();
  });
});

describe("splitting an expense across SKUs", () => {
  const RECORD = { id: "e-7", vendor: "Ad Co", categoryLabel: "Advertising", costClass: "ADVERTISING", amountPaise: 100001 } as unknown as ExpenseRecord;
  const mount = () => {
    const onDone = vi.fn(async () => {});
    const onCancel = vi.fn();
    render(<AssignPanel getToken={async () => "t"} record={RECORD} onCancel={onCancel} onDone={onDone} />);
    return { onDone, onCancel };
  };

  it("sends an equal split as the SKUs only, and then refreshes", async () => {
    handlers[`POST ${BASE}/e-7/assign`] = () => json({ expenseId: "e-7", basis: "EQUAL", skus: ["A", "B"] }, 201);
    const user = userEvent.setup();
    const { onDone } = mount();
    await user.type(screen.getByLabelText("SKU 1"), "A");
    await user.type(screen.getByLabelText("SKU 2"), "B");
    expect(screen.queryByLabelText("Share of SKU 1 (%)")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save the split" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(calls[0].body).toEqual({ basis: "EQUAL", shares: [{ sku: "A" }, { sku: "B" }] });
  });

  it("sends percentages as whole basis points and leaves any remainder to the backend", async () => {
    handlers[`POST ${BASE}/e-7/assign`] = () => json({ expenseId: "e-7", basis: "EXPLICIT_SHARES", skus: ["A", "B"] }, 201);
    const user = userEvent.setup();
    mount();
    await user.selectOptions(screen.getByLabelText("Split"), "EXPLICIT_SHARES");
    await user.type(screen.getByLabelText("SKU 1"), "A");
    await user.type(screen.getByLabelText("Share of SKU 1 (%)"), "60");
    await user.type(screen.getByLabelText("SKU 2"), "B");
    await user.type(screen.getByLabelText("Share of SKU 2 (%)"), "25.5");
    await user.click(screen.getByRole("button", { name: "Save the split" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toEqual({ basis: "EXPLICIT_SHARES", shares: [{ sku: "A", bp: 6000 }, { sku: "B", bp: 2550 }] });
  });

  it.each([
    ["a missing SKU", "", "50", /Enter the SKU on row 1/],
    ["a share of zero", "A", "0", /above 0%/],
    ["a share above 100%", "A", "150", /Row 1/],
    ["an unreadable share", "A", "abc", /Row 1/],
  ])("refuses %s and sends nothing", async (_name, sku, percent, message) => {
    const user = userEvent.setup();
    mount();
    await user.selectOptions(screen.getByLabelText("Split"), "EXPLICIT_SHARES");
    if (sku) await user.type(screen.getByLabelText("SKU 1"), sku);
    await user.type(screen.getByLabelText("Share of SKU 1 (%)"), percent);
    await user.type(screen.getByLabelText("SKU 2"), "B");
    await user.type(screen.getByLabelText("Share of SKU 2 (%)"), "10");
    await user.click(screen.getByRole("button", { name: "Save the split" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("shows the server's refusal in place, adds and removes rows, and cancels", async () => {
    handlers[`POST ${BASE}/e-7/assign`] = () => json({ detail: "only advertising and storage records can be assigned to SKUs" }, 422);
    const user = userEvent.setup();
    const { onCancel } = mount();
    await user.click(screen.getByRole("button", { name: "Add a SKU" }));
    expect(screen.getByLabelText("SKU 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove the last" }));
    expect(screen.queryByLabelText("SKU 3")).toBeNull();
    await user.type(screen.getByLabelText("SKU 1"), "A");
    await user.type(screen.getByLabelText("SKU 2"), "B");
    await user.click(screen.getByRole("button", { name: "Save the split" }));
    expect(await screen.findByText(/Could not save the split|only advertising and storage/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("offers the split only on advertising and storage rows that are not voided", async () => {
    const rec = (o: Record<string, unknown>) => ({
      id: "x", effectiveDate: "2026-09-10", vendor: "V", description: null, category: "advertising", categoryLabel: "Advertising", costClass: "ADVERTISING", treatment: "incremental",
      amountPaise: 100, channelScope: null, sku: null, origin: "MANUAL", sourceReference: "manual", correctsExpenseId: null, refundOfExpenseId: null, createdAt: null,
      reviewState: "confirmed", reviewReason: null, paymentStatus: "unknown", ...o,
    });
    const onAssign = vi.fn();
    const records = [rec({ id: "a" }), rec({ id: "b", costClass: "STORAGE" }), rec({ id: "c", costClass: "OVERHEAD" }), rec({ id: "d", reviewState: "voided" })] as unknown as ExpenseRecord[];
    const user = userEvent.setup();
    render(
      <ExpenseTable records={records} filters={{}} meta={{ ...META, categories: [], reviewStates: ["confirmed"], paymentStatuses: ["unknown"] }} onFilters={() => {}} onCorrect={() => {}}
        onRefund={() => {}} onVoid={() => {}} onPayment={() => {}} onAssign={onAssign} />,
    );
    const buttons = screen.getAllByRole("button", { name: "Split across SKUs" });
    expect(buttons).toHaveLength(2);
    await user.click(buttons[0]);
    expect(onAssign).toHaveBeenCalledWith(expect.objectContaining({ id: "a" }));
  });
});

describe("refund of a spread-over-months entry", () => {
  const amort = tpl({ templateKey: "k-4", kind: "AMORTIZED", amountPaise: 1200000, amortizationMonths: 12, startMonth: "2026-01-01" });
  const mount = () => render(<RecurringPanel getToken={async () => "t"} meta={META} onChanged={async () => {}} />);

  it("builds the refund as integer paise and refuses a missing date or a zero or unreadable amount", () => {
    expect(buildTemplateRefundBody("2026-03-15", "3000")).toEqual({ ok: true, body: { effective_date: "2026-03-15", amount_paise: "300000" } });
    expect(buildTemplateRefundBody("", "3000")).toEqual({ ok: false, error: "Choose the date of the refund." });
    expect(buildTemplateRefundBody("2026-03-15", "0")).toEqual({ ok: false, error: "A refund must be more than zero." });
    expect(buildTemplateRefundBody("2026-03-15", "abc")).toMatchObject({ ok: false });
  });

  it("offers Refund only on a spread-over-months entry that has not ended", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [tpl({}), amort, tpl({ templateKey: "k-5", kind: "AMORTIZED", amortizationMonths: 3, ended: true })] });
    mount();
    await screen.findAllByTestId("template-row");
    expect(screen.getAllByRole("button", { name: "Refund" })).toHaveLength(1);
  });

  it("sends the refund and says what is left to spread, with earlier months unchanged", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [amort] });
    handlers[`POST ${BASE}/templates/k-4/refund`] = () => json({ templateKey: "k-4", remainingFrom: "2026-03-01", remainingMonths: 10, remainingPaise: "700000" }, 201);
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "Refund" }));
    await user.type(screen.getByLabelText("Refund date"), "2026-03-15");
    await user.type(screen.getByLabelText("Refund amount (₹)"), "3000");
    await user.click(screen.getByRole("button", { name: "Record the refund" }));
    expect(await screen.findByTestId("refund-note")).toHaveTextContent("From 2026-03-01, ₹7,000.00 is left to spread over 10 months. Earlier months are not changed.");
    expect(calls.find((c) => c.url.endsWith("/k-4/refund"))!.body).toEqual({ effective_date: "2026-03-15", amount_paise: "300000" });
    expect(screen.queryByTestId("refund-panel")).toBeNull();
  });

  it("explains a refusal in plain words and keeps the form", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [amort] });
    handlers[`POST ${BASE}/templates/k-4/refund`] = () => json({ detail: { code: "REFUND_EXCEEDS_REMAINING" } }, 422);
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "Refund" }));
    await user.type(screen.getByLabelText("Refund date"), "2026-03-15");
    await user.type(screen.getByLabelText("Refund amount (₹)"), "99999");
    await user.click(screen.getByRole("button", { name: "Record the refund" }));
    expect(await screen.findByText("The refund is more than what is left to spread.")).toBeInTheDocument();
    expect(screen.getByTestId("refund-panel")).toBeInTheDocument();
  });

  it("does not send an incomplete refund", async () => {
    handlers[`GET ${BASE}/templates`] = () => json({ templates: [amort] });
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "Refund" }));
    await user.click(screen.getByRole("button", { name: "Record the refund" }));
    expect(await screen.findByText("Choose the date of the refund.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("refund-panel")).toBeNull();
  });
});

describe("splitting by each SKU's own figures", () => {
  const RECORD = { id: "e-8", vendor: "Ad Co", categoryLabel: "Advertising", costClass: "ADVERTISING", amountPaise: 100001 } as unknown as ExpenseRecord;

  it.each([["NET_REVENUE", "By each SKU's revenue this period"], ["UNITS", "By each SKU's units kept this period"], ["ORDERS", "By each SKU's orders this period"]])(
    "sends %s with the SKUs only and no percentage",
    async (basis, label) => {
      handlers[`POST ${BASE}/e-8/assign`] = () => json({ expenseId: "e-8", basis, skus: ["A", "B"] }, 201);
      const user = userEvent.setup();
      render(<AssignPanel getToken={async () => "t"} record={RECORD} onCancel={() => {}} onDone={async () => {}} />);
      await user.selectOptions(screen.getByLabelText("Split"), basis);
      expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
      expect(screen.queryByLabelText("Share of SKU 1 (%)")).toBeNull();
      await user.type(screen.getByLabelText("SKU 1"), "A");
      await user.type(screen.getByLabelText("SKU 2"), "B");
      await user.click(screen.getByRole("button", { name: "Save the split" }));
      await waitFor(() => expect(calls).toHaveLength(1));
      expect(calls[0].body).toEqual({ basis, shares: [{ sku: "A" }, { sku: "B" }] });
    },
  );

  it("offers all five ways to split and says what happens when a SKU has no data", () => {
    render(<AssignPanel getToken={async () => "t"} record={RECORD} onCancel={() => {}} onDone={async () => {}} />);
    expect(within(screen.getByLabelText("Split")).getAllByRole("option")).toHaveLength(5);
    expect(screen.getByText(/stays visible as unassigned, never as zero/)).toBeInTheDocument();
  });

  it("shows the server's reason when the split is refused", async () => {
    handlers[`POST ${BASE}/e-8/assign`] = () => json({ detail: { code: "INVALID_ASSIGNMENT", detail: "The assignment is not valid." } }, 422);
    const user = userEvent.setup();
    render(<AssignPanel getToken={async () => "t"} record={RECORD} onCancel={() => {}} onDone={async () => {}} />);
    await user.selectOptions(screen.getByLabelText("Split"), "UNITS");
    await user.type(screen.getByLabelText("SKU 1"), "A");
    await user.type(screen.getByLabelText("SKU 2"), "A");
    await user.click(screen.getByRole("button", { name: "Save the split" }));
    expect(await screen.findByText(/Could not save the split|not valid/)).toBeInTheDocument();
  });
});
