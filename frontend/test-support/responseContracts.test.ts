import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

/** The response shapes the frontend READS, taken from its own TypeScript types, written to `responseContracts.json`.
 *
 * The backend's response bodies are hand-built dicts the API does not describe, so nothing else ties them to what a screen reads. This file is that tie:
 * this test regenerates the contract from the types and fails when the committed JSON differs (run with `UPDATE_CONTRACTS=1` to rewrite it), and
 * `backend/tests/integration/test_frontend_response_contracts.py` calls the real endpoints and fails when a real response lacks a field listed here.
 * A key ending in `?` is optional in the type and is not required of the backend; `~` before it means the nested value may be null; `[]` marks a list whose items have the shape beside it. */
const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "test-support", "responseContracts.json");

const CONTRACTS: { route: string; file: string; type: string; wrap?: string }[] = [
  { route: "GET /api/v1/session", file: "lib/api.ts", type: "SessionResponse" },
  { route: "GET /api/v1/ci/summary", file: "lib/api.ts", type: "CiSummary" },
  { route: "GET /api/v1/ceo-hub/agents", file: "lib/api.ts", type: "AgentStatus", wrap: "list" },
  { route: "GET /api/v1/cfo/data-requests", file: "lib/api.ts", type: "DataRequestItem", wrap: "list" },
  { route: "GET /api/v1/ci/alerts", file: "lib/api.ts", type: "Layer1AlertsResponse" },
  { route: "GET /api/v1/ci/digest/subscription", file: "lib/api.ts", type: "DigestSubscription" },
  { route: "POST /api/v1/cfo/cash-reconciliation", file: "lib/api.ts", type: "CashReconciliationResponse" },
  { route: "POST /api/v1/cfo/reconcile", file: "lib/api.ts", type: "ReconcileResponse" },
  { route: "POST /api/v1/cfo/preview", file: "lib/api.ts", type: "CfoPreviewResponse" },
  { route: "POST /api/v1/cfo/anomaly-check", file: "lib/api.ts", type: "AnomalyCheckResponse" },
  { route: "POST /api/v1/cfo/period-comparison", file: "lib/api.ts", type: "PeriodComparisonResponse" },
  { route: "POST /api/v1/cfo/landed-cost", file: "lib/api.ts", type: "LandedCostResponse" },
  { route: "POST /api/v1/cfo/suppliers/rank", file: "lib/api.ts", type: "SupplierRankingResponse" },
  { route: "POST /api/v1/cfo/batch-size", file: "lib/api.ts", type: "BatchSizeResponse" },
  { route: "POST /api/v1/cfo/funding-readiness", file: "lib/api.ts", type: "FundingReadinessResponse" },
  { route: "PUT /api/v1/cfo/seller-goal", file: "lib/api.ts", type: "ManualAdjustmentIdResponse" },
  { route: "PUT /api/v1/cfo/expenses", file: "lib/api.ts", type: "ManualAdjustmentIdResponse" },
  { route: "PUT /api/v1/cfo/expenses/budget", file: "lib/api.ts", type: "ManualAdjustmentIdResponse" },
  { route: "POST /api/v1/cfo/pricing", file: "lib/api.ts", type: "PricingCurveResponse" },
  { route: "POST /api/v1/cfo/pnl", file: "lib/api.ts", type: "PeriodPnlResponse" },
  { route: "GET /api/v1/ceo/findings", file: "lib/ceo.ts", type: "SharedFindingsList" },
  { route: "GET /api/v1/ceo/memory", file: "lib/ceo.ts", type: "MemoryItem", wrap: "items" },
  { route: "GET /api/v1/ceo/state/health", file: "lib/ceo.ts", type: "HealthEntry", wrap: "entries" },
  { route: "GET /api/v1/ceo/investigations", file: "lib/ceo.ts", type: "InvestigationSummary", wrap: "list" },
  { route: "GET /api/v1/ceo/investigations/{investigation_id}", file: "lib/ceo.ts", type: "InvestigationDetail" },
  { route: "POST /api/v1/ceo/investigations/{investigation_id}/turns", file: "lib/ceo.ts", type: "TurnResponse" },
];

type Tree = null | Tree[] | { [key: string]: Tree };

