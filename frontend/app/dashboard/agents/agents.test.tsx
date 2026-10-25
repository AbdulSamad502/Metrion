import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({ DashboardShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import AgentsPage from "@/app/dashboard/agents/page";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const stub = (agents: () => Response) => vi.stubGlobal("fetch", vi.fn(async (url: string) => (url.includes("/ceo-hub/agents") ? agents() : json({ trackedCompetitors: 0, lastResearchAt: null, recentPriceEvents7d: 0, pendingManualEntry: 0, staleCompetitors: 0 }))));
afterEach(async () => {
  await waitFor(() => expect((globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBeGreaterThanOrEqual(2)); // both requests settled before teardown
  vi.unstubAllGlobals();
});

describe("Agents page", () => {
  it("lists exactly what the backend reports and says plainly that nothing here changes it", async () => {
    stub(() => json([{ id: "CFO", name: "CFO", status: "CONNECTED" }, { id: "PI", name: "Product Intelligence", status: "NOT_CONNECTED" }]));
    render(<AgentsPage />);
    expect(await screen.findByText("Product Intelligence")).toBeInTheDocument();
    expect(screen.getByText("Not available yet")).toBeInTheDocument();
    expect(screen.getByText(/Adding or removing agents isn’t available yet/)).toBeInTheDocument();
  });

  it("says so when the backend returns no agents", async () => {
    stub(() => json([]));
    render(<AgentsPage />);
    expect(await screen.findByText("The backend returned no agents.")).toBeInTheDocument();
  });

  it("shows a roster failure as an alert and retries", async () => {
    let n = 0;
    stub(() => (++n === 1 ? json("down", 503) : json([{ id: "CFO", name: "CFO", status: "CONNECTED" }])));
    render(<AgentsPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Adding or removing agents isn’t available yet/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("CFO")).toBeInTheDocument();
    expect(screen.getByText(/Adding or removing agents isn’t available yet/)).toBeInTheDocument();
  });
});
