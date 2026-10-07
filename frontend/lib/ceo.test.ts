import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createCeoClient } from "@/lib/ceo";

/** The request contract the CEO Hub depends on (the backend tests pin the other side): paths, verbs, bodies, the bearer token,
 * the explicit period mapping, and that the client never sends a tenant id. */
describe("CEO API client", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  const lastCall = () => {
    const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    return { url, init, body: init.body ? JSON.parse(init.body as string) : undefined, headers: init.headers as Record<string, string> };
  };
  const client = () => createCeoClient(async () => "tok_123");

  it("calls the endpoints with the session token", async () => {
    await client().listInvestigations();
    expect(lastCall().url).toMatch(/\/api\/v1\/ceo\/investigations$/);
    expect(lastCall().headers.Authorization).toBe("Bearer tok_123");
    await client().getInvestigation("abc");
    expect(lastCall().url).toMatch(/\/investigations\/abc$/);
    await client().getFindings("abc");
    expect(lastCall().url).toMatch(/\/investigations\/abc\/findings$/);
    await client().getFindings("abc", "t 1");
    expect(lastCall().url).toMatch(/findings\?turn_id=t%201$/);
    await client().getAvailability();
    expect(lastCall().url).toMatch(/\/api\/v1\/ceo\/agents\/availability$/);
  });

  it("creates, resolves, archives and attaches with the right verbs and bodies", async () => {
    await client().createInvestigation("Margins");
    expect(lastCall()).toMatchObject({ init: { method: "POST" }, body: { title: "Margins" } });
    await client().resolve("abc", "Fees explained it");
    expect(lastCall()).toMatchObject({ init: { method: "POST" }, body: { resolution_note: "Fees explained it" } });
    expect(lastCall().url).toMatch(/\/abc\/resolve$/);
    await client().reopen("abc");
    expect(lastCall()).toMatchObject({ init: { method: "POST" }, body: {} });
    expect(lastCall().url).toMatch(/\/abc\/reopen$/);
    await client().archive("abc");
    expect(lastCall().url).toMatch(/\/abc\/archive$/);
    await client().setAgentAttached("abc", "CFO", false);
    expect(lastCall()).toMatchObject({ init: { method: "PUT" }, body: { attached: false } });
    expect(lastCall().url).toMatch(/\/abc\/agents\/CFO$/);
  });

  it("sends an explicit period as the two ISO dates, and nothing when there is none", async () => {
    await client().postTurn("abc", "Why did profit drop?", { start: "2026-09-01", end: "2026-09-30" });
    expect(lastCall().body).toEqual({ message: "Why did profit drop?", period_start: "2026-09-01", period_end: "2026-09-30" });
    await client().postTurn("abc", "Hello", null);
    expect(lastCall().body).toEqual({ message: "Hello" });
    await client().postTurn("abc", "Hello");
    expect(lastCall().body).toEqual({ message: "Hello" });
  });

  it("never sends a tenant id (the tenant comes only from the session)", async () => {
    await client().postTurn("abc", "hi", { start: "2026-09-01", end: "2026-09-30" });
    await client().createInvestigation("x");
    for (const [, init] of fetchMock.mock.calls as [string, RequestInit][]) expect(String(init.body ?? "")).not.toMatch(/tenant/i);
  });

  it("surfaces a non-2xx response as an ApiError carrying the backend's detail", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 409, statusText: "Conflict", json: async () => ({ detail: { code: "INVESTIGATION_NOT_ACTIVE" } }) });
    await expect(client().postTurn("abc", "hi")).rejects.toMatchObject({ status: 409, detail: { code: "INVESTIGATION_NOT_ACTIVE" } });
  });
});
