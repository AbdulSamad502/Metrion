"use client";

import { Icon } from "@/components/ui/Icon";
import type { InvestigationSummary } from "@/lib/ceo";
import type { AsyncStatus } from "@/lib/useCeoHub";

const MAX = 3;

/** The conversations the seller has resolved, newest first. A resolved conversation is the seller's own recorded outcome, so this shows only that:
 * nothing is inferred, scored or suggested here. */
export function RecentDecisions({
  status,
  items,
  onOpen,
}: {
  status: AsyncStatus;
  items: InvestigationSummary[];
  onOpen: (id: string) => void;
}) {
  const resolved = items
    .filter((i) => i.status === "RESOLVED")
    .sort((a, b) => b.last_message_at.localeCompare(a.last_message_at))
    .slice(0, MAX);

  return (
    <section aria-labelledby="ceo-decisions-h" data-testid="recent-decisions" className="flex min-w-0 flex-col gap-2">
      <h3 id="ceo-decisions-h" className="m-0 mt-eyebrow">Recent decisions</h3>
      <div className="mt-panel flex min-h-[72px] flex-col gap-1 p-3">
        {status === "loading" || status === "idle" ? (
          <p className="m-0 t-body-sm" style={{ color: "var(--text-5)" }}>Loading…</p>
        ) : status === "error" ? (
          <p className="m-0 t-body-sm" style={{ color: "var(--text-5)" }}>Could not load your conversations. Open the conversation list to retry.</p>
        ) : resolved.length === 0 ? (
          <p className="m-0 t-body-sm" style={{ color: "var(--text-5)" }}>No recent decisions yet. A conversation you resolve appears here.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
            {resolved.map((i) => (
              <li key={i.id}>
                <button
                  type="button"
                  onClick={() => onOpen(i.id)}
                  className="mt-row mt-focus flex min-h-6 w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span style={{ color: "var(--accent)" }}><Icon name="check" size={13} strokeWidth={2} /></span>
                    <span className="truncate t-body-sm font-semibold" style={{ color: "var(--text-2)" }}>{i.title || "Untitled conversation"}</span>
                  </span>
                  <time className="flex-shrink-0 t-meta" dateTime={i.last_message_at} style={{ color: "var(--text-5)" }}>{new Date(i.last_message_at).toLocaleDateString()}</time>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
