import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCiSummary } from "@/lib/useCiSummary";

const getToken = async () => "t";
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken }) }));

const SUMMARY = { trackedCompetitors: 3, lastResearchAt: "2026-10-22T10:00:00Z", recentPriceEvents7d: 4, pendingManualEntry: 1, staleCompetitors: 2 };
let mode: "ok" | "fail" | "forbidden";
beforeEach(() => {
  mode = "ok";
  vi.stubGlobal("fetch", vi.fn(async () => (mode === "ok" ? new Response(JSON.stringify(SUMMARY), { status: 200, headers: { "Content-Type": "application/json" } }) : new Response(JSON.stringify({ detail: "x" }), { status: mode === "forbidden" ? 403 : 503, headers: { "Content-Type": "application/json" } }))));
});
afterEach(() => vi.unstubAllGlobals());

describe("useCiSummary", () => {
  it("keeps the last counts when a later read fails, and clears the error when a retry works", async () => {
    const { result } = renderHook(() => useCiSummary());
    await waitFor(() => expect(result.current.summary?.trackedCompetitors).toBe(3));
    mode = "fail";
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.summary?.trackedCompetitors).toBe(3); // still the last good counts
    mode = "ok";
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.summary?.trackedCompetitors).toBe(3);
  });

  it("treats a missing role as 'forbidden', not as an error to retry", async () => {
    mode = "forbidden";
    const { result } = renderHook(() => useCiSummary());
    await waitFor(() => expect(result.current.forbidden).toBe(true));
    expect(result.current.error).toBeNull();
  });
});
