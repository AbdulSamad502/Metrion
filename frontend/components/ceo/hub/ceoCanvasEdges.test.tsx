import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentCanvas } from "@/components/ceo/hub/AgentCanvas";
import type { CanvasNode } from "@/lib/ceoModel";

const node = (code: CanvasNode["code"], state: CanvasNode["state"]): CanvasNode =>
  ({ code, name: code, state, canToggle: state === "ATTACHED" || state === "DETACHED", chatActions: 1, result: { headline: null, headlineAt: null, noCompleteResult: false, newer: null } }) as unknown as CanvasNode;

describe("canvas edges", () => {
  const nodes = [node("CI", "ATTACHED"), node("CFO", "DETACHED"), node("PI", "LOCKED"), node("CMO", "ATTACHED")];

  it("every edge ends exactly at its specialist's port and starts at the CEO port", () => {
    render(<AgentCanvas nodes={nodes} busy={null} onToggle={() => {}} />);
    for (const n of nodes) {
      const d = screen.getByTestId(`edge-${n.code}`).getAttribute("d") ?? "";
      const nums = d.match(/-?\d+(\.\d+)?/g)!.map(Number);
      const port = screen.getByTestId(`port-${n.code}`).style.left;
      expect(nums.slice(0, 2)).toEqual([50, 0]);
      expect(`${nums[nums.length - 2]}%`).toBe(port);
      expect(nums[nums.length - 1]).toBe(100);
    }
    expect(screen.getByTestId("port-ceo").style.left).toBe("50%");
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
