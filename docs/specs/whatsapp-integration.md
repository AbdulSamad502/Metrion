# Metrion — WhatsApp Integration Specification

**Status:** Draft for review
**Prerequisites:** `auth.md` §1.5/§7.5 (`whatsapp_binding`, W1–W11 — identity binding, never an authorization elevation) · `ceo-agent-orchestration.md` §6.7 (WhatsApp turns enter the same pipeline as chat) · `competitor-intelligence-agent.md` §6.9 (`WHATSAPP_CONFIRM`, locked facts only, everything else deferred here).

This spec closes the dependency every other spec has been pointing at: `auth.md` W10, `competitor-intelligence-agent.md` Q1, and `ceo-agent-orchestration.md`'s Q6 all named this file as the place these decisions belong. (`cfo-agent.md` itself holds no WhatsApp-specific content beyond owning the `MARGIN_RISK` alert type — §6.3.)

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Q6 resolved: outbound alerts plus bounded two-way, not open-ended chat.** V1 sends template-based alerts and accepts a narrow reply vocabulary (confirm/decline a specific pending action). Once a seller replies, Meta's 24-hour session window opens, and **that window's follow-up messages route through the same CEO pipeline as in-app chat** (`ceo-agent-orchestration.md` §6.3–§6.5) — this is what "limited two-way" (readiness §5, superseding the planning doc's "invoke/revoke") actually means: the pipeline is identical, but WhatsApp's own platform mechanics (§6.1) bound how much conversation is possible outside an active session. | Q6; readiness §5 "p.3 WhatsApp invoke/revoke" row |
| C2 | **Q7 resolved: integrate through a BSP (Business Solution Provider — e.g. Gupshup or Interakt), not the direct Meta Cloud API, for V1.** A BSP owns WABA hosting, session/rate-limit tracking, and the template-submission UI, which is materially less integration work before Oct 1. Direct Cloud API migration is a later cost/scale decision, not a V1 blocker. | Q7, resolved here |
| C3 | **"Invoke/revoke" maps to two distinct, already-scoped mechanisms — not one.** *Invoke* = replying to confirm a specific **pending action** attached to an alert (e.g. "CONFIRM" runs the CI capture, views the full CFO breakdown). *Revoke* = either declining that one action ("STOP" on this message) or disabling the whole channel (`auth.md` W10/E18, owner-level, unchanged by this spec). Neither is a general "pause this agent" toggle — no such toggle exists anywhere else in the system. | This spec, reconciling the planning doc's ambiguous term |
| C4 | **Alerts are produced by the owning agent, not by WhatsApp itself.** `MARGIN_RISK` (CFO/Leak Shield), `PRICE_CHANGE` (CI), `OPPORTUNITY` (PI) — each alert is a rendering of that agent's own structured output into an approved template. WhatsApp invents no new figures, exactly as `ceo-agent-orchestration.md` C9 already requires of CEO. | This spec |
| C5 | **Every outbound alert uses a pre-approved message template.** Because Metrion always initiates the alert, it is (per Meta's rules, §6.1) outside any open session by default — a template is the only legal way to send it. No alert body is LLM-composed at send time; only the template's variable slots are filled from an `engine_result_ref`/`estimate_ref`/agent report field. | C4, §6.2 |
| C6 | **Existing `auth.md` facts are unchanged and restated, not redecided:** one WhatsApp destination per tenant (W1), no per-partner destinations (W3), inbound from an unverified number never resolves to a tenant (W9), WhatsApp cannot elevate a member's permissions (W11), owner controls channel enable/disable (W10). | `auth.md` §1.5, §7.5 |
| C7 | **A verified WhatsApp message with no open Investigation implicitly opens exactly one** — resolving `ceo-agent-orchestration.md` Q6. This is a narrow, named exception to that spec's C6 ("explicit user action only"), justified because WhatsApp has no "New Investigation" button; the alert itself is the explicit action that starts the thread. | Resolves `ceo-agent-orchestration.md` Q6 |
| C8 | **Identity resolution: WhatsApp resolves to a tenant, and to exactly one member — the binder.** `whatsapp_binding` (`auth.md` §5.1) has no per-member phone directory: one `phone_e164` per tenant (W1/W3), one `bound_by`. Since binding is restricted to the **OWNER role only** (`auth.md` §7.5: "Binding is initiated by the OWNER only"), `bound_by` is always the tenant's OWNER in V1. Every WhatsApp-originated request — a `CONFIRM`/`STOP` reply or free-text session message — is therefore attributed to `bound_by` and re-enters the identical `auth.md` §7.1 six-step chain as a web request from that same member would, using that member's real `membership.role`/`permissions` row. This is not a WhatsApp-specific identity, elevated trust level, or service-account bypass — it is the one real member identity the data model actually captures, carried through unchanged. §6.7 below states the mechanism and its consequences in full, including the residual risk this leaves open. | Resolves item 3 of the pre-implementation checklist; reconciles `auth.md` W6/W10/W11 with the single-destination binding model |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | BSP vendor (C2) | Gupshup or Interakt — both have strong India presence and INR billing; Twilio is a fallback if either falls through on onboarding speed | Reduces vendor-onboarding risk against the Oct 1 date; not a technical differentiator at V1's volume |
| D2 | Reply vocabulary | A small fixed set (`CONFIRM`, `STOP`, plus digit shortcuts like `1`/`2` for multi-option alerts) rather than free-text intent parsing on the alert reply itself | Keeps the invoke/revoke mechanism (C3) deterministic — no LLM classification needed just to know if a seller said yes or no |
| D3 | Alert frequency cap | One alert per tenant per day across all types combined (matches the planning doc's original "1/day opt-in prompt" framing), configurable later per the entitlement spec | Prevents alert fatigue from becoming the reason sellers disable the channel entirely |
| D4 | Session-window follow-up scope | Once a session is open, allow the full CEO pipeline (C1), but do not proactively invite open-ended questions in the alert template's own copy — the window is a side-effect of replying, not a marketed feature | Avoids overpromising a WhatsApp "assistant" experience the 24-hour constraint can't sustain |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | The BSP chosen (D1) exposes a webhook-based inbound model compatible with `auth.md`'s W6 tenant-resolution requirement | Low — this is standard BSP behaviour |
| A2 | Meta's template approval turnaround (typically hours to a few days) fits the Oct 1 timeline if templates are submitted early | Medium — a rejected or slow-approved template blocks that alert type at launch |
| A3 | A fixed reply vocabulary (D2) covers the large majority of real alert responses without frustrating sellers who type free text instead | Medium — a seller typing "yes" instead of "CONFIRM" needs a graceful fallback (E3) |

---

## 4. Goals and non-goals

**Goals** — resolve Q6 and Q7 concretely; define the three alert types and their owning agents; specify the 24-hour window and template-approval mechanics as real constraints, not glossed over; give "invoke/revoke" one unambiguous technical meaning; close the WhatsApp-no-open-investigation gap left by `ceo-agent-orchestration.md`.

**Non-goals (V1)** — WhatsApp as a primary conversational surface (it remains alert-first) · free-form intent parsing on the confirm/decline reply itself (D2) · per-partner WhatsApp destinations (`auth.md` W3, unchanged) · a general per-agent pause/resume toggle (C3 explicitly rejects inventing one) · direct Meta Cloud API integration (C2).

---

## 5. Data model

```sql
whatsapp_template (
  id uuid pk, name text not null, category text not null,   -- UTILITY | MARKETING (Meta's classification)
  approval_status text not null,                             -- PENDING | APPROVED | REJECTED
  version int not null, body_text text not null,
  variable_count int not null, approved_at timestamptz
)

whatsapp_message (
  id uuid pk, tenant_id uuid not null, whatsapp_binding_id uuid not null,
  direction text not null,                -- OUTBOUND_TEMPLATE | OUTBOUND_SESSION | INBOUND
  template_id uuid,                       -- set only for OUTBOUND_TEMPLATE
  agent_run_id uuid,                      -- the agent_run this alert renders (C4)
  variables jsonb, body_rendered text,
  provider_message_id text, status text not null,   -- QUEUED | SENT | DELIVERED | READ | FAILED
  session_window_expires_at timestamptz,  -- null until a seller reply opens one
  created_at timestamptz not null
)

whatsapp_pending_action (               -- the object "invoke/revoke" (C3) actually acts on
  id uuid pk, tenant_id uuid not null, whatsapp_message_id uuid not null fk,
  action_ref text not null,               -- e.g. "ci.capture_run:<id>", "cfo.preview:<id>"
  status text not null,                   -- PENDING | CONFIRMED | DECLINED | EXPIRED
  expires_at timestamptz not null
)

whatsapp_alert_subscription (           -- per-type mute, the "revoke a category" case
  tenant_id uuid not null, alert_type text not null,   -- MARGIN_RISK | PRICE_CHANGE | OPPORTUNITY
  enabled boolean not null default true,
  primary key (tenant_id, alert_type)
)
```

---

## 6. Core rules

### 6.1 The 24-hour session window
Meta permits free-form ("session") messages only within 24 hours of the seller's last inbound message; outside that window, only an approved template may initiate contact. Every alert Metrion sends is business-initiated, so it **always** uses a template (C5). A seller's reply (confirm, decline, or anything else) opens a session window during which CEO's full conversational pipeline may respond in free text (C1, `ceo-agent-orchestration.md` §6.3–§6.5). `whatsapp_message.session_window_expires_at` is the authoritative gate: a synthesis attempt outside it must fall back to a template, not silently send session text that Meta will reject.

### 6.2 Template registry and approval (C5)
Every distinct alert message shape is a row in `whatsapp_template`, submitted to the BSP for Meta approval before use. Approval status gates sending: `PENDING`/`REJECTED` templates are never sent. Variable slots are filled from a structured field (an `engine_result_ref`, `estimate_ref`, or agent-report field) — never from freshly composed LLM text, since an approved template's wording cannot change without re-approval.

### 6.3 Alert types (C4)

| Type | Owning agent | Example trigger | Template variables |
|---|---|---|---|
| `MARGIN_RISK` | CFO (Leak Shield) | A `reconciliation_exception` crosses the tenant's severity threshold | product, leak amount, age |
| `PRICE_CHANGE` | CI | A competitor snapshot crosses the configured price-delta threshold | competitor label, old/new price, % change |
| `OPPORTUNITY` | PI | A `product_candidate`'s `proxy_score` crosses a configured threshold on a fresh run | candidate title reference, proxy score band, category |

Each row above already exists as a finding/output shape in its owning agent's own spec; this spec adds no new calculation, only the alert rendering and delivery path.

### 6.4 Invoke / revoke mechanics (C3)
An alert that names a specific action attaches one `whatsapp_pending_action` row. A `CONFIRM` reply (or digit shortcut, D2) resolves it `CONFIRMED` and triggers the named `action_ref` through that action's own full authorization chain (`auth.md` §7.1) — WhatsApp confirmation is not a bypass, exactly as `competitor-intelligence-agent.md`'s `WHATSAPP_CONFIRM` trigger already assumes. A `STOP` reply resolves it `DECLINED` — nothing runs. An unanswered pending action expires (`EXPIRED`) per D3-adjacent config, never left ambiguous forever. Disabling an entire alert *type* (a different "revoke") is a `whatsapp_alert_subscription.enabled = false` write, either from in-app settings or a recognized "STOP <TYPE>" reply — it never touches the underlying agent's own on/off state, only whether WhatsApp delivers that category.

### 6.5 Investigation creation on first contact (C7)
If a verified destination's inbound message (confirm, decline, or free text) has no `ACTIVE` investigation for its tenant, exactly one is created and the message is appended to it before the reply is otherwise processed. This is the sole exception to `ceo-agent-orchestration.md` C6 in the whole system, and it is scoped to this one condition — it never fires for an in-app message.

**No WhatsApp-specific investigation mechanics exist beyond the trigger itself.** The created row is an ordinary `investigation` (`ceo-agent-orchestration.md` §5), `created_by` set to the resolved `bound_by` member (§6.7). Once it exists, the investigation's context window behaves exactly as it does for a web-originated one: a rolling window of recent messages plus a compressed summary once the regeneration threshold is hit (`ceo-agent-orchestration.md` C5/D2/§6.6) — the same fresh-context-window rule, unmodified. WhatsApp changes *when* the investigation is created (implicitly, on first contact, instead of an explicit UI click); it changes nothing about what the investigation is or how its context is assembled afterward.

### 6.6 Delivery failure and status tracking
Every `whatsapp_message` tracks provider-reported status (`SENT`/`DELIVERED`/`READ`/`FAILED`) via BSP webhook, mirroring the audit fidelity `ceo-agent-orchestration.md` §6.8 requires of `agent_run` — a failed alert is visible, not silently dropped.

### 6.7 Identity resolution and permission enforcement (C8)

**Step 1 — sender to tenant.** An inbound message's sender phone number is matched against `VERIFIED` rows of `whatsapp_binding.phone_e164`. A match resolves exactly one `tenant_id` (`auth.md` W6). No fuzzy or partial matching; the number must equal a currently-`VERIFIED` row exactly. This part is already fully specified in `auth.md` — restated here as the first half of identity resolution, not redecided.

**Step 2 — tenant to member.** The resolved `whatsapp_binding` row's `bound_by` is the acting `app_user_id` for this message. Because binding is OWNER-restricted (`auth.md` §7.5), `bound_by` is always that tenant's `OWNER` membership row in V1 — there is no mechanism, anywhere in the data model, to resolve an inbound message to a *different* member of the same tenant. `whatsapp_binding` carries one phone number and one binder; it was never designed as a per-partner identity directory (W3), so it cannot serve as one.

**Step 3 — identical authorization, no exceptions.** The resolved `(tenant_id, bound_by)` pair is loaded into the exact same `AuthContext` shape (`auth.md` §5.3) a web request would produce, and the request re-enters the full `auth.md` §7.1 six-step chain unmodified:
1. Clerk authentication is **not** re-run per message (there is no Clerk session on a WhatsApp turn) — the binding's own verification (W5) stands in for step 1, since `whatsapp_binding.verification_status = VERIFIED` is itself proof of a completed, owner-authorized identity check at bind time. Steps 2–6 run exactly as specified, against the resolved OWNER's real `membership` row.
2. Step 5 (**required permission**) is evaluated against `bound_by`'s actual `membership.permissions` — for the OWNER this is every permission implicitly (`auth.md` §5.2), same as on the web. **No permission is granted, widened, or defaulted-open because the request arrived over WhatsApp.** A `CONFIRM` reply whose `action_ref` requires a permission the resolved member does not hold is `DENIED` at step 5, exactly as a CEO-routed web request would be (`ceo-agent-orchestration.md` E2), and the `agent_run` row logs it with the same fidelity (§6.4, §8.2).
3. Step 6 (**tenant ownership of the resource**) uses the resolved `tenant_id` from Step 1 — a `whatsapp_pending_action` or alert referencing another tenant's resource is unreachable, structurally, since the row itself is tenant-scoped (§8.4).

**Consequence for `financials.adjust`.** `financials.adjust` is OWNER-implicit and deny-by-default for PARTNER (`auth.md` §5.2). Since WhatsApp in V1 only ever resolves to the OWNER (Step 2), a WhatsApp `CONFIRM` that happened to target a `financials.adjust`-gated `action_ref` would pass step 5 for the same reason it would on the web from that OWNER's own account — **not** because WhatsApp grants it. A `PARTNER` cannot reach `financials.adjust` (or any permission they lack) via WhatsApp, because no `PARTNER` identity is ever attributed to a WhatsApp request at all in V1 — there is nothing to elevate. No currently-defined alert type (§6.3) actually names a `financials.adjust`-gated `action_ref`; this rule is stated generally so it holds if one is added later.

**Consequence for W11.** "Partners cannot bypass assigned permissions via WhatsApp" (`auth.md` W11) is satisfied trivially in V1: since only the OWNER identity is ever resolved, no partner-specific permission check is ever in play to bypass. §13 Q4 below names the one residual gap this leaves.

### 6.8 Unresolvable sender (W9)
An inbound message from a phone number that is not a `VERIFIED` `whatsapp_binding.phone_e164` is **dropped and logged, silently** — no reply is sent (`auth.md` W9, E17). This is a deliberate, not incidental, choice: Metrion never had an open session or approved-template context with that number (§6.1), so any reply would itself require business-initiated messaging Meta does not permit outside those two mechanisms; and confirming or denying whether a number is "known" back to an anonymous sender would leak binding state to whoever is probing it. The drop is logged (`auth_audit`, `auth.md` §5.1) for operational visibility, but produces zero outbound traffic.

### 6.9 Inventory outcome classification prompt (cancellation-after-dispatch / RTO)

`deterministic-engine.md` §5.6 requires an `rto_outcome` classification (`RECOVERED_SELLABLE` |
`RECOVERED_DAMAGED` | `LOST`) before COGS can be computed for a line that was cancelled after
dispatch or returned/RTO'd — no marketplace report states the condition of returned goods, so
the engine reports `UNAVAILABLE` until a seller supplies it (§7, `manual_adjustment`,
`field=rto_outcome`). WhatsApp is one legitimate channel for collecting that answer, using this
approved template question and mapping — **confirmed, not a proposal**:

| Seller reply | `rto_outcome` written | Confidence |
|---|---|---|
| "Not received" | `LOST` | `MANUAL` |
| "Received" + confirmed sellable | `RECOVERED_SELLABLE` | `MANUAL` |
| "Received" + confirmed damaged | `RECOVERED_DAMAGED` | `MANUAL` |
| Unclear, ambiguous, or no response | **No `manual_adjustment` is written at all** | n/a |

**Hard rule:** a bare "received: yes" with no condition confirmed is **not** sufficient to
write `RECOVERED_SELLABLE` — that would silently assume good condition and risk overstating
profit, the same failure mode D2 exists to prevent in `deterministic-engine.md`. The template
flow must obtain condition explicitly (a second question, or a single combined
received+condition prompt) before writing anything other than `LOST`. Where the reply is
unclear or absent, **nothing is written** — the calc-engine line stays `UNAVAILABLE` exactly as
it already does with no answer at all (§5.6, T11). No component in this pipeline — this
template, the CEO's reply parser, or the engine — ever guesses a value here; deterministic
parsing of an explicit menu/button reply (per D2 of this spec, §6.2) is required, not free-text
inference.

---

## 7. AI requirements

| Brain | Role |
|---|---|
| **Brain 1 / named agents** | Produce every figure an alert ever renders (C4) — unchanged from their own specs. |
| **Brain 3 (CEO's LLM)** | Only used for session-window follow-up synthesis (C1, §6.1) — never for composing the alert template itself or for parsing the confirm/decline reply (D2 keeps that deterministic). |

---

## 8. Authorization and security

1. `whatsapp.use` (`auth.md` §5.2) gates whether the channel is reachable for a tenant at all; unchanged here.
2. A confirmed pending action (§6.4) still passes the full six-step chain (`auth.md` §7.1) for its `action_ref` — the WhatsApp confirmation supplies intent, not authorization.
3. Inbound messages from an unverified destination are dropped and logged, never resolved to a tenant (`auth.md` W9) — this spec adds no new identity path.
4. All `whatsapp_message`/`whatsapp_pending_action` rows are tenant-scoped under the same RLS model as everything else — `FORCE ROW LEVEL SECURITY` plus the `tenant_isolation` policy on `tenant_id` (`auth.md` §7.3), which the generic `<tenant_table>` template already covers now that `whatsapp_pending_action` carries `tenant_id`.
5. **Sender identity resolves to exactly one member — `whatsapp_binding.bound_by`, always the OWNER in V1 (C8, §6.7).** Every WhatsApp-originated request carries that member's real `AuthContext` through the unmodified `auth.md` §7.1 chain. WhatsApp is never a separate trust level: it cannot grant a permission the resolved member's `membership.permissions` does not already hold, and — because no `PARTNER` identity is ever resolved through this channel in V1 — it cannot let a `PARTNER` reach anything, `financials.adjust` included, that they could not already reach on the web (§6.7).

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Alert fires but the tenant's alert-type subscription is disabled | Not sent; no `whatsapp_message` row created at all |
| E2 | Seller replies after `whatsapp_pending_action.expires_at` | Treated as `EXPIRED`; the reply is logged but triggers nothing (§6.4) |
| E3 | Seller replies with free text instead of `CONFIRM`/`STOP` | No fixed-vocabulary match; if a session window is open, routed to the CEO pipeline as a normal question (C1) rather than silently ignored |
| E4 | Alert template rejected or still pending Meta approval | That alert type cannot fire; treated as a configuration gap, not a runtime error |
| E5 | Owner disables WhatsApp mid-pending-action | Channel stops per `auth.md` W10/E18; any `PENDING` action is left to expire naturally, not force-resolved |
| E6 | Two alerts would fire the same day for one tenant | Second is deferred to the next day per D3's cap, not dropped silently |
| E7 | A `CONFIRM` reply is received from the tenant's verified number, and it happens to be a `PARTNER` typing on a shared "dedicated WhatsApp Business number for the team" (W2's second binding option), not the OWNER | The request is still processed as `bound_by` (the OWNER) per §6.7 Step 2 — there is no mechanism to detect or attribute it to the actual typist. See Q4 (§13): this is a known, named residual gap, not a silent one. |
| E8 | An unresolvable sender (no `VERIFIED` `whatsapp_binding` match) sends `CONFIRM` or any other message | Dropped and logged; zero outbound reply (§6.8, `auth.md` W9/E17) |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | BSP vendor not yet contracted (D1) | All of §6 |
| V2 | Templates not yet drafted or submitted for Meta approval | §6.2, launch of any alert type |
| V3 | Alert threshold values (severity for `MARGIN_RISK`, delta % for `PRICE_CHANGE`, score band for `OPPORTUNITY`) are each owned by their agent's own spec and not finalized there either | §6.3 |
| V4 | Reconciliation of D3's "1/day" cap against the entitlement spec's eventual tier caps | `billing-and-pricing.md` V4-style gap |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | No outbound alert is ever sent without an `APPROVED` template (C5, §6.2). |
| AC2 | Every alert's variables trace to an `engine_result_ref`, `estimate_ref`, or agent-report field — never LLM-composed at send time (C4). |
| AC3 | A `CONFIRM` reply always re-enters the target action's full authorization chain (§6.4, §8.2). |
| AC4 | A first inbound message with no `ACTIVE` investigation creates exactly one (C7, §6.5). |
| AC5 | No session-window message is sent outside `session_window_expires_at` (§6.1). |
| AC6 | Disabling an alert type never disables the underlying agent (§6.4). |
| AC7 | Every WhatsApp-originated request resolves to exactly `(tenant_id, bound_by)` and passes the unmodified `auth.md` §7.1 six-step chain against that member's real permissions — never a WhatsApp-specific bypass, default-allow, or elevated identity (C8, §6.7). |
| AC8 | An inbound message from a non-`VERIFIED` number produces zero outbound reply and is logged, never resolved to any tenant (§6.8, `auth.md` W9). |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | CFO detects a threshold leak, tenant subscribed to `MARGIN_RISK` | Approved template sent with leak amount/age filled in (AC1, AC2) |
| T2 | Seller replies `CONFIRM` to a `PRICE_CHANGE` alert offering a CI re-check | `whatsapp_pending_action` resolves CONFIRMED; CI run executes through its own auth chain (AC3) |
| T3 | Seller replies `STOP` | Action DECLINED; nothing runs |
| T4 | Seller with no open investigation sends any reply | Investigation created, message appended (AC4) |
| T5 | Seller sends a free-text question 10 minutes after replying to an alert | Session window open; routed through the CEO pipeline (C1) |
| T6 | Seller sends a free-text question 30 hours after their last reply | Window closed; no session message sent (AC5) |
| T7 | Owner mutes `OPPORTUNITY` alerts in-app | No further `OPPORTUNITY` `whatsapp_message` rows created (E1) |
| T8 | `CONFIRM` reply targets an `action_ref` gated by a permission `bound_by` (the OWNER) holds | Step 5 passes; action runs (AC7) |
| T9 | Inbound message from a number with no `VERIFIED` `whatsapp_binding` row | Dropped, logged, no reply sent, no tenant resolved (AC8, E8) |
| T10 | Inbound `CONFIRM` arrives with a stale/`DISCONNECTED` binding for that number (rebound or revoked since) | Treated as unresolvable (AC8) — a `DISCONNECTED` row is not `VERIFIED` |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | Exact per-alert-type thresholds (V3) — each belongs to its owning agent's spec, not finalized there yet | §6.3 |
| Q2 | Final BSP vendor contract (D1, V1) | Launch readiness |
| Q3 | How WhatsApp alert volume interacts with the entitlement/billing spec's eventual caps (V4) | `billing-and-pricing.md` |
| Q4 | **Shared-device attribution.** W2 allows binding a "dedicated WhatsApp Business number for the team," not just the team leader's personal number. If a `PARTNER` has physical access to that shared device, they can send `CONFIRM`/free-text messages that §6.7 attributes to `bound_by` (the OWNER) — genuinely OWNER-level access, not a permission-check bug, because no mechanism in the data model can tell who is physically typing on a shared handset. Is this accepted as a V1 trust boundary (document it, perhaps recommend binding the team leader's personal number rather than a shared device), or does it need a mitigation (e.g. a PIN/keyword-per-partner scheme, restricting the *shared-device* binding option entirely to a safe subset of `action_ref`s)? This is a genuine, unresolved product/security decision — not guessed here. | Residual privilege-escalation surface if the shared-device binding option (W2) is used; §6.7 E7 |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Two-way vs. outbound-only (Q6) | **Alerts plus bounded confirm/decline, with full CEO-pipeline follow-up inside an open session window** (C1). |
| R2 | Direct Meta API vs. BSP (Q7) | **BSP** (Gupshup/Interakt), not direct Cloud API, for V1 (C2). |
| R3 | "Invoke/revoke" meaning | **Two mechanisms**: per-action confirm/decline, and channel/alert-type-level disable — never a per-agent pause (C3). |
| R4 | `ceo-agent-orchestration.md` Q6 (WhatsApp, no open investigation) | **Implicitly opens exactly one**, the sole named exception to that spec's C6 (C7). Propagated into `ceo-agent-orchestration.md` itself (§6.7, R7, AC8, E10/E11) — both files now agree. |
| R5 | WhatsApp identity → tenant/member/permission mapping (checklist item 3) | **Resolved (C8, §6.7):** tenant via `whatsapp_binding.phone_e164` (W6, unchanged); member always `bound_by`, which is always the OWNER since binding is OWNER-restricted (`auth.md` §7.5); every request re-enters the unmodified `auth.md` §7.1 chain against that member's real permissions — no bypass, no elevation, `financials.adjust` included. The one residual gap (shared-device attribution) is named, not resolved, as Q4. |
