import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ImportHistory } from "@/components/cfo/ImportHistory";
import { SubmitButton } from "@/components/cfo/primitives";
import { ExpenseTrackerSection } from "@/components/cfo/sections/ExpenseTrackerSection";
import { GstLookupSection } from "@/components/cfo/sections/GstSections";
import { ToastProvider } from "@/components/ui/Toast";

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const token = async () => "t";
type Call = { method: string; path: string; body: unknown };
let calls: Call[];
let route: (c: Call) => Response | Promise<Response>;

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const c = { method: init?.method ?? "GET", path: String(url).replace(/^https?:\/\/[^/]+/, ""), body: init?.body ? JSON.parse(String(init.body)) : null };
    calls.push(c);
    return route(c);
  }));
});
afterEach(() => vi.unstubAllGlobals());

const LIST = (rows: string[]) => ({ entries: rows.map((r, i) => ({ manualAdjustmentId: `m${i}`, category: r, reason: null, amountPaise: 49900, targetType: "ACCOUNT", targetRef: "default", createdAt: "2026-09-01T00:00:00Z" })), totalPaise: 49900 * rows.length });

describe("SubmitButton", () => {
  it("drops a second click that arrives before the parent has re-rendered as busy", async () => {
    let release: () => void = () => undefined;
    const onClick = vi.fn(() => new Promise<void>((r) => (release = r)));
    render(<SubmitButton onClick={onClick} busy={false} label="Go" busyLabel="Going…" />);
    const b = screen.getByRole("button", { name: "Go" });
    fireEvent.click(b);
    fireEvent.click(b);
    expect(onClick).toHaveBeenCalledTimes(1);
    await act(async () => release());
    fireEvent.click(b);
    expect(onClick).toHaveBeenCalledTimes(2);
  });
  it("shows it is busy, and is disabled, while busy", () => {
    render(<SubmitButton onClick={() => undefined} busy label="Go" busyLabel="Going…" />);
    expect(screen.getByRole("button", { name: "Going…" })).toBeDisabled();
  });
});

describe("Expense Tracker", () => {
  it("confirms an added expense with the toast, once the backend has answered, and keeps the category usable", async () => {
    route = (c) => (c.method === "PUT" ? reply({ manualAdjustmentId: "abcdef123456" }) : reply(LIST([])));
    render(<ToastProvider><ExpenseTrackerSection getToken={token} /></ToastProvider>);
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("e.g. 499"), "499");
    expect(screen.queryByRole("status")).toBeNull(); // nothing is announced before the backend confirms
    await user.click(screen.getByRole("button", { name: "Add expense" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Expense added (ref abcdef12).");
    expect((screen.getAllByLabelText("Category")[0] as HTMLSelectElement).value).toBe("advertising");
  });

  it("says nothing was added when the backend refuses, with no success toast", async () => {
    route = () => reply("financials.adjust permission required", 403);
    render(<ToastProvider><ExpenseTrackerSection getToken={token} /></ToastProvider>);
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("e.g. 499"), "499");
    await user.click(screen.getByRole("button", { name: "Add expense" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/i);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("keeps the last list that loaded, and says it could not refresh, when a refresh fails", async () => {
    let fail = false;
    route = () => (fail ? reply("boom", 500) : reply(LIST(["advertising"])));
    render(<ToastProvider><ExpenseTrackerSection getToken={token} /></ToastProvider>);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "List expenses" }));
    expect(await screen.findByRole("cell", { name: "advertising" })).toBeInTheDocument();
    expect(screen.getByText(/All expenses · loaded/)).toBeInTheDocument();
    fail = true;
    await user.click(screen.getByRole("button", { name: "List expenses" }));
    expect(await screen.findByText(/could not refresh, this is the last list that loaded/)).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "advertising" })).toBeInTheDocument();
  });

  it("refreshes the list on screen, with its own filters, after an expense is added", async () => {
    route = (c) => (c.method === "PUT" ? reply({ manualAdjustmentId: "abcdef123456" }) : reply(LIST(["advertising"])));
    render(<ToastProvider><ExpenseTrackerSection getToken={token} /></ToastProvider>);
    const user = userEvent.setup();
    await user.selectOptions(screen.getAllByLabelText(/Category/)[1], "storage");
    await user.click(screen.getByRole("button", { name: "List expenses" }));
    await screen.findByText(/Filtered: category storage/);
    await user.selectOptions(screen.getAllByLabelText(/Category/)[1], ""); // the inputs change; the list on screen does not
    await user.type(screen.getByPlaceholderText("e.g. 499"), "10");
    await user.click(screen.getByRole("button", { name: "Add expense" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && c.path.startsWith("/api/v1/cfo/expenses?category=storage"))).toHaveLength(2));
  });

  it("labels a budget status with the category and period it answers, and keeps it when a later check fails", async () => {
    let fail = false;
    route = () => (fail ? reply("boom", 500) : reply({ noBudgetSet: false, spentPaise: 100, budgetPaise: 1000, remainingPaise: 900, exceeded: false }));
    render(<ToastProvider><ExpenseTrackerSection getToken={token} /></ToastProvider>);
    const user = userEvent.setup();
    const status = within(screen.getByText("Check budget status").parentElement as HTMLElement);
    fireEvent.change(status.getByLabelText("Period start"), { target: { value: "2026-09-01" } });
    fireEvent.change(status.getByLabelText("Period end"), { target: { value: "2026-09-30" } });
    await user.click(status.getByRole("button", { name: "Check status" }));
    expect(await status.findByText("Result for advertising, 2026-09-01 to 2026-09-30")).toBeInTheDocument();
    fail = true;
    await user.click(status.getByRole("button", { name: "Check status" }));
    expect(await status.findByText("Last successful check: advertising, 2026-09-01 to 2026-09-30")).toBeInTheDocument();
  });
});

