"use client";

import Link from "next/link";
import { useState } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Spinner } from "@/components/ui/LoadingState";
import { agentMeta } from "@/lib/agents";
import type { AgentCode } from "@/lib/ceo";
import { findingStatusView, type CanvasNode, type NodeState } from "@/lib/ceoModel";

const STATE_LABEL: Record<NodeState, string> = {
  ATTACHED: "Connected",
  DETACHED: "Removed: not used for new work",
  LOCKED: "Locked: not on your plan",
  NO_ACCESS: "No access for you",
  UNKNOWN: "Checking availability…",
};

/** What each specialist is for: a fixed description of the role, never data. */
const TAGLINE: Record<AgentCode, string> = { CI: "Competitors & market", CFO: "Financials & P&L", PI: "Discover & research", CMO: "Listings & marketing" };
/** Identity hue per specialist (decorative, icon only; meaning is always carried by the text and the state label as well). */
const HUE: Record<AgentCode, string> = { CI: "#F59E5B", CFO: "#6F8DFF", PI: "#EC6FA9", CMO: "var(--accent)" };

/** Where the four nodes sit (percent of the canvas width) and where the CEO sits. */
const X: Record<AgentCode, number> = { CI: 12.5, CFO: 37.5, PI: 62.5, CMO: 87.5 };
const CEO_X = 50;

/** The CEO orchestration canvas: the CEO and its four specialists, drawn as an n8n-style node graph.
 *
 * A WIRE means "this agent is attached to the CURRENT investigation" (spec §6.22). It is not a workflow edge between agents.
 *  - removing a wire detaches the agent from FUTURE work only; earlier findings stay visible with their original provenance;
 *  - a detached agent can be wired back by the seller; the CEO never does that on its own;
 *  - a locked (not entitled) or no-access agent is drawn as such and has no wire to add: it is never shown as attached.
 * The canvas renders what the backend says and enforces nothing: attachment, permission and entitlement are enforced server-side. */
