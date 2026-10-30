import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TabPanel } from "@/components/ui/Tabs";

describe("TabPanel", () => {
  it("is a keyboard stop that carries the visible focus ring", () => {
    render(<TabPanel id="a" active="a" idPrefix="t">content</TabPanel>);
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("tabindex", "0");
    expect(panel).toHaveClass("mt-focus");
  });
});

import { fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, vi } from "vitest";
import { Tabs } from "@/components/ui/Tabs";

const TABS = [
  { id: "all", label: "All", count: 4 },
  { id: "alerts", label: "Competitor alerts", count: 2 },
  { id: "requests", label: "Data requests", count: 2 },
];
function Harness({ initial = "all" }: { initial?: string }) {
  const [active, setActive] = useState(initial);
  return <Tabs tabs={TABS} active={active} onChange={setActive} label="Types" idPrefix="t" />;
}
/** jsdom has no layout, so the strip's geometry is set by hand: a 358px strip holding 520px of tabs. */
function narrowStrip(scrollLeft = 0) {
  const box = screen.getByRole("tablist");
  let left = scrollLeft;
  Object.defineProperty(box, "clientWidth", { value: 358, configurable: true });
  Object.defineProperty(box, "scrollWidth", { value: 520, configurable: true });
  Object.defineProperty(box, "scrollLeft", { get: () => left, set: (v) => { left = v; }, configurable: true });
  return { box, scroll: (v: number) => { left = v; fireEvent.scroll(box); } };
}

describe("Tabs on a narrow screen", () => {
  beforeEach(() => { vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), addEventListener() {}, removeEventListener() {} })); });
  afterEach(() => vi.unstubAllGlobals());

  it("keeps every tab and its count in the accessibility tree, with the count in the name", () => {
    render(<Harness />);
    expect(screen.getByRole("tab", { name: /^All\s*4$/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Competitor alerts\s*2/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Data requests\s*2/ })).toBeInTheDocument();
    expect(screen.getByRole("tablist")).toHaveAttribute("aria-label", "Types");
  });

  it("marks the edge that has more tabs, and follows the scroll position", () => {
    render(<Harness />);
    const { box, scroll } = narrowStrip(0);
    fireEvent(window, new Event("resize"));
    expect(box.dataset.moreEnd).toBe("true");
    expect(box.dataset.moreStart).toBe("false");
    scroll(80);
    expect(box.dataset.moreStart).toBe("true");
    expect(box.dataset.moreEnd).toBe("true");
    scroll(162); // the end: 520 - 358
    expect(box.dataset.moreEnd).toBe("false");
    expect(box.dataset.moreStart).toBe("true");
  });

  it("shows no cue when every tab fits", () => {
    render(<Harness />);
    const box = screen.getByRole("tablist");
    Object.defineProperty(box, "clientWidth", { value: 600, configurable: true });
    Object.defineProperty(box, "scrollWidth", { value: 520, configurable: true });
    fireEvent(window, new Event("resize"));
    expect(box.dataset.moreEnd).toBe("false");
    expect(box.dataset.moreStart).toBe("false");
  });

  it("brings a newly selected tab fully into view, instantly under reduced motion", async () => {
    render(<Harness />);
    const { box } = narrowStrip(0);
    const last = screen.getByRole("tab", { name: /Data requests/ });
    Object.defineProperty(last, "offsetLeft", { value: 400, configurable: true });
    Object.defineProperty(last, "offsetWidth", { value: 120, configurable: true });
    const scrollTo = vi.fn();
    box.scrollTo = scrollTo as unknown as typeof box.scrollTo;
    await userEvent.click(last);
    expect(scrollTo).toHaveBeenCalledWith({ left: 400 + 120 + 32 - 358, behavior: "auto" }); // clear of the fade, no smooth motion
  });

  it("scrolls smoothly when motion is allowed, and not at all when the tab is already in view", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    render(<Harness />);
    const { box } = narrowStrip(0);
    const mid = screen.getByRole("tab", { name: /Competitor alerts/ });
    Object.defineProperty(mid, "offsetLeft", { value: 60, configurable: true });
    Object.defineProperty(mid, "offsetWidth", { value: 120, configurable: true });
    const last = screen.getByRole("tab", { name: /Data requests/ });
    Object.defineProperty(last, "offsetLeft", { value: 400, configurable: true });
    Object.defineProperty(last, "offsetWidth", { value: 120, configurable: true });
    const scrollTo = vi.fn();
    box.scrollTo = scrollTo as unknown as typeof box.scrollTo;
    await userEvent.click(mid);
    expect(scrollTo).not.toHaveBeenCalled(); // 60..180 is inside 0..358 with room to spare
    await userEvent.click(last);
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: "smooth" }));
  });

  it("still moves between tabs with the arrow keys and keeps roving focus", async () => {
    render(<Harness />);
    narrowStrip(0);
    screen.getByRole("tab", { name: /^All/ }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: /Competitor alerts/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Competitor alerts/ })).toHaveFocus();
    expect(screen.getByRole("tab", { name: /^All/ })).toHaveAttribute("tabindex", "-1");
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("tab", { name: /Data requests/ })).toHaveFocus();
  });

  it("works where ResizeObserver does not exist", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    expect(() => render(<Harness />)).not.toThrow();
  });
});
