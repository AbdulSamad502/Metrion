import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "globals.css"), "utf8");
const rulesFor = (selector: string): string[] => [...css.matchAll(new RegExp(`(?:^|\\n)${selector.replace(/[.[\]"=]/g, "\\$&")}\\s*\\{([^}]*)\\}`, "g"))].map((m) => m[1]);

describe("surfaces that look right in both themes", () => {
  it("a closed drawer casts no shadow (off-screen, a shadow shows as a grey strip on the light theme's right edge)", () => {
    const base = rulesFor(".mt-drawer-panel");
    expect(base.length).toBeGreaterThan(0);
    expect(base[base.length - 1]).toMatch(/box-shadow:\s*none/);
    expect(rulesFor('.mt-drawer-panel[data-open="true"]').some((r) => /box-shadow:\s*-?\d+px/.test(r))).toBe(true);
  });

  it("the Agents page's pure-black surfaces apply to the dark theme only", () => {
    expect(css).toMatch(/:root:not\(\[data-theme="light"\]\) \.mt-pure-black\s*\{/);
    expect(css).not.toMatch(/\n\.mt-pure-black\s*\{/);
  });
});
