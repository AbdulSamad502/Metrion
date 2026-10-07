"use client";

import { Icon, type IconName } from "@/components/ui/Icon";
import { Spinner } from "@/components/ui/LoadingState";
import { agentMeta } from "@/lib/agents";
import type { AgentCode } from "@/lib/ceo";
import type { CanvasNode, NodeState } from "@/lib/ceoModel";

const STATE_LABEL: Record<NodeState, string> = {
  ATTACHED: "Attached to this investigation",
  DETACHED: "Detached: not used for new work",
  LOCKED: "Locked: not on your plan",
  NO_ACCESS: "No access for you",
  UNKNOWN: "Checking availability…",
};

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
}: {
  nodes: CanvasNode[];
  busy: AgentCode | null;
  onToggle: (code: AgentCode, attach: boolean) => void;
}) {
  return (
    <div className="relative" data-testid="agent-canvas" aria-label="CEO orchestration canvas">
      <div className="relative mx-auto w-full max-w-[880px]">
        <div className="flex justify-center">
          <div className="mt-panel mt-panel--elevated flex items-center gap-3 rounded-2xl px-5 py-3" style={{ boxShadow: "var(--glass-shadow-hover)" }} data-testid="ceo-node">
            <span style={{ color: "var(--text-1)" }}>
              <Icon name="ceo" size={22} />
            </span>
            <div>
              <div className="t-card-title font-bold leading-none" style={{ color: "var(--text-1)" }}>
                CEO
              </div>
              <div className="mt-1 t-meta" style={{ color: "var(--text-4)" }}>
                Orchestrates only the agents wired in
              </div>
            </div>
          </div>
        </div>

        <div className="relative hidden h-[84px] md:block" aria-hidden={false}>
          <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
            {nodes.map((n) => {
              const attached = n.state === "ATTACHED";
              const dead = n.state === "LOCKED" || n.state === "NO_ACCESS";
              return (
                <path
                  key={n.code}
                  d={`M ${CEO_X} 0 C ${CEO_X} 55, ${X[n.code]} 45, ${X[n.code]} 100`}
                  fill="none"
                  vectorEffect="non-scaling-stroke"
                  strokeWidth={2}
                  strokeDasharray={attached ? undefined : "5 5"}
                  stroke={attached ? "var(--accent-border-strong)" : "var(--connector-inactive)"}
                  opacity={dead ? 0.5 : 1}
                />
              );
            })}
          </svg>
          {nodes.map((n) => (
            <WireControl key={n.code} node={n} busy={busy === n.code} onToggle={onToggle} />
          ))}
        </div>

        <ul className="m-0 mt-3 grid list-none grid-cols-2 gap-3 p-0 md:mt-0 md:grid-cols-4" aria-label="Specialist agents">
          {nodes.map((n) => (
            <li key={n.code}>
              <AgentNode node={n} busy={busy === n.code} onToggle={onToggle} />
            </li>
          ))}
        </ul>
      </div>
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
      className="mt-btn mt-focus absolute flex h-7 w-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full"
      style={{
        left: `${(CEO_X + X[node.code]) / 2}%`,
        top: "52%",
        background: "var(--bg-card)",
        border: `1px solid ${attached ? "var(--accent-border-strong)" : "var(--border-hover)"}`,
        color: attached ? "var(--accent)" : "var(--text-4)",
      }}
    >
      {busy ? <Spinner size={12} /> : <Icon name={attached ? "close" : "plus"} size={13} strokeWidth={1.9} />}
    </button>
  );
}

function AgentNode({ node, busy, onToggle }: { node: CanvasNode; busy: boolean; onToggle: (c: AgentCode, attach: boolean) => void }) {
  const meta = agentMeta(node.code);
  const live = node.state === "ATTACHED";
  const dead = node.state === "LOCKED" || node.state === "NO_ACCESS";
  const icon: IconName = dead ? "lock" : meta.icon;
  const attached = node.state === "ATTACHED";
  return (
    <div
      data-testid={`agent-node-${node.code}`}
      data-state={node.state}
      className={`mt-chip mt-dash-card ${live ? "mt-dash-card--elevated" : ""} ${dead ? "mt-dash-card--locked" : ""} flex h-full flex-col gap-1.5 rounded-xl px-3.5 py-3`}
      style={{ borderColor: live ? "var(--accent-border-default)" : undefined, borderStyle: node.state === "DETACHED" || dead ? "dashed" : undefined, opacity: dead ? 0.75 : 1 }}
    >
      <span className="flex items-center gap-2">
        <span style={{ color: live ? "var(--accent)" : dead ? "var(--text-7)" : "var(--text-4)" }}>
          <Icon name={icon} size={16} />
        </span>
        <span className="t-body font-semibold leading-tight" style={{ color: dead ? "var(--text-5)" : "var(--text-1)" }}>
          {node.name}
        </span>
      </span>
      <span className="t-meta" style={{ color: live ? "var(--accent)" : "var(--text-5)" }}>
        {STATE_LABEL[node.state]}
      </span>
      {node.state === "ATTACHED" && node.chatActions === 0 && (
        <span className="t-meta" style={{ color: "var(--text-6)" }}>
          Attached, but the CEO cannot run its actions from chat yet. Open its own page.
        </span>
      )}
      {node.state === "ATTACHED" && node.chatActions !== null && node.chatActions > 0 && (
        <span className="t-meta" style={{ color: "var(--text-6)" }}>
          {node.chatActions} {node.chatActions === 1 ? "action" : "actions"} the CEO can run from chat.
        </span>
      )}
      {node.state === "LOCKED" && (
        <span className="t-meta" style={{ color: "var(--text-6)" }}>
          Not available on your current plan. It cannot be attached, and nothing from it will run.
        </span>
      )}
      {node.state === "DETACHED" && (
        <span className="t-meta" style={{ color: "var(--text-6)" }}>
          Earlier findings from it stay visible as history.
        </span>
      )}
      {/* The same control as the wire, for small screens (where the wire is not drawn) and for keyboard / assistive-tech users. */}
      {node.canToggle && (
        <button
          type="button"
          disabled={busy}
          onClick={() => onToggle(node.code, !attached)}
          className="mt-btn mt-focus mt-1 self-start rounded-lg px-2.5 py-1 t-meta font-bold md:hidden"
          style={{ border: "1px solid var(--border-hover)", color: "var(--text-3)" }}
        >
          {attached ? "Detach" : "Attach"}
        </button>
      )}
    </div>
  );
}
