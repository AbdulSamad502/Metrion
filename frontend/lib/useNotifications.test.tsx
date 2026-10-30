import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useNotificationsFeed } from "@/lib/useNotifications";

const getToken = async () => "t";
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken }) }));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(status === 200 ? body : { detail: body }), { status, headers: { "Content-Type": "application/json" } });
const ALERT = { priceEventId: "a1", competitorUrlId: "c", competitorLabel: "Rival", findingType: "PRICE_CHANGE", direction: "DECREASE", deltaPct: "-5", availabilityChange: null, thresholdBreached: true, message: "m", createdAt: "2026-10-09T10:00:00Z", handoff: { findingId: "f", findingType: "PRICE_CHANGE", validatedFact: [] } };
const REQ = { id: "r1", requestedField: "Cost", reason: null, blockingMetric: null, status: "OPEN", createdAt: "2026-10-08T10:00:00Z" };

type Gate = { resolve: () => void };
let alertCalls: number;
let running: number;
let maxRunning: number;
let failAlerts: boolean;
let gates: Gate[];
let hold: boolean;

beforeEach(() => {
  alertCalls = 0; running = 0; maxRunning = 0; failAlerts = false; gates = []; hold = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (String(url).includes("/ci/alerts")) {
      alertCalls++; running++; maxRunning = Math.max(maxRunning, running);
      if (hold) await new Promise<void>((r) => gates.push({ resolve: r }));
      running--;
      return failAlerts ? json("boom", 500) : json({ since: "", until: "", alerts: [ALERT] });
    }
    return json([REQ]);
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("notifications feed", () => {
  it("loads both lists, reports when it checked, and is not refreshing once settled", async () => {
    const { result } = renderHook(() => useNotificationsFeed(true));
    expect(result.current.refreshing).toBe(true);
    await waitFor(() => expect(result.current.alertsStatus).toBe("ok"));
    await waitFor(() => expect(result.current.refreshing).toBe(false));
    expect(result.current.alerts).toHaveLength(1);
    expect(result.current.dataRequests).toHaveLength(1);
    expect(result.current.checkedAt).toMatch(/\d/);
  });

  it("keeps the lists it already has when a later read fails, and marks the failure", async () => {
    const { result } = renderHook(() => useNotificationsFeed(true));
    await waitFor(() => expect(result.current.refreshing).toBe(false));
    failAlerts = true;
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.alertsStatus).toBe("error"));
    expect(result.current.alerts).toHaveLength(1); // the last list that loaded is still there
    expect(result.current.dataRequests).toHaveLength(1);
  });

  it("shows the refresh in progress with the old lists, and never runs two reads at once", async () => {
    const { result } = renderHook(() => useNotificationsFeed(true));
    await waitFor(() => expect(result.current.refreshing).toBe(false));
    hold = true;
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.refreshing).toBe(true));
    expect(result.current.alerts).toHaveLength(1);
    act(() => result.current.reload()); // asked again while one is running
    act(() => result.current.reload());
    expect(alertCalls).toBe(2); // initial + the one running: nothing started in parallel
    await act(async () => gates.shift()!.resolve());
    await waitFor(() => expect(alertCalls).toBe(3)); // exactly one follow-up read for the repeated asks
    await act(async () => { while (gates.length) gates.shift()!.resolve(); });
    await waitFor(() => expect(result.current.refreshing).toBe(false));
    expect(maxRunning).toBe(1);
    expect(alertCalls).toBe(3);
  });
});
