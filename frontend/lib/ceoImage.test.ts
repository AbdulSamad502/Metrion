import { afterEach, describe, expect, it, vi } from "vitest";
import { createCeoClient } from "@/lib/ceo";

afterEach(() => vi.unstubAllGlobals());

describe("the CEO client's picture loader", () => {
  it("fetches the seller's picture from the authenticated image route only, with the session token", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(["x"], { type: "image/png" }) });
    vi.stubGlobal("fetch", fetchSpy);
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} });
    const url = await createCeoClient(async () => "tok").getAttachmentImage("inv-1", "att-9");
    expect(url).toBe("blob:x");
    const [target, init] = fetchSpy.mock.calls[0];
    expect(String(target)).toMatch(/\/api\/v1\/ceo\/investigations\/inv-1\/attachments\/att-9\/image$/);
    expect(init.headers.Authorization).toBe("Bearer tok");
  });

  it("refuses when the server does not serve the picture (another tenant, another file type, unknown id)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, blob: async () => new Blob() }));
    await expect(createCeoClient(async () => "tok").getAttachmentImage("inv-1", "att-9")).rejects.toThrow();
  });
});
