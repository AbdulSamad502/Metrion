import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import contract from "./requestContract.json";
import { findRoute } from "./requestContract";

/** A static pass over every `apiFetch(path, token, { method, body: JSON.stringify(<object>) })` call in the app's own sources: the object literal's field names are
 * compared with the backend's request schema for that route (a field the backend does not have; a required field missing). Names only, not values: the runtime
 * guard (`setup.ts`) checks values for every request the tests actually send. This catches the calls no test reaches.
 * Bodies that are spread, built by a function, or not an object literal are reported as "not analysable" rather than silently passed. */
type Schema = { $ref?: string; properties?: Record<string, Schema>; required?: string[]; items?: Schema; anyOf?: Schema[]; allOf?: Schema[]; additionalProperties?: boolean | Schema };
const schemas = contract.schemas as unknown as Record<string, Schema>;
const ROOT = path.resolve(__dirname, "..");

function files(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) files(p, out);
    else if (/\.tsx?$/.test(e.name) && !/\.test\./.test(e.name)) out.push(p);
  }
  return out;
}

const deref = (s: Schema | undefined): Schema | undefined => {
  while (s?.$ref) s = schemas[s.$ref.split("/").pop() as string];
  if (s?.anyOf) {
    const nonNull = s.anyOf.map((x) => deref(x)).filter((x) => x && (x.properties || x.items));
    if (nonNull.length === 1) return nonNull[0];
  }
  return s;
};

const literalText = (n: ts.Node): string | null => (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n) ? n.text : null);

function templatePath(n: ts.Expression, consts: Map<string, string>): string | null {
  const direct = literalText(n);
  if (direct !== null) return direct;
  if (ts.isTemplateExpression(n)) {
    let out = n.head.text;
    for (const span of n.templateSpans) {
      const e = span.expression;
      out += ts.isIdentifier(e) && consts.has(e.text) ? (consts.get(e.text) as string) : "{}";
      out += span.literal.text;
    }
    return out;
  }
  return null;
}

type Result = { where: string; route: string; problems: string[]; analysable: boolean };

/** The object literal an identifier was declared as, looked up from the call outwards (the nearest enclosing block that declares it), so a same-named variable elsewhere in the file is never used. */
function objectFor(expr: ts.Expression): ts.ObjectLiteralExpression | null {
  if (ts.isObjectLiteralExpression(expr)) return expr;
  if (!ts.isIdentifier(expr)) return null;
  for (let n: ts.Node | undefined = expr.parent; n; n = n.parent) {
    if (!ts.isBlock(n) && !ts.isSourceFile(n)) continue;
    for (const st of n.statements) {
      if (!ts.isVariableStatement(st)) continue;
      for (const d of st.declarationList.declarations) {
        if (ts.isIdentifier(d.name) && d.name.text === expr.text) return d.initializer && ts.isObjectLiteralExpression(d.initializer) ? d.initializer : null;
      }
    }
  }
  return null;
}

function checkObject(obj: ts.ObjectLiteralExpression, schemaIn: Schema | undefined, where: string, sf: ts.SourceFile, problems: string[]): boolean {
  const schema = deref(schemaIn);
  if (!schema?.properties) return true;
  let open = false;
  const keys = new Set<string>();
  for (const p of obj.properties) {
    if (ts.isSpreadAssignment(p)) { open = true; continue; }
    const name = p.name && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) ? p.name.text : null;
    if (!name) { open = true; continue; }
    keys.add(name);
    if (!(name in schema.properties) && schema.additionalProperties !== true) problems.push(`${where}: the backend has no field "${name}"`);
    if (ts.isPropertyAssignment(p) && name in schema.properties) {
      const sub = deref(schema.properties[name]);
      const v = p.initializer;
      if (ts.isObjectLiteralExpression(v)) open = checkObject(v, sub, `${where}.${name}`, sf, problems) === false || open;
      else if (ts.isArrayLiteralExpression(v) && sub?.items) {
        for (const el of v.elements) if (ts.isObjectLiteralExpression(el)) checkObject(el, sub.items, `${where}.${name}[]`, sf, problems);
      }
    }
  }
  if (!open) for (const r of schema.required ?? []) if (!keys.has(r)) problems.push(`${where}: missing required "${r}"`);
  return !open;
}

