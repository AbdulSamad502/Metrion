import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRef } from "react";
import { useSurfaceSheen } from "@/lib/useSurfaceSheen";

function Surface({ big = false }: { big?: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useSurfaceSheen(ref);
  return (
    <div ref={ref} data-testid="root">
      <div className="mt-dash-card" data-testid="card" data-big={big}>card</div>
      <div className="mt-dash-card mt-dash-card--locked" data-testid="locked">locked</div>
      <p data-testid="plain">text</p>
    </div>
  );
}

const move = (el: Element, x = 20, y = 10) => act(() => { el.dispatchEvent(new MouseEvent("pointermove", { bubbles: true, clientX: x, clientY: y })); });
const media = (matches: Record<string, boolean>) => vi.stubGlobal("matchMedia", (q: string) => ({ matches: !!matches[q], media: q, addEventListener() {}, removeEventListener() {} }));

beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { cb(0); return 1; });
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
  media({});
});
afterEach(() => vi.unstubAllGlobals());

describe("useSurfaceSheen", () => {
  it("lights the card under the mouse with its cursor position, and clears it when the mouse leaves the card", () => {
    const { getByTestId } = render(<Surface />);
    const card = getByTestId("card");
    vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON() {} });
    move(card, 50, 25);
    expect(card).toHaveAttribute("data-sheen");
    expect(card.style.getPropertyValue("--mx")).toBe("25.0%");
    expect(card.style.getPropertyValue("--my")).toBe("25.0%");
    move(getByTestId("plain"));
    expect(card).not.toHaveAttribute("data-sheen");
    expect(card.style.getPropertyValue("--mx")).toBe("");
  });

  it("ignores locked cards and containers larger than a card", () => {
    const { getByTestId } = render(<Surface />);
    move(getByTestId("locked"));
    expect(getByTestId("locked")).not.toHaveAttribute("data-sheen");
    const card = getByTestId("card");
    vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 900, height: 700, right: 900, bottom: 700, x: 0, y: 0, toJSON() {} });
    move(card);
    expect(card).not.toHaveAttribute("data-sheen");
  });

  it("does nothing when motion is reduced or the device cannot hover", () => {
    for (const q of ["(prefers-reduced-motion: reduce)", "(hover: none)"]) {
      media({ [q]: true });
      const { getByTestId, unmount } = render(<Surface />);
      move(getByTestId("card"));
      expect(getByTestId("card")).not.toHaveAttribute("data-sheen");
      unmount();
    }
  });

  it("leaves no listeners or marks behind when the shell unmounts", () => {
    const { getByTestId, unmount } = render(<Surface />);
    const card = getByTestId("card");
    vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON() {} });
    move(card);
    expect(card).toHaveAttribute("data-sheen");
    unmount();
    expect(card).not.toHaveAttribute("data-sheen");
  });
});

describe("a shell that renders a loading state first", () => {
  function LateSurface({ ready }: { ready: boolean }) {
    const ref = useRef<HTMLDivElement | null>(null);
    useSurfaceSheen(ref, ready);
    if (!ready) return <div role="status">Loading…</div>;
    return (
      <div ref={ref}>
        <div className="mt-dash-card" data-testid="card">card</div>
      </div>
    );
  }

  it("attaches once the surface exists (the listener was never added when the first effect run found no element)", () => {
    const { rerender, getByTestId } = render(<LateSurface ready={false} />);
    rerender(<LateSurface ready />);
    const card = getByTestId("card");
    vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON() {} });
    move(card, 50, 25);
    expect(card).toHaveAttribute("data-sheen");
  });
});
