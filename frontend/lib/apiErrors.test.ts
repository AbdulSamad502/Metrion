import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";

describe("friendlyApiError", () => {
  it("gives plain wording for 402, 403, 409, 422 and 503", () => {
    expect(friendlyApiError(new ApiError(402, "x"), "f")).toMatch(/plan does not include this/);
    expect(friendlyApiError(new ApiError(403, { code: "X" }), "f")).toMatch(/do not have permission/);
    expect(friendlyApiError(new ApiError(409, null), "f")).toMatch(/conflicts/);
    expect(friendlyApiError(new ApiError(422, [{ loc: ["body", "a"], msg: "bad", type: "x" }]), "f")).toMatch(/not valid/);
    expect(friendlyApiError(new ApiError(503, { code: "PI_NOT_CONFIGURED" }), "f")).toMatch(/not set up/);
  });

  it("appends a short plain backend sentence but never JSON, stack traces or long text", () => {
    expect(friendlyApiError(new ApiError(403, "research.niche_run permission required"), "f")).toContain("(research.niche_run permission required)");
    for (const bad of ['{"a":1}', "Traceback (most recent call last)", "line1\nline2", "x".repeat(200), "ValueError: boom", "[1,2]"]) {
      const out = friendlyApiError(new ApiError(409, bad), "f");
      expect(out).not.toContain(bad);
      expect(out).not.toMatch(/Traceback|\{|\[/);
    }
  });

  it("names the field a 422 is about, in the validator's own words, and never shows the value that was sent", () => {
    const detail = [{ loc: ["body", "lines", 0, "listed_paise"], msg: "Input should be a valid integer", type: "int_type", input: "secret-value" }];
    const out = friendlyApiError(new ApiError(422, detail), "f");
    expect(out).toContain("lines › item 1 › listed_paise: Input should be a valid integer");
    expect(out).not.toContain("secret-value");
    const many = Array.from({ length: 5 }, (_, i) => ({ loc: ["body", `f${i}`], msg: "Field required", type: "missing" }));
    expect(friendlyApiError(new ApiError(422, many), "f")).toMatch(/f0: Field required; f1: Field required; f2: Field required; and 2 more/);
    expect(friendlyApiError(new ApiError(422, [{ loc: ["query", "period_start"], msg: "Field required" }]), "f")).toContain("(period_start: Field required)");
    expect(friendlyApiError(new ApiError(422, [{ nonsense: true }]), "f")).toBe("Some details are missing or not valid. Check the form and try again.");
  });

  it("tells a server failure, a timeout and a dependency failure apart from a refusal, and a lost connection from all of them", () => {
    expect(friendlyApiError(new ApiError(500, "Internal Server Error"), "f")).toMatch(/went wrong on our side, not with what you entered/);
    expect(friendlyApiError(new ApiError(502, "Bad Gateway"), "f")).toMatch(/could not reach a service it depends on/);
    expect(friendlyApiError(new ApiError(504, "Gateway Timeout"), "f")).toMatch(/took too long/);
    expect(friendlyApiError(new TypeError("Failed to fetch"), "Could not run")).toMatch(/Could not reach the server/);
    expect(friendlyApiError(new ApiError(500, "Traceback (most recent call last)"), "f")).not.toMatch(/Traceback/);
  });

  it("never returns a blank message: an empty backend detail falls back to the caller's text", () => {
    expect(friendlyApiError(new ApiError(418, ""), "Could not upload the file")).toBe("Could not upload the file");
  });

  it("keeps the existing message for other statuses and the caller's fallback for non-API errors", () => {
    expect(friendlyApiError(new ApiError(404, "Not found"), "f")).toBe("We could not find that. It may have been removed, so refresh and try again. (Not found)");
    expect(friendlyApiError(new ApiError(418, "Teapot"), "f")).toBe("Teapot");
    expect(friendlyApiError(new ApiError(418, { x: 1 }), "f")).toBe("Request failed with 418");
    expect(friendlyApiError(new Error("network down"), "Could not reach the backend")).toBe("Could not reach the backend");
    expect(friendlyApiError("weird", "fallback")).toBe("fallback");
  });
});
