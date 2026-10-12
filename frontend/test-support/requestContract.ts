/** Checks every API request a frontend test sends against what the backend really accepts.
 *
 * `requestContract.json` is exported from the backend's OpenAPI document by `backend/scripts/export_request_contract.py` (a backend test fails when it is stale).
 * A request is rejected here when: its method + path is not a served route, its JSON body breaks the route's schema (a missing required field, a wrong type, a value
 * outside an enum, a field the backend does not know), or its query string uses a parameter the route does not declare / omits a required one. Responses are not
 * checked: the API does not describe them, so they are covered by the per-endpoint response contracts instead (`backend/tests/contract`). */
import contract from "./requestContract.json";

type Schema = {
  $ref?: string; type?: string | string[]; properties?: Record<string, Schema>; required?: string[]; items?: Schema; enum?: unknown[]; const?: unknown;
  anyOf?: Schema[]; oneOf?: Schema[]; allOf?: Schema[]; additionalProperties?: boolean | Schema; pattern?: string; minLength?: number; maxLength?: number;
  minItems?: number; maxItems?: number; minimum?: number; maximum?: number;
};
type Route = { body?: Schema; multipart?: boolean; query: string[]; requiredQuery: string[] };
const routes = contract.routes as unknown as Record<string, Route>;
const schemas = contract.schemas as unknown as Record<string, Schema>;

const SPECIAL = /[.*+?^$()|[\]\\]/g;
const templates = Object.keys(routes).map((key) => {
  const [method, path] = key.split(" ");
  return { key, method, re: new RegExp("^" + path.replace(SPECIAL, "\\$&").replace(/\{[^}]+\}/g, "[^/]+") + "/?$") };
});

export function findRoute(method: string, path: string): { key: string; route: Route } | null {
  const hit = templates.find((t) => t.method === method.toUpperCase() && t.re.test(path));
  return hit ? { key: hit.key, route: routes[hit.key] } : null;
}

const kind = (v: unknown): string => (v === null ? "null" : Array.isArray(v) ? "array" : Number.isInteger(v) ? "integer" : typeof v);

/** The problems with `value` against `schema`, as readable paths; empty when it conforms. */
export function validate(value: unknown, schema: Schema | undefined, where = "body"): string[] {
  if (!schema) return [];
  if (schema.$ref) return validate(value, schemas[schema.$ref.split("/").pop() as string], where);
  if (schema.allOf) return schema.allOf.flatMap((s) => validate(value, s, where));
  for (const alts of [schema.anyOf, schema.oneOf]) {
    if (alts) return alts.some((s) => validate(value, s, where).length === 0) ? [] : [`${where}: matches none of the allowed shapes (got ${kind(value)})`];
  }
  if (schema.const !== undefined && value !== schema.const) return [`${where}: must be ${JSON.stringify(schema.const)}`];
  if (schema.enum && !schema.enum.includes(value)) return [`${where}: ${JSON.stringify(value)} is not one of ${JSON.stringify(schema.enum)}`];
  const types = schema.type === undefined ? null : Array.isArray(schema.type) ? schema.type : [schema.type];
  if (types) {
    const k = kind(value);
    const ok = types.some((t) => t === k || (t === "number" && k === "integer"));
    if (!ok) return [`${where}: expected ${types.join("|")}, got ${k}`];
  }
  const problems: string[] = [];
  if (typeof value === "string") {
    if (schema.minLength !== undefined && value.length < schema.minLength) problems.push(`${where}: shorter than ${schema.minLength}`);
    if (schema.maxLength !== undefined && value.length > schema.maxLength) problems.push(`${where}: longer than ${schema.maxLength}`);
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) problems.push(`${where}: does not match ${schema.pattern}`);
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) problems.push(`${where}: below ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) problems.push(`${where}: above ${schema.maximum}`);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) problems.push(`${where}: fewer than ${schema.minItems} items`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) problems.push(`${where}: more than ${schema.maxItems} items`);
    value.forEach((item, i) => problems.push(...validate(item, schema.items, `${where}[${i}]`)));
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>;
    const props = schema.properties ?? {};
    for (const r of schema.required ?? []) if (!(r in obj)) problems.push(`${where}: missing required "${r}"`);
    for (const [k, v] of Object.entries(obj)) {
      if (k in props) problems.push(...validate(v, props[k], `${where}.${k}`));
      else if (schema.additionalProperties && typeof schema.additionalProperties === "object") problems.push(...validate(v, schema.additionalProperties, `${where}.${k}`));
      else if (schema.properties && schema.additionalProperties !== true) problems.push(`${where}: the backend has no field "${k}"`);
    }
  }
  return problems;
}

/** Problems with one request; empty when the backend would accept its shape. */
export function checkRequest(method: string, url: string, body: unknown): string[] {
  const { pathname, searchParams } = new URL(url, "http://contract.test");
  if (!pathname.startsWith("/api/v1")) return [];
  const hit = findRoute(method, pathname);
  if (!hit) return [`${method.toUpperCase()} ${pathname} is not a route the backend serves`];
  const problems: string[] = [];
  const { route } = hit;
  for (const q of searchParams.keys()) if (!route.query.includes(q)) problems.push(`query "${q}" is not a parameter of ${hit.key}`);
  for (const q of route.requiredQuery) if (!searchParams.has(q)) problems.push(`query "${q}" is required by ${hit.key}`);
  if (route.multipart) return problems; // a file upload: the form fields are checked by the upload tests
  if (route.body) {
    let parsed: unknown = undefined;
    if (typeof body === "string") {
      try {
        parsed = JSON.parse(body);
      } catch {
        return [...problems, `${hit.key}: the body is not JSON`];
      }
    }
    if (parsed === undefined) problems.push(`${hit.key}: the backend requires a JSON body`);
    else problems.push(...validate(parsed, route.body).map((p) => `${hit.key} ${p}`));
  } else if (typeof body === "string" && body !== "" && body !== "{}") {
    problems.push(`${hit.key}: the backend takes no body`);
  }
  return problems;
}
