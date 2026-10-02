import Link from "next/link";
import { Icon } from "@/components/ui/Icon";
import { agentMeta, agentTier } from "@/lib/agents";
import type { AgentStatus } from "@/lib/api";

export type StageState = "live" | "idle" | "unavailable";

export type PipelineStage = {
  key: string;
  label: string;
  title: string;
  detail: string;
  state: StageState;
};

/** USER → CEO → SPECIALIST AGENTS → FINDINGS → SYNTHESIS → ACTION, as an operational status rail.
 * Each stage reports what is true right now (from real responses): `live` has working backing,
 * `idle` works but has nothing to show, `unavailable` needs a backend capability that does not
 * exist yet and is drawn as visibly disabled. Nothing here animates or invents activity. */
export function PipelineRail({ stages }: { stages: PipelineStage[] }) {
  return (
    <ol className="m-0 grid list-none grid-cols-1 gap-0 p-0 md:grid-cols-3 xl:grid-cols-6" aria-label="How a question becomes an action">
      {stages.map((s, i) => {
        const off = s.state === "unavailable";
        const live = s.state === "live";
        return (
          <li key={s.key} className="relative flex min-w-0 gap-3 py-3 md:flex-col md:gap-0 md:py-0 md:pr-4">
            <div className="flex items-center md:mb-3">
              <span
                aria-hidden
                className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full t-micro font-bold"
                style={{
                  color: live ? "var(--bg-base)" : off ? "var(--text-6)" : "var(--text-3)",
                  background: live ? "var(--text-3)" : "transparent",
                  border: live ? "none" : `1px ${off ? "dashed" : "solid"} ${off ? "var(--connector-inactive)" : "var(--border-hover)"}`,
                }}
              >
                {i + 1}
              </span>
              {i < stages.length - 1 && (
                <span
                  aria-hidden
                  className="ml-3 hidden h-px flex-1 xl:block"
                  style={{ background: live && stages[i + 1].state !== "unavailable" ? "var(--accent-border-default)" : "var(--connector-inactive)" }}
                />
              )}
            </div>
            <div className="min-w-0">
              <div className="mt-eyebrow" style={{ color: off ? "var(--text-7)" : undefined }}>
                {s.label}
              </div>
              <div className="mt-1 t-card-title font-semibold" style={{ color: off ? "var(--text-5)" : "var(--text-1)" }}>
                {s.title}
              </div>
              <div className="mt-1 t-body-sm leading-snug" style={{ color: off ? "var(--text-6)" : "var(--text-4)" }}>
                {off && <span className="sr-only">Not available. </span>}
                {s.detail}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** The star topology (CLAUDE.md: CEO star topology, fixed tool catalog) drawn from the real roster.
 * Presence follows the tier: a wired agent is solid and accented, one with only a workspace is a
 * neutral outline, one that does not exist yet is dashed and muted. */
export function AgentGraph({ agents }: { agents: AgentStatus[] }) {
  return (
    <div className="flex flex-col items-center">
      <div
        className="mt-panel mt-panel--elevated flex items-center gap-3 rounded-2xl px-5 py-3"
        style={{ boxShadow: "var(--glass-shadow-hover)" }}
      >
        <span style={{ color: "var(--text-1)" }}>
          <Icon name="ceo" size={22} />
        </span>
        <div>
          <div className="t-card-title font-bold leading-none" style={{ color: "var(--text-1)" }}>
            CEO
          </div>
          <div className="mt-1 t-meta" style={{ color: "var(--text-4)" }}>
            Dispatches from a fixed tool catalog
          </div>
        </div>
      </div>
      <ul className="m-0 grid w-full list-none grid-cols-2 gap-x-3 p-0 lg:grid-cols-4" aria-label="Specialist agents">
        {agents.map((a) => {
          const tier = agentTier(a);
          const meta = agentMeta(a.id);
          const live = tier === "connected";
          const dead = tier === "unavailable";
          const node = (
            <span
              className={`mt-chip mt-dash-card ${live ? "mt-dash-card--elevated" : ""} ${dead ? "mt-dash-card--locked" : ""} ${meta.href ? "mt-dash-card--interactive" : ""} flex h-full flex-col gap-1 rounded-xl px-3.5 py-3`}
              style={{
                borderColor: live ? "var(--accent-border-default)" : undefined,
                borderStyle: dead ? "dashed" : undefined,
                opacity: dead ? 0.7 : 1,
              }}
            >
              <span className="flex items-center gap-2">
                <span style={{ color: live ? "var(--accent)" : dead ? "var(--text-7)" : "var(--text-4)" }}>
                  <Icon name={meta.icon} size={16} />
                </span>
                <span className="t-body font-semibold leading-tight" style={{ color: dead ? "var(--text-5)" : "var(--text-1)" }}>
                  {a.name}
                </span>
              </span>
              <span className="t-meta" style={{ color: live ? "var(--accent)" : "var(--text-5)" }}>
                {live ? "Wired to CEO" : tier === "available" ? "Workspace only — not routed by CEO" : "Not built yet"}
              </span>
            </span>
          );
          return (
            <li key={a.id} className="flex flex-col items-center">
              <span
                aria-hidden
                className="h-6 w-0"
                style={{ borderLeft: `2px ${live ? "solid" : "dashed"} ${live ? "var(--accent-border-strong)" : "var(--connector-inactive)"}` }}
              />
              <span className="w-full flex-1">
                {meta.href ? (
                  <Link href={meta.href} className="mt-focus block h-full rounded-xl" title={`Open ${a.name}`}>
                    {node}
                  </Link>
                ) : (
                  node
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
