import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// jsdom applies no print CSS, so these tests pin the STYLESHEET TEXT only. The real rendering was checked separately with Chromium's page.pdf() (see the Task 5A report).
const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
const print = css.slice(css.indexOf("@media print"));

describe("print stylesheet scope", () => {
  it("hides the page only when it has a calculator print area, so every other page (the PI report) prints normally", () => {
    expect(print).toMatch(/:where\(body:has\(\.mt-print-area\)\) \* \{ visibility: hidden; \}/);
    expect(print).not.toMatch(/(^|[\s{;])body \* \{ visibility: hidden; \}/); // the old unconditional rule
  });

  it("still makes the print area visible with a rule that out-ranks the (zero-specificity) hiding rule", () => {
    expect(print).toMatch(/\.mt-print-area, \.mt-print-area \* \{ visibility: visible; \}/);
    expect(print).toMatch(/\.mt-no-print[^}]*display: none !important/);
  });
});
