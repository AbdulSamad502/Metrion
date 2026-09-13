# Metrion — WhatsApp Integration Specification

**Status:** Draft for review
**Prerequisites:** `auth.md` §1.5/§7.5 (`whatsapp_binding`, W1–W11 — identity binding, never an authorization elevation) · `ceo-agent-orchestration.md` §6.7 (WhatsApp turns enter the same pipeline as chat) · `competitor-intelligence-agent.md` §6.9 (`WHATSAPP_CONFIRM`, locked facts only, everything else deferred here).

This spec closes the dependency every other spec has been pointing at: `auth.md` W10, `competitor-intelligence-agent.md` Q1, `cfo-agent.md`'s WhatsApp deferral, and `ceo-agent-orchestration.md`'s Q6 all named this file as the place these decisions belong.

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
  id uuid pk, whatsapp_message_id uuid not null fk,
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

### 6.6 Delivery failure and status tracking
Every `whatsapp_message` tracks provider-reported status (`SENT`/`DELIVERED`/`READ`/`FAILED`) via BSP webhook, mirroring the audit fidelity `ceo-agent-orchestration.md` §6.8 requires of `agent_run` — a failed alert is visible, not silently dropped.

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
4. All `whatsapp_message`/`whatsapp_pending_action` rows are tenant-scoped under the same RLS model as everything else.

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

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | Exact per-alert-type thresholds (V3) — each belongs to its owning agent's spec, not finalized there yet | §6.3 |
| Q2 | Final BSP vendor contract (D1, V1) | Launch readiness |
| Q3 | How WhatsApp alert volume interacts with the entitlement/billing spec's eventual caps (V4) | `billing-and-pricing.md` |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Two-way vs. outbound-only (Q6) | **Alerts plus bounded confirm/decline, with full CEO-pipeline follow-up inside an open session window** (C1). |
| R2 | Direct Meta API vs. BSP (Q7) | **BSP** (Gupshup/Interakt), not direct Cloud API, for V1 (C2). |
| R3 | "Invoke/revoke" meaning | **Two mechanisms**: per-action confirm/decline, and channel/alert-type-level disable — never a per-agent pause (C3). |
| R4 | `ceo-agent-orchestration.md` Q6 (WhatsApp, no open investigation) | **Implicitly opens exactly one**, the sole named exception to that spec's C6 (C7). |
