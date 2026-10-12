import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createCeoClient } from "@/lib/ceo";
import { cmo, EMPTY_INTAKE, type ProductIntake } from "@/lib/cmo";

// Every method of the two typed clients is called through the real request helpers against a stubbed fetch. The stub is wrapped (test-support/setup.ts) so a
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
const intake: ProductIntake = { ...EMPTY_INTAKE, sku: "SKU-1", productName: "Steel bottle", brand: "Acme", categoryHint: "Home", attributes: [{ name: "Colour", value: "Blue" }], notes: "a\nb", targetPriceRupees: "499" };

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

describe("the CMO client", () => {
  const sets = ["AMAZON", "FLIPKART"] as const;

  it("every method sends a request the backend accepts", async () => {
    await cmo.titleSets(token, intake, "key-1", [...sets]);
    await cmo.approveTitle(token, ID, { optionId: ID });
    await cmo.approveTitle(token, ID, { editedText: "My own title" });
    await cmo.listingCopy(token, intake, "key-2", "AMAZON", { approvalId: ID });
    await cmo.listingCopy(token, intake, "key-2", "AMAZON", { sellerTitle: "My title" });
    for (const kind of ["description", "bullets", "keywords", "backend-terms"] as const) await cmo.component(token, kind, intake, `key-${kind}`, "AMAZON", { sellerTitle: "My title" });
    await cmo.hashtags(token, intake, "key-3", "AMAZON");
    await cmo.hashtags(token, intake, "key-3", null);
    await cmo.catalog(token, intake, "key-4", ["COLOR", "MATERIAL"], [...sets]);
    await cmo.uploadImage(token, new File(["x"], "p.png", { type: "image/png" }));
    await cmo.analyzeImage(token, ID);
    await cmo.confirmHint(token, ID, "Colour", "SKU-1", "Blue");
    await cmo.suggestNiche(token);
    await cmo.listNiche(token);
    await cmo.confirmNiche(token, [{ term_id: ID, decision: "CONFIRM" }, { term_id: ID, decision: "EDIT", new_text: "steel bottle" }], ["new term"]);
    await cmo.trendPreview(token, ["NICHE", "MARKET_NEWS"], [...sets]);
    await cmo.trendRun(token, "key-5", "a".repeat(64), ["NICHE", "MARKET_NEWS"], [...sets]);
    await cmo.trendList(token);
    await cmo.trendGet(token, ID);
    expect(seen.length).toBe(22);
  });
});
