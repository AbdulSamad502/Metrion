import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { shellData, notifications, TestShell } from "@/test-support/shellMock";
import type { NotificationsState } from "@/lib/useNotifications";

let state: NotificationsState;
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({
  DashboardShell: ({ children }: { children: React.ReactNode }) => <TestShell value={shellData(state)}>{children}</TestShell>,
}));

import CfoPage from "@/app/dashboard/cfo/page";

const fig = (label: string, value: string, register = "DERIVED") => ({ label, value, register, as_of: "2026-10-01", note: null, ref: { kind: "ENGINE_RESULT", id: label, as_of: "2026-10-01" } });
const present = (figures: ReturnType<typeof fig>[], over: object = {}) => ({ version: 1, headline: "h", figures, conflicts: [], facts: [], gaps: [], offers: [], artefacts: [], ...over });
const PNL = { key: "BS_PNL_LATEST", status: "COMPLETE", period: "2026-09-01/2026-09-30", asOf: new Date().toISOString().slice(0, 10), previewHint: null, presentation: present([fig("Contribution profit", "₹1,42,860.00", "VERIFIED"), fig("Net realized revenue", "₹6,84,300.00"), fig("Marketplace fees", "₹98,420.00")]) };
const req = { id: "r1", requestedField: "Cost of SKU 1", reason: "Needed to work out profit", blockingMetric: null, status: "OPEN", createdAt: "2026-10-08T10:00:00Z" };

function stub(entries: unknown[], healthStatus = 200) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
    if (url.includes("/ceo/state/health")) return reply({ entries }, healthStatus);
    if (url.includes("/cfo/imports")) return reply([]);
    return reply({}, 404);
  }));
}
beforeEach(() => { state = notifications(); });
afterEach(async () => {
  await waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull());
  vi.unstubAllGlobals();
});

describe("Profit & Finance (read-only)", () => {
  it("shows the saved profit exactly as the backend wrote it, and says nothing is asked of you here", async () => {
    stub([PNL]);
    const { container } = render(<CfoPage />);
    const hero = await screen.findByTestId("profit-hero");
    expect(within(hero).getByTestId("figure-value")).toHaveTextContent("₹1,42,860.00");
    expect(container.querySelectorAll("form, input, select, textarea, [type=file]")).toHaveLength(0);
  });

  it("lists what the CFO is waiting for, and sends the seller to the CEO to answer", async () => {
    stub([PNL]);
    state = notifications({ dataRequests: [req], attentionCount: 1 });
    render(<CfoPage />);
    const row = await screen.findByRole("link", { name: /Cost of SKU 1/ });
    expect(row).toHaveAttribute("href", "/dashboard/ceo-hub");
  });

  it("says plainly when nothing is saved, and when the saved results could not be loaded", async () => {
    stub([]);
    const none = render(<CfoPage />);
    expect(await screen.findByTestId("health-none-saved")).toBeInTheDocument();
    none.unmount();

    stub([], 500);
    render(<CfoPage />);
    expect(await screen.findByTestId("health-unavailable")).toBeInTheDocument();
  });

  it("keeps the older forms one click away, never on this page", async () => {
    stub([PNL]);
    render(<CfoPage />);
    expect(await screen.findByRole("link", { name: "Open the advanced tools" })).toHaveAttribute("href", "/dashboard/cfo/tools");
  });
});
