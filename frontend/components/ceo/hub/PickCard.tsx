"use client";

import { useState } from "react";
import type { PickCard as PickCardData } from "@/lib/ceo";

/** The CEO's pick card (owner decision 2026-10-21): check boxes (or radio buttons) the seller ticks, then a button. Used for the categories to search, the search results to track, the
 * tracked competitors, and "which competitor is in this screenshot". It shows only what the backend sent. Pressing a button sends the text its template makes ("{numbers}" -> "1, 3",
 * "{labels}" -> "A and B") exactly as if the seller had typed it, so the same checks run and nothing here changes anything by itself. */
export function PickCard({ card, disabled, onSend }: { card: PickCardData; disabled: boolean; onSend: (text: string) => void }) {
  const [ticked, setTicked] = useState<string[]>([]);
  const single = card.mode === "single";
  const limit = single ? 1 : card.maxPick;
  const full = !single && card.maxPick === 0;
  const atLimit = ticked.length >= limit;
  const chosen = card.items.filter((i) => ticked.includes(i.key));

  const toggle = (key: string) =>
    setTicked((t) => (single ? [key] : t.includes(key) ? t.filter((x) => x !== key) : t.length < limit ? [...t, key] : t));
  const numberOf = (i: PickCardData["items"][number]) => String(i.n ?? i.key);
  const text = (template: string) =>
    template
      .replace("{numbers}", chosen.map(numberOf).sort((a, b) => a.length - b.length || (a < b ? -1 : a > b ? 1 : 0)).join(", "))
      .replace("{labels}", chosen.map((i) => i.label).join(" and "));
  const can = (a: PickCardData["actions"][number]) => !disabled && (a.noPick ? true : chosen.length > 0 && (a.exactly ? chosen.length === a.exactly : true));

  return (
    <div data-testid="pick-card" className="mt-2 flex w-full flex-col gap-3 rounded-2xl px-4 py-3.5" style={{ border: "1px solid var(--accent-border-subtle)", background: "var(--hub-card-bg)" }}>
      <div>
        <div className="t-body font-semibold" style={{ color: "var(--text-2)" }}>{card.title}</div>
        <p className="mt-0.5 t-meta-sm" style={{ color: "var(--text-6)" }} data-testid="pick-subtitle">{card.subtitle}</p>
      </div>
      {card.selectAll && !single && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => setTicked(ticked.length === card.items.length ? [] : card.items.map((i) => i.key))}
          className="mt-focus self-start rounded-md px-2.5 py-1 t-meta font-bold"
          style={{ border: "1px solid var(--accent-border-subtle)", color: "var(--accent)" }}
        >
          {ticked.length === card.items.length ? "Clear all" : "Select all"}
        </button>
      )}
      <ul className="m-0 flex max-h-[420px] list-none flex-col gap-1.5 overflow-y-auto p-0" aria-label={card.title}>
        {card.items.map((it) => {
          const on = ticked.includes(it.key);
          const blocked = disabled || full || (!single && !on && atLimit);
          return (
            <li key={it.key}>
              <label
                className="flex cursor-pointer items-start gap-3 rounded-lg p-2.5"
                style={{ background: on ? "var(--fill-hover)" : "transparent", border: `1px solid ${on ? "var(--accent-border-subtle)" : "var(--border-subtle)"}`, opacity: blocked && !on ? 0.55 : 1 }}
              >
                <input
                  type={single ? "radio" : "checkbox"}
                  name={single ? "pick-card" : undefined}
                  className="mt-1 h-4 w-4 shrink-0"
                  style={{ accentColor: "var(--accent)" }}
                  checked={on}
                  disabled={blocked}
                  onChange={() => toggle(it.key)}
                  aria-label={`${it.n ? `${it.n}. ` : ""}${it.label}`}
                />
                <span className="min-w-0 flex-1">
                  <span className="t-body-sm font-semibold" style={{ color: "var(--text-2)" }}>{it.n ? `${it.n}. ` : ""}{it.label}</span>
                  {(it.marketplace || it.note || it.url) && (
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-2 t-meta-sm" style={{ color: "var(--text-6)" }}>
                      {it.marketplace && <span className="font-semibold" style={{ color: "var(--accent)" }}>{it.marketplace}</span>}
                      {it.note && <span>{it.note}</span>}
                      {it.url && (
                        <a href={it.url} target="_blank" rel="noopener noreferrer" className="mt-focus underline" style={{ color: "var(--text-4)" }} onClick={(e) => e.stopPropagation()}>
                          Open listing
                        </a>
                      )}
                    </span>
                  )}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="t-meta-sm" style={{ color: "var(--text-6)" }} aria-live="polite">{ticked.length}{single ? "" : ` of ${card.maxPick}`} selected</span>
        <div className="flex flex-wrap gap-2">
          {card.actions.map((a, idx) => (
            <button
              key={a.id}
              type="button"
              disabled={!can(a)}
              onClick={() => onSend(text(a.template))}
              className="mt-btn mt-focus rounded-lg px-4 py-2 t-body-sm font-bold"
              style={idx === 0 ? { background: "var(--accent)", color: "var(--accent-on-fill)", opacity: can(a) ? 1 : 0.5 } : { border: "1px solid var(--accent-border-subtle)", color: "var(--accent)", opacity: can(a) ? 1 : 0.5 }}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
