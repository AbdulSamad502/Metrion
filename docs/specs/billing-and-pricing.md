# Metrion — Billing and Pricing Specification

**Status: TEMPLATE — not finalized.** This file is a structural placeholder, written to lock the *shape* of billing (tiers, provider, cancellation, invoicing) ahead of the October 1 deadline. Prices, tier names, and several operational timings inside it are explicitly provisional and will be revisited in a dedicated finalization pass. Do not treat any ₹ figure or cap number in this file as a locked commercial decision.

**Prerequisites:** `auth.md` (permission/entitlement separation, §7.2; `billing.view` permission) · `ceo-agent-orchestration.md` (D5, CEO's provisional metering unit) · `cfo-agent.md` / `competitor-intelligence-agent.md` (existing provisional per-agent entitlement numbers this spec must eventually reconcile with — see V4).

**Resolves:** the pricing/billing cluster of the gap report (Q36–Q46) — plan structure, payment provider, cancellation behaviour, and Metrion's own GST invoicing. Partner/referral ledger complexity and usage-based metering are explicitly named and deferred, not silently dropped.

---

## 0. Standing scope decision (confirmed before drafting)

**V1 = flat subscription tiers only.** No per-agent credit purchases, no usage-based overage billing, no metering of individual `agent_run`s against a wallet. Every tenant sits on exactly one tier at a time; a tier is a fixed bundle of agent access plus fixed monthly caps. **Per-agent/credit metering is explicitly deferred to V1.x**, per the confirmation given before this spec was drafted. This is the single decision every other section below is built on — if it is later reversed, most of §5–§6 needs rework, not just a number change.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Flat tiers only for V1** (§0). No credit metering, no usage-based pricing. | User confirmation, this session |
| C2 | **Metering is deferred to V1.x**, as a separate future extension of this spec — not designed here, not stubbed with placeholder tables that imply it exists. | User confirmation, this session |
| C3 | **Payment provider: Razorpay.** Recurring billing uses **UPI AutoPay** (an e-mandate) as the primary mechanism, with Razorpay's card/other methods as fallback where a UPI mandate isn't available. | User instruction, this spec |
| C4 | **Metrion issues its own GST-compliant tax invoice for every subscription charge.** Metrion is the supplier of a SaaS service to the seller-tenant here — this is entirely separate from the seller's *own* marketplace GST, which `cfo-agent.md`'s indicative GST summary computes for their sales, not for what they pay Metrion. | User instruction, this spec |
| C5 | **Partner/referral ledger complexity is out of V1 scope**, not designed even skeletally in this version. No commission table, no payout logic, no affiliate tracking exists here. | User instruction, this spec |

---

## 2. Design decisions requiring review (provisional — this is the template)

| # | Decision | Recommendation (provisional) | Rationale |
|---|---|---|---|
| D1 | Tier structure | Three tiers — **FREE**, **GROWTH**, **SCALE** (placeholder names) — see §6.1 for a skeleton of contents | A three-tier ladder is the smallest structure that separates "trying it out," "one seller running the core loop," and "a seller wanting the full agent set" |
| D2 | Billing cycle | Monthly only for V1; annual/discounted cycles deferred | Simplest to implement against Razorpay's subscription primitives before Oct 1 |
| D3 | Upgrade mid-cycle | Immediate access, prorated charge for the remainder of the current cycle | Standard SaaS pattern; a seller who upgrades expects the new tier's agents *now*, not next month |
| D4 | Downgrade mid-cycle | Takes effect at the **next** billing cycle; no mid-cycle refund or immediate capability loss | Avoids revoking access mid-investigation (see E2); matches most SaaS norms |
| D5 | Cancellation | Access continues through the paid period, then the tenant reverts to FREE — not account deletion | A cancelled subscription is a downgrade-to-free event, not a data-loss event |
| D6 | Failed AutoPay charge (dunning) | Retry up to 3 times over 7 days; on final failure, auto-downgrade to FREE, not immediate hard lockout | Bank-side AutoPay failures are common and often transient (insufficient balance on the mandate date); an immediate cutoff over one bounced debit is harsh |
| D7 | Trial period | None in V1 — FREE tier itself serves as the no-commitment entry point | Avoids building trial-expiry logic separate from the tier system already being built |
| D8 | Refunds | No partial/prorated refund on cancellation — a cancelled subscription simply stops renewing (D5); Razorpay-side chargebacks are handled case-by-case, not automated | SaaS subscriptions are typically non-refundable for the current period; automating refund logic before it's ever been requested is premature |
| D9 | Currency and locale | INR only, GST only — no multi-currency, no international tax regime | Metrion's V1 seller base is India-only, matching every other spec's INR/GST assumptions (`data-foundation.md`, `deterministic-engine.md`) |
| D10 | Multiple subscriptions per tenant | Not allowed — exactly one active `subscription` row per tenant at all times (§5) | A tenant is one seller business on one plan; per-agent à la carte purchasing is exactly the metering model C2 defers |

**Every row above is a recommendation, not a decision.** This section exists so the eventual finalization pass has a concrete starting point instead of a blank page.

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | Razorpay's UPI AutoPay supports the mandate amounts and monthly cycle Metrion's tiers need | Medium — some AutoPay mandate tiers have per-transaction caps; needs verification against Razorpay's current limits before D1's prices are set |
| A2 | GST-compliant invoice generation can be handled through Razorpay's own invoicing/GST features, or a thin invoicing layer on top | Medium — if Razorpay's native invoicing doesn't meet Indian GST invoice-numbering rules, a separate invoicing component is needed (V3) |
| A3 | The flat-tier caps this spec eventually sets will require reconciling against provisional per-agent numbers already written into `competitor-intelligence-agent.md` (3/5 free, 25/100 paid) and `ceo-agent-orchestration.md` (30/month) | High — those numbers were written before this spec existed and were never meant to be final; expect this spec's finalization to supersede them, not the reverse |
| A4 | A tenant is always exactly one `plan_tier` at a time, never a custom mix of agents (D10) | Medium — if à la carte per-agent purchasing turns out to be wanted sooner than V1.x's metering work, this spec's schema needs a `subscription_addon` concept it currently doesn't have |
| A5 | Razorpay's subscription/webhook model maps cleanly onto the `subscription`/`payment_event` shape in §5 without needing an intermediate state machine of its own | Low-Medium — Razorpay's own subscription lifecycle states may not map 1:1 onto `ACTIVE/PAST_DUE/CANCELLED/DOWNGRADED`; worth confirming against their API docs before implementation |

---

## 4. Goals and non-goals

**Goals** — define a flat-tier skeleton (names, bundled agents, caps) as a working template; lock the payment provider and recurring-billing mechanism; define cancellation and downgrade behaviour precisely enough to build against; define Metrion's own GST invoicing obligation as a supplier; explicitly scope out metering and partner/referral complexity so neither is silently assumed into V1.

**Non-goals (V1)** — usage-based or credit-metered billing (deferred to V1.x, C2) · partner/referral/affiliate ledgers of any kind (C5) · annual or multi-cycle billing discounts (D2) · enterprise custom contracts or negotiated pricing · dunning logic beyond a basic retry-then-downgrade (D6) · invoicing for anything other than Metrion's own subscription charge (the seller's marketplace GST remains `cfo-agent.md`'s domain entirely).

---

## 5. Data model

```sql
plan_tier (                              -- the flat-tier definition, versioned
  id uuid pk, tier_key text not null,    -- FREE | GROWTH | SCALE (placeholder)
  name text not null, monthly_price_paise integer not null,
  included_agents jsonb not null,        -- e.g. ["agent.ci"], ["agent.ci","agent.cfo"]
  included_caps jsonb not null,          -- flat caps per agent, e.g. {"ci_runs_month": 5}
  status text not null,                  -- ACTIVE | DEPRECATED
  effective_from timestamptz not null
)

subscription (
  id uuid pk, tenant_id uuid not null,
  plan_tier_id uuid not null,
  status text not null,                  -- ACTIVE | PAST_DUE | CANCELLED | DOWNGRADED
  razorpay_subscription_id text, razorpay_mandate_id text,
  current_period_start timestamptz, current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at timestamptz not null
)

invoice (                                -- C4: Metrion's own GST-compliant tax invoice
  id uuid pk, tenant_id uuid not null, subscription_id uuid not null,
  invoice_number text not null unique,   -- sequential, GST-rule-compliant numbering
  razorpay_invoice_id text,
  amount_paise integer not null, gst_amount_paise integer not null,
  hsn_sac_code text not null,            -- SAC code for SaaS supply
  place_of_supply text not null,
  status text not null,                  -- PAID | FAILED | REFUNDED
  period_start timestamptz, period_end timestamptz, issued_at timestamptz
)

payment_event (                          -- Razorpay webhook audit log
  id uuid pk, subscription_id uuid,
  razorpay_event_id text not null unique,  -- dedup key (E3)
  event_type text not null,              -- CHARGED | FAILED | MANDATE_CANCELLED | ...
  raw_payload jsonb not null, received_at timestamptz not null
)
```

`plan_tier` is versioned by `effective_from` rather than mutated in place, so changing a tier's contents later never rewrites what a past invoice was actually billed against.

---

## 6. Core rules

### 6.1 Tier skeleton (D1, provisional)

| Tier | Bundled agents (placeholder) | Flat caps (placeholder) | Price (placeholder) |
|---|---|---|---|
| **FREE** | `agent.ci` only, reduced | e.g. 5 CI runs/month, 3 saved URLs, 30 CEO turns/month | ₹0 |
| **GROWTH** | `agent.ci` (full) + `agent.cfo` | e.g. 100 CI runs/month, CFO reconciliation on full ingested history, higher CEO turn cap | TBD |
| **SCALE** | `agent.ci` + `agent.cfo` + `agent.pi` + `agent.cmo` | Highest flat caps across all four, including PI's `research.niche_run` and CMO's per-artefact generation cap | TBD |

Per-agent breakdown is intentionally shallow here — each agent's own spec already names the specific cap it needs metered (CI's saved-URL/run count, PI's niche-run count, CMO's generation count, CFO's reconciliation-run count). This table's job is only to say **which tier includes which agent at all**; the exact numeric value inside `plan_tier.included_caps` per tier is finalization work (V1, V4), not decided here.

This table is a **starting skeleton, not a commitment** — it exists so §6.7's entitlement rule has something concrete to point at. Reconciling it against CI's and CEO's own existing provisional numbers is explicit future work (V4), not done silently here.

### 6.2 Razorpay integration and UPI AutoPay (C3)
Subscribing creates a Razorpay Plan (mapped 1:1 to a `plan_tier`) and a Razorpay Subscription for the tenant, with a UPI AutoPay mandate collected at signup or upgrade. The signup sequence:

1. Tenant selects a tier → backend creates (or reuses) the matching Razorpay Plan for `plan_tier.tier_key`.
2. Backend creates a Razorpay Subscription against that plan, tenant completes UPI AutoPay mandate registration (or falls back per E1) on Razorpay's hosted checkout.
3. Razorpay confirms the mandate; a `subscription` row is written `ACTIVE` with the returned `razorpay_subscription_id`/`razorpay_mandate_id`.
4. Recurring charges are Razorpay-initiated against the mandate on each cycle — Metrion never triggers a charge directly.
5. Every charge attempt (success or failure) arrives as a webhook and is written to `payment_event` before anything else happens (§6.5, E3).

Metrion never stores raw payment credentials — Razorpay owns the payment instrument end-to-end.

### 6.3 Upgrade (D3)
An upgrade takes effect immediately: `subscription.plan_tier_id` updates, the new tier's agent access is live at once, and Razorpay prorates the remaining days of the current cycle onto the new plan's price.

### 6.4 Downgrade and cancellation (D4, D5)
A downgrade or cancellation sets `cancel_at_period_end = true` (or schedules the new lower tier) but changes nothing until `current_period_end`. The tenant keeps full access to their *current* tier through the period they already paid for. At period end, a scheduled job applies the change: `plan_tier_id` moves to the new tier (or FREE, for a cancellation), and the Razorpay subscription/mandate is cancelled or replaced accordingly.

### 6.5 Failed payment and dunning (D6)
A `payment_event` of type `FAILED` triggers a retry schedule (up to 3 attempts over 7 days, provisional). `subscription.status` moves to `PAST_DUE` on the first failure. If all retries fail, the tenant auto-downgrades to FREE (§6.4's downgrade path) rather than being locked out mid-cycle with no path back.

### 6.6 GST invoicing for Metrion's own subscription (C4)
Every successful charge produces exactly one `invoice` row: sequential `invoice_number` (GST numbering rules — no gaps, no reuse), the applicable GST amount and HSN/SAC code for a SaaS supply, and the place of supply. Invoices are downloadable by any member holding `billing.view` (`auth.md` §5.2). This invoice concerns **only** what the tenant pays Metrion — it has no relationship to any `sales_line`, `manual_adjustment`, or marketplace-side GST figure CFO produces for the seller's own business.

### 6.7 Entitlement resolution under flat tiers (C1)
For V1, "entitlement" (`auth.md` §7.2's second gate, separate from permission) resolves to one question: **does the tenant's current `plan_tier.included_agents` contain this `agent.*` key, and is the relevant flat cap in `included_caps` not yet exhausted?** There is no credit balance, no per-unit purchase, no wallet. This is the concrete V1 answer that other specs' "entitlement spec" citations (`auth.md` Q4/Q5, `competitor-intelligence-agent.md` Q2/Q3, `ceo-agent-orchestration.md` Q4) should eventually resolve against — though reconciling their existing provisional numbers into `plan_tier.included_caps` is explicit future work (V4), not performed by this draft.

### 6.8 Partner/referral exclusion (C5)
No schema, no commission calculation, and no payout mechanism exists in this version. If a partner/referral program is confirmed as scope later, it is a new spec (or a substantial addition here) — not an extension squeezed into `plan_tier` or `invoice`.

### 6.9 Refunds and currency (D8, D9)
No automated refund path exists — a cancellation stops future renewal (§6.4) but does not reverse a charge already made for the current period. Any refund is a manual, case-by-case action taken directly in Razorpay's dashboard, logged as a `REFUNDED` `invoice.status` after the fact. All amounts are INR; no multi-currency or non-GST tax regime is supported.

### 6.10 Webhook event mapping
Every Razorpay webhook Metrion subscribes to maps to one `payment_event.event_type` and, where applicable, a `subscription.status` transition:

| Razorpay event | `payment_event.event_type` | Effect on `subscription.status` |
|---|---|---|
| `subscription.charged` | `CHARGED` | Stays/returns to `ACTIVE`; `invoice` row created (§6.6) |
| `subscription.pending` / charge retry scheduled | `FAILED` | Moves to `PAST_DUE` (§6.5) |
| `subscription.halted` (all retries exhausted) | `FAILED` (final) | Triggers the auto-downgrade path (D6) |
| `subscription.cancelled` | `MANDATE_CANCELLED` | Confirms a cancellation already recorded via `cancel_at_period_end` (§6.4) — never the trigger for one |
| `payment.failed` (one-off, e.g. mandate setup) | `FAILED` | No subscription exists yet; surfaces as a signup-time error (E1) |

The webhook handler is the **only** writer to `subscription.status` in the steady state (E9) — no user-facing action flips status directly; it always goes through Razorpay first and the webhook second.

### 6.11 GST invoice required fields
Per Indian GST invoicing rules for a B2B SaaS supply, every `invoice` row's rendered document includes: Metrion's GSTIN and registered address, the tenant's GSTIN (if provided at signup — see Q11) and billing address, a sequential `invoice_number` with no gaps, the `hsn_sac_code` for the SaaS service, taxable value, CGST/SGST or IGST breakdown (determined by `place_of_supply` relative to Metrion's registration state), and the total. This is a compliance floor, not a design choice — none of these fields is optional once a real invoice is issued.

---

## 7. AI requirements

**None.** Billing, invoicing, and payment-provider integration involve no LLM, no classification, and no generation. This is a transactional/financial-operations domain, handled entirely by deterministic rules and Razorpay's own APIs.

---

## 8. Authorization and security

1. `billing.view` (already defined in `auth.md` §5.2) gates visibility into `subscription` and `invoice` rows.
2. Only the tenant **OWNER** may change tier, cancel, or update the payment mandate (recommended; not yet confirmed — see Q5). A PARTNER may view billing with `billing.view` but not act on it.
3. `subscription`, `invoice`, and `payment_event` are tenant-scoped under the same RLS model as every other table (`auth.md` §4).
4. The Razorpay webhook endpoint verifies Razorpay's signature on every inbound event before writing to `payment_event` — an unverified or malformed webhook is rejected outright, never processed speculatively.
5. No raw card, UPI ID, or mandate credential is ever stored in Metrion's own database — Razorpay is the system of record for the payment instrument itself.
6. An issued `invoice` row is immutable once `status = PAID` — a correction is a new linked invoice (e.g. a credit note pattern), never an in-place edit, matching GST's own numbering-integrity requirement (§6.11).

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | UPI AutoPay mandate setup fails at signup (bank declines) | Falls back to Razorpay's other supported methods rather than blocking signup entirely |
| E2 | Tenant downgrades mid-cycle while actively using an agent the new tier excludes | Capability is revoked only at the next cycle boundary (D4) — never mid-investigation |
| E3 | Duplicate or delayed webhook delivery | Deduplicated on `payment_event.razorpay_event_id` (unique) — a re-delivered event is a no-op, not a double charge record |
| E4 | Tenant on FREE tries to invoke a paid-only agent | Denied by entitlement (§6.7), same shape as `auth.md` E19 / `cfo-agent.md`'s gated-preview precedent |
| E5 | GST invoice generation fails for an otherwise-successful charge | The charge still stands; invoice generation retries asynchronously — a paid charge must never end up with no compliant invoice, silently |
| E6 | Cancellation requested but Razorpay-side mandate cancellation lags | `cancel_at_period_end` is set immediately regardless of mandate-cancel confirmation timing; no further charge is attempted past the period end either way |
| E7 | Tenant cancels, then re-subscribes before period end | The pending cancellation is simply cleared; no downgrade ever occurs, no double-billing |
| E8 | Tenant requests a refund after a charge | Handled manually in Razorpay's dashboard (D8, §6.9) — no self-service refund flow exists in V1 |
| E9 | Razorpay's own subscription state diverges from Metrion's `subscription.status` (e.g. a manual pause on Razorpay's side) | Metrion's `payment_event` log is the reconciliation source of truth; a scheduled sync job (not yet specified — see Q9) should be the only writer to `subscription.status` outside the webhook handler |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | Actual tier pricing (₹ amounts) is entirely unset | §6.1 — pure placeholder |
| V2 | Razorpay UPI AutoPay's mandate limits and renewal mechanics are unverified against Metrion's intended cycle/amounts | A1, §6.2 |
| V3 | GST invoicing implementation path (Razorpay-native vs. a separate invoicing layer) is undecided | A2, §6.6 |
| V4 | This spec's flat-tier model has not yet been reconciled against the provisional per-agent numbers already written into `competitor-intelligence-agent.md` and `ceo-agent-orchestration.md` | A3, §6.1, §6.7 |
| V5 | Exact dunning timing (retry count/interval in D6) is a guess, not validated against real failure-rate data | §6.5 |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | Every tenant has exactly one active `subscription` row and exactly one current `plan_tier` at any time (C1). |
| AC2 | No code path checks a credit balance or per-unit usage meter in V1 (C1, C2). |
| AC3 | Every successful subscription charge produces exactly one GST-compliant `invoice` row (C4, §6.6). |
| AC4 | A downgrade or cancellation never revokes access before `current_period_end` (D4, D5). |
| AC5 | A failed AutoPay charge triggers the retry schedule before any downgrade occurs (D6). |
| AC6 | No partner/referral schema, calculation, or payout path exists anywhere in this version (C5). |
| AC7 | Every `payment_event` is deduplicated on `razorpay_event_id` (E3). |
| AC8 | `billing.view` is required to see any `subscription` or `invoice` data; RLS prevents cross-tenant access (§8). |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | New tenant signs up, selects GROWTH, sets up UPI AutoPay | `subscription` created ACTIVE, first `invoice` issued with correct GST fields (AC3) |
| T2 | Tenant upgrades FREE → SCALE mid-cycle | Immediate access to SCALE's agents; prorated charge processed (D3) |
| T3 | Tenant downgrades SCALE → GROWTH mid-cycle | Full SCALE access continues until `current_period_end`, then reverts (AC4) |
| T4 | AutoPay charge fails once, succeeds on retry | `status` moves PAST_DUE then back to ACTIVE; no downgrade occurs (AC5) |
| T5 | AutoPay fails all 3 retries | Auto-downgrade to FREE at the end of the retry window (D6) |
| T6 | Razorpay redelivers the same webhook event twice | Second delivery is a no-op; no duplicate `payment_event` or double charge record (AC7) |
| T7 | FREE-tier tenant invokes `agent.cfo` | Denied by entitlement, same shape as an existing `auth.md` denial (E4) |
| T8 | PARTNER with `billing.view` attempts to cancel the subscription | Denied — only OWNER may act on billing (§8.2, pending Q5 confirmation) |
| T9 | Tenant attempts to hold two active subscriptions (e.g. a race between two upgrade clicks) | Rejected — exactly one active `subscription` row per tenant is enforced (D10, AC1) |
| T10 | Manual refund issued in Razorpay's dashboard for a past charge | Corresponding `invoice.status` updated to `REFUNDED`; no automated code path triggers this | 

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | **Actual tier names and pricing.** FREE/GROWTH/SCALE and their ₹ amounts are placeholders only. | §6.1, V1 |
| Q2 | **Razorpay UPI AutoPay mandate limits** — do they comfortably cover the price points D1 will eventually set? | A1, V2 |
| Q3 | **GST invoicing implementation** — Razorpay's native invoicing, or a separate compliant invoicing layer? | A2, V3 |
| Q4 | **Reconciliation plan** for this spec's flat tiers against the provisional per-agent numbers already sitting in `competitor-intelligence-agent.md` and `ceo-agent-orchestration.md` — which numbers win, and does this spec get amended or do the others? | A3, V4 |
| Q5 | **Who may act on billing** — OWNER only, or can a PARTNER role be granted billing-management rights? | §8.2 |
| Q6 | **Is a partner/referral program confirmed as future scope at all**, and if so, roughly when — V1.x, V2, or not planned? Determines whether C5's exclusion is temporary or permanent. | C5, future scope |
| Q7 | **Exact dunning schedule** (retry count/interval in D6) — should be based on real payment-failure data once available, not a guess. | V5 |
| Q8 | **Does metering (V1.x) replace flat tiers outright, or layer usage caps on top of them?** This spec assumes the latter is more likely but does not decide it. | C2, future spec |
| Q9 | **Reconciliation job between Razorpay's subscription state and `subscription.status`** (E9) — is a scheduled sync needed, or is the webhook handler alone considered sufficient? | A5, E9 |
| Q10 | **Refund policy** (D8) — is "no refunds, manual exceptions only" an acceptable stated policy for customer-facing terms, or does product want a formal partial-refund rule? | D8, terms of service |
| Q11 | **Is tenant GSTIN collection mandatory at signup**, or optional (some sole-proprietor sellers may be unregistered)? Affects §6.11's invoice fields and whether B2B reverse-charge rules ever apply. | §6.11 |

---

## 14. Traceability — gap-report cluster (Q36–Q46)

This spec was scoped to resolve the pricing/billing cluster of open questions. The table below maps the cluster's concerns, as given in this session's instructions, to where each is addressed — so a later pass checking gap-report closure can verify coverage without re-deriving it.

| Concern | Addressed in | Status |
|---|---|---|
| V1 billing model (flat vs. metered) | §0, C1, C2 | **Resolved** — flat tiers, metering deferred |
| Plan tiers and contents | §2 D1, §6.1 | **Template only** — structure set, numbers open (Q1) |
| Payment provider and recurring mechanism | C3, §6.2 | **Resolved** — Razorpay + UPI AutoPay |
| Cancellation behaviour | D5, §6.4 | **Resolved in shape** — access-to-period-end, exact grace timing open (V5) |
| GST invoicing for Metrion's own subscription | C4, §6.6, §6.11 | **Resolved in shape** — implementation path open (Q3) |
| Partner/referral ledger complexity | C5, §6.8 | **Explicitly deferred**, not designed |

Where "resolved in shape" appears, the architecture and data model are decided; specific numbers or implementation choices remain in §13 pending finalization.

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | V1 billing model | **Flat subscription tiers only**, no metering (C1, confirmed before drafting). |
| R2 | Metering timeline | **Deferred to V1.x**, a future extension — not designed here (C2). |
| R3 | Payment provider and recurring mechanism | **Razorpay, with UPI AutoPay** for recurring billing (C3). |
| R4 | Metrion's own subscription GST obligation | **Metrion issues its own GST-compliant invoice** as the SaaS supplier, unrelated to the seller's marketplace GST (C4). |
| R5 | Partner/referral scope for V1 | **Explicitly excluded**, not designed even skeletally (C5). |
