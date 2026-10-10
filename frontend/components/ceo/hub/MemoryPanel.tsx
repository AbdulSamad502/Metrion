"use client";

import { Icon } from "@/components/ui/Icon";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { MemoryItem } from "@/lib/ceo";

const OWNER_NAMES: Record<string, string> = { PI: "Product Intelligence", CFO: "The CFO", CMO: "The CMO", CI: "Competitor Intelligence", CEO: "The CEO" };

/** Shared items first, then each agent's own, in a fixed order. Grouping only: nothing is changed or computed. */
function groupByOwner(items: MemoryItem[]): [string, MemoryItem[]][] {
  const order = ["SHARED", "CEO", "PI", "CFO", "CMO", "CI"];
  const by = new Map<string, MemoryItem[]>();
  for (const m of items) {
    const k = m.shared ? "SHARED" : m.agent;
    by.set(k, [...(by.get(k) ?? []), m]);
  }
  const rank = (k: string) => (order.indexOf(k) < 0 ? 99 : order.indexOf(k));
  return [...by.entries()].sort((a, b) => rank(a[0]) - rank(b[0]));
}

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
        <div className="flex flex-col gap-3">
          {groupByOwner(items).map(([owner, rows]) => (
            <div key={owner} data-testid={`memory-group-${owner}`}>
              <h4 className="m-0 mb-1 t-meta font-semibold" style={{ color: "var(--text-4)" }}>{owner === "SHARED" ? "Shared by every agent" : `${OWNER_NAMES[owner] ?? owner} keeps privately`}</h4>
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
          {rows.map((m) => (
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
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
