import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentCanvas } from "@/components/ceo/hub/AgentCanvas";
import type { CanvasNode } from "@/lib/ceoModel";

const node = (code: CanvasNode["code"], state: CanvasNode["state"]): CanvasNode =>
  ({ code, name: code, state, canToggle: state === "ATTACHED" || state === "DETACHED", chatActions: 1, result: { headline: null, headlineAt: null, noCompleteResult: false, newer: null } }) as unknown as CanvasNode;

describe("canvas edges", () => {
  beforeEach(() => window.localStorage.clear());
  const nodes = [node("CI", "ATTACHED"), node("CFO", "DETACHED"), node("PI", "LOCKED"), node("CMO", "ATTACHED")];

  it("every edge runs from the CEO card's centre to its specialist card's centre", () => {
    render(<AgentCanvas nodes={nodes} busy={null} onToggle={() => {}} />);
    const at = (id: string) => { const el = screen.getByTestId(id); return [parseFloat(el.style.left), parseFloat(el.style.top)]; };
    for (const n of nodes) {
      const d = screen.getByTestId(`edge-${n.code}`).getAttribute("d") ?? "";
      const nums = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
      expect(nums.slice(0, 2)).toEqual(at("ceo-slot"));
      expect(nums.slice(-2)).toEqual(at(`agent-slot-${n.code}`));
    }
    expect(screen.getByTestId("port-ceo").style.left).toBe("50%");
  });

  it("moving a card with the arrow keys moves its wire with it, and the layout can be reset", async () => {
    render(<AgentCanvas nodes={nodes} busy={null} onToggle={() => {}} />);
    const slot = screen.getByTestId("agent-slot-CI");
    const before = parseFloat(slot.style.left);
    // jsdom has no layout: report the slot as absolutely placed, as it is in the wide layout
    const real = window.getComputedStyle.bind(window);
    const spy = vi.spyOn(window, "getComputedStyle").mockImplementation((el, pseudo) => { const cs = real(el, pseudo); return el === slot ? ({ ...cs, position: "absolute" } as CSSStyleDeclaration) : cs; });
    slot.focus();
    await userEvent.setup().keyboard("{ArrowRight}");
    spy.mockRestore();
    expect(parseFloat(slot.style.left)).toBeGreaterThan(before);
    const d = screen.getByTestId("edge-CI").getAttribute("d") ?? "";
    expect(Number(d.match(/-?\d+(\.\d+)?/g)!.slice(-2)[0])).toBeCloseTo(parseFloat(slot.style.left));
    await userEvent.setup().click(screen.getByTestId("reset-layout"));
    expect(parseFloat(screen.getByTestId("agent-slot-CI").style.left)).toBe(before);
  });

  it("draws one edge per specialist and nothing else, with removed and locked ones dim", () => {
    render(<AgentCanvas nodes={nodes} busy={null} onToggle={() => {}} />);
    expect(screen.getByTestId("edges").querySelectorAll("path")).toHaveLength(4);
    expect(screen.getByTestId("edge-CI").getAttribute("stroke-dasharray")).toBe("4 4"); // connected: bright, glowing, short dashes (the design draws every wire dashed)
    expect(screen.getByTestId("edge-CI").getAttribute("stroke")).toBe("var(--accent)");
    expect(screen.getByTestId("edge-CFO").getAttribute("stroke")).not.toBe("var(--accent)"); // removed / locked stay visibly dim
    expect(screen.getByTestId("edge-CFO").getAttribute("stroke-dasharray")).toBe("5 5");
    expect(screen.getByTestId("edge-PI").getAttribute("stroke-dasharray")).toBe("5 5");
  });

  it("a running specialist's edge is animated", () => {
    const { container } = render(<AgentCanvas nodes={nodes} busy={null} onToggle={() => {}} working={{ CI: "Working · margin check" }} />);
    expect(container.querySelector('[data-testid="edge-CI"] animate')).not.toBeNull();
  });
});
