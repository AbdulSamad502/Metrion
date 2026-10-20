"use client";

import { useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { Icon } from "@/components/ui/Icon";
import { LoadingState } from "@/components/ui/LoadingState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { InvestigationSummary } from "@/lib/ceo";
import { investigationTitle, visibleInvestigations } from "@/lib/ceoModel";
import type { AsyncStatus } from "@/lib/useCeoHub";

const STATUS_TONE = { ACTIVE: "accent", RESOLVED: "info", ARCHIVED: "neutral" } as const;
const STATUS_LABEL = { ACTIVE: "Active", RESOLVED: "Resolved", ARCHIVED: "Archived" } as const;

/** LEFT: the tenant's investigations (visible tenant-wide), a way to start a new one, and the archived ones behind a toggle. */
export function InvestigationList({
  status,
  items,
  error,
  selectedId,
  showArchived,
  onToggleArchived,
  onDelete,
  onSelect,
  onCreate,
  onRetry,
}: {
  status: AsyncStatus;
  items: InvestigationSummary[];
  error: string | null;
  selectedId: string | null;
  showArchived: boolean;
  onToggleArchived: (v: boolean) => void;
  onDelete?: (id: string) => void;
  onSelect: (id: string) => void;
  onCreate: (title?: string) => void;
  onRetry: () => void;
}) {
  const [title, setTitle] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const shown = visibleInvestigations(items, showArchived);
  const archivedCount = items.filter((i) => i.status === "ARCHIVED").length;

  return (
    <div className="flex flex-col gap-3" data-testid="investigation-list">
      <div className="flex items-center justify-between gap-2">
        <h2 className="mt-eyebrow">Investigations</h2>
      </div>
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          onCreate(title);
          setTitle("");
        }}
      >
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          aria-label="Title for a new investigation (optional)"
          placeholder="New investigation title (optional)"
          className="mt-focus min-w-0 flex-1 rounded-lg bg-transparent px-2.5 py-2 t-body-sm outline-none"
          style={{ border: "1px solid var(--border-subtle)", color: "var(--text-2)" }}
        />
        <button
          type="submit"
          className="mt-btn mt-focus flex flex-shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 t-body-sm font-bold"
          style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}
        >
          <Icon name="plus" size={13} strokeWidth={1.9} /> New
        </button>
      </form>

      {status === "loading" && <LoadingState lines={4} label="Loading investigations" />}
      {error && <ErrorNotice message={error} onRetry={onRetry} />}
      {status === "ready" && shown.length === 0 && (
        <EmptyState
          compact
          icon="ceo"
          title={items.length === 0 ? "No investigations yet" : "Nothing to show"}
          description={items.length === 0 ? "Start one to ask the CEO a question. Each investigation keeps its conversation and findings as history." : "Archived investigations are hidden."}
        />
      )}
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {shown.map((i) => {
          const selected = i.id === selectedId;
          return (
            <li key={i.id} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(i.id)}
                aria-current={selected ? "true" : undefined}
                data-testid={`investigation-${i.id}`}
                className="mt-row mt-focus flex w-full flex-col items-start gap-1 rounded-lg px-2.5 py-2.5 text-left"
                style={{ background: selected ? "var(--fill-hover)" : "transparent", border: `1px solid ${selected ? "var(--accent-border-default)" : "transparent"}` }}
              >
                <span className="t-body font-semibold" style={{ color: "var(--text-2)" }}>
                  {investigationTitle(i)}
                </span>
                <span className="flex items-center gap-2">
                  <StatusBadge tone={STATUS_TONE[i.status]}>{STATUS_LABEL[i.status]}</StatusBadge>
                  <time className="t-meta" dateTime={i.last_message_at} style={{ color: "var(--text-6)" }}>
                    {new Date(i.last_message_at).toLocaleDateString()}
                  </time>
                </span>
              </button>
              {onDelete && i.status !== "ARCHIVED" && (
                <button
                  type="button"
                  aria-label={`Delete conversation ${investigationTitle(i)}`}
                  title="Delete conversation"
                  onClick={() => setConfirmId(i.id)}
                  className="mt-btn mt-focus absolute right-2 top-2 rounded-md p-1.5 opacity-60 transition-opacity hover:opacity-100 focus:opacity-100"
                  style={{ color: "var(--text-4)" }}
                >
                  <Icon name="trash" size={14} />
                </button>
              )}
              {confirmId === i.id && onDelete && (
                <div role="alertdialog" aria-label="Confirm delete" className="mt-1 flex flex-col gap-2 rounded-lg px-2.5 py-2.5" style={{ border: "1px solid var(--border-hover)", background: "var(--fill-hover)" }}>
                  <p className="m-0 t-meta" style={{ color: "var(--text-3)" }}>
                    Delete this conversation? It disappears from your list. Its findings and the audit record are kept by Metrion and are not erased.
                  </p>
                  <div className="flex gap-2">
                    <button type="button" onClick={() => { onDelete(i.id); setConfirmId(null); }} className="mt-btn mt-focus rounded-lg px-3 py-1.5 t-meta font-bold" style={{ background: "var(--accent)", color: "var(--accent-on-fill)" }}>
                      Delete
                    </button>
                    <button type="button" onClick={() => setConfirmId(null)} className="mt-btn mt-focus rounded-lg px-3 py-1.5 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {archivedCount > 0 && (
        <label className="flex cursor-pointer items-center gap-2 t-body-sm" style={{ color: "var(--text-5)" }}>
          <input type="checkbox" checked={showArchived} onChange={(e) => onToggleArchived(e.target.checked)} />
          Show archived ({archivedCount})
        </label>
      )}
    </div>
  );
}
