import { describe, expect, it } from "vitest";
import { miscRoutes } from "@/lib/demo/fixtures/misc";

const run = (path: string) => {
  const r = miscRoutes.find((x) => x.match.test(path))!;
  return r.reply(path.match(r.match) as RegExpMatchArray, undefined);
};

describe("sample misc routes", () => {
  it("serves the backend's fixed four-agent roster", () => {
    const agents = run("/api/v1/ceo-hub/agents") as { id: string; status: string }[];
    expect(agents.map((a) => [a.id, a.status])).toEqual([["CI", "CONNECTED"], ["PI", "NOT_CONNECTED"], ["CFO", "NOT_CONNECTED"], ["CMO", "CONNECTED"]]);
  });

  it("serves a filled-in business profile", () => {
    const r = run("/api/v1/business-profile") as { profile: Record<string, unknown>; complete: boolean };
    expect(r.complete).toBe(true);
    expect(Object.keys(r.profile).sort()).toEqual(["businessName", "businessStage", "categories", "description", "marketplaces", "priceSegment", "state", "targetCustomer", "updatedAt"]);
  });

  it("every route replies with something, only for GET", () => {
    for (const r of miscRoutes) {
      expect(r.method).toBe("GET");
      expect(r.reply(["x"] as unknown as RegExpMatchArray, undefined)).toBeTruthy();
    }
  });
});
