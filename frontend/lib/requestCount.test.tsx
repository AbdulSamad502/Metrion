import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const getToken = async () => "t"; // Clerk hands out one stable getToken; a fresh one per render would refetch forever
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken }) }));

import { useAgentRoster } from "@/lib/agents";
import { useCiSummary } from "@/lib/useCiSummary";

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const CI = { trackedCompetitors: 0, lastResearchAt: null, recentPriceEvents7d: 0, pendingManualEntry: 0, staleCompetitors: 0 };

function Probe() {
  const { agents } = useAgentRoster();
  const ci = useCiSummary();
  return <div>{agents && ci.summary ? "loaded" : "loading"}</div>;
}

function counts() {
  const calls = (globalThis.fetch as unknown as { mock: { calls: [string][] } }).mock.calls.map((c) => String(c[0]));
  return { roster: calls.filter((u) => u.includes("/ceo-hub/agents")).length, ci: calls.filter((u) => u.includes("/ci/summary")).length };
}

afterEach(() => vi.unstubAllGlobals());

describe("request counts per page load", () => {
  const stub = () => vi.stubGlobal("fetch", vi.fn(async (url: string) => (url.includes("/ceo-hub/agents") ? json([{ id: "CFO", name: "CFO", status: "CONNECTED" }]) : json(CI))));

  it("asks for each thing exactly once in production (no StrictMode) and does not refetch after it renders", async () => {
    stub();
    render(<Probe />);
    await screen.findByText("loaded");
    await new Promise((r) => setTimeout(r, 50)); // a refetch loop would show up here
    expect(counts()).toEqual({ roster: 1, ci: 1 });
  });

  it("under StrictMode (development only) mounts twice, so it asks twice, never more, and still ends loaded", async () => {
    stub();
    render(<StrictMode><Probe /></StrictMode>);
    await screen.findByText("loaded");
    await new Promise((r) => setTimeout(r, 50));
    expect(counts()).toEqual({ roster: 2, ci: 2 });
  });
});
