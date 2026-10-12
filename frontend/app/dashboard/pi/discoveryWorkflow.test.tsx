import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("@/components/dashboard/DashboardShell", () => ({ DashboardShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import PiPage from "@/app/dashboard/pi/page";

const RUN = "11111111-1111-1111-1111-111111111111";
const BRIEF = "22222222-2222-2222-2222-222222222222";
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });

let discoverResponse: Promise<Response>;
let discoverBodies: unknown[];
beforeEach(() => {
  discoverBodies = [];
  window.history.replaceState(null, "", "/dashboard/pi");
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/api/v1/pi/discover")) { discoverBodies.push(JSON.parse(String(init?.body))); return discoverResponse; }
    if (url.includes("/api/v1/pi/report/")) return reply({ runId: RUN, status: "COMPLETE", candidates: [], unavailable: [{ field: "demand_signal", reason: "not available yet" }] });
    return reply({}, 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

const run = async () => {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Niche brief id (must be READY)"), BRIEF);
  await user.click(screen.getByRole("button", { name: "Run discovery" }));
  return user;
};

describe("Product Intelligence discovery (the supported route now that chat refuses it)", () => {
  it("refuses an empty brief id without calling the backend", async () => {
    render(<PiPage />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Run discovery" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a READY niche brief id first.");
    expect((fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.filter(([u]) => String(u).endsWith("/pi/discover"))).toHaveLength(0);
  });

  it("shows a pending state, then success only after a successful response, then the report", async () => {
    let finish!: (r: Response) => void;
    discoverResponse = new Promise((res) => { finish = res; });
    render(<PiPage />);
    await run();
    const busy = await screen.findByRole("button", { name: "Discovering…" });
    expect(busy).toBeDisabled();
    expect(screen.queryByText(/candidate\(s\) found/)).toBeNull(); // nothing looks successful yet
    finish(reply({ runId: RUN, agentRunId: "a", status: "COMPLETE", candidateIds: ["c1", "c2"], shortlistedCandidateIds: [], partialReason: null, failedReason: null }));
    expect(await screen.findByText(/status COMPLETE · 2 candidate\(s\) found/)).toBeInTheDocument();
    expect(discoverBodies).toEqual([{ niche_brief_id: BRIEF, depth: "SHALLOW" }]);
    expect(await screen.findByText(/demand_signal: not available yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run discovery" })).toBeEnabled();
  });

  it("a failed request is announced in plain words, never looks successful, and can be retried", async () => {
    discoverResponse = Promise.resolve(reply({ code: "QUOTA", trace: "at /srv/pi.py:1" }, 402));
    render(<PiPage />);
    const user = await run();
    expect(await screen.findByRole("alert")).toHaveTextContent(/plan does not include this/i);
    expect(screen.queryByText(/pi\.py|QUOTA/)).toBeNull();
    expect(screen.queryByText(/candidate\(s\) found/)).toBeNull();
    discoverResponse = Promise.resolve(reply({ runId: RUN, agentRunId: "a", status: "COMPLETE", candidateIds: [], shortlistedCandidateIds: [], partialReason: null, failedReason: null }));
    await user.click(screen.getByRole("button", { name: "Run discovery" }));
    await waitFor(() => expect(screen.queryByText(/plan does not include this/i)).toBeNull());
    expect(await screen.findByText(/0 candidate\(s\) found/)).toBeInTheDocument();
  });

  it("shows a partial or failed run honestly rather than as a clean success", async () => {
    discoverResponse = Promise.resolve(reply({ runId: RUN, agentRunId: "a", status: "PARTIAL", candidateIds: ["c1"], shortlistedCandidateIds: [], partialReason: "YouTube quota reached", failedReason: null }));
    render(<PiPage />);
    await run();
    expect(await screen.findByText(/Partial: YouTube quota reached/)).toBeInTheDocument();
  });
});