export function AgentCanvas({
  nodes,
  busy,
  onToggle,
  working = {},
  ceoStatus = "Ready",
  ceoTone = "idle",
}: {
  nodes: CanvasNode[];
  busy: AgentCode | null;
  onToggle: (code: AgentCode, attach: boolean) => void;
  working?: Partial<Record<AgentCode, string>>;
  ceoStatus?: string;
  ceoTone?: "idle" | "working" | "input";
}) {
  const dot = ceoTone === "input" ? "var(--warning)" : ceoTone === "working" ? "var(--accent)" : "var(--positive)";
  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-xl p-1 pt-12 @container @[1px]:pt-4"
      style={{ backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.07) 1px, transparent 1px)", backgroundSize: "20px 20px", border: "none", backgroundColor: "transparent" }}
      data-testid="agent-canvas" aria-label="CEO orchestration canvas"
    >
      <AddAgent nodes={nodes} busy={busy} onToggle={onToggle} />
      <div className="relative mx-auto w-full max-w-[880px]">
        <div className="relative flex justify-start pt-9 @[1px]:justify-center @[1px]:pt-0">
          <span aria-hidden className="absolute left-6 top-full block h-4 w-px @[1px]:hidden" style={{ background: "var(--accent-border-strong)" }} />
          <div className={`mt-panel mt-panel--elevated flex min-w-[132px] flex-col items-center gap-1.5 rounded-2xl px-5 py-3 text-center ${ceoTone === "working" ? "mt-working-pulse" : ""}`} style={{ boxShadow: "var(--glass-shadow-hover)", borderColor: "var(--accent-border-default)" }} data-testid="ceo-node">
            <span className="relative" style={{ color: "var(--accent)" }}>
              <Icon name="ceo" size={28} />
              <span aria-hidden className="absolute -right-1.5 -top-1 h-2.5 w-2.5 rounded-full" style={{ background: dot }} />
            </span>
            <div>
              <div className="t-card-title font-bold leading-none" style={{ color: "var(--text-1)" }}>
                CEO
              </div>
              <div className="mt-1 flex items-center justify-center gap-1 t-meta" style={{ color: ceoTone === "input" ? "var(--warning)" : "var(--text-4)" }} data-testid="ceo-status">
                {ceoTone === "working" && <Spinner size={10} />}
                {ceoStatus}
              </div>
            </div>
          </div>
        </div>

        <div className="relative hidden h-[96px] @[1px]:block" data-testid="fan">
          <svg className="absolute inset-0 z-0 h-full w-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden data-testid="edges">
            {nodes.map((n) => {
              const attached = n.state === "ATTACHED";
              const dead = n.state === "LOCKED" || n.state === "NO_ACCESS";
              return (
                <path
                  key={n.code}
                  d={`M ${CEO_X} 0 C ${CEO_X} 55, ${X[n.code]} 45, ${X[n.code]} 100`}
                  fill="none"
                  vectorEffect="non-scaling-stroke"
                  strokeWidth={working[n.code] ? 2.5 : 1.75}
                  strokeLinecap="round"
                  data-testid={`edge-${n.code}`}
                  strokeDasharray={working[n.code] ? "6 6" : attached ? undefined : "5 5"}
                  stroke={working[n.code] ? "var(--accent)" : attached ? "rgba(62,207,116,0.55)" : "rgba(140,148,138,0.5)"}
                  opacity={dead ? 0.55 : 1}
                >
                  {working[n.code] && <animate attributeName="stroke-dashoffset" from="12" to="0" dur="0.8s" repeatCount="indefinite" />}
                </path>
              );
            })}
          </svg>
          {/* ports: the edge starts at the CEO's lower port and ends at each specialist's upper port (same percentages as the paths) */}
          <span aria-hidden data-testid="port-ceo" className="absolute z-[1] h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${CEO_X}%`, top: 0, background: "var(--bg-base)", border: "2px solid var(--accent)" }} />
          {nodes.map((n) => (
            <span key={`port-${n.code}`} aria-hidden data-testid={`port-${n.code}`} className="absolute z-[1] h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${X[n.code]}%`, top: "100%", background: "var(--bg-base)", border: `2px solid ${n.state === "ATTACHED" ? "var(--accent)" : "rgba(140,148,138,0.6)"}` }} />
          ))}
          {nodes.map((n) => (
            <WireControl key={n.code} node={n} busy={busy === n.code} onToggle={onToggle} />
          ))}
        </div>

        <ul className="relative m-0 ml-6 mt-4 grid list-none grid-cols-1 gap-3 p-0 @[1px]:ml-0 @[1px]:mt-0 @[1px]:grid-cols-4 @[1px]:gap-0" aria-label="Specialist agents">
          {nodes.map((n, i) => (
            <li key={n.code} className="relative pl-6 @[1px]:px-1.5">
              <TreeConnector node={n} first={i === 0} last={i === nodes.length - 1} running={!!working[n.code]} />
              <AgentNode node={n} busy={busy === n.code} onToggle={onToggle} working={working[n.code] ?? null} />
            </li>
          ))}
        </ul>
        <CanvasLegend />
      </div>
    </div>
  );
}

