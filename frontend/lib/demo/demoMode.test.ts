import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The switch and the router around it, with fixtures replaced by a tiny stand-in: this file checks the RULES (what is answered, what passes through, what is
// refused), not any sample content.
vi.mock("@/lib/demo/fixtures/ci", () => ({ ciRoutes: [{ method: "GET", match: /^\/api\/v1\/ci\/summary$/, reply: () => ({ trackedCompetitors: 3 }) }] }));
vi.mock("@/lib/demo/fixtures/cfo", () => ({ cfoRoutes: [] }));
vi.mock("@/lib/demo/fixtures/pi", () => ({ piRoutes: [] }));
vi.mock("@/lib/demo/fixtures/cmo", () => ({ cmoRoutes: [] }));
vi.mock("@/lib/demo/fixtures/misc", () => ({ miscRoutes: [] }));

import { ApiError } from "@/lib/api";
import { demoRespond } from "@/lib/demo/respond";

describe("sample-data router", () => {
  it("answers a listed GET from the sample table", () => {
    expect(demoRespond("/api/v1/ci/summary")).toEqual({ handled: true, body: { trackedCompetitors: 3 } });
  });

  it("lets the CEO Hub, the session and the calculator go to the real backend", () => {
    for (const p of ["/api/v1/ceo/state/health", "/api/v1/ceo/investigations", "/api/v1/session", "/api/v1/cfo/pnl-scenario", "/api/v1/cfo/pnl-scenario-compare"]) {
      expect(demoRespond(p, { method: "POST" })).toEqual({ handled: false });
    }
  });

  it("refuses a read that has no sample, and any write, with a plain message instead of a real request", () => {
    expect(() => demoRespond("/api/v1/cfo/unknown")).toThrowError(ApiError);
    try {
      demoRespond("/api/v1/cfo/expenses", { method: "PUT", body: "{}" });
      throw new Error("should not be saved");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(400);
      expect(String((e as ApiError).detail)).toMatch(/nothing is saved/);
    }
  });
});

describe("sample-data switch", () => {
  beforeEach(() => { vi.resetModules(); window.localStorage.clear(); });
  afterEach(() => { vi.unstubAllEnvs(); });

  it("cannot be turned on in a build without the flag", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_DEMO_DATA", "");
    const m = await import("@/lib/demo/mode");
    m.setDemo(true);
    expect(m.DEMO_AVAILABLE).toBe(false);
    expect(m.demoActive()).toBe(false);
  });

  it("turns on and off, and remembers the choice in this browser only, when the flag is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_DEMO_DATA", "1");
    const m = await import("@/lib/demo/mode");
    expect(m.demoActive()).toBe(false); // off until chosen
    m.setDemo(true);
    expect(m.demoActive()).toBe(true);
    expect(window.localStorage.getItem(m.DEMO_KEY)).toBe("1");
    m.setDemo(false);
    expect(m.demoActive()).toBe(false);
  });

  it("cannot be turned on in a production build even when the flag is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_DEMO_DATA", "1");
    vi.stubEnv("NODE_ENV", "production");
    window.localStorage.setItem("metrion.demo", "1"); // even a leftover choice is ignored
    const m = await import("@/lib/demo/mode");
    expect(m.DEMO_AVAILABLE).toBe(false);
    m.setDemo(true);
    expect(m.demoActive()).toBe(false);
  });

  it("is off on the CEO Hub route, so the Hub and the shared shell on that page keep using the real backend", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_DEMO_DATA", "1");
    const m = await import("@/lib/demo/mode");
    m.setDemo(true);
    window.history.replaceState(null, "", "/dashboard/cfo");
    expect(m.demoActive()).toBe(true);
    window.history.replaceState(null, "", "/dashboard/ceo-hub");
    expect(m.demoActive()).toBe(false);
    window.history.replaceState(null, "", "/dashboard/ceo-hub/anything");
    expect(m.demoActive()).toBe(false);
    window.history.replaceState(null, "", "/dashboard/ceo-hubby"); // a different page that merely starts with the same letters
    expect(m.demoActive()).toBe(true);
    window.history.replaceState(null, "", "/");
  });

  it("does not touch real requests when it is off: apiFetch goes straight to fetch", async () => {
    vi.stubEnv("NEXT_PUBLIC_ENABLE_DEMO_DATA", "1"); // available but not switched on
    const f = vi.fn(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", f);
    const { apiFetch } = await import("@/lib/api");
    await expect(apiFetch("/api/v1/ci/summary", null)).resolves.toEqual({ ok: 1 });
    expect(f).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
});
