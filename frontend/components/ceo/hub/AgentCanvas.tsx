"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";
import { Spinner } from "@/components/ui/LoadingState";
import { agentMeta } from "@/lib/agents";
import type { AgentCode } from "@/lib/ceo";
import type { CanvasNode, NodeState } from "@/lib/ceoModel";

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
const HUE: Record<AgentCode, string> = { CI: "var(--agent-ci)", CFO: "var(--agent-cfo)", PI: "var(--agent-pi)", CMO: "var(--agent-cmo)" };

/** The CEO's robot mark (the shared icon set has no robot). Decorative. */
function RobotIcon({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="5" y="8" width="14" height="11" rx="3" /><path d="M12 8V5" /><circle cx="12" cy="4" r="1" /><circle cx="9.3" cy="13" r="1.1" fill="currentColor" stroke="none" /><circle cx="14.7" cy="13" r="1.1" fill="currentColor" stroke="none" /><path d="M2.5 12.5v3M21.5 12.5v3M10 16.5h4" />
    </svg>
  );
}

/** True when the visitor asked for less motion (false on the server and where it cannot be known, so the first render matches). */
function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (notify) => { const mq = typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia("(prefers-reduced-motion: reduce)") : null; mq?.addEventListener?.("change", notify); return () => mq?.removeEventListener?.("change", notify); },
    () => typeof window !== "undefined" && typeof window.matchMedia === "function" && !!window.matchMedia("(prefers-reduced-motion: reduce)")?.matches,
    () => false,
  );
}

/** Where each card sits by default (percent of the stage, as the card's centre). The seller can drag any card; the wires follow it. */
type SlotId = "CEO" | AgentCode;
type Layout = Record<SlotId, { x: number; y: number }>;
const DEFAULT_LAYOUT: Layout = { CEO: { x: 50, y: 20 }, CI: { x: 14, y: 70 }, CFO: { x: 38, y: 70 }, PI: { x: 62, y: 70 }, CMO: { x: 86, y: 70 } };
const LAYOUT_KEY = "metrion.hub.canvas.layout.v1";
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));
const isLayout = (v: unknown): v is Layout =>
  !!v && typeof v === "object" && (["CEO", "CI", "CFO", "PI", "CMO"] as const).every((k) => {
    const p = (v as Record<string, { x?: unknown; y?: unknown }>)[k];
    return !!p && typeof p.x === "number" && typeof p.y === "number";
  });
const sameLayout = (a: Layout, b: Layout) => (Object.keys(a) as SlotId[]).every((k) => a[k].x === b[k].x && a[k].y === b[k].y);

