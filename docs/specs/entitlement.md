# Metrion — Entitlement, Metering & Billing Specification

**Status:** Draft for review
**Prerequisites:** `auth.md` (tenancy, membership, the six-step authorization chain, the permission/entitlement two-gate model at §7.2) · `deterministic-engine.md` (F4 — "coefficients, tolerances... are configuration, never constants" — the precedent this spec's config tables follow)
**Related:** `cfo-agent.md` (§6.8/§6.9 entitlement gate and free-tier preview, §7.3.3 recorded input I1/I2, C12) · `competitor-intelligence-agent.md` (C13, D12, Q15, §12 Q2/Q3) · `whatsapp-integration.md` (W10, cap/credit treatment referenced but not resolved here) · `phase-1-readiness-review.md` §1 "Agent cart", item 3 "Entitlement, metering & billing seams", p.17 token-ranking discussion (not reopened) · a future `billing-and-pricing.md` (not written, not this spec — owns final prices, tier names and credit counts)

**This specification is the referent every other spec has been citing as "entitlement spec (not yet written)."** It exists to turn `backend/src/backend/entitlement.py`'s `resolve_ci_entitlement`/`resolve_cfo_entitlement` — both explicitly TEMPORARY, always-pass scaffolds — into real, deny-capable functions. That rewrite is a separate task (F2). This spec defines the schema and mechanism F2 will be built against. It asserts **no price, tier name, or credit count** — every numeric threshold this spec introduces is a real, queryable, unseeded configuration column, mirroring `fee_reference`'s empty-but-real table today.

**This specification contains no LLM.** Entitlement, like authorization, is entirely deterministic — a set of comparisons between recorded usage and configured caps. No decision described here is made by, delegated to, or influenced by a model.

---

## 1. Confirmed decisions

Settled. Not reopened here.

| # | Decision |
|---|---|
| N1 | **Permission and entitlement are separate, both-must-pass gates** (`auth.md` §7.2). This spec owns entitlement only. It does not touch `membership.permissions`, the `agent.*` keys, or the six-step chain. |
| N2 | **No real prices, tier names, or credit counts are defined anywhere in this spec.** Every numeric cap is a named, unseeded config column — the same posture `fee_reference` and `reconciliation_tolerance_config`/`severity_config` already ship in `packages/calc-engine`. |
| N3 | **This spec does not design payment integration.** Razorpay wiring, invoicing, and how a purchase actually happens are out of scope. This spec defines what gets metered and gated — the record a purchase would produce, not the checkout flow that produces it. |
| N4 | **`resolve_ci_entitlement`/`resolve_cfo_entitlement`'s existing shape continues** — a frozen dataclass result (`passed`, `reason`, plus real live-queried usage), one chokepoint function per agent, called from `ceo_hub.py`'s dispatch functions before `agent_run` insertion. This spec extends that shape; it does not replace the integration pattern. |
| N5 | **Money math is untouched by this spec.** Every quantity here is a usage **count** (runs, saved resources, member-scoped sub-allocations) — never a paise amount, never a price. The `BIGINT` paise / no-floats / `UNAVAILABLE`-not-zero discipline governs Brain 1 exclusively and has no surface in this document. |
| N6 (resolves `auth.md` Q6) | **A removed partner's investigations, uploads and manual adjustments remain with the tenant.** The tenant owns the data; only the removed member's access is revoked. This is not entitlement-specific, but it governs the identical question for this spec's own member-scoped rows (`metered_event.member_id`, `member_entitlement_allocation`): a removed member's historical usage rows and any allocation made to them are retained, unmodified, attributed to a now-inactive `app_user`. Inherits the recommendation already on record at `auth.md` Q6; not re-litigated. |

---

## 2. Design decisions requiring review

My recommendations. Each is a mechanism decision — none asserts a number.

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 (resolves `cfo-agent.md` Q13 / `auth.md` E19) | **May an entitlement denial render as a reduced payload instead of a bare error?** | **Yes, but only when explicitly registered.** A denial defaults to a bare error. It may instead render as a reduced payload **only** for a direct action that (a) has its own `capability_entitlement_rule` row setting `denial_rendering = REDUCED_PAYLOAD`, and (b) names a `reduced_payload_action_code` that is itself a registered, spec-defined direct action (e.g. `cfo-agent.md` §6.9's `cfo.preview`). There is no generic "soften the error" behaviour and no ad hoc partial response invented mid-flight. | TRUST is the product's load-bearing property (`CLAUDE.md`). A denial that silently becomes "sort of works" everywhere would let a seller mistake a locked capability for a working one. Restricting the reduced-payload path to pre-registered, spec-reviewed actions keeps every softened denial as deliberate and auditable as a hard error — while still permitting `cfo-agent.md`'s already-designed preview to exist as the mechanism its own spec assumed. Default-to-error means a future capability gets a bare error unless someone explicitly designs and reviews a reduced shape for it — the safe default. |
| D2 (resolves `auth.md` Q5, mechanism only) | **Does the schema support per-member sub-caps, or is every cap strictly per-tenant?** | **Both are expressible.** `entitlement_cap_config.scope` is `TENANT` or `MEMBER`. When `TENANT` (the only value any config row carries in V1, since none are seeded), usage is summed across the whole tenant against one cap. When `MEMBER`, usage is summed per `metered_event.member_id` and may additionally be sub-allocated per member via `member_entitlement_allocation`, gated behind `team.manage` (`auth.md` §5.2). No sub-cap values are seeded; V1 ships with `scope = TENANT` semantics only, exercised nowhere. | The actual policy question (per-member sub-caps vs. first-come-first-served) is a product decision this spec cannot make — see §12 Q1. What it can do is make sure the schema doesn't have to change shape once that decision lands. A nullable, presently-unused `MEMBER` scope costs nothing to ship now and avoids a migration later. |
| D3 | **Usage is computed live from `metered_event`, not from a separately-maintained running counter.** | **No counter table in V1.** `resolve_*_entitlement` aggregates `metered_event` rows for the current `period_key` at check time, exactly as `resolve_ci_entitlement` today live-queries `competitor_url_repo.count_active` and `resolve_cfo_entitlement` live-queries `agent_data_request_repo.count_open`. | Matches the existing, already-built precedent exactly (N4). A cached counter is a legitimate later optimisation once real cap values and real traffic exist to justify it — introducing one now, unseeded and unused, would be premature and would add a second source of truth to keep consistent with zero benefit today. |
| D4 | **A metering-write failure must never block a run whose entitlement check already passed.** | Record the `metered_event` **after** the run reaches a terminal state, best-effort, with retry; a failure to record is logged and reconciled out of band. It never rolls back or blocks the seller's already-delivered result. | Blocking or reverting delivered product value because an internal accounting write failed is a worse failure mode than a temporarily under-counted usage row — especially before any real cap exists to enforce. Metering must degrade gracefully; entitlement **checking** (read path) must not. |
| D5 | **Which terminal states of a run consume a metered unit is each consuming agent's own call, not this spec's.** This spec provides the recording mechanism and the idempotency guarantee; it does not mandate that `COMPLETE`, `PARTIAL`, or `FAILED` all consume a unit uniformly. | Each agent spec (`cfo-agent.md` §6.8, `competitor-intelligence-agent.md`'s direct paths) states, action by action, which of its own terminal states records a `metered_event`. Recorded as a genuine gap at §12 Q3 rather than decided here. | This spec owns the meter's shape, not each capability's consumption semantics — deciding it here would mean re-litigating every direct action table in two other specs. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | `tenant.timezone` (`auth.md` §5.1, default `Asia/Kolkata`) is the correct basis for calendar-period caps (e.g. a "monthly" cap resets on tenant-local month boundaries, not UTC). | Low — affects only exact reset timing, not correctness of the mechanism. |
| A2 | `agent_run` (`auth.md`/orchestration schema) remains the canonical record of one agent invocation, and a `metered_event` may reference it via `agent_run_id` where one exists. | Medium — if orchestration's `agent_run` shape changes materially, this spec's FK needs revisiting. |
| A3 | Shared services (`service.gst_lookup`, `research.niche_run`, `research.market_trends` — the last added 2026-10-03 for the Market Signal Retrieval service, `slim-cmo-agent.md` §6.8) are metered under their own `meter_code`, independently of the owning agent's cap, exactly as `auth.md` §5.2 already states they carry their own entitlement caps. | Low — already confirmed upstream; this spec only needs to represent it, not decide it. |
| A4 | No self-serve purchase flow exists in V1 (N3); `tenant_plan`/`tenant_cart_item` rows above `FREE` are written by an internal, non-application process until Razorpay wiring lands. | Low — explicitly a non-goal; stated so nobody infers a checkout flow from this schema. |

---

## 4. Goals and non-goals

### Goals
- Define the entitlement chokepoint's real (post-scaffold) result shape and resolution mechanism, so F2 can rewrite `resolve_ci_entitlement`/`resolve_cfo_entitlement` against it without inventing anything.
- Define a real, queryable "which plan/tier is this tenant on" data model (the account→plan chain).
- Define a real, queryable "what consumed a unit of entitlement" data model (metered events) general enough to leave CI's discovery-run-vs-upload-run meter question (D12/Q15) answerable later with a config change, not a schema change.
- Define a real, queryable deny-threshold/run-credit config mechanism, config-not-constants, with zero seeded numeric values.
- Resolve, as mechanism only: whether an entitlement denial may render as a reduced payload (Q13), and whether the schema supports per-member sub-caps (Q5).
- Confirm `auth.md` Q6's recommended resolution for this spec's own member-scoped rows.

### Non-goals (V1)
- Any real price, tier name, or credit count (N2).
- Payment/billing integration — Razorpay checkout, invoicing, receipts, refunds (N3).
- Resolving *whether* a discovery run and an evidence-upload run share a meter (CI D12/Q15 stays open — the schema must merely support either answer).
- Resolving the actual per-member sub-cap policy (per-member allocation vs. first-come-first-served) — mechanism only (D2).
- A self-serve upgrade/downgrade flow.
- Redis-backed rate limiting (`cfo-agent.md` §6.8's "Rate limit" column is a separate, lower-level throttling concern from this spec's monthly/period entitlement caps and is not designed here).
- A billable-token or hosted-LLM-cost meter — `cfo-agent.md` §7.3.3 explicitly hands this spec I1/I2 as input, not as a decision to make today; no meter is asserted to be token-based, run-based, or anything else.

---

## 5. Data model

All tenant-owned tables here carry `tenant_id` and are `FORCE ROW LEVEL SECURITY`-scoped exactly per `auth.md` §7.3. Platform-owned config tables (`tenant_id` nullable = platform default) mirror `reconciliation_tolerance_config`/`severity_config`'s precedent exactly, including the "tenant row beats platform default, latest `effective_from` wins" resolution order and the RLS policy that lets a `NULL` `tenant_id` row remain visible to every tenant.

### 5.1 Account → plan chain

```sql
plan (                                    -- platform-owned, no tenant_id — mirrors fee_reference
  id          uuid primary key default gen_random_uuid(),
  code        text unique not null,       -- structural label only, e.g. 'FREE' — no price implied, no tier catalogue asserted as final
  name        text not null,
  status      text not null,              -- ACTIVE | RETIRED
  created_at  timestamptz not null
)

tenant_plan (                             -- which base plan a tenant is on
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenant,
  plan_id     uuid not null references plan,
  status      text not null,              -- ACTIVE | TRIAL | CANCELLED | EXPIRED
  started_at  timestamptz not null,
  ended_at    timestamptz,
  source      text not null               -- SIGNUP_DEFAULT | ADMIN_GRANT | PURCHASE (N3: PURCHASE exists as a value; no purchase flow writes it in V1)
)
-- at most one ACTIVE-or-TRIAL row per tenant:
--   unique index on (tenant_id) where status in ('ACTIVE', 'TRIAL')

tenant_cart_item (                        -- per-agent capability tier — the "agent cart" (readiness §1)
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenant,
  agent_code    text not null,            -- CEO | CFO | CI | PI | CMO — mirrors auth.md's agent.* key space
  tier          text not null,            -- structural only, e.g. FREE | LIMITED | COMPLETE — no price implied; names may change before launch
  status        text not null,            -- ACTIVE | CANCELLED | EXPIRED
  started_at    timestamptz not null,
  ended_at      timestamptz,
  source        text not null,            -- SIGNUP_DEFAULT | ADMIN_GRANT | PURCHASE
  unique (tenant_id, agent_code)          -- partial: where status = 'ACTIVE'
)
```

Every tenant receives a `SIGNUP_DEFAULT` `tenant_cart_item` row per agent at tenant creation (`auth.md` §6.2), atomically with tenant creation. This spec does not assert what `tier` those default rows carry — that is a product/pricing decision (`billing-and-pricing.md`, not written). What is structural and decided here is that the row exists, so "which tier is this tenant on for CFO" is always answerable by a query, never by an absence.

### 5.2 Metered events

```sql
metered_event (                           -- what consumed a unit of entitlement
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenant,
  member_id          uuid references app_user,     -- nullable; who triggered it (D2/Q5 per-member basis)
  agent_code         text not null,                -- CFO | CI | PI | CMO | SHARED (shared services, A3). CMO event_kinds are the trigger ids enumerated in slim-cmo-agent.md §8.1 (cmo.generate_title_sets, cmo.generate_listing_copy, ... cmo.market_trends); one delivered artefact = one event (idempotency_key = the CMO request_key). Shared meter for trends: 'research.market_trends'. No metered_event_meter_map row and no cap value is seeded by this amendment.
  event_kind         text not null,                -- structural trigger id, e.g. 'cfo.reconcile', 'ci.discover',
                                                     -- 'ci.evidence_upload', 'service.gst_lookup' — mirrors the
                                                     -- direct-execution-path trigger ids already enumerated in
                                                     -- cfo-agent.md §6.8 and competitor-intelligence-agent.md's
                                                     -- own direct-path table
  meter_code         text not null,                -- the actual billing "unit" this event counts against —
                                                     -- resolved from metered_event_meter_map at write time (§5.2.1),
                                                     -- NEVER hardcoded by the calling agent
  quantity           int not null default 1,
  agent_run_id       uuid,                          -- FK to agent_run where one exists (A2); nullable for
                                                     -- shared-service calls with no owning agent_run
  source_ref         uuid,                          -- polymorphic pointer (e.g. ci_discovery_run.id); no FK
                                                     -- enforced, mirrors leak_finding's own precedent of a
                                                     -- non-FK-enforced provenance pointer where the referent
                                                     -- table varies by event_kind
  idempotency_key    text not null,                 -- caller-supplied; prevents double-counting on retry
  occurred_at        timestamptz not null,
  period_key         text not null,                 -- tenant-timezone calendar bucket, e.g. '2026-09' (A1)
  unique (tenant_id, idempotency_key)
)
```

#### 5.2.1 `metered_event_meter_map` — the CI-Q15-safe indirection

```sql
metered_event_meter_map (                 -- structural mapping only; config-not-constants (deterministic-engine.md F4)
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid,                    -- null = platform default
  event_kind     text not null,
  meter_code     text not null,
  effective_from date not null,
  version        int not null,
  unique (tenant_id, event_kind, effective_from)
)
```

**This is the mechanism that keeps CI's D12/Q15 genuinely open rather than silently deciding it.** Whether `ci.discover` (a discovery run) and `ci.evidence_upload` share a meter is expressed entirely by whether their `metered_event_meter_map` rows resolve to the *same* `meter_code` or *different* ones. No schema change is required either way — only a config row, seeded when that product decision is made. **This spec seeds no row here and asserts no answer.** See §12 Q3.

A `metered_event` is written with the `event_kind` the calling agent actually performed; `meter_code` is resolved by looking up `metered_event_meter_map` at write time (tenant-specific row beats platform default, latest `effective_from` wins — the same resolution order as every other config table here). If no mapping row exists for an `event_kind` yet, the event is recorded with `meter_code = event_kind` as a 1:1 fallback (never silently dropped) — an explicit, disclosed default, not a guess about final billing shape.

### 5.3 Deny-threshold / run-credit configuration

```sql
entitlement_cap_config (                  -- mirrors reconciliation_tolerance_config's exact shape
  id                  uuid primary key default gen_random_uuid(),
  tenant_id           uuid,               -- null = platform default
  agent_code          text not null,
  meter_code          text not null,
  scope               text not null,      -- TENANT | MEMBER (D2/Q5)
  period_unit         text not null,      -- MONTH | DAY | RUN_LIFETIME — structural; no cadence asserted as final
  cap_value           bigint,             -- NULL = unbounded/unset. NO ROW IN THIS SPEC SEEDS A NON-NULL VALUE.
  saved_resource_cap  bigint,             -- generalizes non-run caps (e.g. CI's "saved URL" count, C13); NULL = unset
  effective_from      date not null,
  version             int not null,
  unique (tenant_id, agent_code, meter_code, scope, effective_from)
)

member_entitlement_allocation (           -- exercised only when a cap's scope = MEMBER (D2); unused in V1
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenant,
  member_id       uuid not null references app_user,
  agent_code      text not null,
  meter_code      text not null,
  allocated_value bigint,                 -- NULL = draws from the tenant-wide pool, not a personal sub-cap
  period_unit     text not null,
  effective_from  date not null,
  unique (tenant_id, member_id, agent_code, meter_code, effective_from)
)
```

Writing a `tenant_id`-not-null `entitlement_cap_config` row (a negotiated per-tenant override) is reserved for a future admin process; no such row is written by any application code path in V1. Writing a `member_entitlement_allocation` row requires `team.manage` (`auth.md` §5.2, OWNER-held by default) — consistent with every other team-management action.

### 5.4 Denial rendering — the Q13 mechanism

```sql
capability_entitlement_rule (
  id                          uuid primary key default gen_random_uuid(),
  tenant_id                   uuid,       -- null = platform default; almost always platform-level
  agent_code                  text not null,
  direct_action_code          text not null,   -- e.g. 'cfo.reconcile', 'cfo.preview', 'ci.discover' —
                                                -- matches the trigger ids already enumerated in each
                                                -- agent's own §6.8-style direct-path table
  denial_rendering            text not null default 'ERROR',   -- ERROR | REDUCED_PAYLOAD
  reduced_payload_action_code text,            -- required when denial_rendering = REDUCED_PAYLOAD; must
                                                -- itself be a registered direct action defining a reduced
                                                -- shape (e.g. cfo-agent.md §6.9)
  effective_from               date not null,
  version                      int not null,
  unique (tenant_id, agent_code, direct_action_code, effective_from)
)
```

A row is seeded here for `cfo.reconcile`/`cfo.pnl`/`cfo.pricing`/etc. → `denial_rendering = ERROR` (the default, requiring no row at all since `ERROR` is the column default) and — **once `cfo-agent.md`'s Q13 is formally closed by this spec landing** — a row for the agent-code/action-code pair `CFO`/`cfo.reconcile` (or whichever action the preview stands in for) → `denial_rendering = REDUCED_PAYLOAD`, `reduced_payload_action_code = 'cfo.preview'`. **This spec does not itself insert that seed row** — doing so is F2's job, once it also rewrites `resolve_cfo_entitlement`. What this spec fixes today is that the *mechanism* exists and defaults safely to `ERROR` everywhere until a row explicitly says otherwise.

### 5.5 The resolution result contract

`resolve_ci_entitlement`/`resolve_cfo_entitlement` (and any future `resolve_pi_entitlement`/`resolve_cmo_entitlement`) are rewritten, at F2, against this result shape:

```
EntitlementResult {
  passed:                       bool
  reason:                       str | None
  meter_code:                   str
  usage_count:                  int             -- real, live-aggregated from metered_event for period_key
  cap_value:                    int | None       -- None = NO_CAP_CONFIGURED, i.e. today's actual state
  evaluation_basis:             NO_CAP_CONFIGURED | UNDER_CAP | OVER_CAP
  denial_rendering:             ERROR | REDUCED_PAYLOAD
  reduced_payload_action_code:  str | None
  period_key:                   str
}
```

`evaluation_basis = NO_CAP_CONFIGURED` is distinct from `UNDER_CAP` even though both currently `pass=True` — **the distinction matters for TRUST**: a seller-facing "you have runs remaining" claim must never be synthesised from a cap that was never actually set. Everywhere `cap_value` is `NULL` (true of every row this spec seeds — none), `evaluation_basis` is always `NO_CAP_CONFIGURED` and the result always passes. This is the exact, honest continuity path from today's always-pass scaffold: **the scaffold is correct behaviour for a system with no seeded caps, not a placeholder faking a deny path.** F2's rewrite changes nothing about *outcome* until the first non-`NULL` `cap_value` is seeded; it only changes the *mechanism* from hardcoded `passed=True` to a real, comparison-based evaluation that happens to always resolve `NO_CAP_CONFIGURED` today.

---

## 6. Core rules

1. **Two independent gates, unchanged.** Entitlement never substitutes for permission and is evaluated only after the six-step chain's permission check (step 5) has already passed (`auth.md` §7.1/§7.2). An un-permissioned member never reaches entitlement evaluation at all.
2. **Resolution order for every config table here** (`entitlement_cap_config`, `metered_event_meter_map`, `capability_entitlement_rule`) is identical to `reconciliation_tolerance_config`'s: a tenant-specific row (`tenant_id` not null) beats a platform-default row (`tenant_id IS NULL`) for the same key; the latest `effective_from ≤ as_of_date` wins within each tier.
3. **A `metered_event` is written after the triggering action reaches a terminal state**, never before or speculatively — recording a unit for work that has not actually happened is exactly the kind of invented figure `CLAUDE.md`'s hard rule forbids by analogy, even though this is a usage count, not money. Which terminal states of a given action consume a unit is that action's own agent spec's decision (D5, §12 Q3), not this spec's.
4. **Idempotency is mandatory.** Every `metered_event` insert carries a caller-supplied `idempotency_key`, unique per tenant. A retried write with the same key is a no-op, never a double count.
5. **A metering-write failure never blocks or reverts a delivered result** (D4). The entitlement *check* (read path, before the action runs) is synchronous and must succeed or fail closed; the metering *write* (after the action runs) is best-effort and degrades gracefully, logged for reconciliation.
6. **`meter_code` is never chosen by the calling agent inline.** It is always resolved through `metered_event_meter_map` at write time (§5.2.1). This is what keeps CI's discovery-run-vs-upload-run question (D12/Q15) answerable by configuration alone.
7. **Shared services are metered under their own `meter_code`, independently of the owning agent's cap** (`auth.md` §5.2, A3) — e.g. `service.gst_lookup` resolves to a `meter_code` distinct from CFO's own run meter, exactly as `cfo-agent.md` §6.8's `cfo.gst_lookup` row already states ("Shared-service cap (OP9), independent of CFO entitlement").
8. **Period boundaries are computed in the tenant's own timezone** (`tenant.timezone`, default `Asia/Kolkata`, `auth.md` §5.1) for any `period_unit = MONTH` or `DAY` cap. `period_key` is precomputed at write time, not derived lazily at read time, so a timezone or calendar-logic change never silently reinterprets historical events.
9. **A denial's rendering is resolved from `capability_entitlement_rule`, never decided ad hoc by the calling code.** Default is `ERROR` (the column default; absence of a row means `ERROR`). `REDUCED_PAYLOAD` requires an explicit row naming a `reduced_payload_action_code` that is itself a registered direct action with its own spec-defined shape.
10. **Every displayed entitlement-usage figure a seller sees (e.g. "12 of your CFO runs used this month") must be labelled by its `evaluation_basis`.** A `NO_CAP_CONFIGURED` state is never rendered with wording implying a real, enforced ceiling exists.
11. **No client-supplied identifier ever selects a plan, tier, cap, or meter.** Exactly as `auth.md` §7.4 forbids a client-supplied `tenant_id`, no request body field here is trusted to name which plan or cap applies — resolution is always server-derived from authenticated tenant context.

---

## 7. Authorization and security

1. Every table here that carries `tenant_id` not-null is `FORCE ROW LEVEL SECURITY`-scoped exactly per `auth.md` §7.3 — `tenant_plan`, `tenant_cart_item`, `metered_event`, `member_entitlement_allocation`. Nullable-`tenant_id` platform-config tables (`plan`, `entitlement_cap_config`, `metered_event_meter_map`, `capability_entitlement_rule`) follow the exact RLS predicate `reconciliation_tolerance_config` already ships (`tenant_id IS NULL OR tenant_id = current_setting(...)`), so a platform-default row remains visible to every tenant while a tenant-specific override remains private to its own tenant.
2. **Writing a platform-default row (`tenant_id IS NULL`) in any config table here is a `metrion_migrate`-run data migration, never an application code path** — identical posture to `fee_reference`'s existing precedent (`config_repo.py`'s own docstring: "seeding is a `metrion_migrate`-run data migration, not an application code path"). The runtime application role (`metrion_app`) has no business writing a value every tenant will be evaluated against.
3. Writing a **tenant-specific** override row in `entitlement_cap_config`, `metered_event_meter_map`, or `capability_entitlement_rule` is reserved for a future admin process; no application code path in V1 writes one.
4. `tenant_plan`/`tenant_cart_item` rows are written at tenant creation (`SIGNUP_DEFAULT`, atomic with tenant creation, `auth.md` §6.2) or by an internal, non-self-serve process (`ADMIN_GRANT`/`PURCHASE`, A4) — never by a seller-facing endpoint that lets a tenant set its own tier.
5. `member_entitlement_allocation` writes require `team.manage` (OWNER-held by default, `auth.md` §5.2).
6. Every `resolve_*_entitlement` call and its result is server-side only; the six-step chain (`auth.md` §7.1) already guarantees the request carries authenticated, server-derived tenant context before entitlement is ever evaluated. Frontend display of remaining usage is never a security mechanism — it mirrors what the server already decided (`auth.md` S7 precedent).
7. Cross-tenant access to any row here (another tenant's `metered_event`, `tenant_cart_item`, etc.) returns `404`, never `403`, per `auth.md` §7.4 — consistent everywhere else tenant-scoped resources are looked up by id.
8. No endpoint accepts a client-supplied `tenant_id`, `member_id`-as-actor, `meter_code`, or `cap_value` that would override server-resolved context (Core rule 11).

---

## 8. Edge cases

| # | Case | Required behaviour |
|---|---|---|
| E1 | No `entitlement_cap_config` row resolves for a given `(agent_code, meter_code)` | `evaluation_basis = NO_CAP_CONFIGURED`; always passes (§5.5) — today's real, universal state |
| E2 | Two concurrent requests both check entitlement while exactly one unit of headroom remains under a real (future, non-null) cap | Both may pass — this spec accepts eventual consistency in V1; no distributed lock is designed here. Flagged as V1 (§10 V1) |
| E3 | A `metered_event` write fails after its action already completed successfully | The result is still returned to the seller; the metering write is retried/reconciled out of band; never rolled back (D4) |
| E4 | A retried request replays the same `idempotency_key` | No-op; usage is not double-counted (Core rule 4) |
| E5 | `metered_event_meter_map` has no row for a given `event_kind` | Records with `meter_code = event_kind` as an explicit 1:1 fallback, never dropped (§5.2.1) |
| E6 | A tenant's `ACTIVE` `tenant_cart_item` for an agent expires (`ended_at` reached) without a replacement row | The next entitlement check for that agent finds no `ACTIVE` row and denies with `reason = 'NO_ACTIVE_CART_ITEM'` — distinct from a cap-exhaustion denial |
| E7 | A `capability_entitlement_rule` names `denial_rendering = REDUCED_PAYLOAD` but its `reduced_payload_action_code` does not resolve to any registered direct action | Configuration error; the calling agent must fail closed to a bare `ERROR`, never guess at a reduced shape |
| E8 | A member is removed from a tenant (`membership.status = REMOVED`) with existing `metered_event`/`member_entitlement_allocation` rows attributed to them | Rows are retained unmodified, tenant-owned (N6, inherits `auth.md` Q6's recommendation) |
| E9 | A `MEMBER`-scope cap is configured but a given member has no `member_entitlement_allocation` row | `allocated_value = NULL` for that member draws from the tenant-wide pool, not a personal zero-cap (§5.3) |
| E10 | `period_key` computation spans a tenant timezone change (rare: tenant edits `timezone`) | Historical `period_key` values on already-written `metered_event` rows are never recomputed retroactively (Core rule 8) |

---

## 9. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | **Concurrent-request race at cap boundary** (E2) has no locking design in V1. | Correctness of a hard cap under real concurrent load, once any `cap_value` is non-null |
| V2 | **`period_unit = MONTH` calendar-boundary correctness under DST-free but leap/short-month edge cases in `Asia/Kolkata`.** Untested against real data. | Cap reset accuracy |
| V3 | **No cached usage counter exists (D3).** Live aggregation of `metered_event` at every entitlement check has unverified performance at scale. | Latency of the entitlement chokepoint once caps are real and traffic is real |
| V4 | **F2 (the rewrite of `resolve_ci_entitlement`/`resolve_cfo_entitlement` against this spec) is not built.** This spec is a prerequisite for it, not a substitute. | Any real deny behaviour whatsoever — today's scaffolds remain always-pass until F2 ships |

---

## 10. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | No config table in this spec ships a seeded, non-null price, tier name, or credit-count value. |
| AC2 | Every tenant-owned table (`tenant_plan`, `tenant_cart_item`, `metered_event`, `member_entitlement_allocation`) is `FORCE ROW LEVEL SECURITY`-scoped. |
| AC3 | Every platform-config table (`plan`, `entitlement_cap_config`, `metered_event_meter_map`, `capability_entitlement_rule`) follows the tenant-row-beats-platform-default resolution order, verified identical to `reconciliation_tolerance_config`'s. |
| AC4 | A `metered_event` insert with a previously-used `idempotency_key` for the same tenant is a no-op. |
| AC5 | `resolve_*_entitlement`'s result always states `evaluation_basis`, and `NO_CAP_CONFIGURED` is never rendered to a seller as an enforced ceiling. |
| AC6 | An entitlement denial renders as `ERROR` unless a `capability_entitlement_rule` row explicitly sets `REDUCED_PAYLOAD` and names a valid, registered `reduced_payload_action_code`. |
| AC7 | No application code path (only `metrion_migrate`) writes a platform-default (`tenant_id IS NULL`) row to any config table here. |
| AC8 | No endpoint accepts a client-supplied value that overrides server-resolved `tenant_id`, `meter_code`, `cap_value`, or acting `member_id`. |
| AC9 | Cross-tenant access to any entitlement-owned resource returns `404`. |
| AC10 | `metered_event_meter_map` allows `ci.discover` and `ci.evidence_upload` (or any two `event_kind`s) to resolve to either the same or different `meter_code` without a schema change. |
| AC11 | A metering-write failure never causes a previously-successful action's result to be withheld or reverted from the seller. |
| AC12 | `entitlement_cap_config.scope = MEMBER` is a representable, non-placeholder value, and `member_entitlement_allocation` writes require `team.manage`. |

---

## 11. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Query `resolve_cfo_entitlement` for a tenant with no `entitlement_cap_config` rows at all (today's real state) | `passed=True`, `evaluation_basis=NO_CAP_CONFIGURED` (AC5) |
| T2 | Seed a platform-default `entitlement_cap_config` row with a non-null `cap_value`, then check a tenant under that usage | `evaluation_basis=UNDER_CAP`, `passed=True` |
| T3 | Same as T2, tenant usage at or above `cap_value` | `evaluation_basis=OVER_CAP`, `passed=False` |
| T4 | Seed a **tenant-specific** override row alongside the platform-default row for the same `(agent_code, meter_code, scope)` | The tenant-specific row's `cap_value` governs for that tenant (AC3) |
| T5 | Record two `metered_event` writes with the same `idempotency_key` for the same tenant | Second write is a no-op; usage count unchanged (AC4) |
| T6 | Record `metered_event` for `event_kind='ci.discover'` with no `metered_event_meter_map` row seeded | `meter_code` falls back to `'ci.discover'` itself, never dropped (E5) |
| T7 | Seed `metered_event_meter_map` mapping both `ci.discover` and `ci.evidence_upload` to the same `meter_code` | Both event kinds' usage sums into one shared cap check (AC10) |
| T8 | Seed `metered_event_meter_map` mapping them to two distinct `meter_code`s instead | Each event kind's usage is checked against its own independent cap (AC10) |
| T9 | Invoke an action with no `capability_entitlement_rule` row at all and a failing entitlement check | Denial renders as a bare `ERROR` (AC6, default) |
| T10 | Seed a `capability_entitlement_rule` row for `cfo.reconcile` → `denial_rendering=REDUCED_PAYLOAD`, `reduced_payload_action_code='cfo.preview'`, then fail entitlement | Denial renders as the `cfo.preview` reduced payload instead of a bare error (AC6) |
| T11 | Attempt to write a platform-default row to `entitlement_cap_config` as the `metrion_app` runtime role | Rejected — only `metrion_migrate` may write it (AC7) |
| T12 | Client request includes a `tenant_id`, `meter_code`, or `cap_value` field in its body | Ignored entirely; server-derived context governs (AC8) |
| T13 | Tenant A requests tenant B's `metered_event` by id | `404` (AC9) |
| T14 | Simulate a `metered_event` write throwing after its owning action already returned a successful result to the seller | Seller-visible result is unaffected; the write is retried/reconciled separately (AC11) |
| T15 | Owner grants `team.manage` to nobody (default), attempts to write `member_entitlement_allocation` as a plain partner | `403` (AC12) |
| T16 | A removed partner's historical `metered_event` rows are queried after removal | Rows persist unmodified, still attributed to the removed `app_user` (E8, N6) |
| T17 | A tenant's `ACTIVE` `tenant_cart_item` for CFO expires with no successor row | Next CFO entitlement check denies with `reason='NO_ACTIVE_CART_ITEM'`, distinct from a cap-exhaustion denial (E6) |

---

## 12. Explicit open questions

Recorded rather than invented.

| # | Question | Impact |
|---|---|---|
| **Q1 (was `auth.md` Q5)** | **The actual per-member sub-cap policy** — first-come-first-served across a team's shared tenant-wide cap, or explicit per-member sub-allocation via `member_entitlement_allocation`? The schema supports either (D2); the product decision does not exist. | `billing-and-pricing.md` / product |
| **Q2 (was `cfo-agent.md`/CI Q5/Q6/Q3)** | **Every actual `cap_value`, `saved_resource_cap`, tier name, and plan code.** No numeric or naming value is seeded by this spec. | `billing-and-pricing.md` |
| **Q3 (was `competitor-intelligence-agent.md` D12/Q15)** | **Does a discovery run consume the same `meter_code` as an evidence-upload run, or a distinct one?** The schema (`metered_event_meter_map`) supports either without a migration; this spec deliberately does not seed the mapping and does not decide it. CI's own D12/Q15 remain open, now with a concrete mechanism to resolve them against. | Entitlement config seeding, `billing-and-pricing.md` |
| **Q4** | **Which terminal states of a given action consume a metered unit** (D5) — e.g. does a `FAILED` CI discovery run that still spent paid provider queries consume a unit, or only a `COMPLETE`/`PARTIAL` one? Left to each consuming agent spec, not decided here. Directly relevant to `competitor-intelligence-agent.md` T15/E9 ("Quota exhausted mid-run... pending the entitlement spec"). | `cfo-agent.md` §6.8, `competitor-intelligence-agent.md` direct-path table |
| **Q5** | **Concurrent-request race at a cap boundary** (E2, V1) — is an eventual-consistency gap acceptable at launch, or does a real cap require a locking/serialization mechanism before it can be trusted? Not designed here. | Correctness under load once any cap is non-null |
| **Q6** | **WhatsApp cap/credit treatment** (`auth.md` W10, `whatsapp-integration.md` §13 Q3, `competitor-intelligence-agent.md` §12 Q1) — whether a WhatsApp-triggered run consumes the same `meter_code` as its in-app equivalent, and cap behaviour mid-thread. This spec's `metered_event.event_kind`/`meter_code` indirection can express either answer, but does not choose one. | `whatsapp-integration.md` |
| **Q7** | **Self-serve purchase/upgrade flow** — entirely out of scope here (N3); `tenant_plan`/`tenant_cart_item` rows above `FREE` are written by an internal process only in V1. When Razorpay wiring is designed, does it write these same tables directly, or through a new service layer? | Future payments integration spec |
| **Q8** | **A cached usage counter** (D3, V3) — at what traffic level does live-aggregating `metered_event` at every check become a performance problem worth a materialized counter? Not measured. | Performance, not correctness |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | `cfo-agent.md` Q13 / `auth.md` E19 — may an entitlement denial render as a reduced payload? | **Resolved (§2 D1).** Yes, but only via an explicit `capability_entitlement_rule` row naming a registered reduced-shape action; default is a bare error. |
| R2 | `auth.md` Q5 — does the schema support per-member sub-caps? | **Resolved as mechanism (§2 D2).** Yes, via `scope=MEMBER` and `member_entitlement_allocation`; the actual policy choice is Q1 above, not this. |
| R3 | `auth.md` Q6 — partner-created content on removal | **Resolved by inheritance (N6).** Tenant owns the data; this spec's own member-scoped rows follow the same rule. |
