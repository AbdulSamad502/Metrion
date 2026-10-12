import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const getToken = async () => "t";
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken }) }));

import { agentTier, useAgentRoster, withChatAvailability } from "@/lib/agents";
import type { AgentStatus } from "@/lib/api";

const roster: AgentStatus[] = [
  { id: "CI", name: "Competitor Intelligence", status: "CONNECTED" },
  { id: "PI", name: "Product Intelligence", status: "NOT_CONNECTED" },
  { id: "CFO", name: "CFO", status: "NOT_CONNECTED" },
  { id: "CMO", name: "CMO", status: "CONNECTED" },
];
const live = (over: Record<string, unknown> = {}) => ({
  CFO: { status: "PRESENT", chatActions: 6 }, CI: { status: "PRESENT", chatActions: 1 }, PI: { status: "PRESENT", chatActions: 1 }, CMO: { status: "PRESENT", chatActions: 1 }, ...over,
});
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("which agents work with Ask Metrion", () => {
  it("marks an agent connected when the CEO can really run something for this member, even if the fixed roster says otherwise", () => {
    const merged = withChatAvailability(roster, live() as never);
    expect(merged.map((a) => [a.id, a.status])).toEqual([["CI", "CONNECTED"], ["PI", "CONNECTED"], ["CFO", "CONNECTED"], ["CMO", "CONNECTED"]]);
  });

  it("does not connect an agent with no chat action, or one the member may not use, or one the plan excludes", () => {
    const merged = withChatAvailability(roster, live({ PI: { status: "PRESENT", chatActions: 0 }, CFO: { status: "NOT_ENTITLED", chatActions: 6 } }) as never);
    expect(merged.find((a) => a.id === "PI")?.status).toBe("NOT_CONNECTED");
    expect(merged.find((a) => a.id === "CFO")?.status).toBe("NOT_CONNECTED");
  });

  it("never connects an agent from nothing, and never disconnects one the roster connected", () => {
    expect(withChatAvailability(roster, null)).toEqual(roster);
    expect(withChatAvailability(roster, {} as never)).toEqual(roster);
    expect(withChatAvailability(roster, live({ CI: { status: "NOT_PERMITTED", chatActions: 0 } }) as never).find((a) => a.id === "CI")?.status).toBe("CONNECTED");
  });

  it("the tier follows the merged status", () => {
    expect(agentTier(withChatAvailability(roster, live() as never).find((a) => a.id === "PI") as AgentStatus)).toBe("connected");
    expect(agentTier(roster.find((a) => a.id === "PI") as AgentStatus)).toBe("available");
  });
});

function Probe() {
  const { agents, error } = useAgentRoster();
  return <div>{error ?? (agents ? agents.map((a) => `${a.id}:${a.status}`).join(",") : "loading")}</div>;
}

describe("the roster hook", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("combines the roster with the real availability, asking each once", async () => {
    const fetchMock = vi.fn(async (url: string) => (url.includes("/ceo-hub/agents") ? json(roster) : json(live())));
    vi.stubGlobal("fetch", fetchMock);
    render(<Probe />);
    expect(await screen.findByText("CI:CONNECTED,PI:CONNECTED,CFO:CONNECTED,CMO:CONNECTED")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map((c) => String(c[0]).replace(/^.*\/api\/v1/, ""))).toEqual(["/ceo-hub/agents", "/ceo/agents/availability"]);
  });

  it("keeps the roster as it is when availability cannot be read (a member without the CEO key gets a 403)", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (url.includes("/ceo-hub/agents") ? json(roster) : json({ detail: "forbidden" }, 403))));
    render(<Probe />);
    expect(await screen.findByText("CI:CONNECTED,PI:NOT_CONNECTED,CFO:NOT_CONNECTED,CMO:CONNECTED")).toBeInTheDocument();
  });
});
