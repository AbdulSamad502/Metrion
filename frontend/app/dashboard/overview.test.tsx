import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { shellData, notifications, TestShell } from "@/test-support/shellMock";
import type { Layer1Alert } from "@/lib/api";
import type { NotificationsState } from "@/lib/useNotifications";

let state: NotificationsState;
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/HeaderContext", () => ({ HeaderContext: () => null }));
vi.mock("@/components/dashboard/DashboardShell", () => ({
  DashboardShell: ({ children }: { children: React.ReactNode }) => <TestShell value={shellData(state)}>{children}</TestShell>,
}));

import DashboardPage from "@/app/dashboard/page";

type Routes = { health?: unknown; healthStatus?: number; ci?: unknown; ciStatus?: number; agents?: unknown; agentsStatus?: number; hang?: boolean };
const today = new Date().toISOString().slice(0, 10);
const entry = (asOf: string | null) => ({ key: "BS_PNL_LATEST", status: "COMPLETE", period: "September 2026", asOf, previewHint: null, presentation: null });
const CI = { trackedCompetitors: 3, lastResearchAt: "2026-10-05T10:00:00Z", recentPriceEvents7d: 4, pendingManualEntry: 1, staleCompetitors: 2 };
const AGENTS = [{ id: "CFO", name: "CFO", status: "CONNECTED" }, { id: "PI", name: "Product Intelligence", status: "NOT_CONNECTED" }];

let hung = false;
function stub(r: Routes) {
  hung = !!r.hang;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (r.hang) return new Promise<Response>(() => undefined);
    const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
    if (url.includes("/ceo/state/health")) return reply(r.health ?? { entries: [] }, r.healthStatus);
    if (url.includes("/ci/summary")) return reply(r.ci ?? CI, r.ciStatus);
    if (url.includes("/ceo-hub/agents")) return reply(r.agents ?? AGENTS, r.agentsStatus);
    return reply({}, 404);
  }));
}

const alert = { priceEventId: "a1", competitorUrlId: "c", competitorLabel: "Rival", findingType: "PRICE_CHANGE", direction: "DECREASE", deltaPct: "-5", availabilityChange: null, thresholdBreached: true, message: "Rival cut its price", createdAt: "2026-10-09T10:00:00Z", handoff: {} } as unknown as Layer1Alert;
const req = { id: "r1", requestedField: "Cost of SKU 1", reason: null, blockingMetric: null, status: "OPEN", createdAt: "2026-10-08T10:00:00Z" };

beforeEach(() => { state = notifications(); });
afterEach(async () => {
  // every request the page made must have settled (no loading placeholder left) before the stub goes away, or a late reply lands after teardown
  if (!hung) await waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull());
  await new Promise((r) => setTimeout(r, 20));
  hung = false;
  vi.unstubAllGlobals();
});

