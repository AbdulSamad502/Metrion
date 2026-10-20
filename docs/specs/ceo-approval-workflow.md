# Metrion — CEO Approval Workflow Specification

**Status:** Revision 5, for review (S0 complete: VP-1 FAIL, VP-2 FAIL; owner decisions Q-S0-1…4 and Q-R1…10 applied; prerequisite remediation R0–R7 designed, not implemented; unresolved facts F1–F10 listed in §12). **Nothing in this spec is implemented.** No migration, endpoint, permission or orchestrator change may be made until it is approved.
**Date:** 2026-10-10 (rev 1: 2026-10-09; rev 3 added the S0 results; rev 4 applied the billing/recovery decisions and linked the remediation design; rev 5 applies Q-R1…10)
**Extends:** `ceo-agent-orchestration.md` (turn pipeline §6.3–§6.14, decision cards §6.32, guided input §6.34, Q12) · `auth.md` (permission chain §7.1, RLS §7.3) · `entitlement.md` (meters) · `agent-flow-visualization.md` (node states).
**Related:** `docs/design/ui-ux-phase1-audit.md` §4, `ui-ux-phase2-notes.md` §1, `ui-ux-phase3-clarification.md`.

> **Amendment 2026-10-12 (owner decision CD4; adds to, does not rewrite, the text below).** Source: `ceo-cmo-delegation.md` §6.6. Where this block and a later section disagree, this block wins for the three points it names; every other rule stands.
>
> **1. In-chat plan card.** The plan is surfaced to the seller as a `PLAN` chat message in the CEO thread, rendered from the stored plan row. **Approve** and **Decline** are buttons on that card, shown only while `AWAITING_APPROVAL` and only to the requester (AC-A17); they call `POST …/approve` (with the card's `plan_hash`) and `POST …/decline`. The seller never needs the CMO (or any agent) dashboard to approve. This is the only approval surface; a typed "yes" is still **not** approval (C3, §6.4) — **owner-decided final, 2026-10-12 (`ceo-cmo-delegation.md` CD11)**: only an explicit click on the correct card, an API call bound to the plan id **and** `plan_hash`, can approve quota-consuming work; no typed phrase in any wording ever does, and the classifier has no approve intent or plan-id slot. **Image analysis (CD10, option A):** an attachment hand-off to a vision model is itself a small plan (`force_approval`, 0 CMO units, names the receiving endpoint label and model) approved by its own click, followed by a separate generation plan; quota is never charged twice for the same operation (the generation plan does not re-bill the analysis, a replay of an executed plan records no second meter event) and is never consumed by a failed, refused, `UNAVAILABLE` or `OUTCOME_UNKNOWN` leg. Whether the analysis plan's execution turn consumes a CEO conversation unit is open (`ceo-cmo-delegation.md` OQ-18). The card additionally lists, written by code, any **attachment hand-off** a leg performs (file, detected type, hash prefix, the receiving model endpoint label, trust-gate state, unit cost) with `data_basis` kind `ATTACHMENT`; an endpoint not in `LLM_OPERATOR_CONTROLLED_HOSTS` makes the integration `UNAVAILABLE` (E12) and is re-resolved at approval (§6.6 step 10). Title *choice* (`cmo.approve_title`) is a separate zero-unit record, never a plan approval.
>
> **2. Stale facts corrected (verified against the repository on 2026-10-12).**
> - **Migration numbering.** `20261011_0018_ceo_approval_workflow` (§13.6, §13.10, §14) **can no longer be used**: revision `20261012_0018` is `app_role_least_privilege` (down `20261011_0017`), and `20261012_0015_rag_foundation` (uncommitted) revises `20261012_0018`. Existing chain: `…0015_attachment_append_only` → `…0016_turn_status_planned` (R4, done) → `…0017_accounting_cutover` (R0, done) → `20261012_0018` → `20261012_0015` (rag). **Decided (owner, 2026-10-12, `ceo-cmo-delegation.md` CD9): the approval migration is `20261012_0019_ceo_approval_workflow` with `down_revision = "20261012_0015"`** (the RAG foundation migration, already in the working tree with passing tests, is the single head; the `0015`-over-`0018` id inversion is accepted; unrelated unfinished migration work is not merged). Wherever §13.6, §13.10 or §14 below say `20261011_0018_ceo_approval_workflow`, read `20261012_0019_ceo_approval_workflow` on `20261012_0015`. The implementer re-verifies exactly one head when writing it and, if another migration landed meanwhile, re-bases `down_revision` onto the then-single head and records it. It must create exactly what §13.6 lists (the `PLANNED` status is already in 0016). CI's `downgrade base` on an empty DB must still pass.
> - **Privileges.** `20261012_0018` revoked UPDATE/DELETE on `auth_audit` and `metered_event` and made reference/config tables read-only, but **default privileges still grant `metrion_app` full CRUD on every new table**; the explicit `REVOKE` plus column-level `UPDATE` in §5.4 remain mandatory, and `KNOWN_APP_DELETABLE` must stay accurate.
> - **R5 / VP-2 status (§14) may be stale.** `ceo/recovery.py` and `ceo/deadlines.py` (orchestration §6.42, 2026-10-11) implement ownership-based stuck-turn settlement and a hard leg deadline that §14 does not mention. Whether they satisfy VP-2 / the "P1 done" enablement gate, and whether the header's "VP-1 FAIL" is current given §14's "R0–R4, R6, R7 PASS", is an **unrecorded owner/architect restatement** (`ceo-cmo-delegation.md` OQ-9). Until restated, the text of §13/§14 is read as written.
> - **Chat status.** `cmo.generate_*` and `cmo.market_trends` remain refused from chat (D-8); CD4 makes enabling them depend on this workflow being implemented first.
>
> **3. §12 "Unresolved" items, classified (not decided).**
>
> | Item | Blocks | Needed |
> |---|---|---|
> | Q-A9 `CEO_PLAN_TTL_SECONDS` knob vs constant | **Blocks S2 (schema/config)** | Architect |
> | Q-A10 transition completeness mechanism (repo function only / `SECURITY DEFINER` / constraint trigger) | **Blocks S2 design** | Architect |
> | S1/S2/S3 boundary statement (§14; proposed in `ceo-approval-s1-readiness.md`) and P1 review acceptance | **Blocks S2 start** | Owner |
> | VP-1 / VP-2 restatement (OQ-9 above) and **F1** staleness threshold | Does not block schema work; **blocks enabling approval** (the "gate to enable approval at all") | Owner; F1 needs a calibration run |
> | Q-A4 reuse existing permission keys | Needed before S4 (approval endpoints); recommendation already stated | Architect |
> | Q-A7 D6 accounting consistency with `entitlement.md` | Needed before enablement (documentation) | Product |
> | Q-A8 how long declined/expired plans stay visible | Needed for S6 frontend only | UX |
> | F4 deployment environment | Blocks only the **periodic** reconciliation deployment | Owner / ops |
> | F5 third-party model endpoint disclosure policy | Does not block: operator-controlled hosts only (`LLM_OPERATOR_CONTROLLED_HOSTS`); blocks any future hosted endpoint | Owner |
> | F2 `OUT_OF_SCOPE` billing documentation; F6 `PARTIAL` data request billing; F7 "not available yet" unit | Do not block; documented behaviour stands; F6 matters for any CMO `PARTIAL` leg | Owner |
> | F3 reservation strategy; F8 PI usable-result predicates; F10 PI double `agent_run` | Do not block CMO/chat approval; block **PI** caps and PI enablement only | Owner |
> | F9 durable cut-over table | Appears **already satisfied** by migration `…0017_accounting_cutover`; confirm and close | Owner |
>
> **Implementation order (owner, 2026-10-12): this workflow first, then the CMO delegation (`ceo-cmo-delegation.md` §14).**

This spec defines *when* the CEO must stop and ask the seller to approve what it is about to run, how that approval is stored and audited, and how it can and cannot be given. It is **recommend-only-compatible** (V1 has no `WRITE` effect — a marketplace is never written to) and **code-decided**: no model decides whether something needs approval, writes the plan, or can approve.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | Consequential execution — **metered actions and external data transmission** — requires explicit approval of a stored plan. Ordinary questions, read-only analysis and informational responses stay conversational and never require approval. | Owner, 2026-10-10 (decision 3) |
| C2 | No schema or backend approval behaviour changes until this spec is reviewed and approved. | Owner, 2026-10-09 |
| C3 | An answer to a clarification question is **not** approval. Clarification fills slots; approval is a separate, explicit act on a stored plan. | Owner, 2026-10-09 |
| C4 | The plan is built by **code** from the action registry and already-validated slots. The LLM writes nothing in a plan and cannot approve, decline or alter one. | `CLAUDE.md`; orchestration C21 |
| C5 | Tenant isolation is by `FORCE` RLS plus tenant-scoped queries; the client never supplies `tenant_id`; a foreign plan id is indistinguishable from a missing one. | `auth.md` §1.4, §7.3 |
| **C6** | **Plan expiry: 30 minutes (1800 s) after creation.** An expired plan can never be approved or executed; the CEO must produce a fresh plan. | Owner, 2026-10-10 (1) |
| **C7** | **Approver: only the authenticated user who requested the action.** No cross-user approval, not even an OWNER in the same tenant, unless a future, explicitly designed authorization model changes this. | Owner, 2026-10-10 (2) |
| **C8** | **Immutable approval bound to the exact frozen plan hash shown to the user.** Any material plan change invalidates the previous approval (it creates a new plan with a new id and hash; nothing is edited in place). | Owner, 2026-10-10 (4) |
| **C9** | **Execution safety:** authorization, tenant ownership, entitlements, relevant data and execution limits are **re-validated at approval time**; crashes and uncertain external outcomes have defined recovery; **nothing potentially duplicated is retried automatically.** | Owner, 2026-10-10 (5) |
| **C10** | **Auditability:** every state transition records actor, timestamp and reason in an append-only history. | Owner, 2026-10-10 (6) |
| **C11** | **Decision playbooks get no blanket exemption.** The same *action-level* rule applies to every leg of every playbook: a playbook needs approval exactly when at least one of its legs does. | Owner, 2026-10-10 (7) |

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | **What is "consequential"** (implements C1/C11, Q-S0-2) | Explicit registry metadata on every `ActionSpec` (designed in `docs/planning/ceo-approval-remediation-design.md` R1): `meters` (meter codes the action **actually records**), `external: NONE \| MODEL \| PUBLIC_FETCH \| SELLER_DATA_OUT`, `egress` (which seller data classes leave Metrion), `destinations` (labels for the plan card) and a **derived** `requires_approval = bool(meters) or external == SELLER_DATA_OUT` (may be forced `True`, never `False` for those cases). **Ordinary GST public-page lookups and internal LLM calls do not independently require approval (Q-S0-2).** A turn/playbook needs a plan iff **any** leg does. The data lives in a reviewed code table, never in the DB or model output; a registered action without an entry fails startup (AC-A2). "Outbound leg" elsewhere in this spec means `external == SELLER_DATA_OUT`. | S0 evidence: the declared `effect` understates real behaviour. Classification is by **actual data flow** (findings §D, design R1.3): e.g. `pi.discover` sends the seller-entered niche category text to Tavily/YouTube; `pi.supplier_lookup` sends public candidate titles; `cmo.market_trends` sends only confirmed terms. The `MODEL` tier is "internal" only while the LLM endpoint is operator-controlled (Q-R9). |
| D2 | Where the gate sits | After classification and slot validation (`PLAN_VALIDATED`), before dispatch. For guided input, at `input_session.Done` (today it runs the playbook immediately, `orchestrator.py:228`). | The pipeline already has this stage. |
| D3 | Execution is a **new turn** | Approval creates an execution turn (`route_source='APPROVAL'`) linked to the plan; the planning turn ends `PLANNED`. | Keeps one-turn = one run = one anchor `agent_run`, the per-investigation lock and append-only history. |
| D4 | Plan lifetime storage | `expires_at = created_at + 1800 s` stored **per plan, immutable**; a later config change never extends an existing plan. Time source is the server clock (`runtime.clock()`), never the client. | C6. |
| D5 | Failure after approval | The approved plan is **consumed**. A failed or interrupted execution is never retried by Metrion; the seller asks again → a **new plan** and a **new approval**. | C9. |
| D6 | **CEO conversation-unit accounting (Q-S0-3, Q-R1, Q-R6 applied)** | **Invariant: a CEO turn with any failed required leg consumes no CEO unit, regardless of optional-leg success; a delivered answer alone does not establish successful execution.** The decision is computed once when the turn is finalised and stored once on the turn (first writer wins); only the call that finalised the turn writes the event (key `ceo:turn:<turn_id>`, idempotent); recovery repairs a missing unit only from the stored decision. `DUE`: no legs planned; or every required leg `COMPLETE`/`PARTIAL`; or an `OUT_OF_SCOPE` explanation delivered (outcome `DECLINED`, distinct from failed execution). `NOT_DUE`: any required leg failed (`FAILED`/`UNAVAILABLE`/`DENIED`/`NOT_ENTITLED`/not finished), and every `CLARIFIED`/`DENIED`/`FAILED`/interrupted turn. A stored `outcome` (`SUCCEEDED`/`PARTIAL`/`FAILED`/`DECLINED`) is shown with a `DELIVERED` turn so optional results can be returned with the failure clearly represented. A `PLANNED` turn is never metered; the approved execution turn is metered once if `DUE`; a declined/expired plan costs nothing; the execution turn still passes `open_turn`'s cap check. Legacy turns (before the accounting cut-over, or without a stored decision) are never re-evaluated, repaired or refunded (Q-R4). Exact table: `docs/planning/ceo-approval-remediation-design.md` §1.1. | Today's code charges any `DELIVERED` turn, including one whose required leg raised (X1); the owner decided that must stop (R2). `OUT_OF_SCOPE` is charged today only implicitly (D5 + "delivered answer"; no sentence or test names it) — the owner kept the policy provided it is documented; confirmation is open fact F2. |
| D7 | Audit store | A dedicated **append-only `investigation_plan_event`** table (§5.2), not `auth_audit` and not only mutable plan columns. | `auth_audit` is in `KNOWN_APP_DELETABLE` (the app role can delete it) — unsuitable as an approval trail; the plan row itself is updatable. |
| D8 | Approval record message | Approval writes a code-authored `SYSTEM`/`SYSTEM_NOTE` message ("Approved: <summary>") whose id becomes the execution turn's `user_message_id`, because `investigation_turn.user_message_id` is `NOT NULL` and `create_turn` requires a visible message. | Fits the existing schema without a nullable change. |
| D9 | Reconciliation of non-terminal work | **Lazy reconciliation** (on investigation read, on approve, on the next turn) plus an optional periodic task; staleness threshold = `ceo_leg_timeout_seconds` + margin. If `ceo_leg_timeout_seconds` is unset (it currently returns `None`), approval **refuses to enable** (fail closed). | There is no existing sweeper (§6.8). |

## 3. Assumptions

| # | Assumption | Status |
|---|---|---|
| A1 | The registry is the complete, closed set of things a turn can run (C21; `FORBIDDEN_ACTION_KEYS` blocks write-class keys). | Verified in `registry.py`. |
| A2 | The advisory turn lock (`investigation_turn_lock`) serialises approve vs. turns across workers and is released if the process dies (session-level lock). | Verified in `turn_lock.py` docstring/code. |
| A3 | One open plan per investigation is enough for V1. | Open to review. |
| A4 | Approval happens in the app UI only; WhatsApp `CONFIRM` stays a separate alert-scoped mechanism. | Scope decision. |
| A5 | Metering on failed or interrupted legs behaves correctly for every action. | **VP-1 — FAIL (decisions made, remediation designed, not implemented).** CMO and the CEO unit behave as designed and are test-proven; PI actions record no usage today (decision Q-S0-1: record one idempotent event per successful run — R3); CFO/CI/GST usage is never recorded; a CEO unit is consumed when a required leg failed (decision Q-S0-3: it must not be — R2). No document may claim PI caps are enforced until R3's tests pass. §13.1. |
| A6 | A hard crash leaves nothing permanently non-terminal. | **VP-2 — FAIL (confirmed; recovery designed, not implemented).** Experiment X2: the turn, the CEO anchor run and the leg run stay non-terminal forever; no reconciler exists. Decision Q-S0-4: lazy **and** periodic reconciliation (R5). §6.8, §13.2. |

## 4. Goals and non-goals

**Goals.** Show the seller exactly what will run (agents, integrations, assumptions, metered units, what leaves Metrion) before it runs; run exactly that after an explicit approval by the person who asked; keep a complete, append-only record; never let chat text, a clarification answer, a retry, a replay, another user or a stale plan stand in for approval.

**Non-goals (V1).** Marketplace writes (none exist); delegated/multi-approver approval; approval over WhatsApp; editing a plan in place (edit = decline/supersede + ask again); LLM-written plan text; a general workflow engine; automatic retry of any approved execution.

## 5. Data model (proposed — not to be migrated until approved)

### 5.1 `investigation_plan` (tenant-owned; `ENABLE` + `FORCE ROW LEVEL SECURITY`; `tenant_isolation` policy identical to the other CEO tables)
| Column | Notes |
|---|---|
| `id uuid pk default gen_random_uuid()` | |
| `tenant_id uuid not null` | RLS key |
| `investigation_id uuid not null → investigation(id)` | |
| `planned_turn_id uuid not null → investigation_turn(id)` | turn that produced it (ends `PLANNED`); `UNIQUE` |
| `execution_turn_id uuid null → investigation_turn(id)` | set on approval |
| `plan jsonb not null` | **frozen**, §5.3 |
| `plan_hash text not null` | §6.2 |
| `status text not null` | `AWAITING_APPROVAL \| APPROVED \| DECLINED \| EXPIRED \| SUPERSEDED` (CHECK) |
| `requested_by uuid not null → app_user(id)` | the only permitted approver (C7) |
| `created_at timestamptz not null default now()`, `expires_at timestamptz not null` | `CHECK (expires_at > created_at)` |
| `decided_by uuid null`, `decided_at timestamptz null`, `decision_reason text null` (≤ 200) | denormalised convenience; the event table is the record |

Constraints: `UNIQUE (planned_turn_id)`; partial unique `(tenant_id, investigation_id) WHERE status = 'AWAITING_APPROVAL'`; CHECK `status='APPROVED' ⇒ execution_turn_id, decided_by, decided_at NOT NULL`; CHECK `status IN ('DECLINED') ⇒ decided_by, decided_at NOT NULL`; index `(investigation_id, created_at)`.

### 5.2 `investigation_plan_event` (tenant-owned, `FORCE` RLS, **append-only**)
`id`, `tenant_id`, `plan_id → investigation_plan(id)`, `event text` (CHECK), `from_status text null`, `to_status text null`, `actor_user_id uuid null` (**null = the system**, e.g. expiry), `actor_kind text` (`USER`/`SYSTEM`), `occurred_at timestamptz not null default now()`, `plan_hash text`, `reason_code text null`, `metadata jsonb null` (refs only: execution turn id, agent_run ids, the refusal check that failed; **never** figures or seller text).
Events: `CREATED`, `APPROVAL_REFUSED` (with `reason_code` = the §6.5 check that failed), `APPROVED`, `DECLINED`, `EXPIRED`, `SUPERSEDED` (metadata: the new plan id), `EXECUTION_STARTED`, `EXECUTION_FINISHED`, `EXECUTION_FAILED`, `EXECUTION_NOT_STARTED`, `OUTCOME_UNKNOWN`.
A state change and its event are written **in one transaction** by a single repository function; no code path updates `status` without inserting the event (AC-A10 test).

### 5.3 `plan` JSON (frozen at creation; canonical form fixes the hash)
`{plan_version: 1, route, route_key, legs: [{action_key, agent, effect, requires_approval, external, slots (validated, text/ints only; money as integer paise), refs, meters: [{meter_code, units}], destinations: [<fixed registry labels of external services>]}], integrations: [{code, status: AVAILABLE|UNAVAILABLE}], assumptions: [<code-derived strings>], data_basis: [{kind, id, as_of, fingerprint}], limits: {max_legs, leg_timeout_seconds}, prior_attempt: {plan_id, outcome: UNKNOWN|FAILED|…} | null, summary_text}`. `summary_text`, `assumptions` and labels are rendered by **code** from the registry and slots. No floats anywhere in the canonical form.

### 5.4 Changes to existing tables
- **`investigation_turn`:** extend `investigation_turn_status_check` with `PLANNED`; extend `investigation_turn_route_source_check` with `APPROVAL`; add `plan_id uuid null` (the plan an execution turn runs). Existing values and rows unchanged.
- **`investigation_message`:** extend `investigation_message_kind_check` with `PLAN` (the CEO message carrying the plan card; structure is read from the plan row, never parsed from message text).
- **`agent_run`:** no schema change (no status CHECK exists). A planning turn's anchor closes `COMPLETE` (a plan was produced; no leg ran). An interrupted external-capable leg (`external != NONE`) is closed `FAILED` with `error_reason='OUTCOME_UNKNOWN'`; any other interrupted leg `FAILED`/`INTERRUPTED` (§6.8).
- **Privileges** (the 0007/0015 lesson: `02-roles.sql` default privileges give `metrion_app` full CRUD on every new table, so each must be narrowed by `REVOKE`):
  - `investigation_plan`: `REVOKE ALL FROM metrion_app` then `GRANT SELECT, INSERT` + **column-level** `GRANT UPDATE (status, execution_turn_id, decided_by, decided_at, decision_reason)`. No `UPDATE` on `plan`, `plan_hash`, `tenant_id`, `investigation_id`, `requested_by`, `expires_at`; no `DELETE`/`TRUNCATE`.
  - `investigation_plan_event`: `SELECT, INSERT` only.
  - Note `has_table_privilege(…,'UPDATE')` is false for column-only grants, so column privileges must be asserted with `has_column_privilege` / `information_schema.column_privileges` (§10).

### 5.5 Registry (code, not DB)
`ActionSpec` gains required `meters`, `external` and `requires_approval` (D1; no defaults at registration, A1/AC-A2). **Evidence-based classification from S0** (full table with sources: `docs/planning/ceo-approval-s0-findings.md` §D). "Chat" = reachable from a CEO turn today; every other registered action is refused `OUT_OF_CATALOG` with no leg dispatched (experiment X3).
| Action(s) | declared `effect` | `external` (evidence) | `meters` actually recorded | Needs approval | Chat today |
|---|---|---|---|---|---|
| `cfo.pnl_for_tenant`, `pricing`, `gst_summary`, `landed_cost`, `supplier_ranking`, `funding_readiness`, `batch_size`, `reconcile`, `cash_reconciliation`, `anomaly_check` (narration pinned off by the CEO slot) | `COMPUTE_PERSIST` | NONE | none | no | playbook legs / `reconcile`, `anomaly_check`, `cash_reconciliation` |
| `cfo.period_comparison` | `COMPUTE_PERSIST` | **MODEL** (Ollama narration) | none | no (Q-S0-2) | no |
| `cfo.financial_health`, `cfo.strategic_briefing` (narration pinned off), `cfo.preview`, `pi.report` | `READ` | NONE | none | no | financial_health, briefing, pi.report |
| `cfo.gst_lookup`, `service.gst_lookup` | `COMPUTE_PERSIST` | **PUBLIC_FETCH** (fixed allowlisted public pages) + **MODEL** (title + page text) | none (count-based scaffold) | **no by default** (Q-S0-2) | yes |
| `ci.request_price_scenario` | `COMPUTE_PERSIST` | NONE (engine over stored captures) | none | no | yes |
| `ci.discover_competitors` | `COMPUTE_PERSIST` | **NONE today** (`MockSearchProvider` is the composition root); **becomes SELLER_DATA_OUT when a real provider is wired** — guard test required | none | no today; **yes the moment a provider is wired** | no |
| `ci.research_now` | `COMPUTE_PERSIST` | not wired | — | n/a | no |
| `pi.discover`, `pi.supplier_lookup` | `GENERATE_METERED` | **SELLER_DATA_OUT** (Tavily, YouTube, Google Places) + MODEL | **none recorded (gap)** | **yes** (external) | no |
| `cmo.generate_*`, `cmo.catalog_answer`, `cmo.generate_title_sets` | `GENERATE_METERED` | MODEL | per COMPLETE artefact | **yes** (metered) | no |
| `cmo.market_trends` | `GENERATE_METERED` | **SELLER_DATA_OUT** (confirmed niche terms) + MODEL | CMO + shared, per COMPLETE report | **yes** | no |
| `cmo.market_trends_preview`, `cmo.suggest_niche_terms` | `READ` | NONE | none | no | no |
| `cmo.approve_title`, `cmo.confirm_niche_terms`, `cmo.confirm_image_hint` | `RECORD_CHOICE` | NONE | none (free) | no | no |
| **Decision playbooks** (C11): `COMPETITOR_PRICE_IMPACT` = `ci.request_price_scenario` + `cfo.pricing`; `NEW_PRODUCT_DECISION` = `cfo.landed_cost` + `cfo.supplier_ranking` + `cfo.batch_size` | — | no blanket exemption: gated iff a leg is | — | **Under this evidence no leg is flagged, so neither runs behind a plan today**; if `ci.discover_competitors` or a PI/CMO leg is ever added to a playbook, it is gated automatically | form / guided input |
The CEO conversation unit is metered by the CEO turn itself (`DELIVERED` only), not by any leg.
**"Chat today" (corrected 2026-10-10, decision D-8).** After the 2026-10-10 chat work (orchestration 6.35/6.40) the metered or seller-data-out actions `pi.discover`, `cmo.generate_title_sets`, `cmo.generate_hashtags`, `cmo.generate_description`, `cmo.generate_keywords` and `cmo.market_trends` were defined as chat actions and ran behind an in-conversation confirmation (a card for PI discovery and market trends; **none** for the four CMO generators). That is not approval (C3). They are now **refused from chat** (`DENIED` turn with an explanation, no question asked, nothing saved, run, sent or charged) in the orchestrator, and again in `dispatch()`; `GET /ceo/agents/availability` no longer counts them. The "Chat today = no" cells above therefore describe the enforced behaviour, but by refusal, not because the actions are absent from the chat catalog. **No plan, hash, expiry, approve or decline exists**: S2 and S3 are not implemented, so these actions stay unavailable from chat until they are. Test scenario 2 below (`cmo.market_trends` → `PLANNED`) is the S3 target; today the turn is refused instead.


## 6. Core rules

### 6.1 When a plan is created
After classification and slot validation, code evaluates the leg rule (D1). If **no** leg needs approval, the turn proceeds exactly as today. If **any** does: no leg is dispatched; the turn ends `PLANNED`; the plan row, its `CREATED` event and a `PLAN` message are written in one transaction; the response carries the plan. A missing required slot is still `CLARIFY` first — a plan is never built from a guess, a default or an unanswered question. If the plan cannot be built (an integration unavailable, `ceo_playbook_max_legs` exceeded, or the config in D9 absent), the seller is told plainly and nothing is created.

### 6.2 Canonical form and hash (C8)
`plan_hash = sha256(canonical_json({plan_id, tenant_id, investigation_id, requested_by, expires_at, plan}))` where canonical JSON = UTF-8, keys sorted, no insignificant whitespace, integers only (money in paise), UUIDs lowercase, timestamps UTC ISO-8601, `plan_version` included. Binding the identifiers into the hash means a hash cannot be replayed on another plan, investigation, tenant or user. The server **recomputes** the hash from the stored row at approval and compares in constant time with both the stored hash and the client-sent value; the client's value is never trusted as a source.

**Material change** = any change to a leg set/order, any slot value, any meter code or units, any destination, `data_basis` (a referenced result id, its `as_of`, or its fingerprint), the integration availability set, `limits`, `route`, or the identity fields. A material change **never edits** a plan: a new plan is created (new id, new hash), the old one becomes `SUPERSEDED`, and an approval for the old hash cannot be applied to the new one.

### 6.3 Turn and plan state transitions
```
turn:  RECEIVED → CAP_CHECKED → CLASSIFIED → PLAN_VALIDATED ─┬→ (no approval needed) DISPATCHED → GATHERED → COMPOSED → DELIVERED | FAILED
                                                              └→ PLANNED   (terminal for this turn; plan created)
execution turn (route_source='APPROVAL'): PLAN_VALIDATED → DISPATCHED → GATHERED → COMPOSED → DELIVERED | FAILED   (no re-classification)
plan:  AWAITING_APPROVAL ─┬→ APPROVED    (execution turn created in the same transaction)
                          ├→ DECLINED    (by the requester)
                          ├→ EXPIRED     (expires_at passed; persisted lazily on read/approve and by reconciliation)
                          └→ SUPERSEDED  (a newer plan in the same investigation; or the investigation was resolved/archived; or a material change)
```
`APPROVED`, `DECLINED`, `EXPIRED`, `SUPERSEDED` are terminal. The execution turn's status is the outcome; the plan does not duplicate it.

### 6.4 Clarification answer ≠ approval (C3)
A clarification reply (`clarification` on `POST …/turns`), a typed message, a UI action and any classifier output can only fill slots, answer an input question, or create a plan. None can set a plan to `APPROVED`; the classifier has no "approve" route; "yes"/"go ahead"/"run it" are ordinary text. Answering the last question of a guided input ends in a plan (D2), never in execution. Only `POST …/approve` approves.

### 6.5 Endpoints (under `/api/v1/ceo`; `require_auth`; tenant from the JWT only; no `tenant_id` anywhere in a path or body)
| Method & path | Behaviour |
|---|---|
| `GET /investigations/{id}/plans` · `GET /investigations/{id}/plans/{plan_id}` | tenant-scoped reads; lazily persist `EXPIRED`; include `status`, `expires_at`, `plan`, `plan_hash`, the event history |
| `POST /investigations/{id}/plans/{plan_id}/approve` body `{plan_hash}` | §6.6; returns the execution turn (same shape as `POST …/turns`); progress via the existing SSE `…/events` and polling fallback (note: `event_bus` is in-process, §6.8 of the existing spec — polling remains the fallback) |
| `POST /investigations/{id}/plans/{plan_id}/decline` body `{reason?}` | CAS `AWAITING_APPROVAL → DECLINED`; `DECLINED` event; `SYSTEM_NOTE`; **no model call; no CEO unit** |
Errors reuse the existing `HTTPException(detail={"code": …})` style: `404`, `403`, `409` (`PLAN_CHANGED`, `PLAN_EXPIRED`, `PLAN_NOT_AWAITING`, `PLAN_STALE`, `TURN_IN_PROGRESS`, `INVESTIGATION_NOT_ACTIVE`, `INTEGRATION_UNAVAILABLE`), entitlement refusals as today.

### 6.6 Approval checks, in order (fail closed; the first failure wins; **nothing runs, nothing is metered, no turn is created**; each refusal writes an `APPROVAL_REFUSED` event with its reason code)
1. Authenticated tenant context present; the investigation is visible under RLS and `ACTIVE` (else 404 / 409).
2. Plan visible under RLS **and** `plan.investigation_id = {id}` (else 404 — a foreign id looks exactly like a missing one).
3. **`ctx.app_user_id == plan.requested_by`** (else 403; roles, including OWNER, grant no override — C7). A requester who has since lost membership cannot approve (membership re-resolved by `require_auth`).
4. Hash: recomputed hash equals stored hash **and** the client's `plan_hash` (else 409 `PLAN_CHANGED`).
5. `status = AWAITING_APPROVAL` and `now < expires_at` (else 409; expiry is persisted `EXPIRED` with its event — C6).
6. **Authorization re-evaluated now:** `agent.ceo`, `investigation.view` and every leg's `registry.required_permissions` via `has_permission` (else 403 and a `DENIED` `agent_run`, as `open_turn` does today).
7. **Attachment re-checked:** each leg's agent is still attached to the investigation (`dispatch` R13 behaviour).
8. **Entitlements re-resolved now:** the CEO cap via `open_turn`/`resolve_ceo_entitlement` and each leg's `spec.entitlement` preflight (the specialist's own quota admission, e.g. CMO's, still runs again inside the leg). Refusal returns the standard denial text; the plan stays `AWAITING_APPROVAL` so the seller can fix the cause or decline.
9. **Data re-validated:** every `data_basis` ref still resolves for this tenant and its `as_of`/fingerprint is unchanged, and the frozen slots pass the same deterministic validators (`_validate_slots`, slot resolvers) (else 409 `PLAN_STALE`; the seller gets a fresh plan).
10. **Execution limits:** leg count ≤ `ceo_playbook_max_legs`; `ceo_leg_timeout_seconds` is set (else refuse to run); required integrations still `AVAILABLE` (else 409 `INTEGRATION_UNAVAILABLE`).
11. Acquire the investigation turn lock (`investigation_turn_lock`; 409 `TURN_IN_PROGRESS` if busy, per `ceo_turn_lock_wait_seconds`).

Then, **in one transaction**: CAS `AWAITING_APPROVAL → APPROVED` (`UPDATE … WHERE id=:id AND status='AWAITING_APPROVAL' AND expires_at > :now`; 0 rows ⇒ treat as a duplicate/loss, §6.7), write the approval `SYSTEM_NOTE` message (D8), create the execution turn (`create_turn`, `route_source='APPROVAL'`, `plan_id`), set `execution_turn_id`/`decided_*`, insert the `APPROVED` event. Only after commit does dispatch begin, running **exactly** the frozen legs with the frozen validated slots (no classifier, no model call for routing). Events `EXECUTION_STARTED` / `EXECUTION_FINISHED` / `EXECUTION_FAILED` follow, with the turn and `agent_run` ids.

### 6.7 Duplicates and concurrency
- **Repeat or concurrent `approve`:** the CAS lets exactly one win. A repeat by the same requester for an `APPROVED` plan returns the **same** execution turn (idempotent): `200` with the turn's current status (a still-running turn is reported as running, so a client that timed out and retried never starts a second run and can poll). A repeat for `DECLINED`/`EXPIRED`/`SUPERSEDED` is `409`.
- **Approve racing decline:** whichever CAS wins; the loser gets `409` with the winner's status.
- **Approve racing a new turn in the same investigation:** the turn lock serialises them; a new consequential plan supersedes the open one (partial unique index).
- **HTTP timeout/network retry:** safe by the idempotent replay above. There is no client-supplied idempotency key; the plan id is the key.

### 6.8 Crashes, uncertain external outcomes and recovery (C9, D5, D9) — **designed here, not implemented; see VP-2**
Evidence in the code today: the in-process exception handler in `run_turn` finalises a turn `FAILED` and `dispatch` closes each leg's `agent_run`; a **hard crash** (process kill, power loss) bypasses both and leaves the execution turn non-terminal and any in-flight leg `agent_run` at `RUNNING`; the advisory lock is released with the session; **no sweeper exists** (searched `repositories`, `ceo`, `services`, `main`).
Rules:
1. **Never started** — execution turn non-terminal, plan `APPROVED`, **no** leg `agent_run` rows: reconciliation marks the turn `FAILED` (`EXECUTION_NOT_STARTED`). The plan stays consumed; the seller asks again (conservative: no silent second chance).
2. **Interrupted internal leg** (`external == NONE`): leg `FAILED`/`INTERRUPTED`; turn `FAILED`; safe to recompute in a *new, newly approved* plan.
3. **Interrupted external-capable leg** (`external != NONE`; a request may or may not have reached an external service): leg `FAILED` with `error_reason='OUTCOME_UNKNOWN'`; turn `FAILED` with `safety_result.outcome_uncertain=true` and the leg keys; event `OUTCOME_UNKNOWN`. The seller is told in plain words that the request **may already have been sent and may have been charged**, and that Metrion will not repeat it automatically. A later plan for the same legs carries `prior_attempt: {plan_id, outcome: UNKNOWN}` so the new plan shows an explicit duplicate warning before it can be approved.
4. **No automatic retry of anything** after approval, by Metrion or by any job, ever. The only retry is the seller's explicit new request → new plan → new approval.
5. **Metering on uncertain/failed outcomes:** meters are recorded only for a leg that persisted a COMPLETE result (VP-1). An `OUTCOME_UNKNOWN` leg records no meter; if the provider may have billed externally, that is surfaced to the operator via the event, not silently reconciled.
6. **Reconciliation trigger and bound:** lazily on reads/approve/next turn and by an optional periodic task; a row is "stale" when older than `ceo_leg_timeout_seconds` + margin; if that setting is unset reconciliation cannot decide staleness, so approval is refused at plan time (D9).
7. A plan whose execution is **in flight** when it would have expired is unaffected: expiry only blocks *starting* execution.

## 7. AI requirements
The classifier selects only a route/key/slots from the closed catalog (unchanged); it receives no plan or approval state and has no way to emit approval. For a `PLANNED` turn the composer's reply is a **fixed code template** (it states a plan exists and is waiting; it cites nothing it computed). The plan card text is code-rendered. **Evals required** (`CLAUDE.md`): no number outside the plan; no claim that anything ran or was approved before approval; no narration of a declined/expired/superseded plan as executed; an `OUTCOME_UNKNOWN` turn is never narrated as a success or as a clean failure (it is a non-result stated as uncertain, `AnomalyInsufficientHistory`-style); the duplicate warning is never dropped.

## 8. Authorization and security
- Tenant from the auth context only; RLS `FORCE` on both new tables; foreign ids are 404; missing tenant context fails closed.
- Requester-only approval (C7) is enforced in code (§6.6-3) **and** recorded; no permission key is added (Q-A4).
- Every check in §6.6 is evaluated at approval, not planning, time; approving never grants anything the requester does not already hold.
- `plan`, `plan_hash`, `requested_by`, `expires_at` are immutable at the **database privilege level**; history tables are append-only at the privilege level.
- Plan text comes from registry labels and validated slots; seller text (SKU names, attachment text) is escaped on display and never interpreted as instructions.
- All transitions are audited (§5.2); no plan or event row is ever deleted by the application.

## 9. Edge cases and verification prerequisites

| # | Case | Behaviour |
|---|---|---|
| E1 | New informational question while a plan is open | Answered normally; the plan stays open. |
| E2 | New consequential ask while a plan is open | New plan supersedes the old (`SUPERSEDED`, event with new plan id). |
| E3 | Investigation resolved/archived with an open plan | Plan → `SUPERSEDED` in the same transaction as the status change; approve refused (409). Reopen does not revive it. |
| E4 | Data changed after the plan | `PLAN_STALE`; fresh plan required. |
| E5 | Cap/entitlement exhausted between plan and approval | Standard denial; plan stays open until expiry. |
| E6 | Requester's role/membership changes | Re-check at approval fails closed. |
| E7 | Two tabs approve at once | CAS; one run; the other receives the idempotent replay. |
| E8 | Approve after 30 minutes | 409 `PLAN_EXPIRED`; `EXPIRED` persisted with a `SYSTEM` event. |
| E9 | Another member (even OWNER) tries to approve | 403; `APPROVAL_REFUSED` event; plan untouched. |
| E10 | Guided input finished | A plan, with the collected inputs frozen in it; a bad/changed input means decline + ask again. |
| E11 | LLM unavailable | Planning is deterministic and unaffected; composition falls back as today. |
| E12 | A `SELLER_DATA_OUT` leg's integration not configured | Plan lists it `UNAVAILABLE`; approval refused (409 `INTEGRATION_UNAVAILABLE`); no partial run. |
| E13 | Process killed mid-execution | §6.8 reconciliation; no retry. |
| E14 | Client sends a modified hash/plan | 409 `PLAN_CHANGED`; the server never accepts plan content from the client. |

**Verification prerequisites (explicitly unresolved; do not build around assumptions):**
- **VP-1 Billing/metering on failed or interrupted legs — FAIL until R2 and R3 are implemented and their tests pass.** Confirmed by S0: only three code paths write `metered_event` (CEO turn unit on `DELIVERED`; CMO artefacts and trend reports on COMPLETE); CMO failure/replay/reservation/metering-write-failure paths are test-proven; a spy over 68 CFO/CI/GST/PI direct-path tests saw zero usage writes. Gaps: PI records no usage; CFO/CI/GST usage is never recorded; a delivered turn with a failed required leg is charged. **Decisions (2026-10-10):** PI records one idempotent event per successful run (failed/interrupted → none); a CEO turn with any failed required leg consumes no CEO unit (even if an optional leg succeeded). Nothing in billing has been changed yet. Design: `docs/planning/ceo-approval-remediation-design.md` §1, R2, R3.
- **VP-2 Crashed-turn recovery — FAIL until R5 exists and its kill-process tests pass.** Confirmed by S0 (experiment X2): after a mid-leg kill the turn is `PLAN_VALIDATED`, the CEO anchor run and leg run are `RUNNING`, a question is unanswered; the lock is released and the next turn works, but the stuck rows are never touched. **Decision (2026-10-10):** lazy **and** periodic reconciliation; the periodic runner is a separately testable CLI/function, never a loop inside the web server; per-investigation advisory lock as the liveness proof; guarded idempotent transitions; `OUTCOME_UNKNOWN` for external-capable work; never retried. Design: remediation design R5.

## 10. Acceptance criteria
- **AC-A1** A READ / Business State / advisory / non-flagged turn never creates a plan and behaves exactly as today (existing suites unchanged).
- **AC-A2** Every `ActionSpec` declares `meters`, `external` and `requires_approval` explicitly; registering one without them fails; a test enumerates all 36 registered actions against the §5.5 table and pins the CI discovery provider so wiring a real one forces a registry review.
- **AC-A3** A turn with any flagged leg dispatches **zero** legs, ends `PLANNED`, and atomically writes one plan, one `CREATED` event and one `PLAN` message. A playbook is gated iff one of its legs is (C11).
- **AC-A4** No chat text, clarification reply, UI action, classifier output, replay or other user can move a plan to `APPROVED`; only the requester's `approve` can.
- **AC-A5** Plan expiry is exactly `created_at + 1800 s`; an expired plan returns 409 and runs nothing; the CEO produces a fresh plan.
- **AC-A6** `approve` runs the §6.6 checks in order; each failure leaves state unchanged (no turn, no meter, no leg) and writes an `APPROVAL_REFUSED` event.
- **AC-A7** Approval binds to the exact hash: any change to any material field yields a different hash, a new plan and invalidates the old approval; client-supplied content is never used.
- **AC-A8** Approval executes exactly the frozen legs/slots; a test proves no classifier or routing-model call occurs in an execution turn.
- **AC-A9** Repeat/concurrent approve ⇒ exactly one execution turn and one set of leg runs; decline/expiry/supersession are terminal and approve on them is 409.
- **AC-A10** Every status change has exactly one matching event with actor, timestamp and reason; no code path changes status without it; the event table has no `UPDATE`/`DELETE` for `metrion_app`.
- **AC-A11** RLS: tenant B cannot read, approve, decline or list tenant A's plans/events; foreign id ⇒ the same 404 as unknown; missing tenant context fails closed.
- **AC-A12** `metrion_app` cannot `UPDATE` `plan`/`plan_hash`/`requested_by`/`expires_at`, cannot `DELETE` or `TRUNCATE` either table (direct SQL as `metrion_app`, and `has_column_privilege` assertions in the extended boundary test); `KNOWN_APP_DELETABLE` stays accurate.
- **AC-A13** Authorization, attachment, entitlement, data and limits are re-validated at approval; revoking any after planning blocks execution.
- **AC-A14** Crash recovery per §6.8 (after VP-2 is resolved): no permanent `RUNNING`; `OUTCOME_UNKNOWN` set for interrupted external-capable legs; nothing retried automatically; the next plan carries the duplicate warning.
- **AC-A15** Metering per VP-1 (after it is resolved): a failed/interrupted leg records no meter; one CEO unit per approved-and-`DELIVERED` request; none for a declined/expired plan.
- **AC-A16** Composer evals (§7) pass.
- **AC-A17** Frontend shows Planning / Awaiting approval / Running / Completed / Failed / Declined / Expired / "Outcome uncertain" from backend status only; no Approve control unless `AWAITING_APPROVAL` **and** the viewer is the requester; the expiry countdown comes from the server's `expires_at`.

## 11. Test scenarios
1 Informational → direct answer, no plan. 2 `cmo.market_trends` → `PLANNED` listing queries/destinations/meters; zero legs ran. 3 Guided-input playbook with all legs unflagged → runs; with a flagged leg → plan. 4 Clarification answers (option, typed, "yes") never approve. 5 Wrong/missing hash → 409. 6 Mutating any material field changes the hash. 7 Approve twice (sequential + concurrent) → one run. 8 Approve at 30 min + 1 s → 409, `EXPIRED` + system event. 9 New consequential ask → previous `SUPERSEDED`. 10 Another member/OWNER approves → 403 + refusal event. 11 Requester loses a permission/attachment/entitlement → refusal, plan intact. 12 Data basis changed → `PLAN_STALE`. 13 Cross-tenant read/approve/decline → 404, nothing changed. 14 Direct SQL as `metrion_app`: update `plan`, delete, truncate, event update → denied. 15 Execution fails → turn `FAILED`, plan `APPROVED`, no auto-retry; new ask → new plan. 16 Kill a worker mid-leg → reconciliation per §6.8. 17 Interrupted outbound leg → `OUTCOME_UNKNOWN`, no meter, next plan warns. 18 Per-action metering tests (VP-1). 19 Resolve/archive with open plan → `SUPERSEDED`. 20 Frontend state mapping and requester-only controls. 21 Migration upgrade/downgrade round-trip on an empty DB; downgrade refuses (does not silently destroy) when plan/event rows exist. 22 Existing turn/RLS/privilege/clarification suites unchanged and green.

## 12. Questions

### Resolved (2026-10-10)
| # | Resolution |
|---|---|
| Q-A2 | Plan TTL = **30 minutes** (C6). |
| Q-A3 | **Requester only**; no cross-user approval (C7). |
| Q-A5 / Q12 | Always plan before **metered** or **externally transmitting** execution, even when the seller asked for that output (C1). |
| Q-A1 (rule) | Decision playbooks are **not exempt**; the same action-level rule applies (C11). |
| Q-A6 (design) | No automatic retry of potentially duplicated actions; recovery defined in §6.8 (C9). |

### Resolved by S0 and the 2026-10-10 reviews
| # | Resolution |
|---|---|
| Q-A1b | Per-action classification is evidence-based, by actual data flow (§5.5, findings §D, design R1). |
| Q-A6 (a)/(b) | Audited (§13.1, §13.2); both FAIL; remediation designed (R0–R7). |
| Q-S0-1 | PI records one idempotent usage event per successful run; failed/interrupted/empty runs consume nothing. |
| Q-S0-2 | GST public fetch and internal LLM calls do not independently need approval; approval for metered actions and seller-specific confidential data leaving Metrion; classify by actual data flow. |
| Q-S0-3 / **Q-R1** | Any failed required leg ⇒ no CEO unit even if an optional leg succeeded; optional results are returned with the failure/partial outcome shown (D6). |
| Q-S0-4 / **Q-R7** | Lazy recovery plus a standalone one-shot CLI (no scheduler or thread in FastAPI); `OUTCOME_UNKNOWN` for external-capable work; never retried. Scheduler deployment is documented only after the environment is confirmed (F4). |
| **Q-R2** | A PI `PARTIAL` run is billable only with a usable result under the documented criterion (≥ 1 computed candidate; lookup ≥ 1 lead); empty/failed/interrupted never billable; ≤ 1 event per meter per run. |
| **Q-R3** | Only successful `research.niche_run` executions count toward usage and enforcement; started/failed/interrupted/successful counts are kept separate; `niche_run_count` (consumers audited) keeps its meaning. |
| **Q-R4** | No refunds, retroactive charges or backfills; durable cut-over records (R0); the reconciler never reinterprets legacy rows. |
| **Q-R5** | No invented threshold: a required, validated setting checked against a floor derived from timeouts; **final value is a reported blocker (F1)**. |
| **Q-R6** | `OUT_OF_SCOPE` billing preserved and made explicit (outcome `DECLINED`); documentation confirmation is F2. |
| **Q-R8** | No quota overshoot once PI caps are enabled: atomic reservation (R6) and a concurrent-last-unit test come first; until then PI caps are **not enforced** and must not be seeded. |
| **Q-R9** | LLM endpoint guard (R7): loopback or operator-attested ⇒ internal, otherwise external ⇒ fail closed; the disclosure policy is undefined (F5). |
| **Q-R10** | `pi.supplier_lookup` payload = public candidate title + fixed suffix; approval because metered; payload pin tests force reclassification if it changes. |

### Unresolved — facts and decisions needed before implementation (design §5)
| # | Question / fact | Needed from |
|---|---|---|
| **F1** | Staleness threshold: structural floors computed (PI discover ≈ 1,640 s upper bound; supplier lookup ≈ 70–140 s); **no measured durations from a target host; LLM hardware undecided — blocker for the final value.** | Calibration run + owner acceptance of the margin |
| **F2** | `OUT_OF_SCOPE` billing is implicit (D5 + "delivered answer"); no spec sentence or test names it. Confirm intent, then document in `ceo-agent-orchestration.md` §6.3 / `entitlement.md`. | Owner |
| **F3** | Reservation strategy: reuse `cmo_quota_reservation`/`reserve()` for PI and SHARED (recommended) vs a new neutral table. | Owner |
| **F4** | Deployment environment never chosen (readiness 2.19, 3.9 `[P]`; no Dockerfile/IaC). | Owner / ops |
| **F5** | No data-disclosure policy exists for a third-party model endpoint; design fails closed. | Owner |
| **F6 (Q-R11)** | Is a required leg that is `PARTIAL` with no usable figure (a data request) a failure for billing? Counts as not failed until decided. | Owner |
| **F7 (Q-R12)** | Is a delivered `BUSINESS_STATE` answer of "not available yet" a unit? Charged today. | Owner |
| **F8** | Accept or adjust the PI usable-result predicates (§1.2 of the design). | Owner |
| **F9** | Accept a durable `accounting_cutover` table (extra migration) rather than an environment variable. | Owner |
| **F10** | Observed: a PI discover writes two `agent_run` rows; not changed. Dedupe separately? | Owner |
| Q-A4 | Reuse existing permission keys (recommended; `auth.md` grid unchanged)? | Architect |
| Q-A7 | D6 accounting consistent with the above — confirm. | Product / `entitlement.md` |
| Q-A8 | How long declined/expired plans stay visible in the UI history. | UX |
| Q-A9 | `CEO_PLAN_TTL_SECONDS`: config knob seeded to 1800 or a constant? | Architect |
| Q-A10 | DB-level transition completeness: (1) one transactional repository function (necessary), (2) `SECURITY DEFINER` function, (3) constraint trigger. | Architect |
| VP-1 | **FAIL** until R2, R3 (and R6 for caps) are implemented and proven. | — |
| VP-2 | **FAIL** until R5 exists and passes the kill-process, repeated-reconciliation and uncertain-outcome tests. | — |



---

## 13. S0 verification results, consistency review and required-change inventory (2026-10-10)

Method: read-only code inspection plus isolated experiments on the scratch Postgres (`:5544`); no schema, billing, endpoint or dev-database change. Full evidence, per-action tables and reproduction steps: **`docs/planning/ceo-approval-s0-findings.md`** (scripts in `docs/planning/ceo-approval-s0/`).

### 13.0 Verdicts and decisions (updated 2026-10-10 after the Q-R decisions)
| Item | Verdict |
|---|---|
| **VP-1 Metering** | **FAIL** — decisions made (PI: one idempotent event per successful, usable run; no CEO unit if any required leg failed), remediation designed (R0, R2, R3, R6), **nothing implemented**; PI usage caps are **not enforced** and must not be seeded until R6's concurrency tests pass |
| **VP-2 Crash recovery** | **FAIL** — no reconciler exists; lazy + standalone-CLI design decided (R5), **nothing implemented**; final staleness threshold is a reported blocker (F1) |
| Reachability | **CONFIRMED** — no metered or seller-data-sending action is reachable from CEO chat today |
| Approval-state representation | **Verified**; correctness blocker §13.4-1 addressed by R4 |
| Requester-only / 30 min / hash-bound / revalidation | **Verified enforceable** with existing building blocks (§13.4) |

**Decisions applied (owner, 2026-10-10):** Q-S0-1…4 and Q-R1…10 (see §12). The remediation design is **`docs/planning/ceo-approval-remediation-design.md`** (revision 2): R0 accounting cut-over records, R1 effects metadata, R2 CEO unit semantics, R3 PI usage and `research.niche_run`, R4 `PLANNED` vocabulary, R5 reconciliation (CLI + lazy), R6 PI quota reservation, R7 LLM endpoint guard — with the exact billing outcomes, proposed acceptance criteria (AC-R0…AC-R7), failure-injection tests and the unresolved facts F1–F10. These prerequisites may be implemented in a **separate, reviewable checkpoint** that must **not** include plan creation, approval endpoints, approval execution or the workflow editor, and must not touch the development database before review.

### 13.1 VP-1 evidence (summary)
- Only three paths write `metered_event`: the CEO turn unit (`DELIVERED` turns only, best-effort, key `ceo:turn:<id>`), CMO artefacts (per COMPLETE artefact, key `cmo:<generation_id>`), CMO trend reports (two meters, COMPLETE only). A spy over the CFO, CI, GST and PI direct-path suites (68 tests) observed **no** usage write (positive control: it does fire for CEO and CMO).
- CMO is sound under failure and retry (tests: failed artefact free; exception releases the reservation; a failed metering write never blocks delivery, keeps quota held, reconciles on same-key replay; replay never double-counts; failed/degraded trend report rules).
- **Gap 1:** `pi.discover`/`pi.supplier_lookup` (`GENERATE_METERED`) record no usage; `niche_run` is the all-time row count of `pi_research_run`. **Gap 2:** CFO/CI/GST usage is never recorded, so a cap seeded for them could not bind (no caps are seeded today, so there is no current financial effect). **Semantic risk:** a `DELIVERED` turn with a failed required leg consumes a CEO unit (experiment X1). External calls can succeed while Metrion records failure (CMO trends: retrieval precedes the model step; PI: external calls precede a later exception; hard crash after a send).
- **No billing behaviour has been changed.** Decisions taken (2026-10-10): Q-S0-1 (PI records one idempotent event per successful run) and Q-S0-3 (no CEO unit when any required leg failed); both are designed (R3, R2) and unimplemented.

### 13.2 VP-2 evidence (summary)
- Experiment X2: killed process mid-leg ⇒ turn `PLAN_VALIDATED`, CEO anchor run `RUNNING`, leg run `RUNNING`, an unanswered `USER` message; lock auto-released; next turn fine; **stuck rows never reconciled**. Ten stuck-state classes enumerated (findings §B.2), including PI runs stuck `QUEUED`/`RUNNING`, a `DELIVERED` turn missing its CEO unit, and late legs that legitimately outlive their turn.
- Recoverable: turn rows, anchor runs, internal legs, orphaned messages, a missing CEO-unit event (idempotent repair), CMO reservations (self-heal by TTL + same-key replay). **Outcome-unknown:** any external-capable leg that was `RUNNING` at the crash.
- Required mechanisms (spec §6.8): per-investigation advisory lock as the **liveness proof** (a successful `pg_try_advisory_lock` means no live turn), reconciler (lazy on read/approve/next turn; periodic optional), `OUTCOME_UNKNOWN`, plan CAS, plan-derived idempotency keys for metered legs, **no automatic retry and no charge for an uncertain outcome**, fail closed when `ceo_leg_timeout_seconds` is unset.

### 13.3 External-effect classification (summary)
36 registered actions inspected. Declared `effect` understates real behaviour in three ways: network use under `COMPUTE_PERSIST` (`cfo.gst_lookup` fetches fixed public pages), model calls under `COMPUTE_PERSIST` (`cfo.period_comparison`, GST extraction), and PI actions declared metered that record nothing. **`ci.discover_competitors` is internal today** (the composition root is `MockSearchProvider`; no network code in the run) but is the designed seam for a future real provider ⇒ a guard test must force a registry review when a provider is wired. Replacement fields: `meters`, `external`, `requires_approval` (D1); table in §5.5.

### 13.4 Approval-state representation and audit integrity
1. **Correctness blocker:** `orchestrator.py:271` stores any status outside `{DELIVERED, CLARIFIED, DENIED, FAILED}` as `FAILED`; `PLANNED` must be added there or a planned turn is silently recorded as failed.
2. **Constraints:** extend `investigation_turn_status_check` (+`PLANNED`), `investigation_turn_route_source_check` (+`APPROVAL`), `investigation_message_kind_check` (+`PLAN`); add `investigation_turn.plan_id`.
3. **Metering:** `_finish` meters only `DELIVERED` turns whose billing snapshot is `DUE` (after R2), so `PLANNED` is correctly unmetered; the approved execution turn meters once when `DELIVERED` and `DUE`.
4. **Message classification:** `_turn_context` (classifier) and `summary._due_messages` exclude only `SYSTEM_NOTE` ⇒ `PLAN` must be excluded too, and the approval note must be a `SYSTEM_NOTE`. Typed "yes" after a plan is **not** treated as a clarification reply (that path requires `choices.kind == "INPUT"`; a `PLAN` message has no `choices`). Plan text is code-rendered; seller strings are escaped data; the composer's `PLANNED` reply is a fixed template ⇒ plan and approval messages cannot be read as execution instructions.
5. **Frontend:** `TurnStatus`, `MessageKind`, `route_source` unions, `ExecutionPanel.executionStatusOf`/status map, `ceoModel.messageView` (an unknown kind currently renders as a plain CEO bubble ⇒ plan card required).
6. **Database enforcement:** narrow grants (explicit `REVOKE`, column-level `UPDATE`, events `SELECT, INSERT`) — tests must use `has_column_privilege`; `FORCE` RLS + `tenant_isolation`; **recommended composite FK `(tenant_id, plan_id)` with `UNIQUE (tenant_id, id)`** because FK checks bypass RLS; transition completeness by one transactional repository function (necessary) with a `SECURITY DEFINER` function or constraint trigger as optional hardening (Q-A10).
7. **Rules re-confirmed:** requester-only (`ctx.app_user_id == plan.requested_by`, no role override); 30-minute expiry from a single clock (`runtime.clock()`), blocks starting only; hash over canonical integer-only JSON bound to plan/tenant/investigation/requester/expiry, constant-time compare; revalidation reuses `registry.required_permissions`, attachment check, `open_turn`/`spec.entitlement`, `_validate_slots`, `data_basis` fingerprints (`state_cache`), `ceo_playbook_max_legs`, `ceo_leg_timeout_seconds`.

### 13.5 Inconsistencies found (cumulative)
1. Status whitelist coercion (13.4-1). 2. CEO unit metering is `DELIVERED`-only (D6 corrected). 3. `user_message_id NOT NULL` ⇒ approval note message (D8). 4. `auth_audit` is app-deletable ⇒ dedicated append-only event table (D7). 5. Default privileges defeat plain `GRANT` ⇒ explicit `REVOKE` (the 0010→0011 lesson). 6. Message-kind filters need `PLAN`. 7. `ceo_leg_timeout_seconds`/`ceo_playbook_max_legs` return `None` when unset ⇒ fail closed. 8. Declared `effect` understates behaviour (13.3). 9. SSE `event_bus` is per-process ⇒ polling stays the fallback. 10. `POST …/turns` is synchronous and not idempotent ⇒ approve needs CAS + idempotent replay that reports an in-flight turn. 11. CI round-trips `downgrade base` on an empty DB ⇒ the new downgrade must pass there and refuse when approval rows exist. 12. `pi_research_run.has_active_run` is defined but never called in `src` (no edit-lock effect). 13. Out-of-catalog UI actions end `DENIED` while out-of-catalog classifier decisions end `CLARIFIED` (X3 vs `test_a_write_class_request_is_declined…`) — cosmetic inconsistency, optional.

### 13.6 Schema changes for the approval build (one migration: ~~`20261011_0018_ceo_approval_workflow`, `down_revision = 20261011_0017`~~ — **superseded 2026-10-12: that id/parent is taken, see "Amendment 2026-10-12" at the top**). Prerequisites: `0016` (R4) adds `PLANNED` to the turn status CHECK; `0017` (R0) adds the `accounting_cutover` table (and a PI-package migration adds `pi_research_run.created_at`, `outcome_code`, `usage_due`). The `route_source` + `APPROVAL`, message kind + `PLAN`, `plan_id` and both new tables below belong to 0018.
| Change | Detail | Migration notes | Tests |
|---|---|---|---|
| `investigation_plan` | §5.1; FORCE RLS + `tenant_isolation`; partial unique index; CHECKs; **`UNIQUE (tenant_id, id)`** | create; `REVOKE ALL` then narrow grants | RLS isolation (pattern of `test_ceo_foundation_rls`), constraint tests, privilege tests |
| `investigation_plan_event` | §5.2; FORCE RLS; append-only; **composite FK `(tenant_id, plan_id)`** | create; `SELECT, INSERT` only | RLS, append-only direct-SQL test, cross-tenant FK test |
| `investigation_turn` | route_source CHECK + `APPROVAL`; `plan_id uuid null` (the status CHECK + `PLANNED` is already done by 0016 / R4) | `DROP CONSTRAINT … / ADD CONSTRAINT …` (0006 used `NOT VALID`; add then `VALIDATE`); downgrade first fails if any `PLANNED`/`APPROVAL` row exists | `test_ceo_turn.py` (references `PLAN_VALIDATED`); new transition tests |
| `investigation_message` | kind CHECK + `PLAN` | same pattern; downgrade fails if any `PLAN` row | message-kind tests |
| Privileges | §5.4 | explicit `REVOKE`s; column-level `UPDATE` | extend `test_privilege_boundary.py` with `has_column_privilege` and direct-SQL `metrion_app` attempts; keep `KNOWN_APP_DELETABLE` accurate |
| Downgrade | drops new tables/columns, restores CHECKs | **refuses when rows exist**; CI `downgrade base` on an empty DB passes | CI migration round-trip |
No change to `agent_run`, `auth_audit`, `membership` or any other package's migrations. `tools/testkit/tenant_cleanup.py` discovers tenant-owned tables from the catalog (deletes as the owner role), so it needs no change but must be run to confirm the new tables purge children-first.

### 13.7 API changes
`GET …/plans`, `GET …/plans/{id}`, `POST …/plans/{id}/approve`, `POST …/plans/{id}/decline` (§6.5). `POST …/turns` response gains `status: "PLANNED"` and a `plan` object (`id, status, expiresAt, planHash, summary, legs, meters, external, destinations, assumptions, priorAttempt`). Investigation detail gains `plans`. New error codes (§6.5). Tests: API contract tests beside `test_ceo_api*.py`; frontend client contract in `lib/ceo.test.ts`.

### 13.8 Permission changes
**None required** under the recommended design (Q-A4): approval reuses `agent.ceo`, `investigation.view` and each leg's `required_permissions`, plus the in-code requester check. `permissions.py` `ALL_KEYS`, the role grid and `auth.md` §5.2 stay unchanged.

### 13.9 Code changes outside the schema
`contract.py`/`registry.py` (fields, per-action values, enumeration + provider-pin tests); `orchestrator.py` (planning stage, `PLANNED` finalisation **and whitelist fix**, `input_session.Done` → plan, `PLAN` context filter); `summary.py` (kind filter); new `ceo/approval.py` (canonical hash, plan builder, approval checks, execution turn, reconciler); `investigation_repo.py` (plan/event functions; `resolve`/`archive` supersede open plans); `api/v1/ceo.py` (four routes); `config.py` + `.env.example`; composer `PLANNED` template + evals; frontend `lib/ceo.ts`, `lib/ceoModel.ts`, `ExecutionPanel.tsx`, new `PlanCard.tsx`, `Conversation.tsx`; docs (`ceo-agent-orchestration.md` §5/§6.32/Q12/C21, `agent-flow-visualization.md` D3, `ceo-build-status.md`).

### 13.10 Ordered remediation plan (revision 2)
**Prerequisite fixes (separate checkpoint; none implemented):** R4 `PLANNED` vocabulary (`20261011_0016_turn_status_planned`) → R0 accounting cut-over (`20261011_0017_accounting_cutover` + PI `20261011_0002_pi_run_accounting`) → R1 effects metadata ∥ R7 LLM endpoint guard → R2 CEO unit ∥ R3 PI usage (R6 PI quota reservation lands before any PI cap is seeded) → R5a/b stuck-row reconciliation → R5c repairs. Each of R4, R0, R1, R7, R2, R3, R6 can be implemented and reviewed independently; R5c depends on R0, R2 and R3.
**Approval build (after the prerequisites are accepted):** migration ~~`20261011_0018_ceo_approval_workflow`~~ *(id superseded 2026-10-12, see the amendment at the top)* (plan and event tables, `route_source` + `APPROVAL`, message kind + `PLAN`, `plan_id`, narrow grants, safe downgrade); planning; approve/decline + execution; frontend. N6 (approve CAS + plan-derived idempotency keys for metered legs), N7 (exclude `PLAN` from classifier context and summary) and N8 (fail-closed enablement config) belong here.
**Optional** — O1 composite `(tenant_id, plan_id)` FK (recommended) · O2 `SECURITY DEFINER` transition function or constraint trigger · O4 usage recording for CFO/CI/GST · O5 call or remove `has_active_run` · O6 unify out-of-catalog statuses · O7 idempotency key on `POST …/turns` · dedupe PI's double `agent_run` (F10).

### 13.11 Implementation plan
| Step | Scope | Exit criteria |
|---|---|---|
| **S0** | Verification — done. | VP-1 FAIL, VP-2 FAIL (owner reviewed) |
| **P0 Remediation design** | `ceo-approval-remediation-design.md` revision 2 — done; awaiting review | owner answers F1–F10 or explicitly defers them (F1 and F5 block only the reconciliation threshold and any third-party model endpoint) |
| **P1 Prerequisite implementation checkpoint** | R4, R0, R1, R7, R2, R3, R6, R5 per the design; each with its failure-injection tests; scratch DB first; dev DB only after review with a before/after fingerprint | AC-R0…AC-R7 pass; VP-1 and VP-2 PASS demonstrated; **no** plan creation, approval endpoints, approval execution or workflow editor |
| **S1–S3 Registry gate, approval schema, planning** | `ActionEffects`-driven gate, migration 0018, planner, hash, `PLANNED` production, composer template, evals | AC-A1–A3, A5, A7, A10–A12, A16 |
| **S4 Approve/decline + execution** | endpoints, §6.6 checks, execution turn, locking, events, supersession | AC-A4, A6, A8, A9, A13 |
| **S6 Frontend** | types, plan card, panel states, requester-only controls | AC-A17; vitest/lint/tsc/build; owner's signed-in check |
| **S7 Hardening** | full suites, security review, spec amendments | all ACs; owner sign-off |
Enablement stays gated by the D9 configuration: when unset, approval is disabled and flagged actions are **refused with an explanation**, never run unapproved. **Gate to enable approval at all:** P1 done (VP-1 and VP-2 PASS).

### 13.12 Files likely to change in the prerequisite checkpoint (P1)
Source: `backend/src/backend/ceo/effects.py`, `billing.py`, `reconcile.py` (all new); `ceo/contract.py`, `registry.py`, `orchestrator.py`; `repositories/agent_run_repo.py`, `investigation_repo.py`, `entitlement_repo.py`, `accounting_cutover_repo.py` (new), `quota_reservation_repo.py` (new); `api/v1/pi.py`, `api/v1/ceo.py`; `services/pi_usage.py` (new); `entitlement.py`, `config.py`, `llm/model.py`, the LLM call-site factories, `.env.example`, `backend/README.md`; PI package `pi_research_run_repo.py`. Migrations: core `20261011_0016_turn_status_planned.py`, `20261011_0017_accounting_cutover.py`; PI `20261011_0002_pi_run_accounting.py`. Tests: new `test_ceo_effects.py`, `test_pi_payload_pins.py`, `test_ceo_unit_decision.py`, `test_ceo_unit_billing.py`, `test_pi_usage.py`, `test_pi_quota_reservation.py`, `test_ceo_turn_status_vocabulary.py`, `test_accounting_cutover.py`, `test_ceo_reconcile.py`, `test_ceo_reconcile_cli.py`, `test_llm_endpoint_trust.py`, `test_llm_external_refusal.py`; updated `test_privilege_boundary.py`, `test_ceo_dispatch_integration.py`, `test_pi_discover_api.py`, `test_pi_route_permission_entitlement_enforcement.py`; frontend `lib/ceo.ts`, `lib/ceoModel.ts`, `ExecutionPanel.tsx` and their tests. Per-fix breakdown: remediation design §4.

## 14. Prerequisite implementation status (2026-10-10)

Prerequisites R0–R4, R6, R7 are implemented and verified with targeted tests (R5 crash reconciliation is **BLOCKED** until a safe staleness threshold is supported by evidence). Migration numbering after the merge: `20261011_0016` (R4 `PLANNED`), `20261011_0017` (R0 cut-over); the approval migration was planned as `20261011_0018_ceo_approval_workflow` *(superseded 2026-10-12: `20261012_0018` is now `app_role_least_privilege`; see the amendment at the top)*. The CEO billing section is §6.42 of `ceo-agent-orchestration.md`. `candidate_cap` on `POST /pi/discover` is bounded `1..100` (a proposed contract narrowing to be confirmed). No approval endpoint, plan creation, execution or editor exists. Evidence and the PASS/FAIL/BLOCKED table: `docs/planning/ceo-approval-remediation-design.md` §6.

**Test evidence and S1 readiness (2026-10-10).** Evidence: `ceo-approval-remediation-design.md` §7. R0–R4, R6, R7 PASS (targeted); **R5 BLOCKED**; therefore VP-2 is still **FAIL** and the "gate to enable approval at all" (P1 done) is **not** met. The first row of the approval build in §13.11 is one row, "S1–S3 Registry gate, approval schema, planning", with no boundary between S1, S2 and S3 in this specification. The registry half of it (AC-A2: all 36 actions classified, the CI provider pin) is already satisfied by R1 (`ceo/effects.py`, `tests/unit/test_ceo_effects.py`). Anything beyond that (the schema migration `20261011_0018`, planning, `PLANNED` production) is **not started**: it waits for the P1 review, for the S1/S2/S3 boundaries to be stated, and for Q-A9 (plan TTL knob) and Q-A10 (transition mechanism).

**S1–S3 boundary, R5 evidence plan, verification gate and decision register (2026-10-10, proposal, nothing accepted):** `docs/planning/ceo-approval-s1-readiness.md`. Two findings recorded there that affect this specification: (1) the §5.5 "Chat today" column is **stale**: after the pulled branch, `pi.discover`, `cmo.generate_*` and `cmo.market_trends` run from chat after an in-session confirm card with no plan, hash, expiry or requester binding (orchestration 6.35/6.40); under C3 that confirmation is not approval, so the interim status of those paths is an open owner decision (D-8); (2) D9 words the staleness threshold as `ceo_leg_timeout_seconds + margin`, but late legs keep running after the turn and its lock end (`pool.shutdown(wait=False)`), so the threshold must be per action (the remediation design's R5.6), and a free investigation lock does not prove a `RUNNING` leg is dead.

**Runtime closure of the chat paths (D-8, 2026-10-10).** The six approval-required chat actions are refused from chat (orchestrator + `dispatch()` backstop, using the S1 gate `ceo/approval_gate.py`); `chatActions` excludes them; tests `tests/integration/test_ceo_approval_blocked_chat.py`. This is a safety closure, **not** the approval workflow: no plan table, endpoint, hash, expiry or execution exists, and S2/S3 are not started.

## 15. Checkpoint 1 implementation status (2026-10-12; S1-S4 backend)

Implemented (backend only; no frontend): migration `20261012_0019_ceo_approval_workflow` on `20261012_0015`; `investigation_plan` / `investigation_plan_event`; `repositories/investigation_plan_repo.py`; `ceo/approval.py` (canonical form, hash, plan builder, checks 1-10 of section 6.6, decline, lazy expiry); `ceo/approval_run.py` (check 11, the approval transaction, execution of exactly the frozen legs); `ApprovalGrant` in `dispatch()`; the four endpoints of section 6.5 plus `plans` on the investigation detail; supersession on a newer plan and on resolve / archive. Tests: `tests/unit/test_ceo_approval_unit.py`, `tests/integration/test_ceo_approval_workflow.py`, `tests/integration/test_ceo_approval_schema.py`, additions to `test_privilege_boundary.py`.

Implementation choices that stand until the owner confirms or changes them (recorded here, not decided silently):
- **Q-A9 (TTL).** The recommendation in `docs/planning/ceo-approval-r5-decision-matrix.md` was followed: `PLAN_TTL_SECONDS = 1800` is a code constant stored in each plan's `expires_at`; no setting exists. Awaiting the architect's one-line confirmation.
- **Q-A10 (transition completeness).** Option (1)+trigger: one transactional repository function, plus a guard trigger (frozen plan and identity immutable even for the owner role, a plan starts AWAITING_APPROVAL, terminal states are final) and a deferred constraint trigger (a status change or a new plan without its matching event cannot commit). Not `SECURITY DEFINER`: the app role keeps column-level UPDATE on the five decision columns. Awaiting the architect.
- **Enablement.** `CEO_APPROVAL_ENABLED` (default off) controls only whether CHAT creates plans. Off: a gated request is refused exactly as before (`APPROVAL_UNAVAILABLE_TEXT`). The plan / approve / decline API acts on stored plans either way. Turning it on is the owner's gate (VP-1 / VP-2 restatement, `ceo-cmo-delegation.md` OQ-9); R5 crash reconciliation (section 6.8 rules 1-3, `EXECUTION_NOT_STARTED`, `OUTCOME_UNKNOWN`) is NOT built here.
- **Accounting guard.** Plan creation and approval fail closed (`ACCOUNTING_NOT_READY`) when the CEO unit rule 2 cut-over (`accounting_cutover`) is not in effect, because otherwise an approved run that fails would still cost a conversation unit.
- **Integrations.** A plan lists each destination of a leg; a `SELLER_DATA_OUT` leg's destinations are all `required`. Section 6.1 (no plan when an integration is unavailable) is followed at planning time, and E12 / 6.6-10 (refuse at approval) is applied if it disappears afterwards. Whether one unavailable destination among several should block (for example only Tavily configured for `pi.discover`) is open.
- **Units.** A plan lists `units: 1` per meter code per run; the exact count (for example one per COMPLETE marketplace artefact) is decided by the specialist at run time and is stated as such on the card.
- **Execution answer.** The execution turn's answer is the deterministic template over what the legs returned (no composer call). An execution whose required leg failed is a DELIVERED turn with outcome FAILED and no unit, exactly as a normal turn (D6).
- **Not built (later checkpoints):** image-analysis plan (CD10), the frontend plan card, composer evals for the PLANNED reply (the reply is a fixed code template today), the optional periodic reconciler.
