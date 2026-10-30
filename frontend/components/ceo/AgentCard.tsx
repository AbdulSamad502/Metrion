import Link from "next/link";
import { Icon } from "@/components/ui/Icon";
import { agentMeta, agentTier, LOCK_LABEL, TIER_LABEL, type RosterAgent } from "@/lib/agents";
import "@/components/overview/overview.css";

/** One agent, answering five questions in reading order: who is it, what does it do, is it
 * available, what did it last do, and where do I go next. A wired agent has a green dot; an
 * available one a grey dot; an unbuilt or locked one is dimmed and is NOT clickable (there is
 * nowhere to go).
 *
 * The whole card is the link when a workspace exists, so the target is large and the card is one tab
 * stop; the arrow label is the always-visible affordance.
 *
 * `lastActivity`: an ISO timestamp when the backend records one for this agent, `null` when it does
 * but nothing has happened yet, `undefined` when the backend does not track it at all. */
export function AgentCard({ agent, lastActivity }: { agent: RosterAgent; lastActivity?: string | null }) {
  const meta = agentMeta(agent.id);
  const tier = agentTier(agent);
  const live = tier === "connected" && !agent.lock;
  const locked = Boolean(agent.lock); // the backend says this member cannot use it: say so and offer no link
  const dead = tier === "unavailable" || locked;
  const href = locked ? undefined : meta.href;
  const stateLabel = agent.lock ? LOCK_LABEL[agent.lock] : TIER_LABEL[tier];

  const body = (
    <>
      <span className="ov-agent-top">
        <span className="ov-badge-circle" style={dead ? { background: "var(--ov-soft)", color: "var(--ov-ink-3)" } : undefined}>
          <Icon name={meta.icon} size={20} />
        </span>
        <span className="ov-pill">
          <i className={`ov-dot${live ? " ov-dot--good" : ""}`} aria-hidden />
          {stateLabel}
        </span>
      </span>

      <span style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span className="ov-title" style={dead ? { color: "var(--ov-ink-3)" } : undefined}>{agent.name}</span>
        <span className="ov-body" style={{ fontSize: "var(--ov-s1)", lineHeight: 1.5 }}>{meta.description.split(/(?<=\.)\s/)[0]}</span>
      </span>

      <span style={{ marginTop: "auto", display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 16 }}>
        <span className="ov-meta">
          {dead ? (
            locked ? (
              "Activity is not shown while this agent is locked for you."
            ) : (
              "No activity — this agent does not exist yet."
            )
          ) : lastActivity === undefined ? (
            "No activity recorded yet."
          ) : lastActivity === null ? (
            "No activity yet."
          ) : (
            <>
              Last activity <time dateTime={lastActivity}>{new Date(lastActivity).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}</time>
            </>
          )}
        </span>
        {href ? (
          <span className="ov-title" style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--ov-brand-ink)", whiteSpace: "nowrap" }}>
            {meta.workspaceLabel ?? "Open"} <Icon name="arrow" size={14} strokeWidth={2} className="ov-arrow" />
          </span>
        ) : (
          <span className="ov-meta" style={{ flexShrink: 0, fontWeight: 700 }}>{locked ? "Locked" : "No workspace"}</span>
        )}
      </span>
    </>
  );

  return href ? (
    <Link href={href} className="ov-agent" style={{ height: "100%" }} aria-label={`${agent.name}, ${stateLabel}. ${meta.workspaceLabel ?? "Open"}`}>
      {body}
    </Link>
  ) : (
    <div className="ov-agent" style={{ height: "100%", opacity: dead ? 0.8 : 1 }}>
      {body}
    </div>
  );
}
