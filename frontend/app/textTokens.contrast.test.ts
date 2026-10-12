import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "globals.css"), "utf8");
const token = (name: string): [number, number, number] => {
  const m = css.match(new RegExp(`--${name}: *#([0-9a-fA-F]{6})`));
  if (!m) throw new Error(`token --${name} not found`);
  const h = m[1];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
};
const lin = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
const lum = (c: number[]) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
const ratio = (a: number[], b: number[]) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
const over = (top: number[], alpha: number, under: number[]) => top.map((v, i) => v * alpha + under[i] * (1 - alpha));

// The lightest surface text sits on EVERYWHERE, built from the real layers: the page base, a glass card (white 3.5%) and, inside the agent canvas, a
// dot of its grid (white 3.5%). The app surface's green glow is deliberately not stacked here: it only peaks in one corner, so it is position-dependent
// and was measured in the browser at the text's real position (worst case 4.5-5.9:1 on every route, desktop and mobile).
const base = token("bg-base");
const worstBackdrop = over([255, 255, 255], 0.035, over([255, 255, 255], 0.035, base));

describe("text tokens keep their contrast on the lightest surface", () => {
  for (const name of ["text-1", "text-2", "text-3", "text-4", "text-5", "text-6"]) {
    it(`--${name} is at least 4.5:1 (WCAG AA, normal text)`, () => {
      expect(ratio(token(name), worstBackdrop)).toBeGreaterThanOrEqual(4.5);
    });
  }
});
