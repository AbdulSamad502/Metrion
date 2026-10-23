---
name: agent-orchestration-patterns
description: Metrion's CEO star topology, how agent_run.parent_run_id links a CEO turn to the sub-agent/Brain-1 runs it fans out to, and the fixed-tool-catalog constraint. Use when working on CEO orchestration, any agent's conversational or direct-execution path, agent_run logging, or the flow-visualization surface.
---

# CEO star topology

Source of truth: `docs/specs/ceo-agent-orchestration.md`, `AGENTS.md`.

**CEO owns all agent-to-agent routing. No agent calls another agent, ever.** PI never calls CI, CFO never calls CMO — there is no code path for it (C1). Every agent may call Brain 1 (and the GST Applicability Lookup) directly, but that's shared-service access, not delegation — CEO is not in that path at all.

Two execution paths, structurally decided (not by a runtime classifier):

- **Direct execution path** — a dashboard button hits a registered action on one agent directly. No CEO, no LLM call at all. Fast, and it's what makes the fast path fast.
- **Conversational path** — a chat message enters through CEO, which does exactly one classification pass, then either issues parallel Brain 1 reads or delegates to **exactly one** named agent, then makes exactly one synthesis call. Never a multi-turn LLM→tool→LLM chain (§6.3–6.5).

CEO's routing decision is advisory, never authoritative — the target action's own six-step `auth.md` §7.1 chain still runs and can still deny it (C8).

## `parent_run_id` — how a turn's runs connect

Every invocation, direct or conversational, writes one `agent_run` row (`ceo-agent-orchestration.md` §5, C7). For a conversational turn:

1. CEO's own turn-level row is written first, with `parent_run_id = NULL`.
2. Every row that turn fans out to — each Brain 1 bundle call, or the one delegated named-agent call — is written with `parent_run_id` set to that CEO row's `id` (§6.8).

A turn's full set of runs is exactly `{anchor row} ∪ {rows where parent_run_id = anchor_run_id}` — this is the reliable grouping key `agent-flow-visualization.md` uses to build the CEO → fan-out → synthesis diagram, no timestamp-overlap heuristics needed once this is populated correctly.

**Don't:** invent a second correlation field, group by `investigation_id` + timing as anything but a documented legacy fallback, or set `parent_run_id` on a direct-path row (direct-path runs have no CEO turn to parent to).

## Fixed tool catalog — no freeform code generation

From `AGENTS.md`: **CEO orchestration uses a fixed tool catalog. No LLM-generated SQL or Python execution, in any agent, ever.** (`OP10` in the readiness review.) Every calculation path is a typed, pre-built, tested tool the LLM calls — the model chooses *which* tool and *what arguments*, never writes the computation itself. This is also why there's no LangGraph or similar dynamic-graph orchestration framework in this codebase: the topology is fixed (star, CEO-brokered), not something an agent negotiates at runtime.

If you find yourself building a code path where a model's output is executed as SQL/Python, or where an agent is given a general "call any tool" capability instead of a pre-registered one — stop, that's outside the locked architecture.
