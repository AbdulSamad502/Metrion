import { afterEach, describe, expect, it, vi } from "vitest";
import { newSubmissionId, submissionFingerprint } from "@/lib/ceoModel";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

describe("the identifier of one logical submission", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is a UUID and is different every time", () => {
    const ids = Array.from({ length: 50 }, () => newSubmissionId());
    expect(ids.every((i) => UUID.test(i))).toBe(true);
    expect(new Set(ids).size).toBe(50);
  });

  it("still produces unique, well-formed ids when the platform has only getRandomValues", () => {
    const real = globalThis.crypto;
    vi.stubGlobal("crypto", { getRandomValues: (a: Uint8Array) => real.getRandomValues(a) });
    const ids = Array.from({ length: 20 }, () => newSubmissionId());
    expect(ids.every((i) => UUID.test(i))).toBe(true);
    expect(new Set(ids).size).toBe(20);
  });

  it("still produces unique, well-formed ids with no platform randomness at all", () => {
    vi.stubGlobal("crypto", undefined);
    const ids = Array.from({ length: 20 }, () => newSubmissionId());
    expect(ids.every((i) => UUID.test(i))).toBe(true);
    expect(new Set(ids).size).toBe(20);
  });

  it("treats two sends as the same submission only when everything the server would act on is equal", () => {
    const base = submissionFingerprint("inv", "hello", null, null, null, []);
    expect(submissionFingerprint("inv", "hello", null, null, null, [])).toBe(base);
    expect(submissionFingerprint("inv", "hello!", null, null, null, [])).not.toBe(base);
    expect(submissionFingerprint("inv2", "hello", null, null, null, [])).not.toBe(base);
    expect(submissionFingerprint("inv", "hello", { start: "2026-09-01", end: "2026-09-30" }, null, null, [])).not.toBe(base);
    expect(submissionFingerprint("inv", "hello", null, { kind: "SYNTHESIZE" }, null, [])).not.toBe(base);
    expect(submissionFingerprint("inv", "hello", null, null, null, ["a1"])).not.toBe(base);
  });
});
