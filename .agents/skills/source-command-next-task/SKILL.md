---
name: "source-command-next-task"
description: "Suggest the next task respecting build dependency order"
---

# source-command-next-task

Use this skill when the user asks to run the migrated source command `next-task`.

## Command Template

Suggest **one** next task. Respect this dependency order strictly — don't suggest something downstream just because it looks more interesting:

1. **Deterministic engine** (`docs/specs/deterministic-engine.md`) and **auth/tenancy** (`docs/specs/auth.md`) — foundational, before anything else.
2. **Individual agents** (`docs/specs/cfo-agent.md`, `docs/specs/competitor-intelligence-agent.md`, `docs/specs/product-intelligence-agent.md`, `docs/specs/slim-cmo-agent.md`) — before CEO orchestration.
3. **CEO orchestration** (`docs/specs/ceo-agent-orchestration.md`) — before flow visualization.
4. **Flow visualization** (`docs/specs/agent-flow-visualization.md`) and **WhatsApp** (`docs/specs/whatsapp-integration.md`) — last; both depend on `agent_run` and investigations already existing.

Run `/status` first (or use its recent output) to see what's actually built, then pick the next task honoring both the order above and current progress. State the one task and the one-line reason it's next — not a full roadmap.
