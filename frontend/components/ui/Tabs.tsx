"use client";

import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

export type TabItem = { id: string; label: string; count?: number | null; disabled?: boolean };

/** Accessible tab strip (WAI-ARIA tabs pattern): roving tabindex, Left/Right/Home/End keys,
 * `aria-selected`, and a matching `TabPanel`. Controlled — the page owns which tab is active,
 * so deep links / sub-navigation stay possible.
 *
 * When the tabs do not fit (a narrow phone), the strip scrolls sideways and the edge that has more tabs fades out, so a cut-off tab reads as "more this
 * way" and not as a layout fault. The fade is set from the scroll position straight on the element (`data-more-start` / `data-more-end`), with no
 * re-render. Changing the active tab scrolls it fully into view. Every tab and count stays in the DOM and in the accessibility tree. */
const EDGE = 32; // px kept clear of the fade around the active tab
export function Tabs({
  tabs,
  active,
  onChange,
  label,
  idPrefix = "tab",
  panels = true,
}: {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
  label: string;
  idPrefix?: string;
  /** false when the tabs filter one view and no separate TabPanel exists, so no tab points at a panel that is not there */
  panels?: boolean;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const listRef = useRef<HTMLDivElement | null>(null);
  const enabled = tabs.filter((t) => !t.disabled);

  // Which edges have more tabs beyond them. Written to the element, not to state: it follows the scroll position and must not re-render the page.
  const markEdges = () => {
    const box = listRef.current;
    if (!box) return;
    const max = box.scrollWidth - box.clientWidth;
    box.dataset.moreStart = String(box.scrollLeft > 1);
    box.dataset.moreEnd = String(max > 1 && box.scrollLeft < max - 1);
  };
  const tabKey = tabs.map((t) => `${t.id}:${t.label}:${t.count ?? ""}`).join("|"); // a changed label or count can change the width
  useEffect(() => {
    markEdges();
    const box = listRef.current;
    if (!box) return;
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(markEdges) : null;
    ro?.observe(box);
    window.addEventListener("resize", markEdges);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", markEdges);
    };
  }, [tabKey]);

  // The active tab is brought fully into view, clear of the fade (instantly when the visitor prefers reduced motion).
  useEffect(() => {
    const box = listRef.current;
    const el = refs.current[active];
    if (!box || !el) return;
    const left = el.offsetLeft - EDGE;
    const right = el.offsetLeft + el.offsetWidth + EDGE - box.clientWidth;
    const to = box.scrollLeft > left ? left : box.scrollLeft < right ? right : null;
    if (to === null) return;
    const reduced = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (typeof box.scrollTo === "function") box.scrollTo({ left: Math.max(0, to), behavior: reduced ? "auto" : "smooth" });
    else box.scrollLeft = Math.max(0, to);
  }, [active]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = enabled.findIndex((t) => t.id === active);
    let next: number | null = null;
    if (e.key === "ArrowRight") next = (i + 1) % enabled.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + enabled.length) % enabled.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = enabled.length - 1;
    if (next === null) return;
    e.preventDefault();
    const target = enabled[next];
    onChange(target.id);
    refs.current[target.id]?.focus();
  };

  return (
    <div ref={listRef} role="tablist" aria-label={label} onKeyDown={onKeyDown} onScroll={markEdges} className="mt-tabs">
      {tabs.map((t) => {
        const selected = t.id === active;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[t.id] = el;
            }}
            id={`${idPrefix}-${t.id}`}
            role="tab"
            type="button"
            aria-selected={selected}
            aria-controls={panels ? `${idPrefix}-panel-${t.id}` : undefined}
            tabIndex={selected ? 0 : -1}
            disabled={t.disabled}
            onClick={() => onChange(t.id)}
            className="mt-tab mt-focus"
          >
            {t.label}
            {t.count != null && t.count > 0 && <span className="mt-tab__count">{t.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ id, active, idPrefix = "tab", children }: { id: string; active: string; idPrefix?: string; children: ReactNode }) {
  if (id !== active) return null;
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-${id}`} tabIndex={0} className="mt-fade-up mt-focus rounded-lg outline-none">
      {children}
    </div>
  );
}
