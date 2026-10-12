# UI/UX Phase 2 — notes, backend dependencies and tracked gaps

Companion to `ui-ux-phase1-audit.md`. Date: 2026-10-09.

## 1. Planning and approval states (decision 1) — backend change required, NOT yet built

**Decision:** implement planning and approval for *consequential* actions; informational questions need no approval.

**Why the UI cannot do it alone.** The turn lifecycle the backend reports is `DELIVERED | CLARIFIED | DENIED | FAILED` (investigation: `ACTIVE | RESOLVED | ARCHIVED`). A turn is classified, executed, synthesised and returned in one request; there is no stored plan and no pause point. A UI-only "Approve" button would be decoration — the work would already have run. Per `CLAUDE.md`, an LLM must not decide what code runs, so the plan must be produced by the deterministic classifier/registry, not by the model.

**Also note:** per `ceo-agent-orchestration.md` C21 V1 has no `WRITE` effect; every registered action is `READ`, `COMPUTE_PERSIST`, `GENERATE_METERED` or `RECORD_CHOICE`. "Consequential" therefore has to be defined in the spec before any gate is built. Candidates (to be decided in the spec, not here): `GENERATE_METERED` (consumes quota/entitlement), `COMPUTE_PERSIST` that creates a saved result, multi-agent playbooks (several metered legs), and anything that sends text to an outside research service (CMO market trends).

**Required backend work (needs an `architect` spec change first — it touches the turn state machine and data model):**
1. Spec: define "consequential" per action in the registry (a flag on the action, e.g. `requires_approval`), and the plan contents (outcome, agents, integrations, assumptions, metered units) as a deterministic render of the registry entry + classifier slots — no LLM text.
2. Migration: turn statuses `PLANNED` / `AWAITING_APPROVAL` (+ `APPROVED`/`DECLINED`), a persisted plan row or JSON on `investigation_turn`, CHECK constraints, RLS unchanged (tenant-owned), app role privileges narrowed (append-only history, per 0007/0011).
3. API: `POST …/turns` returns a plan for consequential routes instead of executing; `POST …/turns/{id}/approve|decline`. An answer to a clarification must never auto-approve (separate explicit call, requires the same permission the action needs).
4. Tests: approval cannot be skipped by replaying the turn; clarification answer ≠ approval; cross-tenant approve is refused; entitlement re-checked at approval time.

**Frontend, already in place for this:** `ExecutionPanel` has a single place to add `PLANNED` / `AWAITING_APPROVAL` once the backend reports them (`executionStatusOf`). Until then those states are not shown.

## 2. Portfolio profit/margin endpoint (decision 3) — tracked separately

**Gap:** the backend has no portfolio-level revenue/profit/margin endpoint. CFO computes per request (`POST /cfo/pnl`, `/period-comparison`, `/financial-health`) and the CEO exposes only the latest *saved* results (`GET /ceo/state/health`).

**Phase 2 behaviour:** the Overview "Profit snapshot" renders exactly those saved results (period, as-of, provenance) and, when none exist, says so and links to upload. Nothing is summed or trended in the browser.

**To build (engine/backend, not UI):** a read-only endpoint over persisted `metric_result` rows returning, per period, revenue / net profit / margin with `engine_result_ref`s and an explicit `UNAVAILABLE` + reason when inputs are missing; spec addition in `deterministic-engine.md` / `cfo-agent.md`; RLS-scoped tests. Until it lands, the Overview must keep its "combined profit trend is not available yet" line.

## 3. Workflow editor (decision 2) — scope for Phase 4
Attach/detach per investigation via the existing `PUT /ceo-hub/investigations/{id}/agents/{code}` only. Canvas/connector rendering will be rebuilt (measured ports) in Phase 4; arbitrary visual connections will not be presented as routing. Free-form workflow persistence is deferred until the backend supports it.

## 4. Workflow reference image (decision 4)
No image is attached to the conversation or present in the repository, so the black-connector cause is still an inference from code (see Phase 1 §6). It will be confirmed in Phase 4 if the image is supplied.

## 5. Phase 2 implementation summary
See the Phase 2 checkpoint report in the conversation for files changed and verification.
