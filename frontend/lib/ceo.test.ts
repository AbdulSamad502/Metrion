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

  it("sends clientRequestId only when one is given, and never a tenant id", async () => {
    await client().postTurn("abc", "Hello", null, null, null, [], "5d1b0b52-6f0c-4f0e-9d0a-0a7a2f1d9c11");
    expect(lastCall().body).toEqual({ message: "Hello", clientRequestId: "5d1b0b52-6f0c-4f0e-9d0a-0a7a2f1d9c11" });
    await client().postTurn("abc", "Hello");
    expect(lastCall().body).toEqual({ message: "Hello" });
    expect(JSON.stringify(lastCall().body)).not.toMatch(/tenant/i);
  });

  it("sends a quick action as {kind, key, slots}, only when one was chosen; reads health and flow from their own endpoints", async () => {
    await client().postTurn("abc", "Health bands", null, { kind: "BUSINESS_STATE", key: "BS_HEALTH_BANDS" });
    expect(lastCall().body).toEqual({ message: "Health bands", action: { kind: "BUSINESS_STATE", key: "BS_HEALTH_BANDS", slots: {} } });
    await client().postTurn("abc", "Why did profit drop?", { start: "2026-09-01", end: "2026-09-30" }, { kind: "PLAYBOOK", key: "PROFIT_DIAGNOSIS" });
    expect(lastCall().body).toEqual({
      message: "Why did profit drop?", period_start: "2026-09-01", period_end: "2026-09-30", action: { kind: "PLAYBOOK", key: "PROFIT_DIAGNOSIS", slots: {} },
    });
    await client().postTurn("abc", "Typed", null, null);
    expect(lastCall().body).toEqual({ message: "Typed" }); // no action key at all for a typed question
    await client().getHealth();
    expect(lastCall().url).toMatch(/\/api\/v1\/ceo\/state\/health$/);
    await client().getFlow("abc", "t1");
    expect(lastCall().url).toMatch(/\/investigations\/abc\/turns\/t1\/flow$/);
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

describe("CEO live event stream client", () => {
  const enc = new TextEncoder();
  const streamOf = (chunks: string[]) =>
    new ReadableStream<Uint8Array>({
      start(c) {
        chunks.forEach((x) => c.enqueue(enc.encode(x)));
        c.close();
      },
    });
  const frame = (kind: string, data: Record<string, unknown> = {}) => `event: ${kind}\ndata: ${JSON.stringify({ kind, atMs: 5, data })}\n\n`;

  afterEach(() => vi.unstubAllGlobals());

  it("parses frames split across chunks, skips keep-alives and malformed frames, and sends the bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: streamOf(["retry: 3000\n\n", ": keepalive\n\n", frame("CLASSIFIED", { route: "ACTION" }).slice(0, 20), frame("CLASSIFIED", { route: "ACTION" }).slice(20),
        "event: X\ndata: {not json\n\n", frame("LEG_FINISHED", { findingId: "f1" }), frame("TURN_DONE", { status: "DELIVERED" })]),
    });
    vi.stubGlobal("fetch", fetchMock);
    const seen: string[] = [];
    await createCeoClient(async () => "tok_9").streamEvents("inv-1", (e) => seen.push(e.kind));
    expect(seen).toEqual(["CLASSIFIED", "LEG_FINISHED", "TURN_DONE"]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/ceo\/investigations\/inv-1\/events$/);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok_9");
    expect((init.headers as Record<string, string>).Accept).toBe("text/event-stream");
  });

  it("rejects when the stream cannot be opened (the findings poll then does the whole job)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, statusText: "Not Found", body: null }));
    await expect(createCeoClient(async () => "t").streamEvents("x", () => undefined)).rejects.toMatchObject({ status: 404 });
  });

  it("sends no tenant id and no body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: streamOf([]) });
    vi.stubGlobal("fetch", fetchMock);
    await createCeoClient(async () => "t").streamEvents("inv-1", () => undefined);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeUndefined();
    expect(url).not.toMatch(/tenant/i);
  });
});
