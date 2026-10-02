"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import type { IconName } from "@/components/ui/Icon";
import { ApiError, apiFetch, type AgentStatus } from "@/lib/api";

/** Presentation metadata for the agents the backend roster can return. The roster itself
 * (`GET /api/v1/ceo-hub/agents`) only carries id / name / CONNECTED|NOT_CONNECTED — what each
 * agent does and where its workspace lives is UI knowledge, kept here in one place.
 *
 * `href` is set only when a real workspace page exists. An agent without one (CMO) renders as
 * "no workspace yet" — never as a screen that pretends to work. */
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
    workspaceLabel: "Open Competitors",
  },
  PI: {
    role: "Product Intelligence",
    description: "Finds niches and candidate products, checks feasibility against your costs, shortlists suppliers.",
    icon: "products",
    href: "/dashboard/pi",
    workspaceLabel: "Open Products",
  },
  CFO: {
    role: "Finance",
    description: "Reconciles settlements, computes true contribution profit, GST and leaks from your uploaded reports.",
    icon: "finance",
    href: "/dashboard/cfo",
    workspaceLabel: "Open CFO",
  },
  CMO: {
    role: "Marketing",
    description: "Not built yet. There is no marketing agent or workspace in this version.",
    icon: "marketing",
  },
};

const FALLBACK: AgentMeta = { role: "Agent", description: "No description available.", icon: "agents" };

export function agentMeta(id: string): AgentMeta {
  return AGENT_META[id] ?? FALLBACK;
}

/** Loads the real agent roster. `status` is what the backend reports about CEO routing
 * ("CONNECTED" = the CEO can dispatch to this agent) — it is NOT an entitlement or a
 * per-investigation attachment, and the UI must not present it as either. */
export function useAgentRoster() {
  const { getToken } = useAuth();
  const [agents, setAgents] = useState<AgentStatus[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      setAgents(await apiFetch<AgentStatus[]>("/api/v1/ceo-hub/agents", token));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reach the backend");
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
