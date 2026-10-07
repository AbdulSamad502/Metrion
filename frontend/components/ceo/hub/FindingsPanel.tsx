"use client";

import { useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { AgentCode, FindingRow } from "@/lib/ceo";
import {
  actionLabel, findingStatusView, groupFindings, isHistorical, isProblemFinding, refLabel, sourceLabel, type FindingGroup,
} from "@/lib/ceoModel";
import type { CeoMessage, TurnRow } from "@/lib/ceo";

/** RIGHT: structured specialist findings, one card per finding, grouped under the question that produced them (newest first).
 *
 * A finding carries REFERENCES, never a value the UI could re-derive: the numbers live in the CEO's gated answer. A card shows who
 * produced it, its status (a failed or partial leg is shown plainly and never blocks the others), the provenance references it cites,
 * and, when its agent has since been detached, that it is historical evidence with its original provenance intact. */
export function FindingsPanel({
  findings,
  messages,
  turns,
  agents,
  arrivedIds,
  inFlightQuestion,
  processing,
}: {
  findings: FindingRow[];
  messages: CeoMessage[];
  turns: TurnRow[];
  agents: Partial<Record<AgentCode, boolean>> | null;
  arrivedIds: string[];
  inFlightQuestion: string | null;
  processing: boolean;
}) {
  const groups = groupFindings(findings, messages, turns, inFlightQuestion);
  const arrived = new Set(arrivedIds);
  return (
    <div className="flex flex-col gap-3" data-testid="findings-panel">
      <div className="flex items-center justify-between gap-2">
        <h2 className="mt-eyebrow">Specialist findings</h2>
        {processing && <StatusBadge tone="accent" dot>Live</StatusBadge>}
      </div>
      {groups.length === 0 ? (
        <EmptyState
          compact
          icon="check"
          title={processing ? "Waiting for the first finding" : "No findings yet"}
          description={processing ? "Each specialist's result appears here the moment it finishes." : "Findings appear here as the CEO runs specialists or reads your saved results. They stay with the investigation as history."}
        />
      ) : (
        groups.map((g, gi) => <Group key={g.key} group={g} agents={agents} arrived={arrived} defaultOpen={gi === 0} />)
      )}
    </div>
  );
}

function Group({ group, agents, arrived, defaultOpen }: { group: FindingGroup; agents: Partial<Record<AgentCode, boolean>> | null; arrived: Set<string>; defaultOpen: boolean }) {
  return (
    <section aria-label={group.question ?? "Findings"} className="flex flex-col gap-2">
      {group.question && (
        <div className="t-meta" style={{ color: "var(--text-5)" }}>
          For &ldquo;{group.question}&rdquo;
        </div>
      )}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {group.findings.map((f) => (
          <li key={f.id}>
            <FindingCard finding={f} historical={isHistorical(f, agents)} arrived={arrived.has(f.id)} defaultOpen={defaultOpen} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function FindingCard({ finding: f, historical, arrived, defaultOpen }: { finding: FindingRow; historical: boolean; arrived: boolean; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const status = findingStatusView(f.status);
  const problem = isProblemFinding(f);
  const refs = f.figure_refs ?? [];
  return (
    <article
      data-testid={`finding-${f.id}`}
      data-status={f.status}
      data-historical={historical ? "true" : "false"}
      className="rounded-xl px-3.5 py-3"
      style={{
        background: "var(--bg-card)",
        border: `1px solid ${problem ? "var(--warning-border)" : arrived ? "var(--accent-border-default)" : "var(--border-subtle)"}`,
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="t-body font-semibold" style={{ color: "var(--text-1)" }}>
          {actionLabel(f.action_key)}
        </span>
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        {arrived && <StatusBadge tone="accent" dot>Just arrived</StatusBadge>}
        {historical && <StatusBadge tone="neutral">Historical</StatusBadge>}
      </div>
      <div className="mt-1 t-meta" style={{ color: "var(--text-5)" }}>
        {sourceLabel(f.source)} · <time dateTime={f.created_at}>{new Date(f.created_at).toLocaleString()}</time>
      </div>
      {historical && (
        <div className="mt-1.5 t-meta" style={{ color: "var(--text-6)" }}>
          This agent has since been detached. This is historical evidence; its original sources are unchanged.
        </div>
      )}
      {f.gap_reason && (
        <div className="mt-1.5 t-body-sm" style={{ color: problem ? "var(--warning)" : "var(--text-4)" }}>
          {f.gap_reason}
        </div>
      )}
      {problem && !f.gap_reason && (
        <div className="mt-1.5 t-body-sm" style={{ color: "var(--warning)" }}>
          This part did not complete. Other results are unaffected.
        </div>
      )}
      <div className="mt-2">
        {refs.length === 0 ? (
          <span className="t-meta" style={{ color: "var(--text-6)" }}>
            No figures cited.
          </span>
        ) : (
          <>
            <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="mt-focus t-meta font-semibold" style={{ color: "var(--text-3)" }}>
              Provenance: {refs.length} verified {refs.length === 1 ? "reference" : "references"} {open ? "▾" : "▸"}
            </button>
            {open && (
              <ul className="m-0 mt-1.5 flex list-none flex-col gap-0.5 p-0 t-meta" style={{ color: "var(--text-5)" }}>
                {refs.map((r) => (
                  <li key={`${r.kind}-${r.id}`}>{refLabel(r)}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </article>
  );
}
