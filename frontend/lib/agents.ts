"use client";

import { PAGE_COPY } from "@/lib/navigation";
import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState, useRef } from "react";
import type { IconName } from "@/components/ui/Icon";
import { friendlyApiError } from "@/lib/apiErrors";
import { apiFetch, type AgentStatus } from "@/lib/api";
import type { AgentAvailability } from "@/lib/ceo";

/** Presentation metadata for the agents the backend roster can return. The roster itself
 * (`GET /api/v1/ceo-hub/agents`) only carries id / name / CONNECTED|NOT_CONNECTED — what each
 * agent does and where its workspace lives is UI knowledge, kept here in one place.
 *
 * `href` is set only when a real workspace page exists. An agent without one (CMO) renders as
 * "no workspace yet" — never as a screen that pretends to work. (CMO has one since P9.) */
export type AgentMeta = {
  role: string;
  description: string;
  icon: IconName;
  href?: string;
  workspaceLabel?: string;
};

const AGENT_META: Record<string, AgentMeta> = {
  CI: {
    role: "Competitor Intelligence",
    description: "Tracks competitor prices and availability from evidence you provide, and flags what changed.",
    icon: "competitors",
    href: "/dashboard/competitors",
    workspaceLabel: `Open ${PAGE_COPY.competitors.title}`,
  },
  PI: {
    role: "Product Intelligence",
    description: "Finds niches and candidate products, checks feasibility against your costs, shortlists suppliers.",
    icon: "products",
    href: "/dashboard/pi",
    workspaceLabel: `Open ${PAGE_COPY.products.title}`,
  },
  CFO: {
    role: "Finance",
    description: "Reconciles settlements, computes true contribution profit, GST and leaks from your uploaded reports.",
    icon: "finance",
    href: "/dashboard/cfo",
    workspaceLabel: `Open ${PAGE_COPY.cfo.title}`,
  },
  CMO: {
    role: "Marketing",
    description: "Writes marketplace titles and listing copy, answers catalog questions and researches your niche — as text for you to copy; it never publishes anything.",
    icon: "marketing",
    href: "/dashboard/cmo",
    workspaceLabel: `Open ${PAGE_COPY.cmo.title}`,
  },
};

const FALLBACK: AgentMeta = { role: "Agent", description: "No description available.", icon: "agents" };

/** How a specialist's availability is worded everywhere (Overview, Agents, the diagram), so one state never has three names. */
export const TIER_LABEL: Record<AgentTier, string> = {
  connected: "Works with Ask Metrion",
  available: "Own page only",
  unavailable: "Not built yet",
};

export function agentMeta(id: string): AgentMeta {
  return AGENT_META[id] ?? FALLBACK;
}

/** The backend's roster (`GET /ceo-hub/agents`) is a fixed list that still marks Product Intelligence and the CFO as not connected, although the CEO registry has
 * wired actions for both. What the CEO can really run for this member is `GET /ceo/agents/availability` (permission, plan and wired chat actions), so an agent that
 * answers PRESENT with at least one chat action is shown as connected. An agent the member may not use, or one the plan excludes, is left as the roster says. */
export function withChatAvailability(roster: AgentStatus[], availability: Partial<AgentAvailability> | null | undefined): AgentStatus[] {
  if (!availability) return roster;
  return roster.map((a) => {
    const live = (availability as Record<string, { status?: string; chatActions?: number } | undefined>)[a.id];
    return live && live.status === "PRESENT" && typeof live.chatActions === "number" && live.chatActions > 0 ? { ...a, status: "CONNECTED" as const } : a;
  });
}

/** Loads the real agent roster. `status` is what the backend reports about CEO routing
 * ("CONNECTED" = the CEO can dispatch to this agent) — it is NOT an entitlement or a
 * per-investigation attachment, and the UI must not present it as either. */
export function useAgentRoster() {
  const { getToken } = useAuth();
  const [agents, setAgents] = useState<AgentStatus[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const alive = useRef(true); // a reply that arrives after the page is gone must not update it
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  const load = useCallback(async () => {
    try {
      const token = await getToken();
      const [list, live] = await Promise.all([
        apiFetch<AgentStatus[]>("/api/v1/ceo-hub/agents", token),
        // best effort: a member without the CEO key, or a failed read, simply keeps the roster's own statuses
        apiFetch<AgentAvailability>("/api/v1/ceo/agents/availability", token).catch(() => null),
      ]);
      if (!alive.current) return;
      setAgents(withChatAvailability(list, live));
      setError(null);
    } catch (e) {
      if (alive.current) setError(friendlyApiError(e, "Could not reach the backend"));
    }
  }, [getToken]);

  useEffect(() => {
    (async () => {
      await load();
    })();
  }, [load]);

  return { agents, error, reload: load };
}

/** How prominently an agent should be shown (CEO Hub / Agents):
 *  connected    the backend reports it as wired to the CEO — strongest presence
 *  available    not wired to the CEO, but it has a working workspace — secondary
 *  unavailable  no workspace at all — visibly disabled */
export type AgentTier = "connected" | "available" | "unavailable";

export function agentTier(agent: AgentStatus): AgentTier {
  if (agent.status === "CONNECTED") return "connected";
  return agentMeta(agent.id).href ? "available" : "unavailable";
}
