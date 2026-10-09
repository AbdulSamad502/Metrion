"use client";

import { useState } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Spinner } from "@/components/ui/LoadingState";
import { agentMeta } from "@/lib/agents";
import type { AgentCode } from "@/lib/ceo";
import type { CanvasNode } from "@/lib/ceoModel";

type Tone = "idle" | "working" | "input" | "off" | "locked";

const TONE_COLOR: Record<Tone, string> = {
  idle: "var(--positive)",
  working: "var(--accent)",
  input: "var(--warning)",
  off: "var(--text-6)",
  locked: "var(--text-7)",
};

/** What one chip says. Driven only by what the backend reported: attachment / plan / permission from the roster, "working" from the live leg events of the
 * running turn, "needs your input" from an unanswered card. Nothing here is inferred or invented. */
function chipState(node: CanvasNode, working: string | null): { tone: Tone; text: string } {
  if (node.state === "LOCKED") return { tone: "locked", text: "Locked · not on your plan" };
  if (node.state === "NO_ACCESS") return { tone: "locked", text: "No access" };
  if (node.state === "DETACHED") return { tone: "off", text: "Off for this conversation" };
  if (node.state === "UNKNOWN") return { tone: "off", text: "Checking…" };
  return working ? { tone: "working", text: working } : { tone: "idle", text: "Ready" };
}

/** The top bar: the CEO and every agent, always visible. Click an agent to turn it on or off for this conversation (future work only: earlier findings stay). */
export function AgentStrip({
  nodes, busy, onToggle, ceoWorking, ceoNeedsInput, workingByAgent, hasConversation, onMenu,
}: {
  nodes: CanvasNode[];
  busy: AgentCode | null;
  onToggle: (code: AgentCode, attach: boolean) => void;
  ceoWorking: string | null;
  ceoNeedsInput: boolean;
  workingByAgent: Partial<Record<AgentCode, string>>;
  hasConversation: boolean;
  onMenu: () => void;
}) {
  const [open, setOpen] = useState<AgentCode | null>(null);
  const ceoTone: Tone = ceoNeedsInput ? "input" : ceoWorking ? "working" : "idle";
  const ceoText = ceoNeedsInput ? "Needs your input" : ceoWorking ?? (hasConversation ? "Ready" : "Start a conversation");
  return (
    <header className="mt-panel flex flex-wrap items-stretch gap-2 px-3 py-2.5" data-testid="agent-strip" aria-label="CEO and agents">
      <button type="button" onClick={onMenu} aria-label="Conversations and business overview" data-testid="open-drawer" className="mt-btn mt-focus flex items-center gap-2 rounded-xl px-3" style={{ border: "1px solid var(--border-subtle)", color: "var(--text-3)" }}>
        <Icon name="menu" size={16} />
        <span className="hidden t-body-sm font-semibold sm:inline">Conversations</span>
      </button>
      <div className="flex min-w-0 flex-1 flex-wrap gap-2" role="list">
        <Chip testid="ceo-node" icon="ceo" name="CEO" tone={ceoTone} text={ceoText} strong />
        {nodes.map((n) => {
          const meta = agentMeta(n.code);
          const { tone, text } = chipState(n, workingByAgent[n.code] ?? null);
          const dead = n.state === "LOCKED" || n.state === "NO_ACCESS";
          return (
            <div key={n.code} className="relative" role="listitem">
              <Chip
                testid={`agent-node-${n.code}`} state={n.state} icon={dead ? "lock" : meta.icon} name={n.name} tone={tone} text={text} dashed={n.state === "DETACHED" || dead}
                onClick={n.canToggle ? () => setOpen(open === n.code ? null : n.code) : undefined} expanded={open === n.code}
              />
              {open === n.code && n.canToggle && (
                <div role="menu" className="absolute left-0 top-full z-20 mt-1 w-64 rounded-xl p-3 shadow-lg" style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }}>
                  <p className="m-0 mb-2 t-meta" style={{ color: "var(--text-4)" }}>
                    {n.state === "ATTACHED"
                      ? "Turning it off stops new work from this agent in this conversation. Its earlier results stay as history."
                      : "Turn it on so the CEO can use it in this conversation."}
                  </p>
                  <button
                    type="button" role="menuitem" data-testid={`wire-${n.code}`} disabled={busy === n.code}
                    aria-label={n.state === "ATTACHED" ? `Detach ${n.name} from this investigation` : `Attach ${n.name} to this investigation`}
                    onClick={() => { onToggle(n.code, n.state !== "ATTACHED"); setOpen(null); }}
                    className="mt-btn mt-focus flex w-full items-center justify-center gap-2 rounded-lg px-3 py-1.5 t-body-sm font-bold"
                    style={{ border: "1px solid var(--border-hover)", color: "var(--text-2)" }}
                  >
                    {busy === n.code ? <Spinner size={12} /> : null}
                    {n.state === "ATTACHED" ? "Turn off" : "Turn on"}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </header>
  );
}

function Chip({
  testid, icon, name, tone, text, strong, dashed, onClick, expanded, state,
}: { testid: string; icon: IconName; name: string; tone: Tone; text: string; strong?: boolean; dashed?: boolean; onClick?: () => void; expanded?: boolean; state?: string }) {
  const body = (
    <>
      <span className="relative flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg" style={{ background: "var(--fill-hover)", color: tone === "locked" ? "var(--text-7)" : "var(--text-2)" }}>
        <Icon name={icon} size={16} />
        <span aria-hidden className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full" style={{ background: TONE_COLOR[tone], boxShadow: tone === "working" ? "0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent)" : undefined }} />
      </span>
      <span className="flex min-w-0 flex-col text-left">
        <span className={`truncate t-body-sm ${strong ? "font-bold" : "font-semibold"}`} style={{ color: tone === "locked" ? "var(--text-5)" : "var(--text-1)" }}>{name}</span>
        <span className="flex items-center gap-1 truncate t-meta" style={{ color: tone === "input" ? "var(--warning)" : "var(--text-5)" }}>
          {tone === "working" && <Spinner size={10} />}
          {text}
        </span>
      </span>
    </>
  );
  const cls = "mt-chip flex min-w-[148px] items-center gap-2.5 rounded-xl px-2.5 py-1.5";
  const style = { border: `1px ${dashed ? "dashed" : "solid"} ${strong ? "var(--accent-border-default)" : "var(--border-subtle)"}` };
  return onClick ? (
    <button type="button" data-testid={testid} data-state={state} aria-expanded={expanded} onClick={onClick} className={`${cls} mt-focus`} style={style}>{body}</button>
  ) : (
    <div data-testid={testid} data-state={state} className={cls} style={style}>{body}</div>
  );
}
