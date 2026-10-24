import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "app", "globals.css"), "utf8");
const block = css.slice(css.indexOf(':root[data-theme="light"] {'));
const light = block.slice(0, block.indexOf("}"));
const rgb = (name: string): [number, number, number] => {
  const m = light.match(new RegExp(`--${name}: *#([0-9a-fA-F]{6})`));
  if (!m) throw new Error(`light token --${name} not found`);
  const h = m[1];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
};
const lin = (v: number) => ((v /= 255) <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
const lum = (c: number[]) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
const ratio = (a: number[], b: number[]) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);

// The darkest ground text can sit on in light: the page base (cards are lighter still).
const ground = rgb("bg-base");

const rgba = (name: string): [number, number, number, number] => {
  const m = light.match(new RegExp(`--${name}: *rgba\\((\\d+), *(\\d+), *(\\d+), *([\\d.]+)\\)`));
  if (!m) throw new Error(`light token --${name} not found`);
  return [Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4])];
};
const over = (top: number[], a: number, under: number[]) => top.map((v, i) => v * a + under[i] * (1 - a));

describe("light theme: status and secondary text on their own tinted backgrounds (badges, chips, pills)", () => {
  const surfaces: [string, number[]][] = [["the page", rgb("bg-base")], ["a white card", [255, 255, 255]]];
  const pairs: [string, string][] = [["accent", "accent-fill-default"], ["warning", "warning-fill"], ["negative", "negative-fill"], ["info", "info-fill"], ["text-inactive", "fill-hover"], ["text-5", "fill-hover"], ["text-6", "fill-hover"]];
  for (const [fg, fill] of pairs) {
    for (const [where, under] of surfaces) {
      it(`--${fg} on --${fill} over ${where} is at least 4.5:1`, () => {
        const f = rgba(fill);
        expect(ratio(rgb(fg), over(f.slice(0, 3), f[3], under))).toBeGreaterThanOrEqual(4.5);
      });
    }
  }
});

describe("light theme keeps WCAG AA contrast", () => {
  for (const name of ["text-1", "text-2", "text-3", "text-4", "text-5", "text-6", "text-inactive", "accent", "warning", "negative", "info", "text-mint"]) {
    it(`--${name} is at least 4.5:1 on the page base`, () => {
      expect(ratio(rgb(name), ground)).toBeGreaterThanOrEqual(4.5);
    });
  }
  it("text on a filled accent button is at least 4.5:1", () => {
    expect(ratio(rgb("accent-on-fill"), rgb("accent"))).toBeGreaterThanOrEqual(4.5);
  });
  it("overrides every text token the dark theme defines, so none falls through to a dark-theme light colour", () => {
    for (const n of ["text-1", "text-2", "text-3", "text-4", "text-5", "text-6", "text-7", "text-8"]) expect(light).toContain(`--${n}:`);
  });
});