describe("Overview", () => {
  it("says it is checking while results load, and never shows a figure before they arrive", () => {
    stub({ hang: true });
    state = notifications({ alertsStatus: "loading", dataRequestsStatus: "loading" });
    render(<DashboardPage />);
    expect(screen.getByLabelText("Loading your summary")).toBeInTheDocument();
    expect(screen.getByText("Checking your saved results…")).toBeInTheDocument();
  });

  it("counts what needs attention and links each kind to its next step", async () => {
    stub({});
    state = notifications({ alerts: [alert], dataRequests: [req], attentionCount: 2 });
    render(<DashboardPage />);
    expect(screen.getByRole("heading", { name: "2 things need your attention." })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /1 data request from the CFO/ })).toHaveAttribute("href", "/dashboard/cfo#anomalies");
    expect(screen.getByRole("link", { name: /1 competitor alert in the last 14 days/ })).toHaveAttribute("href", "/dashboard/competitors");
    await waitFor(() => expect(screen.getByText("Competitors tracked")).toBeInTheDocument());
  });

  it("says nothing needs attention when there is nothing", async () => {
    stub({});
    render(<DashboardPage />);
    expect(screen.getByRole("heading", { name: "Nothing needs your attention right now." })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Competitors tracked")).toBeInTheDocument());
  });

  it("never calls a failed feed an all-clear: unknown is not none", async () => {
    stub({});
    state = notifications({ alertsStatus: "error", alertsError: "Could not reach the server." });
    const { unmount } = render(<DashboardPage />);
    expect(screen.getByRole("heading", { name: "We could not check everything." })).toBeInTheDocument();
    expect(screen.queryByText("Nothing needs your attention right now.")).toBeNull();
    expect(screen.getByTestId("attention-unchecked")).toHaveTextContent("This is not an all-clear: competitor alerts could not be loaded.");
    await waitFor(() => expect(screen.getByText("Competitors tracked")).toBeInTheDocument());
    unmount();

    // something is known to need attention AND a feed failed: the count is shown, with the warning that there may be more
    stub({});
    state = notifications({ dataRequests: [req], dataRequestsStatus: "ok", alertsStatus: "error", alertsError: "x", attentionCount: 1 });
    render(<DashboardPage />);
    expect(screen.getByRole("heading", { name: "1 thing needs your attention." })).toBeInTheDocument();
    expect(screen.getByTestId("attention-unchecked")).toHaveTextContent("There may be more: competitor alerts could not be loaded.");
  });

  it("marks saved results current, stale, missing or unavailable truthfully", async () => {
    stub({ health: { entries: [entry(today)] } });
    const { unmount } = render(<DashboardPage />);
    expect(await screen.findByText("Saved results are current")).toBeInTheDocument();
    expect(screen.getByTestId("data-freshness")).toHaveTextContent(`as of ${today} (today)`);
    unmount();

    stub({ health: { entries: [entry("2020-01-01")] } });
    const stale = render(<DashboardPage />);
    expect(await screen.findByText("Saved results are stale")).toBeInTheDocument();
    expect(screen.getByTestId("data-freshness")).toHaveTextContent(/may not reflect recent orders/);
    stale.unmount();

    stub({ health: { entries: [] } });
    const none = render(<DashboardPage />);
    expect(await screen.findByText("No saved profit results yet")).toBeInTheDocument();
    none.unmount();

    stub({ healthStatus: 500, health: "boom" });
    render(<DashboardPage />);
    expect(await screen.findByText("Saved results unavailable")).toBeInTheDocument();
  });

  it("shows market-watch counts from the backend only", async () => {
    stub({});
    render(<DashboardPage />);
    const tile = await screen.findByTestId("market-watch");
    expect(tile).toHaveTextContent("Competitors tracked");
    expect(tile).toHaveTextContent("3");
    expect(tile).toHaveTextContent("Need manual entry");
  });

  it("hides market watch for a role without Competitor Intelligence and shows an error otherwise", async () => {
    stub({ ciStatus: 403, ci: "forbidden" });
    const { unmount } = render(<DashboardPage />);
    await waitFor(() => expect(screen.queryByTestId("market-watch")).toBeNull());
    expect(screen.queryByText("Market watch")).toBeNull();
    unmount();

    stub({ ciStatus: 503, ci: "backend down" });
    render(<DashboardPage />);
    expect(await screen.findByText(/not set up on the server yet/i)).toBeInTheDocument();
  });

  it("states honestly what agents are wired to the CEO and when activity is not recorded", async () => {
    stub({});
    render(<DashboardPage />);
    expect(await screen.findByText("Works with Ask Metrion")).toBeInTheDocument();
    expect(screen.getAllByText("Not recorded").length).toBeGreaterThan(0);
  });

  it("gives every per-agent link its own name instead of a row of identical 'Open' links", async () => {
    stub({});
    render(<DashboardPage />);
    await screen.findByText("Works with Ask Metrion");
    const names = screen.getAllByRole("link").map((l) => l.getAttribute("aria-label") ?? l.textContent?.trim());
    expect(names).not.toContain("Open");
    expect(screen.queryAllByRole("columnheader").every((h) => (h.textContent ?? "").trim() !== "")).toBe(true); // no empty table header (axe: empty-table-header)
    // the visually hidden text is absolutely positioned: the header must be its containing block or it escapes the table's scroll box and widens the page on phones (seen in the browser at 375 px)
    expect(screen.getByText("Open agent workspace").closest("th")).toHaveClass("relative");
    expect(screen.getAllByRole("link", { name: /^Open (Competitor|Product|Profit|Marketing)/ }).length).toBeGreaterThan(0);
  });

  it("shows a roster error in plain words", async () => {
    stub({ agentsStatus: 403, agents: "down" });
    render(<DashboardPage />);
    expect(await screen.findByText(/do not have permission/i)).toBeInTheDocument();
  });

  it("never states an invented headline profit figure or health score", async () => {
    stub({});
    render(<DashboardPage />);
    await screen.findByText("Competitors tracked");
    expect(screen.queryByText(/health score|\/100|₹/i)).toBeNull();
  });
});
