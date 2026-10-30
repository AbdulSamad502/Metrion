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

describe("the brand mark on a light surface", () => {
  it("swaps to the transparent light mark by CSS only, leaving the dark mark untouched in the dark theme", () => {
    expect(css).toMatch(/\.mt-brand-mark--light\s*\{\s*display:\s*none/);
    expect(css).toMatch(/:root\[data-theme="light"\] \.mt-brand-mark--dark\s*\{\s*display:\s*none/);
    expect(css).toMatch(/:root\[data-theme="light"\] \.mt-brand-mark--light\s*\{\s*display:\s*block/);
  });
  it("ships a transparent light mark (a PNG with an alpha channel), distinct from the opaque dark one", () => {
    const png = (f: string) => readFileSync(join(process.cwd(), "public", f));
    const colourType = (b: Buffer) => b[25]; // IHDR colour type: 6 = RGBA
    expect(colourType(png("metrion-mark-light.png"))).toBe(6);
    expect(png("metrion-mark-light.png").equals(png("metrion-mark.png"))).toBe(false);
  });
});

describe("tab strip", () => {
  it("fades only the edge that has more tabs", () => {
    expect(css).toMatch(/\.mt-tabs\[data-more-end="true"\]\s*\{[^}]*mask-image/);
    expect(css).toMatch(/\.mt-tabs\[data-more-start="true"\]\[data-more-end="true"\]\s*\{[^}]*mask-image/);
  });
});
