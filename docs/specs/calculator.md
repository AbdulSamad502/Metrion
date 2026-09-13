# Metrion — Calculator Specification

**Status:** Draft for review
**Prerequisites:** `deterministic-engine.md` (sole source of formula/fee logic) · `cfo-agent.md` (owns `margin_curve`) · `auth.md` (direct execution path definition) · `ceo-agent-orchestration.md` (`agent_run`).

Three surfaces, one formula source: **Brain 1** (tenant, canonical), the **in-app quick-calc widget** (tenant, direct path), and the **public lead-gen calculator** (anonymous, marketing site). All three call the same calculation logic. None of them reimplements a formula.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Shared calculation core.** The fee-application and margin arithmetic `deterministic-engine.md` already implements is factored into a stateless module. Brain 1, the quick-calc widget, and the public calculator all call it — none reimplements it. This is packaging, not a new brain. | User instruction, this spec |
| C2 | **Quick-calc widget = CFO's existing `margin_curve` interface, as a direct execution path.** Not a new agent, not a new interface exception. Requires `agent.cfo`; produces one `agent_run` (`trigger_type = DIRECT`, `agent_id = CFO`), exactly like any other CFO direct action. | `deterministic-engine.md` §5.13.1 (`margin_curve`, CFO-exclusive); `auth.md` §5.2 |
| C3 | **The public calculator is not an agent action.** No tenant, no RLS, no permission chain, no `agent_run`. It calls the shared core (C1) directly against user-typed hypothetical inputs and a published fee snapshot (§5). This is a deliberate, narrow exception to "every figure traces to an `agent_run`" — named here, not smuggled in. | this spec |
| C4 | **Q76 resolved: unauthenticated, rate-limited.** Requiring login would kill the lead-gen conversion the tool exists for, so no signup is required. The abuse surface (compute cost, scraping, spam) is controlled by rate limiting and bot-detection instead of identity (§6.4) — not by pretending the risk doesn't exist. | Q76, resolved here |
| C5 | **Public calculator touches no tenant data, ever.** It reads only the published fee snapshot (§5) and the user's own typed numbers. No `manual_adjustment`, no `sales_line`, no real seller figures. This is what makes C4 safe — there is nothing to exfiltrate, only compute to throttle. | this spec |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Rate-limit thresholds | Start at 15 calcs/hour per IP+fingerprint, bot-challenge above 5/hour, hard block above 30/day/IP — tunable ops config, not hardcoded | Real abuse patterns will need iteration; the number matters less than that a number exists |
| D2 | Lead capture | Optional email gate on "email me this breakdown" only — never required to see the base result | Forcing an email wall before any value is shown kills conversion; a value-first gate is the standard pattern |
| D3 | Public fee data freshness | Publish a versioned, deliberately-lagged snapshot of `deterministic-engine.md` §5.14's fee reference, not the live tenant-facing table | Prevents scraping the freshest fee schedule; a small lag doesn't mislead a rough estimate |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | The core arithmetic in `deterministic-engine.md` can be extracted into a standalone module without touching its determinism contract (§4) | Low — packaging change, not a behaviour change, if done as a pure refactor |

---

## 4. Goals and non-goals

**Goals** — one formula source reused by three surfaces; a concrete, real answer to Q76 rather than a deferred one; a public surface with zero tenant-data exposure; a quick-calc widget that reuses CFO's existing ownership of `margin_curve` rather than inventing a parallel path.

**Non-goals (V1)** — the public calculator producing a canonical or tenant-specific figure · any LLM involvement in either calculator · authentication on the public calculator (explicitly rejected, C4) · a general-purpose "calculator agent."

---

## 5. Data model

```
fee_reference_public_snapshot (        -- D3: decoupled from the live tenant fee reference
  id uuid pk, snapshot_version text, published_at timestamptz,
  marketplace text, category text, fee_schema jsonb
)

public_calc_submission (               -- rate-limiting + abuse analytics only
  id uuid pk, ip_hash text, fingerprint_hash text,
  inputs jsonb, created_at timestamptz,
  purge_after timestamptz              -- default now()+30d; no tenant_id — this table predates any tenant
)

public_calc_lead (                     -- created only if the user opts into email capture (D2)
  id uuid pk, submission_id uuid fk, email text, consented_at timestamptz
)
```

The quick-calc widget introduces **no new table** — it is CFO's `margin_curve` call, audited by the existing `agent_run` (`ceo-agent-orchestration.md` §5).

---

## 6. Core rules

### 6.1 Shared calculation core (C1)
Contains: fee-application arithmetic, margin/formula composition, `formula_version` stamping. Excludes: any read of `manual_adjustment`, any tenant table, any ingestion step. Both consumers stay strictly inside this boundary.

