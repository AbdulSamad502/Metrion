import { Card, CardCta } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { agentMeta, agentTier, TIER_LABEL } from "@/lib/agents";
import type { AgentStatus } from "@/lib/api";

/** One agent, answering five questions in reading order: who is it, what does it do, is it
 * available, what did it last do, and where do I go next. Presence follows the tier — a wired
 * agent is elevated glass with the accent; an available one is plain glass; an unbuilt one is
 * visibly dead and is NOT clickable (there is nowhere to go).
 *
 * The whole card is the link when a workspace exists, so the target is large and the card is one tab
 * stop; the arrow label is the always-visible affordance.
 *
 * `lastActivity`: an ISO timestamp when the backend records one for this agent, `null` when it does
 * but nothing has happened yet, `undefined` when the backend does not track it at all. */
export function AgentCard({ agent, lastActivity }: { agent: AgentStatus; lastActivity?: string | null }) {
  const meta = agentMeta(agent.id);
  const tier = agentTier(agent);
  const live = tier === "connected";
  const dead = tier === "unavailable";

  return (
    <Card
      href={meta.href}
      variant={live ? "elevated" : dead ? "locked" : "default"}
      selected={false}
      ariaLabel={meta.href ? `${agent.name}, ${TIER_LABEL[tier]}. ${meta.workspaceLabel ?? "Open"}` : undefined}
      className="h-full"
    >
      <div className="flex h-full flex-col gap-3.5 p-4">
        <div className="flex items-start gap-3">
          <span
            className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl"
            style={{
              background: "var(--fill-hover)",
              color: live ? "var(--text-1)" : dead ? "var(--text-7)" : "var(--text-4)",
            }}
          >
            <Icon name={meta.icon} size={19} />
          </span>
          <div className="min-w-0">
            <div className="t-card-title break-words" style={{ color: dead ? "var(--text-5)" : "var(--text-1)" }}>
              {agent.name}
            </div>
            <div className="t-meta mt-1 flex items-center gap-1.5" style={{ color: live ? "var(--accent)" : "var(--text-5)" }}>
              <span
                aria-hidden
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: live ? "var(--accent)" : "transparent", border: live ? "none" : "1px solid var(--text-6)" }}
              />
              {TIER_LABEL[tier]}
            </div>
          </div>
        </div>

        <p className="t-body-sm" style={{ color: dead ? "var(--text-6)" : "var(--text-4)" }}>
          {meta.description}
        </p>

        <div className="mt-auto flex items-end justify-between gap-3">
          <div className="t-meta" style={{ color: "var(--text-5)" }}>
            {dead ? (
              "No activity — this agent does not exist yet."
            ) : lastActivity === undefined ? (
              "Activity is not recorded for this agent yet."
            ) : lastActivity === null ? (
              "No activity yet."
            ) : (
              <>
                Last activity <time dateTime={lastActivity}>{new Date(lastActivity).toLocaleString()}</time>
              </>
            )}
          </div>
          {meta.href ? (
            <CardCta>{meta.workspaceLabel ?? "Open"}</CardCta>
          ) : (
            <span className="t-meta flex-shrink-0 font-semibold" style={{ color: "var(--text-6)" }}>
              No workspace
            </span>
          )}
        </div>
      </div>
    </Card>
  );
}
