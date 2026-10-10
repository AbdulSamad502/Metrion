"use client";

import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { MemoryItem } from "@/lib/ceo";

/** What the agents remember about this business, exactly as the seller gave it. Nothing is hidden and everything can be forgotten here. Shared items are visible to
 * every agent; the rest belong to one agent. The values are shown verbatim: this panel never computes or rewrites anything. */
export function MemoryPanel({ items, onForget }: { items: MemoryItem[]; onForget: (id: string) => void }) {
  return (
    <section aria-labelledby="ceo-memory" data-testid="memory-panel">
      <h3 id="ceo-memory" className="mb-2 mt-eyebrow">What I remember</h3>
      {items.length === 0 ? (
        <p className="m-0 t-body-sm" style={{ color: "var(--text-5)" }} data-testid="memory-empty">
          Nothing yet. Tell me about your business, for example “my business name is …” or “my niche is …”, and I will remember it for next time.
        </p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {items.map((m) => (
            <li key={m.id} data-testid={`memory-${m.id}`} className="flex items-center justify-between gap-2 rounded-lg px-3 py-2" style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-card)" }}>
              <span className="min-w-0">
                <span className="block truncate t-meta" style={{ color: "var(--text-5)" }}>{m.label}</span>
                <span className="block truncate t-body-sm font-semibold" style={{ color: "var(--text-1)" }}>{m.value}</span>
              </span>
              <span className="flex flex-shrink-0 items-center gap-2">
                <StatusBadge tone={m.shared ? "accent" : "neutral"}>{m.shared ? "Shared" : m.agent}</StatusBadge>
                <button type="button" aria-label={`Forget ${m.label}`} onClick={() => onForget(m.id)} className="mt-btn mt-focus rounded-lg p-1.5" style={{ color: "var(--text-4)" }}>
                  <Icon name="close" size={14} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
