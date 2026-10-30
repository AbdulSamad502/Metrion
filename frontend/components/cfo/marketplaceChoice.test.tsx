import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PeriodPnlSection } from "@/components/cfo/sections/PeriodPnlSection";
import { CashReconciliationSection, CfoPreviewSection, ReconcileSection } from "@/components/cfo/sections/ReportingSections";
import { FinancialHealthSection } from "@/components/cfo/sections/ImportAndGoalSections";

// The marketplace used to be a free-text box. It is now a choice of the three supported ids (backend/tests/unit/test_cfo_marketplace_options_parity.py proves they are exactly the
// adapters' and the engine's). These tests pin what the choice must NOT change: the id sent, the request's field names, its route, and the "fill it in first" guard.
let calls: { url: string; body: Record<string, unknown> | null }[];
beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url).replace(/^https?:\/\/[^/]+/, ""), body: init?.body ? JSON.parse(String(init.body)) : null });
    return new Response(JSON.stringify({ detail: "not computed in this test" }), { status: 503, headers: { "Content-Type": "application/json" } });
  }));
});
afterEach(() => vi.unstubAllGlobals());

const token = async () => "t";
const IDS = ["AMAZON", "FLIPKART", "MEESHO"] as const;
const FORMS: [string, string, (t: () => Promise<string | null>) => ReactElement, string][] = [
  ["reconcile", "/api/v1/cfo/reconcile", (t) => <ReconcileSection getToken={t} />, "Run reconciliation"],
  ["cash reconciliation", "/api/v1/cfo/cash-reconciliation", (t) => <CashReconciliationSection getToken={t} />, "Check cash received"],
  ["free preview", "/api/v1/cfo/preview", (t) => <CfoPreviewSection getToken={t} />, "Load preview"],
];

async function dates(u: ReturnType<typeof userEvent.setup>) {
  await u.type(screen.getByLabelText("Period start"), "2026-09-01");
  await u.type(screen.getByLabelText("Period end"), "2026-09-30");
  await u.type(screen.getByLabelText("As-of date"), "2026-09-30");
}

describe.each(FORMS)("%s", (_name, route, make, button) => {
  it.each(IDS)("sends %s as the same upper-case id, with the same four fields, to the same route", async (id) => {
    render(make(token));
    const u = userEvent.setup();
    await u.selectOptions(screen.getByLabelText("Marketplace"), id);
    await dates(u);
    await u.click(screen.getByRole("button", { name: button }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].url).toBe(route);
    expect(calls[0].body).toEqual({ marketplace: id, period_start: "2026-09-01", period_end: "2026-09-30", as_of_date: "2026-09-30" });
    expect(Object.keys(calls[0].body!).sort()).toEqual(["as_of_date", "marketplace", "period_end", "period_start"]);
  });

  it("starts with no marketplace chosen, and refuses to send until one is, with the same message as before", async () => {
    render(make(token));
    const u = userEvent.setup();
    expect((screen.getByLabelText("Marketplace") as HTMLSelectElement).value).toBe("");
    await dates(u);
    await u.click(screen.getByRole("button", { name: button }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Fill in marketplace and all three dates first.");
    expect(calls).toHaveLength(0);
  });
});

describe("period profit & loss", () => {
  it("starts with no marketplace chosen and refuses to send until one is, with the same message as before", async () => {
    render(<PeriodPnlSection getToken={token} />);
    const u = userEvent.setup();
    expect((screen.getByLabelText("Marketplace") as HTMLSelectElement).value).toBe("");
    await u.type(screen.getByLabelText("Sales line id (UUID)"), "7c1d3e50-0000-4000-8000-000000000001");
    await u.type(screen.getByLabelText("Gross item amount (₹)"), "999");
    await dates(u);
    await u.click(screen.getByRole("button", { name: "Compute period P&L" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Fill in sales line id, marketplace, document type, gross amount and all three dates first.");
    expect(calls).toHaveLength(0);
  });
});

describe("period shortcuts leave the as-of date alone", () => {
  it("does not overwrite an as-of date the seller already typed, and sends nothing", async () => {
    render(<FinancialHealthSection getToken={token} />);
    const u = userEvent.setup();
    await u.type(screen.getByLabelText("As-of date"), "2026-10-24");
    await u.click(screen.getByRole("button", { name: "This month" }));
    expect(screen.getByLabelText("As-of date")).toHaveValue("2026-10-24");
    expect(screen.getByLabelText("Period start")).not.toHaveValue("");
    expect(calls).toHaveLength(0);
  });

  it("never submits when pressed: the buttons are plain buttons, not form submit buttons", () => {
    render(<FinancialHealthSection getToken={token} />);
    for (const name of ["This month", "Last month", "Last 30 days"]) expect(screen.getByRole("button", { name })).toHaveAttribute("type", "button");
  });
});