/** What the wires and dots mean. Only states the canvas really has: connected to this conversation, removed from it, or not known yet. */
function CanvasLegend() {
  const item = (label: string, mark: React.ReactNode) => (
    <li className="flex items-center gap-1.5">
      {mark}
      {label}
    </li>
  );
  return (
    <ul className="m-0 mt-4 flex list-none flex-wrap items-center justify-end gap-x-4 gap-y-1 p-0 t-meta" style={{ color: "var(--text-5)" }} aria-label="Legend" data-testid="canvas-legend">
      {item("Connected", <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--positive)" }} />)}
      {item("Removed", <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--text-6)" }} />)}
      {item("Checking", <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--warning)" }} />)}
      {item("Wired to this conversation", <span aria-hidden className="block w-5" style={{ borderTop: "2px solid var(--accent-border-strong)" }} />)}
      {item("Removed or locked", <span aria-hidden className="block w-5" style={{ borderTop: "2px dashed var(--connector-inactive)" }} />)}
    </ul>
  );
}

/** Narrow layout only: the wire from the CEO's spine to this agent's left port. Same meaning as the fan wires: solid = connected to this conversation,
 * dashed = removed or locked, pulsing port = running now. Hidden once the container is wide enough for the fan. */
function TreeConnector({ node, first, last, running }: { node: CanvasNode; first: boolean; last: boolean; running: boolean }) {
  const attached = node.state === "ATTACHED";
  const dead = node.state === "LOCKED" || node.state === "NO_ACCESS";
  const color = attached ? "var(--accent-border-strong)" : "var(--connector-inactive)";
  const dash = attached ? "solid" : "dashed";
  return (
    <span aria-hidden className="@[1px]:hidden" data-testid={`tree-wire-${node.code}`}>
      <span className="absolute left-0 w-px" style={{ top: first ? "-1rem" : "-0.75rem", height: last ? `calc(${first ? 1 : 0.75}rem + 1.75rem)` : `calc(100% + ${first ? 1 : 0.75}rem)`, borderLeft: `1px ${dash} ${color}`, opacity: dead ? 0.5 : 1 }} />
      <span className="absolute left-0 top-7 h-px w-6" style={{ borderTop: `2px ${dash} ${color}`, opacity: dead ? 0.5 : 1 }} />
      <span className={`absolute top-[calc(1.75rem-3px)] h-1.5 w-1.5 rounded-full ${running ? "animate-pulse" : ""}`} style={{ left: "calc(1.5rem - 3px)", background: attached ? "var(--accent)" : "var(--text-6)" }} />
    </span>
  );
}

/** Top-right "Add agent": wires a detached agent back in. Only agents that CAN be attached are offered (locked / no-access ones never are). */
function AddAgent({ nodes, busy, onToggle }: { nodes: CanvasNode[]; busy: AgentCode | null; onToggle: (c: AgentCode, attach: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const addable = nodes.filter((n) => n.canToggle && n.state === "DETACHED");
  return (
    <div className="absolute right-0 top-0 z-10 flex flex-col items-end gap-1.5">
      <button
        type="button"
        data-testid="add-agent"
        disabled={addable.length === 0}
        aria-expanded={open && addable.length > 0}
        title={addable.length === 0 ? "Every specialist you can use is already connected." : "Connect a specialist to this conversation"}
        onClick={() => setOpen((o) => !o)}
        className="mt-btn mt-focus flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 t-meta font-bold"
        style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)", opacity: addable.length === 0 ? 0.5 : 1 }}
      >
        <Icon name="plus" size={13} strokeWidth={1.9} /> Add specialist
      </button>
      {open && addable.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 rounded-xl p-2" style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} aria-label="Specialists you can add">
          {addable.map((n) => (
            <li key={n.code}>
              <button
                type="button"
                data-testid={`add-${n.code}`}
                disabled={busy === n.code}
                onClick={() => {
                  onToggle(n.code, true);
                  setOpen(false);
                }}
                className="mt-btn mt-focus w-full rounded-lg px-2.5 py-1 text-left t-body-sm"
                style={{ color: "var(--text-2)" }}
              >
                {n.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function WireControl({ node, busy, onToggle }: { node: CanvasNode; busy: boolean; onToggle: (c: AgentCode, attach: boolean) => void }) {
  if (!node.canToggle) return null;
  const attached = node.state === "ATTACHED";
  const label = attached ? `Detach ${node.name} from this investigation` : `Attach ${node.name} to this investigation`;
  return (
    <button
      type="button"
      data-testid={`wire-${node.code}`}
      title={label}
      aria-label={label}
      disabled={busy}
      onClick={() => onToggle(node.code, !attached)}
      className="mt-btn mt-focus absolute z-10 flex h-8 w-8 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full"
      style={{
        left: `${(CEO_X + X[node.code]) / 2}%`,
        top: "52%",
        background: "var(--bg-popover)",
        border: `1px solid ${attached ? "var(--accent-border-strong)" : "var(--border-hover)"}`,
        color: attached ? "var(--accent)" : "var(--text-4)",
      }}
    >
      {busy ? <Spinner size={12} /> : <Icon name={attached ? "close" : "plus"} size={13} strokeWidth={1.9} />}
    </button>
  );
}

function AgentNode({ node, busy, onToggle, working }: { node: CanvasNode; busy: boolean; onToggle: (c: AgentCode, attach: boolean) => void; working: string | null }) {
  const meta = agentMeta(node.code);
  const live = node.state === "ATTACHED";
  const dead = node.state === "LOCKED" || node.state === "NO_ACCESS";
  const icon: IconName = dead ? "lock" : meta.icon;
  const attached = node.state === "ATTACHED";
  return (
    <div
      data-testid={`agent-node-${node.code}`}
      data-state={node.state}
      className={`mt-chip mt-dash-card ${live ? "mt-dash-card--elevated" : ""} ${dead ? "mt-dash-card--locked" : ""} flex h-full flex-col items-center gap-1.5 rounded-xl px-2 py-3 text-center`}
      style={{ borderColor: live ? "var(--accent-border-default)" : undefined, borderStyle: node.state === "DETACHED" || dead ? "dashed" : undefined, opacity: dead ? 0.75 : 1 }}
    >
      <span className="flex flex-col items-center gap-1.5 text-center">
        <span className="relative" style={{ color: live ? HUE[node.code] : dead ? "var(--text-7)" : "var(--text-4)" }}>
          <Icon name={icon} size={26} />
        </span>
        <span className="min-w-0">
          <span className="block break-words t-body font-semibold leading-tight" style={{ color: dead ? "var(--text-5)" : "var(--text-1)" }}>
            {node.name}
          </span>
          <span className="block break-words t-meta" style={{ color: "var(--text-5)" }}>{TAGLINE[node.code]}</span>
        </span>
      </span>
      <span className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1">
      <span className="flex items-center gap-1.5 t-meta" style={{ color: live ? "var(--accent)" : "var(--text-5)" }}>
        {working ? <Spinner size={10} /> : <span aria-hidden className="h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: live ? "var(--positive)" : node.state === "UNKNOWN" ? "var(--warning)" : "var(--text-6)" }} />}
        {working ?? STATE_LABEL[node.state]}
      </span>
      {/* The same control as the wire, for small screens (where the wire is not drawn) and for keyboard / assistive-tech users. */}
      {node.canToggle && (
        <button type="button" disabled={busy} onClick={() => onToggle(node.code, !attached)} className="mt-btn mt-focus min-h-[28px] rounded-md px-2 py-0.5 t-meta font-bold" style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}>
          {attached ? "Remove" : "Connect"}
        </button>
      )}
      </span>
      {meta.href && !dead && (
        <Link href={meta.href} data-testid={`workspace-${node.code}`} className="mt-focus inline-flex min-h-6 items-center self-center t-meta font-bold" style={{ color: "var(--text-3)" }}>
          {meta.workspaceLabel ?? "Open"} &rarr;
        </Link>
      )}
      {node.state === "ATTACHED" && node.chatActions === 0 && (
        <span className="t-meta" style={{ color: "var(--text-6)" }}>
          No chat actions yet; use its own page.
        </span>
      )}
      {node.state === "ATTACHED" && node.chatActions !== null && node.chatActions > 0 && (
        <span className="t-meta" style={{ color: "var(--text-6)" }}>
          {node.chatActions} chat {node.chatActions === 1 ? "action" : "actions"}
        </span>
      )}
      {node.result.headline && (
        <span className="flex flex-col gap-0.5">
          <span className="line-clamp-2 t-body-sm font-semibold" style={{ color: "var(--text-2)" }} data-testid={`headline-${node.code}`} title={node.result.headline}>
            {node.result.headline}
          </span>
          {node.result.headlineAt && (
            <span className="t-meta" style={{ color: "var(--text-6)" }}>
              Latest complete result · <time dateTime={node.result.headlineAt}>{new Date(node.result.headlineAt).toLocaleString()}</time>
            </span>
          )}
        </span>
      )}
      {node.result.noCompleteResult && (
        <span className="t-body-sm font-semibold" style={{ color: "var(--text-4)" }} data-testid={`no-result-${node.code}`}>
          No complete result yet.
        </span>
      )}
      {node.result.newer && (
        <span className="t-meta" style={{ color: node.result.newer.status === "COMPLETE" ? "var(--text-5)" : "var(--warning)" }} data-testid={`newer-${node.code}`}>
          Latest check: {node.result.newer.label} · {findingStatusView(node.result.newer.status).label} ·{" "}
          <time dateTime={node.result.newer.at}>{new Date(node.result.newer.at).toLocaleString()}</time>
        </span>
      )}
      {node.state === "LOCKED" && (
        <span className="t-meta" style={{ color: "var(--text-6)" }}>
          Not available on your current plan.
        </span>
      )}
      {node.state === "DETACHED" && (
        <span className="t-meta" style={{ color: "var(--text-6)" }}>
          Earlier findings stay as history.
        </span>
      )}
    </div>
  );
}
