import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { shellData, notifications, TestShell } from "@/test-support/shellMock";
import type { Layer1Alert } from "@/lib/api";
import type { NotificationsState } from "@/lib/useNotifications";

let state: NotificationsState;
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/HeaderContext", () => ({ HeaderContext: () => null }));
vi.mock("@/components/dashboard/DashboardShell", () => ({
  DashboardShell: ({ children, ...rest }: { children: React.ReactNode }) => { void rest; return <TestShell value={shellData(state)}>{children}</TestShell>; },
}));

import DashboardPage from "@/app/dashboard/page";

type Routes = { health?: unknown; healthStatus?: number; ci?: unknown; ciStatus?: number; agents?: unknown; agentsStatus?: number; hang?: boolean };
const today = new Date().toISOString().slice(0, 10);
const fig = (label: string, value: string, register = "DERIVED") => ({ label, value, register, as_of: "2026-10-01", note: null, ref: { kind: "ENGINE_RESULT", id: label, as_of: "2026-10-01" } });
const present = (figures: ReturnType<typeof fig>[], over: object = {}) => ({ version: 1, headline: "h", figures, conflicts: [], facts: [], gaps: [], offers: [], artefacts: [], ...over });
const entry = (asOf: string | null, figures = [fig("Contribution profit", "₹142,860.00", "VERIFIED"), fig("Net realized revenue", "₹684,300.00"), fig("Marketplace fees", "₹98,420.00")]) =>
  ({ key: "BS_PNL_LATEST", status: "COMPLETE", period: "2026-09-01/2026-09-30", asOf, previewHint: null, presentation: present(figures) });
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
    expect(screen.getByText("Checking what needs you…")).toBeInTheDocument();
    expect(screen.getByTestId("health-loading")).toBeInTheDocument();
    expect(screen.queryByText(/₹/)).toBeNull();
  });

  it("counts what needs attention and links each kind to its next step", async () => {
    stub({});
    state = notifications({ alerts: [alert], dataRequests: [req], attentionCount: 2 });
    render(<DashboardPage />);
    expect(screen.getByText("2 things need you.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /1 request/ })).toHaveAttribute("href", "/dashboard/cfo#anomalies");
    expect(screen.getByRole("link", { name: /1 competitor alert/ })).toHaveAttribute("href", "/dashboard/competitors");
    await screen.findByTestId("market-watch");
  });

  it("says you are caught up when there is nothing", async () => {
    stub({});
    render(<DashboardPage />);
    expect(screen.getByText("You’re all caught up.")).toBeInTheDocument();
    await screen.findByTestId("market-watch");
  });

  it("never calls a failed feed an all-clear: unknown is not none", async () => {
    stub({});
    state = notifications({ alertsStatus: "error", alertsError: "Could not reach the server." });
    render(<DashboardPage />);
    expect(screen.getByText("We couldn’t check everything.")).toBeInTheDocument();
    expect(screen.queryByText("You’re all caught up.")).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("Could not reach the server.");
    await screen.findByTestId("market-watch");
  });

  it("shows the profit the backend saved, exactly as written, with its period and how it is known", async () => {
    stub({ health: { entries: [entry(today)] } });
    render(<DashboardPage />);
    const hero = await screen.findByTestId("profit-hero");
    expect(within(hero).getByTestId("figure-value")).toHaveTextContent("₹142,860.00");
    expect(hero).toHaveTextContent("1 Sep – 30 Sep");
    expect(within(hero).getByText("Verified")).toBeInTheDocument();
    // the bar says what it shows without relying on how it looks
    expect(within(hero).getByRole("img")).toHaveAccessibleName(/₹684,300.00 revenue: ₹98,420.00 went to marketplace fees, ₹142,860.00 is profit/);
  });

  it("draws no bar when the figures cannot honestly be drawn together", async () => {
    stub({ health: { entries: [entry(today, [fig("Contribution profit", "₹142,860.00", "VERIFIED"), fig("Net realized revenue", "₹100,000.00"), fig("Marketplace fees", "₹98,420.00")])] } });
    render(<DashboardPage />);
    const hero = await screen.findByTestId("profit-hero");
    expect(within(hero).queryByTestId("profit-flow")).toBeNull();
    expect(within(hero).getByTestId("figure-value")).toHaveTextContent("₹142,860.00");
  });

  it("is honest about saved results that are stale, missing, or could not be loaded", async () => {
    stub({ health: { entries: [entry("2020-01-01")] } });
    const stale = render(<DashboardPage />);
    expect(await screen.findByTestId("data-freshness")).toHaveTextContent(/days old/);
    stale.unmount();

    stub({ health: { entries: [] } });
    const none = render(<DashboardPage />);
    expect(await screen.findByTestId("health-none-saved")).toHaveTextContent("Let’s get your first numbers");
    expect(screen.getByRole("link", { name: /Upload reports/ })).toHaveAttribute("href", "/dashboard/cfo#import");
    none.unmount();

    stub({ healthStatus: 500, health: "boom" });
    render(<DashboardPage />);
    expect(await screen.findByTestId("health-unavailable")).toHaveTextContent("Couldn’t load your results");
  });

  it("reads health bands with a word and a shape, never colour alone", async () => {
    stub({ health: { entries: [{ key: "BS_HEALTH_BANDS", status: "AVAILABLE", period: "2026-09-01/2026-09-30", asOf: today, previewHint: null, presentation: present([fig("Contribution margin band", "GOOD"), fig("Fee ratio band", "WATCH")], { facts: [{ label: "Overall health band", text: "WATCH (classified by the engine)", basis: "SOURCE_DERIVED" }] }) }] } });
    render(<DashboardPage />);
    const card = await screen.findByTestId("health-BS_HEALTH_BANDS");
    expect(within(card).getByText("Contribution margin")).toBeInTheDocument();
    expect(within(card).getAllByText("Watch").length).toBe(2); // overall + fee ratio
    expect(within(card).getByText("Good")).toBeInTheDocument();
  });

  it("lists open leaks in plain words with the amount the backend gave", async () => {
    stub({ health: { entries: [{ key: "BS_LEAK_OPEN", status: "PARTIAL", period: null, asOf: today, previewHint: null, presentation: present([fig("SHORT_SETTLEMENT — AMAZON (SKU SHG-STL-12) [HIGH]", "₹18,640.00")], { gaps: ["More exist."] }) }] } });
    render(<DashboardPage />);
    const card = await screen.findByTestId("health-BS_LEAK_OPEN");
    expect(card).toHaveTextContent("Short settlement");
    expect(card).toHaveTextContent("Amazon · SHG-STL-12 · High priority");
    expect(card).toHaveTextContent("₹18,640.00");
    expect(card).toHaveTextContent("There are more.");
  });

  it("shows market-watch counts from the backend only", async () => {
    stub({});
    render(<DashboardPage />);
    const tile = await screen.findByTestId("market-watch");
    expect(tile).toHaveTextContent("Competitors");
    expect(tile).toHaveTextContent("3");
    expect(tile).toHaveTextContent("Unreadable");
  });

  it("hides competitors for a role without Competitor Intelligence and shows an error otherwise", async () => {
    stub({ ciStatus: 403, ci: "forbidden" });
    const { unmount } = render(<DashboardPage />);
    await waitFor(() => expect(screen.queryByTestId("market-watch")).toBeNull());
    unmount();

    stub({ ciStatus: 503, ci: "backend down" });
    render(<DashboardPage />);
    expect(await screen.findByText(/not set up on the server yet/i)).toBeInTheDocument();
  });

  it("offers a retry when the competitor counts fail to load, and shows them once it works", async () => {
    const routes: Routes = { ciStatus: 503, ci: "backend down" };
    stub(routes);
    render(<DashboardPage />);
    const notice = await screen.findByText(/not set up on the server yet/i);
    routes.ciStatus = undefined;
    routes.ci = undefined;
    await userEvent.setup().click(within(notice.closest("[role=alert]") as HTMLElement).getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("market-watch")).toHaveTextContent("Competitors");
    expect(screen.queryByText(/not set up on the server yet/i)).toBeNull();
  });

  it("names each specialist, says whether it works in chat, and gives every link its own name", async () => {
    stub({});
    render(<DashboardPage />);
    expect(await screen.findByText("In chat")).toBeInTheDocument();
    const names = screen.getAllByRole("link").map((l) => l.getAttribute("aria-label") ?? l.textContent?.trim());
    expect(names).not.toContain("Open");
    expect(screen.getAllByRole("link", { name: /^Open (Competitor|Product|Profit|Marketing)/ }).length).toBeGreaterThan(0);
  });

  it("shows a roster error in plain words", async () => {
    stub({ agentsStatus: 403, agents: "down" });
    render(<DashboardPage />);
    expect(await screen.findByText(/do not have permission/i)).toBeInTheDocument();
  });

  it("never states a profit figure or a health score the backend did not save", async () => {
    stub({});
    render(<DashboardPage />);
    await screen.findByTestId("market-watch");
    expect(screen.queryByText(/health score|\/100|₹/i)).toBeNull();
  });
});
