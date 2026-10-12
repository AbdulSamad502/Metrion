import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { appendFileSync } from "node:fs";
import { checkRequest, findRoute } from "./requestContract";

afterEach(() => {
  cleanup();
  sessionStorage.clear(); // nothing a test remembers (the open CEO conversation) may leak into the next one
});

// Every fetch a test stubs is wrapped so that a request the real backend would refuse (an unknown route, a body that breaks its schema, an undeclared
// query parameter) fails the test, instead of passing against a fake that accepts anything. The mock itself is untouched: a Proxy forwards everything.
const stubGlobal = vi.stubGlobal.bind(vi);
vi.stubGlobal = ((name: string, value: unknown) => {
  if (name !== "fetch" || typeof value !== "function") return stubGlobal(name, value);
  return stubGlobal(
    name,
    new Proxy(value as (...a: unknown[]) => unknown, {
      apply(target, thisArg, args: unknown[]) {
        const [input, init] = args as [RequestInfo | URL, RequestInit | undefined];
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
        const method = init?.method ?? "GET";
        const problems = checkRequest(method, url, init?.body);
        // CONTRACT_LOG=file records which backend routes the tests exercised (a coverage report, not a check)
        if (process.env.CONTRACT_LOG) appendFileSync(process.env.CONTRACT_LOG, `${findRoute(method, new URL(url, "http://x").pathname)?.key ?? "UNMATCHED " + url}
`);
        if (problems.length > 0) return Promise.reject(new Error(`CONTRACT: ${problems.join("; ")}`));
        return Reflect.apply(target, thisArg, args);
      },
    }),
  );
}) as typeof vi.stubGlobal;
