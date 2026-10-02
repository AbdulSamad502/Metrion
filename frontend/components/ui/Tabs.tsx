"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";

export type TabItem = { id: string; label: string; count?: number | null; disabled?: boolean };

/** Accessible tab strip (WAI-ARIA tabs pattern): roving tabindex, Left/Right/Home/End keys,
 * `aria-selected`, and a matching `TabPanel`. Controlled — the page owns which tab is active,
 * so deep links / sub-navigation stay possible. */
export function Tabs({
  tabs,
  active,
  onChange,
  label,
  idPrefix = "tab",
}: {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
  label: string;
  idPrefix?: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const enabled = tabs.filter((t) => !t.disabled);

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
    <div role="tablist" aria-label={label} onKeyDown={onKeyDown} className="mt-tabs">
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
            aria-controls={`${idPrefix}-panel-${t.id}`}
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
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-${id}`} tabIndex={0} className="mt-fade-up outline-none">
      {children}
    </div>
  );
}
