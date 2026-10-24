import { ApiError } from "@/lib/api";
import { miscRoutes } from "./fixtures/misc";
import { cfoRoutes } from "./fixtures/cfo";
import { ciRoutes } from "./fixtures/ci";
import { cmoRoutes } from "./fixtures/cmo";
import { piRoutes } from "./fixtures/pi";

/** One sample endpoint. `reply` returns the JSON body a real response would carry (same shape as the typed response in `lib/api.ts` and friends).
 * Every figure in a fixture is a fictional sample written by hand, never computed from anything. */
export type DemoRoute = { method: "GET" | "POST" | "PUT" | "DELETE"; match: RegExp; reply: (m: RegExpMatchArray, body: unknown) => unknown };

const ROUTES: DemoRoute[] = [...ciRoutes, ...cfoRoutes, ...piRoutes, ...cmoRoutes, ...miscRoutes];

/** Paths that keep going to the real backend even with sample data on: the CEO Hub's own endpoints (it is never fed sample data), the signed-in
 * session, and the Profit Calculator, which only works out the numbers the seller typed and saves nothing. */
const PASS_THROUGH = [/^\/api\/v1\/ceo\//, /^\/api\/v1\/session(\?|$)/, /^\/api\/v1\/cfo\/pnl-scenario(-compare)?(\?|$)/];

export type DemoOutcome<T> = { handled: true; body: T } | { handled: false };

/** `handled: false` means "use the real backend". Anything else under /api/v1 either gets a sample or fails with a plain message: sample data
 * never leaks a real request, and never pretends a write was saved. */
export function demoRespond<T>(path: string, init?: RequestInit): DemoOutcome<T> {
  if (PASS_THROUGH.some((p) => p.test(path))) return { handled: false };
  const method = (init?.method ?? "GET").toUpperCase();
  const route = ROUTES.find((r) => r.method === method && r.match.test(path));
  if (!route) {
    if (method === "GET") throw new ApiError(404, "This is not part of the sample data.");
    throw new ApiError(400, "Sample data is on: nothing is saved.");
  }
  let body: unknown = undefined;
  try {
    body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
  } catch {
    /* a body that is not JSON is ignored: sample replies never depend on it */
  }
  const m = path.match(route.match) as RegExpMatchArray;
  return { handled: true, body: route.reply(m, body) as T };
}

export function demoRejectsUpload(): never {
  throw new ApiError(400, "Sample data is on: uploads are not accepted and nothing is saved.");
}
