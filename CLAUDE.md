# Metrion — Project Instructions

## Mission

Metrion is an AI profit-optimization OS for Indian e-commerce sellers on Amazon,
Flipkart and Meesho. Sellers **upload** marketplace reports — there are no seller-side
marketplace API integrations — and Metrion turns those files into true contribution
profit, finds the leaks, and recommends what to do next. The product loop is
**ASK → UNDERSTAND → TRUST → DECIDE → ACT**: the seller asks in plain language, Metrion
understands the question against their own data, every figure carries enough provenance
to be *trusted*, the seller decides, and Metrion acts — **recommend-only**, never writing
back to a marketplace. TRUST is the load-bearing step. A number a seller cannot trace is
worse than no number at all.

## Stack

- **Frontend** — Next.js (App Router), React, TypeScript
- **Backend** — Python, FastAPI
- **Database** — PostgreSQL, with Row-Level Security (`FORCE`) as the isolation boundary
- **Vector / RAG** — pgvector, in the same Postgres. *Not Qdrant* (V1 decision; Qdrant is a documented future migration path only)
- **Cache / queues** — Redis
- **Identity** — Clerk, using Clerk Organizations (one Organization = one tenant)
- **Payments** — Razorpay
- **WhatsApp** — via a BSP (Gupshup / Interakt), not the direct Meta Cloud API
- **LLM** — local Ollama in dev, always behind a provider abstraction; vision behind a separate `VisionProvider` slot
- **Agent orchestration** — CEO star topology, fixed tool catalog. No LLM-generated SQL or Python. No LangGraph.

## The hard rule: LLMs explain numbers, they never compute them

**Any calculation that touches money lives in the deterministic engine (Brain 1) — Python
and SQL, unit-tested, no LLM in the path.** An LLM may narrate, explain, rank-by-judgement
or caveat a figure. It may never originate one, re-derive one, or sum a set of them.

This is not a style preference. It is the architectural constraint the whole product rests
on, and it is the first thing to check in any code review.

- If you are about to write arithmetic on money anywhere outside the engine — stop. It belongs in the engine.
- All money is signed `BIGINT` **paise**. No floats in any calculation path, frontend included.
- A missing input is **not zero**. It yields `UNAVAILABLE`, flagged, never a silent default.
- Every displayed figure cites an `engine_result_ref` (or, for estimates, an `estimate_ref` — different contract, never interchangeable).

Full detail, formulas, confidence model and acceptance criteria: `docs/specs/deterministic-engine.md`.
Do not restate or reimplement any of it elsewhere.

## Multi-tenancy

**Every tenant-owned table carries `tenant_id`, and every query is tenant-scoped.** Isolation
is defence-in-depth: Postgres RLS is the final boundary, application-level filtering sits
above it, and neither is trusted alone. Missing tenant context **fails closed**. No endpoint
ever accepts a client-supplied `tenant_id`. Frontend filtering is never a security mechanism.

A cross-tenant leak is existential — treat isolation as a first-class requirement of every
change, not a hardening pass. Mechanism, roles, `SET LOCAL` context handling, worker scoping
and the permission grid: `docs/specs/auth.md` (§1.4, §7.3).

## Where things live

| Path | What it holds |
|---|---|
| `docs/specs/*.md` | One spec per feature area. The authority for that feature. |
| `docs/planning/phase-1-readiness-review.md` | **Decisions of record.** Locked decisions, superseded plan items, and every open `[B]`/`[P]`/`[D]` ambiguity. |
| `docs/planning/metrion-master-plan.pdf` | Original plan. Substantially superseded — check the readiness review before trusting anything in it. |
| `docs/design/design_status.md` | Branding, colors, typography and UI are **not final**. Keep them configurable; never couple business logic to them. |
| `.claude/agents/spec-reviewer.md` | Reviews drafted specs against locked decisions. Run it after writing a spec, before coding. |

**Before implementing any feature, read its spec in `docs/specs/` first. If a spec doesn't
exist, write one before coding.** Never infer a feature's behaviour from the code, the
mockups, or the master plan PDF — infer it from the spec, and if the spec is silent, that
is an open question to raise, not a gap to fill with a guess.

New specs follow the existing section template: Confirmed decisions · Design decisions
requiring review · Assumptions · Goals and non-goals · Data model · Core rules · AI
requirements · Authorization and security · Edge cases · Production-validation blockers ·
Acceptance criteria · Test scenarios · Explicit open questions.

## Git

- **Branches** — `type/short-description`, e.g. `feat/margin-curve`, `fix/rls-worker-context`, `spec/entitlement`, `docs/claude-md`
- **Commits** — `type(scope): imperative summary`, e.g. `feat(engine): add largest-remainder allocation`. Types: `feat`, `fix`, `spec`, `docs`, `test`, `refactor`, `chore`
- Never commit or push unless asked. Never commit directly to `main`.

## Definition of Done

A change is done when **the acceptance criteria and test scenarios in its own spec pass** —
every spec carries both, and they are the contract. Concretely:

- Every acceptance criterion in the relevant spec is satisfied, or explicitly deferred in writing.
- Tests exist for that spec's test scenarios. Any money-touching path has deterministic unit tests.
- Tenant isolation holds — verified, not assumed.
- Anything genuinely undecided is recorded in the spec's **Explicit open questions**, never silently resolved.

## Model usage

Default to **Sonnet** for implementation work — writing code, tests, specs to an agreed
shape, and refactors. Reserve **Opus** for architecture-level ambiguity: cross-spec
conflicts, decisions that change the data model or the brain boundaries, and anything where
the right answer is genuinely unclear. Routine coding does not need Opus.
