import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createCeoClient } from "@/lib/ceo";

// Every method of the typed clients is called through the real request helpers against a stubbed fetch. The stub is wrapped (test-support/setup.ts) so a
// request the backend would refuse (unknown route, missing/unknown field, wrong type, undeclared query parameter) rejects with "CONTRACT: ..." and fails here.
const ID = "7c1d3e50-0000-4000-8000-000000000001";
const TURN = "7c1d3e50-0000-4000-8000-000000000002";
let seen: { method: string; url: string }[];

beforeEach(() => {
  seen = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    seen.push({ method: init?.method ?? "GET", url: String(url).replace("http://localhost:8000", "") });
    return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  }));
});
afterEach(() => vi.unstubAllGlobals());

const token = async () => "t";
const file = () => new File(["x"], "orders.csv", { type: "text/csv" });

describe("the CEO client", () => {
  const c = () => createCeoClient(token);

  it("every method sends a request the backend accepts", async () => {
    const k = c();
    await k.listInvestigations();
    await k.createInvestigation("Why did profit drop?");
    await k.createInvestigation();
    await k.getInvestigation(ID);
    await k.getFindings(ID);
    await k.getFindings(ID, TURN);
    await k.getNeeds(ID);
    await k.uploadAttachment(ID, file());
    await k.postTurn(ID, "hello");
    await k.postTurn(ID, "hello", { start: "2026-09-01", end: "2026-09-30" });
    await k.postTurn(ID, "run", null, { kind: "ACTION", key: "cfo.financial_health", slots: {} }, { id: ID, option: "a" }, [ID]);
    await k.getHealth();
    await k.getMemory();
    await k.forgetMemory(ID);
    await k.getSharedFindings();
    await k.forgetSharedFinding(ID);
    await k.getPriceImpactForm();
    await k.getPriceImpactForm("SKU-1");
    await k.getNewProductForm("SKU-1");
    await k.getFlow(ID, TURN);
    await k.resolve(ID, "done");
    await k.reopen(ID);
    await k.archive(ID);
    await k.setAgentAttached(ID, "CFO", false);
    await k.getAvailability();
    expect(seen.length).toBeGreaterThanOrEqual(24);
  });

  it("saving a decision-form input uses the CFO expense route with a body it accepts", async () => {
    await c().saveInput({ target_type: "SKU", target_ref: "SKU-1", field: "cogs_per_unit", value: { amount_paise: 30000 } });
    expect(seen.some((s) => s.method === "PUT" && s.url.startsWith("/api/v1/cfo/expenses"))).toBe(true);
  });
});
