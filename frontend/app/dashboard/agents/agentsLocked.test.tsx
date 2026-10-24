import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// MOCKED responses only. No real tenant with a NOT_ENTITLED or NOT_PERMITTED verdict has been exercised: the seeded entitlement caps pass for everyone
// today (backend/src/backend/entitlement.py), so the locked wording below is verified against the documented response shape, not a live locked tenant.
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({ DashboardShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import AgentsPage from "@/app/dashboard/agents/page";

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const ROSTER = [
  { id: "CI", name: "Competitor Intelligence", status: "CONNECTED" },
  { id: "PI", name: "Product Intelligence", status: "NOT_CONNECTED" },
  { id: "CFO", name: "CFO", status: "NOT_CONNECTED" },
];
const stub = (availability: unknown) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url.includes("/ceo-hub/agents") ? json(ROSTER) : url.includes("/ceo/agents/availability") ? json(availability) : json({ trackedCompetitors: 0, lastResearchAt: null, recentPriceEvents7d: 0, pendingManualEntry: 0, staleCompetitors: 0 }),
    ),
  );
afterEach(() => vi.unstubAllGlobals());

describe("Agents page: locked agents (mocked availability)", () => {
  it("says 'Not in your plan' for NOT_ENTITLED and offers no link into that agent", async () => {
    stub({ CI: { status: "PRESENT", chatActions: 1 }, PI: { status: "NOT_ENTITLED", chatActions: 2 }, CFO: { status: "PRESENT", chatActions: 5 } });
    render(<AgentsPage />);
    expect(await screen.findByText("Not in your plan")).toBeInTheDocument();
    expect(screen.queryByText("Own page only")).toBeNull();
    expect(screen.queryByRole("link", { name: /Open Products/ })).toBeNull();
    expect(screen.getByText("Locked")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Competitor Intelligence.*Works with Ask Metrion/ })).toBeInTheDocument(); // an unlocked agent keeps its link
  });

  it("says 'Your role can't use this' for NOT_PERMITTED, a different message from NOT_ENTITLED", async () => {
    stub({ CI: { status: "PRESENT", chatActions: 1 }, PI: { status: "NOT_PERMITTED", chatActions: 0 }, CFO: { status: "NOT_ENTITLED", chatActions: 5 } });
    render(<AgentsPage />);
    expect(await screen.findByText("Your role can't use this")).toBeInTheDocument();
    expect(screen.getByText("Not in your plan")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open Products|Open Profit/ })).toBeNull();
  });

  it("keeps the old wording and link when the availability read fails, because nothing says it is locked", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (url.includes("/ceo-hub/agents") ? json(ROSTER) : url.includes("/availability") ? new Response("{}", { status: 500 }) : json({ lastResearchAt: null }))));
    render(<AgentsPage />);
    await waitFor(() => expect(screen.getAllByText("Own page only").length).toBe(2));
    expect(screen.getByRole("link", { name: /Open Products/ })).toBeInTheDocument();
  });

  it("explains purchasing plainly and no longer claims the backend has no entitlement service", async () => {
    stub({});
    render(<AgentsPage />);
    expect(await screen.findByText("Buying and removing agents")).toBeInTheDocument();
    expect(screen.getByText(/No way to buy, add or remove agents yet\./)).toBeInTheDocument();
    expect(screen.queryByText(/Agent Cart/)).toBeNull();
    expect(screen.queryByText(/no entitlement or purchasing service/)).toBeNull();
  });
});
