# Mechanical setup log

Record of the Claude Code tooling and repo-layout setup done before any implementation
began, so it's fast to review without reconstructing it from conversation history.

---

## 1. Commands — `.claude/commands/`

| File | Purpose |
|---|---|
| `spec-feature.md` | Create/update a spec for a named feature before implementation begins. Refuses if no feature is named. |
| `implement.md` | Implement code against an existing spec. Refuses and points to `/spec-feature` if the spec doesn't exist yet. |
| `review.md` | Code review pass for Metrion's core invariants: no money math outside the engine, tenant_id/RLS present, no spec contradictions. |
| `status.md` | Summarize what's built against the current scope-of-record doc. |
| `next-task.md` | Suggest the next task, respecting dependency order (engine/auth → agents → CEO orchestration → flow viz/WhatsApp). |

## 2. Skills — `.claude/skills/`

| Skill | Purpose |
|---|---|
| `metrion-domain/` | Indian e-commerce fee/GST/marketplace terminology, pulled from `deterministic-engine.md` and `cfo-agent.md`. |
| `deterministic-engine-rules/` | The money-math-never-via-LLM rule, with before/after examples. |
| `agent-orchestration-patterns/` | CEO star topology, `agent_run.parent_run_id`, the fixed-tool-catalog constraint. |

Audited for token efficiency in a later pass — found already concise, no changes applied.

## 3. Subagents — `.claude/agents/`

`spec-reviewer.md` (pre-existing) was deleted by the user before this work began. Confirmed
empty before creating anything new — no duplication.

| Agent | Tools | Model |
|---|---|---|
| `architect.md` | Read, Grep, Glob, Write, Edit | sonnet |
| `backend-engineer.md` | Read, Grep, Glob, Edit, Write, Bash | sonnet |
| `frontend-engineer.md` | Read, Grep, Glob, Edit, Write, Bash | sonnet |
| `code-reviewer.md` | Read, Grep, Glob (read-only) | sonnet |

Audited for token efficiency in a later pass: `auth.md` §7.3's RLS SQL pattern and
`CLAUDE.md`'s spec template were inlined directly into `architect.md`/`backend-engineer.md`/
`code-reviewer.md` to avoid a full-file read on every invocation. `frontend-engineer.md`
needed no changes.

**Standing rule (user instruction):** none of these subagents are invoked without explicit
permission per instance — Claude does not spawn them proactively.

## 4. Pre-commit hook — `.claude/hooks/pre-commit`

Blocks a commit if any staged `.py` file under `packages/calc-engine/` imports a known
LLM/AI provider library (openai, anthropic, langchain*, llama_index, cohere, mistralai,
google.generativeai, ollama, transformers, vertexai). Enforces CLAUDE.md's hard rule: the
deterministic engine never imports an LLM, not even the local Ollama client.

- Activated via `git config core.hooksPath .claude/hooks` — **local git config, not
  version-controlled.** Every clone/machine must run this once:
  ```bash
  git config core.hooksPath .claude/hooks
  ```
- Tested end-to-end: a staged file importing `openai` was correctly blocked; a clean file
  with no provider import was correctly allowed through. Both test artifacts were removed
  afterward and no test commits were left in history.

This step was originally blocked because `deterministic-engine.md` never states a code
directory and repo layout was an open item (readiness review 2.5). Resolved in the
same session — see §5 below — then the hook was written against the confirmed path.

## 5. Repo layout decision (readiness review item 2.5, resolved)

Monorepo, confirmed with the user:

- `packages/calc-engine/` — the deterministic engine (Brain 1). Only Python/SQL, no LLM
  imports, enforced by the hook above.
- `backend/` — FastAPI application (agents, orchestration, auth, API).
- `frontend/` — Next.js App Router application.

All three currently contain only a placeholder `README.md` — no implementation yet.
`docs/planning/phase-1-readiness-review.md` item 2.5 updated to RESOLVED accordingly.

---

**Not done in this pass:** the six specs flagged in `docs/planning/pending-reviews.md`
(`ceo-agent-orchestration`, `cfo-agent`, `competitor-intelligence-agent`,
`product-intelligence-agent`, `slim-cmo-agent`, `whatsapp-integration`) still need their
consistency audit — tracked as a separate step, not folded into this mechanical setup.