### 6.2 Quick-calc widget (C2)
Member types price, cost, marketplace, category; the widget calls `margin_curve` with those inputs, optionally pre-filled from the tenant's own fee reference. Requires `agent.cfo` only — no `agent.ceo`, no LLM, no free-form input beyond the numeric fields (`auth.md`'s direct-path guardrail: one action, one key, no open-ended text). Writes one `agent_run` row, `trigger_type = DIRECT`.

### 6.3 Public calculator flow (C3, C4)
1. Rate-limit check runs **before** any calculation (reject fast; never compute then discard).
2. Inputs run through the shared core against `fee_reference_public_snapshot`.
3. Result renders immediately — no login, no submission required to see it.
4. An optional "email me this" action creates `public_calc_lead`, the conversion event this tool exists for.

### 6.4 Abuse controls — Q76 detail
Per-IP+fingerprint rate limiting (D1); a bot-challenge above the soft threshold; no batch/bulk input field (one calculation per submission, never a CSV). Submission records live in `public_calc_submission`, purged on a TTL — the table exists to make abuse *detectable and throttleable*, not to build a marketing profile.

### 6.5 Data hygiene
`public_calc_submission` carries no `tenant_id` — the public calculator's process has no tenant DB context at all (architectural isolation, not a policy line). A later tenant signup is never linked back to prior anonymous submissions.

---

## 7. AI requirements

**None.** Both calculators are deterministic arithmetic over the shared core (§6.1) — the same Brain 1 logic `deterministic-engine.md` already defines. No classification, no generation, no LLM call anywhere in either surface.

---

## 8. Authorization and security

1. Quick-calc widget: `agent.cfo` only, reusing CFO's own permission key — no new key invented (C2).
2. Public calculator: no identity check exists or is expected. Protection is rate limiting and bot-detection (§6.4), not a permission chain, because there is no identity to check against (C4).
3. The public calculator process is denied any tenant DB connection/RLS context at the infrastructure level — not merely instructed not to query tenant tables. This is what makes C5 a guarantee rather than a convention.
4. `public_calc_lead.email` is collected only on explicit opt-in (D2) — never inferred, never pre-filled from any other source.

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Public calculator rate limit exceeded | Blocked before computing, with a plain wait-time message — never a silently degraded or fake result |
| E2 | Marketplace/category combo missing from the fee snapshot | Result honestly widens/flags the gap, same pattern as `product-intelligence-agent.md`'s feasibility estimate — never a silently assumed fee |
| E3 | Public-calculator user later becomes a tenant | No automatic linkage between prior anonymous submissions and the new account (§6.5) |
| E4 | Script rotates IPs to evade the rate limit | Fingerprint-based signal still applies independent of IP (§6.4) |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | Shared-core extraction from `deterministic-engine.md` is not yet done as a real refactor | C1, both consumers |
| V2 | Rate-limit thresholds (D1) unvalidated; fee-snapshot publishing pipeline (D3) doesn't exist | §6.4, §5 |
| V3 | Target CRM/marketing system for `public_calc_lead` is undecided | D2 |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | Neither calculator surface contains its own copy of a fee or margin formula — both call the shared core (C1). |
| AC2 | The quick-calc widget requires `agent.cfo` and produces exactly one `agent_run` row per use (C2). |
| AC3 | The public calculator never queries a tenant-scoped table (C3, C5, §8.3). |
| AC4 | No public-calculator request is authenticated or required to be (C4). |
| AC5 | Every public-calculator request passes the rate-limit check before any calculation runs (§6.3). |
| AC6 | A missing fee-snapshot entry produces a flagged gap, never a silently assumed value (E2). |
| AC7 | Anonymous submissions are never linked to a later tenant signup (E3). |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Member without `agent.cfo` opens the quick-calc widget | Denied at the permission check, same as any other CFO direct path |
| T2 | Public calculator, 20 requests/hour from one IP+fingerprint | Blocked after the configured threshold (D1), no calculation performed (AC5) |
| T3 | Public calculator, valid single submission | Result renders with no login prompt anywhere (AC4) |
| T4 | Public calculator submission for a category missing from the snapshot | Response flags the gap explicitly (AC6) |
| T5 | Script rotates source IP mid-abuse | Fingerprint signal still triggers the block (E4) |
| T6 | User uses the public calculator, later signs up as a tenant | No trace of the anonymous submission appears on the new tenant account (AC7) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | Exact rate-limit numbers (D1) — placeholder until real traffic exists | §6.4 |
| Q2 | Fee-snapshot publish cadence (D3) — weekly? on every engine fee-reference update? | §5 |
| Q3 | Target CRM/marketing tool for `public_calc_lead` (D2) | V3 |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Public calculator auth requirement (Q76) | **Unauthenticated, rate-limited instead** (C4). |
| R2 | Formula reuse across surfaces | **One shared core**, extracted from `deterministic-engine.md`, never reimplemented (C1). |
| R3 | Quick-calc widget's architecture | **CFO's existing `margin_curve` direct path** — no new agent or interface exception (C2). |
