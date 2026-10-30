import { describe, expect, it } from "vitest";
import { agentMeta } from "@/lib/agents";

/** Descriptions must match what the agents actually do (docs: PI_details.md, CFO_details.md, CMO_details.md, CI_details.md). */
describe("agent descriptions", () => {
  it("does not say PI checks feasibility against the seller's costs: its feasibility is a price-and-fee spread, never a margin", () => {
    const d = agentMeta("PI").description;
    expect(d).not.toMatch(/against your costs/i);
    expect(d).toMatch(/Research starts in the CEO Hub/);
    expect(d).toMatch(/never calculates money/);
  });

  it("calls CFO's GST indicative and says it files nothing", () => {
    const d = agentMeta("CFO").description;
    expect(d).toMatch(/indicative GST/);
    expect(d).toMatch(/files nothing/);
  });

  it("keeps CMO recommend-only and CI evidence-based", () => {
    expect(agentMeta("CMO").description).toMatch(/never publishes/);
    expect(agentMeta("CI").description).toMatch(/evidence you provide/);
  });
});