describe("GST rate acceptance", () => {
  const LOOKUP = { noMatch: null, result: { id: "r1", likelyRatePct: "12", likelyHsn: "6302", likelyCategory: "Bed linen", sourceUrl: null, ambiguityNote: null, disclaimer: "Indicative only.", alternatives: [] } };
  async function lookedUp() {
    route = (c) => (c.path.endsWith("/accept") ? reply({ manualAdjustmentId: "abcdef123456" }) : reply(LOOKUP));
    render(<ToastProvider><GstLookupSection getToken={token} /></ToastProvider>);
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("e.g. Cotton bedsheet set"), "Bedsheet");
    await user.click(screen.getByRole("button", { name: "Look up GST rate" }));
    await screen.findByText(/Likely rate/);
    await user.type(screen.getByPlaceholderText("SKU"), "SKU-1");
    return user;
  }

  it("asks first, sends nothing until confirmed, and Cancel changes nothing", async () => {
    const user = await lookedUp();
    await user.click(screen.getByRole("button", { name: "Accept rate" }));
    const dialog = await screen.findByRole("dialog", { name: "Use 12% GST for SKU-1?" });
    expect(calls.some((c) => c.path.endsWith("/accept"))).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.some((c) => c.path.endsWith("/accept"))).toBe(false);
  });

  it("closes on Escape and gives focus back to the button that opened it", async () => {
    const user = await lookedUp();
    const opener = screen.getByRole("button", { name: "Accept rate" });
    await user.click(opener);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("sends the acceptance only on confirm, then confirms with the toast", async () => {
    const user = await lookedUp();
    await user.click(screen.getByRole("button", { name: "Accept rate" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Accept rate" }));
    expect(await screen.findByRole("status")).toHaveTextContent("GST rate accepted for SKU-1 (ref abcdef12).");
    expect(calls.filter((c) => c.path.endsWith("/accept"))).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps the dialog open and says why when the backend refuses, with no success toast", async () => {
    const user = await lookedUp();
    route = (c) => (c.path.endsWith("/accept") ? reply("financials.adjust permission required", 403) : reply(LOOKUP));
    await user.click(screen.getByRole("button", { name: "Accept rate" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Accept rate" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/do not have permission/i);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("Import history refresh", () => {
  const IMPORT = { reportFileId: "f1", filename: "orders.csv", marketplace: "MEESHO", reportCategory: "ORDERS", adapter: "meesho.orders.v1", uploadedAt: "2026-09-01T00:00:00Z", status: "COMPLETE", counts: { read: 10, accepted: 9, rejected: 1, duplicate: 0 } };
  it("keeps the imports already shown when a refresh fails, and says the list may be out of date", async () => {
    let fail = false;
    route = () => (fail ? reply("boom", 500) : reply([IMPORT]));
    const { rerender } = render(<ImportHistory getToken={token} refreshTick={0} lastUpload={null} />);
    expect(await screen.findByText("orders.csv")).toBeInTheDocument();
    fail = true;
    rerender(<ImportHistory getToken={token} refreshTick={1} lastUpload={null} />);
    expect(await screen.findByText(/may be out of date/)).toBeInTheDocument();
    expect(screen.getByText("orders.csv")).toBeInTheDocument();
  });
});