function build(): Record<string, Tree> {
  const cfg = ts.readConfigFile(path.join(ROOT, "tsconfig.json"), ts.sys.readFile);
  const parsed = ts.parseJsonConfigFileContent(cfg.config, ts.sys, ROOT);
  const roots = [...new Set(CONTRACTS.map((c) => path.join(ROOT, c.file)))];
  const program = ts.createProgram(roots, { ...parsed.options, noEmit: true, incremental: false });
  const checker = program.getTypeChecker();

  const tree = (type: ts.Type, node: ts.Node, depth: number): Tree => {
    if (depth > 5) return null;
    // drop null / undefined from a union
    if (type.isUnion()) {
      const members = type.types.filter((t) => !(t.flags & (ts.TypeFlags.Null | ts.TypeFlags.Undefined)));
      if (members.length !== 1) return null; // a real union (several shapes, or a literal enum): a leaf
      return tree(members[0], node, depth);
    }
    if (checker.isArrayType(type)) {
      const el = checker.getTypeArguments(type as ts.TypeReference)[0];
      const sub = tree(el, node, depth + 1);
      return sub && typeof sub === "object" && !Array.isArray(sub) ? [sub] : null;
    }
    if (type.flags & (ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BooleanLike | ts.TypeFlags.Any | ts.TypeFlags.Unknown)) return null;
    if (checker.getIndexInfosOfType(type).length > 0 && type.getProperties().length === 0) return null; // a map: its keys are data
    const props = type.getProperties();
    if (props.length === 0) return null;
    const out: { [key: string]: Tree } = {};
    for (const p of props) {
      const optional = (p.flags & ts.SymbolFlags.Optional) !== 0;
      const pt = checker.getTypeOfSymbolAtLocation(p, node);
      const sub = tree(pt, node, depth + 1);
      const nullable = sub !== null && pt.isUnion() && pt.types.some((x) => (x.flags & ts.TypeFlags.Null) !== 0);
      out[p.name + (nullable ? "~" : "") + (optional ? "?" : "")] = sub;
    }
    return Object.fromEntries(Object.entries(out).sort(([a], [b]) => a.localeCompare(b)));
  };

  const result: Record<string, Tree> = {};
  for (const c of CONTRACTS) {
    const sf = program.getSourceFile(path.join(ROOT, c.file));
    if (!sf) throw new Error(`no source ${c.file}`);
    let decl: ts.TypeAliasDeclaration | undefined;
    sf.forEachChild((n) => {
      if (ts.isTypeAliasDeclaration(n) && n.name.text === c.type) decl = n;
    });
    if (!decl) throw new Error(`no type ${c.type} in ${c.file}`);
    const t = tree(checker.getTypeAtLocation(decl.name), decl, 0);
    if (!t || Array.isArray(t)) throw new Error(`${c.type} is not an object type`);
    result[c.route] = c.wrap === "list" ? [t] : c.wrap ? { [c.wrap]: [t] } : t;
  }
  return result;
}

describe("the response shapes the frontend reads", () => {
  const built = build();
  const text = JSON.stringify(built, null, 1) + "\n";

  it("matches the committed responseContracts.json (regenerate with UPDATE_CONTRACTS=1)", () => {
    if (process.env.UPDATE_CONTRACTS) fs.writeFileSync(OUT, text, "utf8");
    expect(fs.readFileSync(OUT, "utf8")).toBe(text);
  });

  it("describes the fields a screen depends on", () => {
    const findings = built["GET /api/v1/ceo/findings"] as { items: [Record<string, unknown>]; hidden: unknown; hiddenTotal: unknown };
    expect(Object.keys(findings.items[0])).toEqual(expect.arrayContaining(["id", "trust", "trustLabel", "text", "figureRefs"]));
    const cash = built["POST /api/v1/cfo/cash-reconciliation"] as Record<string, Record<string, unknown>>;
    expect(Object.keys(cash)).toEqual(expect.arrayContaining(["cashReceived", "cashExpected", "cashVariance", "tdsDeducted", "datesMissingCount"]));
    expect(Object.keys(cash.cashExpected)).toEqual(expect.arrayContaining(["isAvailable", "unavailableReason", "valuePaise"]));
  });
});
