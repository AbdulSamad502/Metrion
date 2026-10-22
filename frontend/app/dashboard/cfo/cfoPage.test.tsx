import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({ DashboardShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import CfoPage from "@/app/dashboard/cfo/page";

const stubAll = (status: number, body: unknown) =>
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const ok = status === 200;
    const payload = !ok ? { detail: body } : url.includes("/data-requests") || url.includes("/imports") ? [] : body;
    return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
  }));
beforeEach(() => window.history.replaceState(null, "", "/dashboard/cfo"));
afterEach(() => vi.unstubAllGlobals());

describe("CFO workspace (after the split into section modules)", () => {
  it("keeps all seven tabs and switches between them with the keyboard", async () => {
    stubAll(200, []);
    render(<CfoPage />);
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Overview", "Profitability", "Cash & reconciliation", "GST", "Anomalies & requests", "Import data", "Data & imports"]);
    const user = userEvent.setup();
    screen.getByRole("tab", { name: "Overview" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Profitability" })).toHaveAttribute("aria-selected", "true");
  });

  it("renders the expense form with each label tied to its control", async () => {
    stubAll(200, { items: [], totalPaise: 0, count: 0 });
    window.history.replaceState(null, "", "/dashboard/cfo#cash");
    render(<CfoPage />);
    const cats = await screen.findAllByLabelText("Category");
    expect(cats.every((c) => c instanceof HTMLSelectElement)).toBe(true);
    expect(screen.getByLabelText("Amount (₹)")).toBeInstanceOf(HTMLInputElement);
  });

  it("shows a failed section call in plain words and as an alert, never the raw payload", async () => {
    stubAll(403, { code: "NOT_PERMITTED", trace: "at /srv/x.py:9" });
    window.history.replaceState(null, "", "/dashboard/cfo#anomalies");
    render(<CfoPage />);
    const alerts = await screen.findAllByRole("alert");
    expect(within(alerts[0]).getByText(/do not have permission/i)).toBeInTheDocument();
    expect(screen.queryByText(/x\.py|NOT_PERMITTED/)).toBeNull();
  });
});