/** The CEO orchestration canvas: the CEO and its four specialists, drawn as an n8n-style node graph you can rearrange.
 *
 * A WIRE means "this agent is attached to the CURRENT investigation" (spec §6.22). It is not a workflow edge between agents.
 *  - the seller does not remove or reconnect agents here; a locked (not entitled) or no-access agent is drawn as such and is never shown as attached;
 *  - dragging a card only changes where it is drawn (remembered in this browser). It never changes what is attached or what runs.
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
  const still = useReducedMotion();
  const [layout, setLayout] = useState<Layout>(DEFAULT_LAYOUT);
  const [dragging, setDragging] = useState<SlotId | null>(null);
  const stage = useRef<HTMLDivElement | null>(null);
  const drag = useRef<{ id: SlotId; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const justDragged = useRef(false);
  const restored = useRef(false);

  // Restore the remembered arrangement after hydration (never during render: SSR has no storage).
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(LAYOUT_KEY);
      const saved: unknown = raw ? JSON.parse(raw) : null;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (isLayout(saved)) setLayout(saved);
    } catch {
      /* storage unavailable or unreadable: default arrangement */
    }
    restored.current = true;
  }, []);
  useEffect(() => {
    if (!restored.current) return;
    try {
      window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
    } catch {
      /* ignore */
    }
  }, [layout]);

  const place = (id: SlotId, x: number, y: number) => setLayout((l) => ({ ...l, [id]: { x: clamp(x, 11, 89), y: clamp(y, 12, 88) } }));
  /** Free positioning only exists in the wide layout (the cards are absolutely placed there); the narrow tree layout is fixed. */
  const free = (el: HTMLElement) => getComputedStyle(el).position === "absolute";
  /* These are event handlers: the refs are only read when the pointer or key event fires, never while rendering. */
  /* eslint-disable react-hooks/refs */
  const slot = (id: SlotId) => ({
    "data-dragging": dragging === id ? "true" : undefined,
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
      if (e.button !== 0 || !free(e.currentTarget)) return;
      drag.current = { id, sx: e.clientX, sy: e.clientY, ox: layout[id].x, oy: layout[id].y, moved: false };
      e.currentTarget.setPointerCapture?.(e.pointerId);
    },
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => {
      const d = drag.current;
      const box = stage.current?.getBoundingClientRect();
      if (!d || d.id !== id || !box || box.width === 0 || box.height === 0) return;
      const dx = e.clientX - d.sx, dy = e.clientY - d.sy;
      if (!d.moved && Math.hypot(dx, dy) < 4) return;
      d.moved = true;
      setDragging(id);
      place(id, d.ox + (dx / box.width) * 100, d.oy + (dy / box.height) * 100);
    },
    onPointerUp: () => {
      const moved = drag.current?.moved;
      drag.current = null;
      setDragging(null);
      if (moved) { justDragged.current = true; setTimeout(() => { justDragged.current = false; }, 0); } // a drag must not also count as a click on a link inside the card
    },
    onPointerCancel: () => { drag.current = null; setDragging(null); },
    onClickCapture: (e: React.MouseEvent) => { if (justDragged.current) { e.preventDefault(); e.stopPropagation(); } },
    onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
      if (e.target !== e.currentTarget || !free(e.currentTarget)) return;
      const step = e.shiftKey ? 5 : 2;
      const d = e.key === "ArrowLeft" ? [-step, 0] : e.key === "ArrowRight" ? [step, 0] : e.key === "ArrowUp" ? [0, -step] : e.key === "ArrowDown" ? [0, step] : null;
      if (!d) return;
      e.preventDefault();
      place(id, layout[id].x + d[0], layout[id].y + d[1]);
    },
  });
  /* eslint-enable react-hooks/refs */
  const slotClass = (id: SlotId) =>
    `@[640px]:absolute @[640px]:z-[2] @[640px]:-translate-x-1/2 @[640px]:-translate-y-1/2 @[640px]:touch-none @[640px]:select-none @[640px]:cursor-grab ${dragging === id ? "@[640px]:cursor-grabbing @[640px]:z-[3] [&>*]:shadow-[0_14px_34px_rgba(0,0,0,0.6)]" : ""} outline-none focus-visible:[&>*]:outline focus-visible:[&>*]:outline-2 focus-visible:[&>*]:outline-[var(--accent)]`;
  const moved = !sameLayout(layout, DEFAULT_LAYOUT);
  return (
    <div
      className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl p-1 pt-12 @container @[640px]:pt-1"
      style={{ backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.07) 1px, transparent 1px)", backgroundSize: "22px 22px", border: "none", backgroundColor: "transparent" }}
      data-testid="agent-canvas" aria-label="CEO orchestration canvas"
    >
      <AddAgent nodes={nodes} busy={busy} onToggle={onToggle} />
      <div className="absolute left-1 top-1 z-10 hidden items-center gap-2 t-meta @[640px]:flex" style={{ color: "var(--text-6)" }}>
        <span>Drag a card to arrange it</span>
        {moved && (
          <button type="button" data-testid="reset-layout" onClick={() => setLayout(DEFAULT_LAYOUT)} className="mt-btn mt-focus rounded-md px-2 py-0.5 font-semibold" style={{ border: "1px solid var(--border-default)", color: "var(--text-3)" }}>
            Reset layout
          </button>
        )}
      </div>
      <div ref={stage} className="relative mx-auto w-full @[640px]:min-h-[300px] @[640px]:flex-1">
        <svg className="pointer-events-none absolute inset-0 z-0 hidden h-full w-full overflow-visible @[640px]:block" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden data-testid="edges">
          {nodes.map((n) => {
            const attached = n.state === "ATTACHED";
            const dead = n.state === "LOCKED" || n.state === "NO_ACCESS";
            const a = layout.CEO, b = layout[n.code];
            const mid = (b.y - a.y) / 2;
            return (
              <path
                key={n.code}
                d={`M ${a.x} ${a.y} C ${a.x} ${a.y + mid}, ${b.x} ${b.y - mid}, ${b.x} ${b.y}`}
                fill="none"
                vectorEffect="non-scaling-stroke"
                strokeWidth={working[n.code] ? 2.5 : 1.5}
                strokeLinecap="round"
                data-testid={`edge-${n.code}`}
                className={attached ? `mt-hub-edge ${working[n.code] ? "" : "mt-hub-edge--flow"}` : undefined}
                strokeDasharray={working[n.code] ? "6 6" : attached ? "4 4" : "5 5"}
                stroke={working[n.code] ? "var(--accent)" : attached ? "var(--accent)" : "rgba(140,148,138,0.5)"}
                opacity={dead ? 0.55 : 1}
              >
                {working[n.code] && !still && <animate attributeName="stroke-dashoffset" from="12" to="0" dur="0.8s" repeatCount="indefinite" />}
              </path>
            );
          })}
        </svg>

        <div className="relative flex justify-start pt-9 @[640px]:static @[640px]:pt-0">
          <span aria-hidden className="absolute left-6 top-full block h-4 w-px @[640px]:hidden" style={{ background: "var(--accent-border-strong)" }} />
          <div data-testid="ceo-slot" tabIndex={0} aria-label="CEO card. Use the arrow keys to move it." className={slotClass("CEO")} style={{ left: `${layout.CEO.x}%`, top: `${layout.CEO.y}%` }} {...slot("CEO")}>
            <div className={`mt-glow-card relative flex min-w-[104px] flex-col items-center gap-0.5 rounded-lg px-4 py-1.5 text-center ${ceoTone === "working" ? "mt-working-pulse" : ""}`} data-testid="ceo-node">
              <div className="flex items-center gap-2.5">
                <span className="relative" style={{ color: "var(--accent)" }}>
                  <RobotIcon size={24} />
                  <span aria-hidden className="absolute -right-1.5 -top-1 h-2.5 w-2.5 rounded-full" style={{ background: dot }} />
                </span>
                <span className="t-card-title font-semibold leading-none" style={{ color: "var(--text-1)" }}>CEO</span>
              </div>
              <div className="flex items-center justify-center gap-1 t-meta" style={{ color: ceoTone === "input" ? "var(--warning)" : "var(--text-5)" }} data-testid="ceo-status">
                {ceoTone === "working" && <Spinner size={10} />}
                {ceoStatus}
              </div>
              <span aria-hidden data-testid="port-ceo" className="absolute -bottom-[5px] hidden h-2.5 w-2.5 -translate-x-1/2 rounded-full @[640px]:block" style={{ left: "50%", background: "var(--bg-base)", border: "2px solid var(--accent)" }} />
            </div>
          </div>
        </div>

        <ul className="relative m-0 ml-6 mt-4 grid list-none grid-cols-1 gap-3 p-0 @[640px]:contents" aria-label="Specialist agents">
          {nodes.map((n, i) => {
            const attached = n.state === "ATTACHED";
            return (
              <li key={n.code} data-testid={`agent-slot-${n.code}`} tabIndex={0} aria-label={`${n.name} card. Use the arrow keys to move it.`} className={`relative pl-6 @[640px]:w-[19%] @[640px]:min-w-[128px] @[640px]:p-0 ${slotClass(n.code)}`} style={{ left: `${layout[n.code].x}%`, top: `${layout[n.code].y}%` }} {...slot(n.code)}>
                <TreeConnector node={n} first={i === 0} last={i === nodes.length - 1} running={!!working[n.code]} />
                <AgentNode node={n} busy={busy === n.code} onToggle={onToggle} working={working[n.code] ?? null} />
                {!(n.canToggle && (n.state === "ATTACHED" || n.state === "DETACHED")) && <span aria-hidden data-testid={`port-${n.code}`} className="absolute -top-[5px] hidden h-2.5 w-2.5 -translate-x-1/2 rounded-full @[640px]:block" style={{ left: "50%", background: attached ? "var(--accent)" : "var(--bg-base)", boxShadow: attached ? "0 0 8px var(--hub-glow)" : undefined, border: `2px solid ${attached ? "var(--accent)" : "rgba(140,148,138,0.6)"}` }} />}
              </li>
            );
          })}
        </ul>
      </div>
      <CanvasLegend />
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
    <ul className="m-0 mt-2 flex list-none flex-wrap items-center justify-center gap-x-4 gap-y-1 p-0 t-meta" style={{ color: "var(--text-5)" }} aria-label="Legend" data-testid="canvas-legend">
      {item("Connected", <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--positive)" }} />)}
      {item("Removed", <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--text-6)" }} />)}
      {item("Checking", <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: "var(--warning)" }} />)}
      {item("Wired to this conversation", <span aria-hidden className="block w-5" style={{ borderTop: "2px dashed var(--accent)" }} />)}
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
    <span aria-hidden className="@[640px]:hidden" data-testid={`tree-wire-${node.code}`}>
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

function AgentNode({ node, busy, onToggle, working }: { node: CanvasNode; busy: boolean; onToggle: (c: AgentCode, attach: boolean) => void; working: string | null }) {
  const meta = agentMeta(node.code);
  const live = node.state === "ATTACHED";
  const dead = node.state === "LOCKED" || node.state === "NO_ACCESS";
  const icon: IconName = dead ? "lock" : meta.icon;
  return (
    <div
      data-testid={`agent-node-${node.code}`}
      data-state={node.state}
      className={`mt-glow-card ${live ? "" : "mt-glow-card--off"} ${working ? "mt-agent-glow" : ""} relative flex h-full flex-col items-center gap-0.5 rounded-lg px-1.5 py-1.5 text-center`}
    >
      {node.canToggle && (node.state === "ATTACHED" || node.state === "DETACHED") && (
        <button
          type="button"
          data-testid={`${live ? "remove" : "attach"}-${node.code}`}
          disabled={busy}
          aria-label={live ? `Remove ${node.name} from the CEO` : `Reconnect ${node.name} to the CEO`}
          title={live ? "Remove from the CEO: not used for new work in this conversation" : "Reconnect to the CEO"}
          onPointerDown={(e) => e.stopPropagation()} /* a click here is never the start of a card drag */
          onClick={() => onToggle(node.code, !live)}
          className="mt-focus absolute -top-2.5 left-1/2 z-[4] flex h-5 w-5 -translate-x-1/2 items-center justify-center rounded-full transition-colors"
          style={{ background: "var(--bg-popover)", border: `1px solid ${live ? "var(--border-hover)" : "var(--accent)"}`, color: live ? "var(--text-4)" : "var(--accent)", opacity: busy ? 0.5 : 1 }}
        >
          <Icon name={live ? "close" : "plus"} size={11} strokeWidth={2.2} />
        </button>
      )}
      <span className="flex items-center gap-1.5" style={{ color: live ? HUE[node.code] : dead ? "var(--text-7)" : "var(--text-4)" }}>
        <Icon name={icon} size={16} strokeWidth={1.6} />
        <span className="min-w-0 break-words t-meta font-semibold leading-tight" style={{ color: dead ? "var(--text-5)" : "var(--text-1)" }}>{node.name}</span>
      </span>
      <span className="block break-words t-micro leading-tight" style={{ color: "var(--text-5)" }}>{TAGLINE[node.code]}</span>
      <span className="flex items-center gap-1 t-micro" style={{ color: live ? "var(--accent)" : "var(--text-5)" }}>
        {working ? <Spinner size={9} /> : <span aria-hidden className="h-1.5 w-1.5 flex-shrink-0 rounded-full" style={{ background: live ? "var(--positive)" : node.state === "UNKNOWN" ? "var(--warning)" : "var(--text-6)" }} />}
        {working ?? STATE_LABEL[node.state]}
      </span>
      {meta.href && !dead && (
        <Link href={meta.href} data-testid={`workspace-${node.code}`} className="mt-focus inline-flex min-h-5 items-center self-center t-micro font-bold" style={{ color: "var(--text-3)" }}>
          {meta.workspaceLabel ?? "Open"} &rarr;
        </Link>
      )}
      {node.state === "LOCKED" && (
        <span className="t-micro" style={{ color: "var(--text-6)" }}>Not available on your current plan.</span>
      )}
    </div>
  );
}
