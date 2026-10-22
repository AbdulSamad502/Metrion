import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** B4 guard: the CEO Hub renders what the backend decided and computes nothing. None of the hub's source may contain numeric formatting
 * or arithmetic helpers that could derive, round or re-format a figure (the hard rule: LLMs and UIs explain numbers, only the engine
 * computes them), nor a currency literal, nor a made-up score/forecast. Dates are formatted with Date's own methods only. */
const ROOT = join(__dirname, "..");
/** Every non-test source file under a directory, recursively (the CFO 2.0 dashboard has sub-folders). */
const walk = (dir: string): string[] =>
  readdirSync(join(ROOT, dir), { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(`${dir}/${e.name}`) : /\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name) ? [`${dir}/${e.name}`] : [],
  );
const files = [
  "lib/ceo.ts", "lib/ceoModel.ts", "lib/ceoPolling.ts", "lib/useCeoHub.ts",
  ...readdirSync(join(ROOT, "components/ceo/hub")).filter((f) => /\.tsx$/.test(f) && !f.endsWith(".test.tsx")).map((f) => `components/ceo/hub/${f}`),
  // CFO 2.0 dashboard (docs/specs/cfo-dashboard-implementation.md AC-DI1): renders the server's display strings and nothing else.
  ...walk("lib/cfoV2"), ...walk("components/cfo/v2"),
];

describe("the CEO Hub and the CFO 2.0 dashboard do no money math", () => {
  for (const file of files) {
    it(file, () => {
      const src = readFileSync(join(ROOT, file), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
      for (const banned of [/toFixed/, /parseFloat/, /parseInt/, /Number\(/, /Math\.(round|floor|ceil|trunc)/, /Intl\.NumberFormat/, /toLocaleString\(\s*["'][a-z-]+["']\s*,\s*\{[^}]*currency/, /₹/, /health ?score/i, /uplift/i, /projected/i]) {
        expect(src, `${file} contains ${banned}`).not.toMatch(banned);
      }
    });
  }
});
