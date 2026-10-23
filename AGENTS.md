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
- **Backend** — Python, **FastAPI only**. Confirmed decision: Flask is not added alongside it — one web framework, no fragmentation. (Pydantic is FastAPI's request/response validation layer, already in use on every route — not a separate future adoption.)
- **Database** — PostgreSQL, with Row-Level Security (`FORCE`) as the isolation boundary. **Confirmed decision: MySQL is not adopted**, for this or any other core store — Postgres RLS *is* the multi-tenancy security boundary (see below), and MySQL has no equivalent. A different engine for a genuinely separate concern (e.g. an analytics warehouse) is a new, explicit decision to raise when that need is real, not a default.
- **Vector / RAG** — pgvector, in the same Postgres. *Not Qdrant* (V1 decision; Qdrant is a documented future migration path only)
- **Cache / queues** — Redis
- **Runtime / infra** — Docker (Docker Compose locally for Postgres/Redis; the same containers this project's tests run against). Formalized here because it already is the de facto runtime, not a new addition.
- **Identity** — Clerk, using Clerk Organizations (one Organization = one tenant)
- **Payments** — Razorpay
- **WhatsApp** — via a BSP (Gupshup / Interakt), not the direct Meta Cloud API
- **LLM** — local Ollama in dev, always behind a provider abstraction (`LlmProvider`: `complete(model, prompt) -> str`, text in/text out, no numeric parameter anywhere in the interface — this shape is deliberate, see the hard rule below); vision behind a separate `VisionProvider` slot
- **Agent orchestration** — CEO star topology, fixed tool catalog. No LLM-generated SQL or Python. **No LangGraph, no LangChain-as-orchestrator** — confirmed decision, reaffirmed explicitly when reconsidered: an LLM must never silently decide what code runs or touch a number, which is exactly what a fixed, hand-rolled tool catalog (`ceo_hub.py`'s dispatch functions) enforces structurally and a general agent framework's tool-calling loop does not. **LangChain is permitted only for narrow, non-orchestration utilities** — e.g. a document loader or text-splitter feeding pgvector ingestion for RAG — never for agent routing, never wrapping a `dispatch_cfo_*`/CEO-hub call, never anywhere an LLM's output could change which deterministic function runs.
- **Data analytics / parsing** — pandas, openpyxl and equivalents for marketplace-report ingestion (`data-foundation`'s adapters) — already in real use, not a future addition.
- **Web scraping** — httpx-based fetchers behind a `Fetcher` Protocol, hardcoded domain allowlists (`competitor-intelligence`'s pattern, reused by the GST Applicability Lookup) — already in real use.
- **NLP (non-LLM)** — permitted for narrow, deterministic text-matching jobs (e.g. GST/HSN description matching) where a classical technique is a better fit than an LLM call — never for anything that produces or adjusts a money figure, which stays inside the hard rule below regardless of technique.
- **ML / DL** — **statistical only at V1, no trained models** (`docs/planning/phase-1-readiness-review.md` C13, confirmed; built as Brain 2's anomaly engine — z-score, percentile threshold, period-over-period delta). A trained-model path (PyTorch, MLOps, drift monitoring) is a legitimate V2+ upgrade, but reopening C13 is its own explicit product decision — training-data sourcing, monitoring, and eval strategy all need deciding *before* any model code, not a retrofit onto existing statistical code.
- **LLM evals** — required for any new Brain-3 narration surface (a prompt template, an extraction step like the GST Applicability Lookup's, a new `narrate_*` composition). At minimum: does it ever state a number not present in its cited figures/`FigureToken`s, does it drop a required disclaimer, does it narrate a non-result (`AnomalyInsufficientHistory`-style) as if it were a real negative result. This was a real, missing practice as of this note — add eval coverage alongside the narration code, not after.

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

**Before implementing any feature, read its spec in `docs/specs/` first. If a spec doesn't
exist, write one before coding.** Never infer a feature's behaviour from the code, the
mockups, or the master plan PDF — infer it from the spec, and if the spec is silent, that
is an open question to raise, not a gap to fill with a guess.

New specs follow the existing section template: Confirmed decisions · Design decisions
requiring review · Assumptions · Goals and non-goals · Data model · Core rules · AI
requirements · Authorization and security · Edge cases · Production-validation blockers ·
Acceptance criteria · Test scenarios · Explicit open questions.

## Git

- **Branches** — `type/short-description`, e.g. `feat/margin-curve`, `fix/rls-worker-context`, `spec/entitlement`, `docs/Codex-md`
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
