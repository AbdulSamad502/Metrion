import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "globals.css"), "utf8");
const MARK = "PREMIUM APP LAYER";
const layerStart = css.lastIndexOf("/*", css.indexOf(MARK)); // the layer begins at its header comment
const layerEnd = css.indexOf("END PREMIUM APP LAYER"); // the CEO Hub canvas rules that follow are scoped by their own classes
const layer = css.slice(layerStart, layerEnd).replace(/\/\*[\s\S]*?\*\//g, "");

/** Every rule prelude in the layer (at-rule names and keyframe steps excluded), split into its comma-separated selectors. */
function selectors(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(/([^{}]+)\{/g)) {
    const prelude = m[1].trim();
    if (!prelude || prelude.startsWith("@") || /^(from|to|\d+%)$/.test(prelude)) continue;
    let depth = 0;
    let cur = "";
    for (const ch of prelude) {
      if (ch === "(") depth++;
      if (ch === ")") depth--;
      if (ch === "," && depth === 0) {
        out.push(cur.trim());
        cur = "";
      } else cur += ch;
    }
    out.push(cur.trim());
  }
  return out;
}

describe("the premium app layer cannot reach the landing page or the auth screens", () => {
  it("exists, and every selector in it starts at the authenticated shell root", () => {
    expect(css.indexOf(MARK)).toBeGreaterThan(0);
    const all = selectors(layer);
    expect(all.length).toBeGreaterThan(20);
    const stray = all.filter((s) => !s.startsWith(".mt-app-surface"));
    expect(stray).toEqual([]);
  });

  it("is placed after every landing rule, never uses a landing-only class, and leaves the contrast-corrected text tokens alone", () => {
    for (const landing of [".mt-reveal", ".mt-hover-card", ".mt-glow-panel", ".mt-float", ".mt-orbit", ".mt-tilt", ".mt-cta-glow", ".mt-badge-shimmer"]) {
      expect(layer, landing).not.toContain(landing);
    }
    expect(layer).not.toMatch(/--text-5\s*:/);
    expect(layer).not.toMatch(/--text-6\s*:/);
    expect(css.slice(0, css.indexOf(MARK))).toContain(".mt-reveal"); // the landing rules come first and are untouched by what follows
  });

  it("the shell root class is applied only by the signed-in frame", () => {
    const frame = readFileSync(join(process.cwd(), "components", "dashboard", "ShellFrame.tsx"), "utf8");
    expect(frame).toContain("mt-app-surface");
    for (const file of ["app/page.tsx", "app/(marketing)/layout.tsx"]) expect(readFileSync(join(process.cwd(), file), "utf8")).not.toContain("mt-app-surface");
  });
});
