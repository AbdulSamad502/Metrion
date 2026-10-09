"use client";

import Link from "next/link";
import { Icon } from "@/components/ui/Icon";
import { Spinner } from "@/components/ui/LoadingState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { agentMeta } from "@/lib/agents";
import type { AgentCode } from "@/lib/ceo";
import { findingStatusView, type CanvasNode } from "@/lib/ceoModel";

const BADGE: Record<CanvasNode["state"], { tone: "accent" | "neutral" | "warning" | "info"; label: string }> = {
  ATTACHED: { tone: "accent", label: "Connected" },
  DETACHED: { tone: "neutral", label: "Removed" },
  LOCKED: { tone: "warning", label: "Locked" },
  NO_ACCESS: { tone: "neutral", label: "No access" },
  UNKNOWN: { tone: "neutral", label: "Checking…" },
};

/** The agents, as cards: what each does, whether it is connected to this conversation, what it last found, and Connect / Remove. Removing stops NEW work from that agent in
 * this conversation (its earlier results stay as history); connecting wires it back in. A locked agent (not on your plan) and one you have no access to have no button:
 * nothing here enforces anything, the backend checks attachment, permission and plan on every call. */
export function AgentsPanel({
  nodes, busy, working, onToggle,
}: { nodes: CanvasNode[]; busy: AgentCode | null; working: Partial<Record<AgentCode, string>>; onToggle: (code: AgentCode, attach: boolean) => void }) {
  return (
    <section aria-label="Agents" data-testid="agents-panel" className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="m-0 mt-eyebrow">Agents</h2>
        <span className="t-meta" style={{ color: "var(--text-6)" }}>Connect or remove an agent for this conversation</span>
      </div>
      <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
        {nodes.map((n) => {
          const meta = agentMeta(n.code);
          const dead = n.state === "LOCKED" || n.state === "NO_ACCESS";
          const on = n.state === "ATTACHED";
          const b = BADGE[n.state];
          return (
            <li key={n.code}>
              <article data-testid={`agent-card-${n.code}`} data-state={n.state} className="flex h-full flex-col gap-2 rounded-xl p-3.5" style={{ border: `1px ${on ? "solid" : "dashed"} ${on ? "var(--accent-border-default)" : "var(--border-subtle)"}`, background: "var(--bg-card)", opacity: dead ? 0.8 : 1 }}>
                <header className="flex items-start justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg" style={{ background: "var(--fill-hover)", color: on ? "var(--accent)" : "var(--text-4)" }}>
                      <Icon name={dead ? "lock" : meta.icon} size={17} />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate t-body font-semibold" style={{ color: "var(--text-1)" }}>{n.name}</span>
                      <span className="block truncate t-meta" style={{ color: "var(--text-5)" }}>{meta.role}</span>
                    </span>
                  </span>
                  <StatusBadge tone={b.tone} dot={on}>{b.label}</StatusBadge>
                </header>
                <p className="m-0 t-body-sm" style={{ color: "var(--text-4)" }}>{meta.description}</p>
                {working[n.code] && (
                  <p className="m-0 flex items-center gap-1.5 t-meta" style={{ color: "var(--accent)" }}><Spinner size={11} /> {working[n.code]}</p>
                )}
                {n.result.headline ? (
                  <p className="m-0 line-clamp-2 t-body-sm font-semibold" style={{ color: "var(--text-2)" }} data-testid={`headline-${n.code}`} title={n.result.headline}>
                    {n.result.headline}
                    {n.result.headlineAt && <span className="block t-meta font-normal" style={{ color: "var(--text-6)" }}>Latest complete result · <time dateTime={n.result.headlineAt}>{new Date(n.result.headlineAt).toLocaleString()}</time></span>}
                  </p>
                ) : n.result.noCompleteResult ? (
                  <p className="m-0 t-body-sm font-semibold" style={{ color: "var(--text-4)" }} data-testid={`no-result-${n.code}`}>No complete result yet.</p>
                ) : null}
                {n.result.newer && (
                  <p className="m-0 t-meta" style={{ color: n.result.newer.status === "COMPLETE" ? "var(--text-5)" : "var(--warning)" }} data-testid={`newer-${n.code}`}>
                    Latest check: {n.result.newer.label} · {findingStatusView(n.result.newer.status).label}
                  </p>
                )}
                {on && n.chatActions === 0 && <p className="m-0 t-meta" style={{ color: "var(--text-6)" }}>Connected, but the CEO cannot run its actions from chat yet. Open its own page.</p>}
                {on && n.chatActions !== null && n.chatActions > 0 && <p className="m-0 t-meta" style={{ color: "var(--text-6)" }}>{n.chatActions} {n.chatActions === 1 ? "action" : "actions"} the CEO can run from chat.</p>}
                {n.state === "LOCKED" && <p className="m-0 t-meta" style={{ color: "var(--text-6)" }}>Not on your current plan, so it cannot be connected and nothing from it will run.</p>}
                {n.state === "DETACHED" && <p className="m-0 t-meta" style={{ color: "var(--text-6)" }}>Removed from this conversation. Its earlier results stay as history.</p>}
                <footer className="mt-auto flex flex-wrap items-center gap-2 pt-1">
                  {n.canToggle && (
                    <button
                      type="button" disabled={busy === n.code} data-testid={`${on ? "remove" : "connect"}-${n.code}`} onClick={() => onToggle(n.code, !on)}
                      aria-label={on ? `Remove ${n.name} from this conversation` : `Connect ${n.name} to this conversation`}
                      className="mt-btn mt-focus flex items-center gap-1.5 rounded-lg px-3 py-1.5 t-body-sm font-bold"
                      style={on ? { border: "1px solid var(--border-hover)", color: "var(--text-3)" } : { background: "var(--accent)", color: "var(--accent-on-fill)" }}
                    >
                      {busy === n.code ? <Spinner size={12} /> : <Icon name={on ? "close" : "plus"} size={13} strokeWidth={1.9} />}
                      {on ? "Remove" : "Connect"}
                    </button>
                  )}
                  {meta.href && <Link href={meta.href} className="mt-focus t-meta font-semibold underline" style={{ color: "var(--text-4)" }}>{meta.workspaceLabel ?? "Open"}</Link>}
                </footer>
              </article>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
