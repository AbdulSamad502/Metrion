import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** calculator.md N-AC1: the Profit Calculator page only collects typed numbers and renders what Brain 1 returned. None of its source may contain
 * number parsing, rounding, locale/currency formatting or float helpers; money is handled as integer STRINGS by plain string operations. */
const ROOT = join(__dirname, "..");
const files = [
  "lib/pnlText.ts", "lib/pnlScenario.ts", "lib/pnlFeeFields.ts",
  ...readdirSync(join(ROOT, "components/pnl")).filter((f) => /\.tsx$/.test(f)).map((f) => `components/pnl/${f}`),
];
const BANNED = [/toFixed/, /parseFloat/, /parseInt/, /\bNumber\(/, /Math\./, /Intl\.NumberFormat/, /toLocaleString/, /\bBigInt\b/, /\bDecimal\b/, /\bunary \+/];

describe("the Profit Calculator does no money math in the browser", () => {
  for (const file of files) {
    it(file, () => {
      const src = readFileSync(join(ROOT, file), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
      for (const banned of BANNED) expect(src, `${file} contains ${banned}`).not.toMatch(banned);
    });
  }
  it("never labels a figure as a verified result or cites an engine result reference", () => {
    for (const file of files.filter((x) => x.startsWith("components/"))) {
      const src = readFileSync(join(ROOT, file), "utf-8");
      expect(src, file).not.toMatch(/engineResultRef|engine_result_ref/);
      expect(src, file).not.toMatch(/Verified/);
    }
  });
});