function analyse(file: string): Result[] {
  const text = fs.readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const consts = new Map<string, string>();
  sf.forEachChild(function find(n) {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer) {
      const t = literalText(n.initializer);
      if (t !== null && t.startsWith("/api/v1")) consts.set(n.name.text, t);
    }
    ts.forEachChild(n, find);
  });
  const results: Result[] = [];
  const visit = (n: ts.Node) => {
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "apiFetch" && n.arguments.length >= 3) {
      const p = templatePath(n.arguments[0], consts);
      const init = n.arguments[2];
      if (p && p.startsWith("/api/v1") && ts.isObjectLiteralExpression(init)) {
        let method = "GET";
        let bodyExpr: ts.Expression | null = null;
        for (const prop of init.properties) {
          if (!ts.isPropertyAssignment(prop) || !ts.isIdentifier(prop.name)) continue;
          if (prop.name.text === "method") method = literalText(prop.initializer) ?? "GET";
          if (prop.name.text === "body") bodyExpr = prop.initializer;
        }
        const clean = p.split("?")[0];
        // a path with a runtime piece that is not a whole id segment (an action name, a helper's path argument) cannot be matched to one route here
        const segments = clean.split("/");
        const dynamic = segments.some((s) => s.includes("{}") && s !== "{}") || (segments.length > 2 && segments[segments.length - 1] === "{}" && segments[segments.length - 2] === "{}");
        const hit = dynamic ? null : findRoute(method, clean);
        const where = `${path.relative(ROOT, file).split(path.sep).join("/")}:${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}`;
        const problems: string[] = [];
        let analysable = true;
        if (dynamic) analysable = false;
        else if (!hit) problems.push(`${method} ${clean} is not a route the backend serves`);
        else if (bodyExpr && ts.isCallExpression(bodyExpr) && bodyExpr.expression.getText(sf) === "JSON.stringify" && bodyExpr.arguments[0]) {
          const obj = objectFor(bodyExpr.arguments[0]);
          if (!obj) analysable = false;
          else if (!hit.route.body) problems.push(`${hit.key}: the backend takes no body`);
          else analysable = checkObject(obj, hit.route.body, hit.key, sf, problems);
        } else if (bodyExpr) analysable = false;
        results.push({ where, route: hit?.key ?? `${method} ${clean}`, problems, analysable });
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return results;
}

const all = ["app", "components", "lib"].flatMap((d) => files(path.join(ROOT, d))).flatMap(analyse);

describe("request bodies built in the app's own sources", () => {
  it("finds the calls (a guard against the scan silently seeing nothing)", () => {
    expect(all.length).toBeGreaterThanOrEqual(20); // was 30 before the form-heavy CI workspace was removed (CI spec C32): the dashboard now makes read calls only
  });

  it("every call goes to a served route with field names the backend knows and every required field present", () => {
    expect(all.flatMap((r) => r.problems.map((p) => `${r.where} ${p}`))).toEqual([]);
  });

  it("reports how many bodies could be analysed (the rest are covered only by the runtime guard)", () => {
    const withBody = all.filter((r) => r.route.startsWith("POST") || r.route.startsWith("PUT") || r.route.startsWith("PATCH"));
    const unanalysed = withBody.filter((r) => !r.analysable).map((r) => `${r.where} ${r.route}`);
    console.info(`static request-shape analysis: ${all.length} apiFetch calls, ${withBody.length} with a body, ${withBody.length - unanalysed.length} fully analysed`);
    if (unanalysed.length) console.info(`not analysable here:\n  ${unanalysed.join("\n  ")}`);
    expect(withBody.length - unanalysed.length).toBeGreaterThan(0);
  });
});

describe("the analyser itself", () => {
  const run = (src: string) => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "shape-"));
    const f = path.join(dir, "probe.ts");
    fs.writeFileSync(f, src);
    try {
      return analyse(f);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  };

  it("flags a field the backend does not have and a missing required field", () => {
    const [r] = run(`apiFetch("/api/v1/cfo/cash-reconciliation", t, { method: "POST", body: JSON.stringify({ marketplace: "X", periodStart: "2026-09-01" }) });`);
    const text = r.problems.join(" | ");
    expect(text).toContain('no field "periodStart"');
    expect(text).toContain('missing required "period_start"');
  });

  it("passes a body that matches, resolves a variable from the nearest scope, and flags a route that does not exist", () => {
    const ok = run(`function a() { const body = { marketplace: "X", period_start: "a", period_end: "b", as_of_date: "c" }; apiFetch("/api/v1/cfo/cash-reconciliation", t, { method: "POST", body: JSON.stringify(body) }); }
      function b() { const body = { nonsense: 1 }; return body; }`);
    expect(ok[0].problems).toEqual([]);
    expect(run(`apiFetch("/api/v1/cfo/nope", t, { method: "POST", body: JSON.stringify({}) });`)[0].problems.join(" ")).toContain("not a route");
  });
});
