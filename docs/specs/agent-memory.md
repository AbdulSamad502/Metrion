# Agent memory — private memory per agent, one shared memory

Status: V1 specified and built 2026-10-10 (owner-directed). Authority for what agents remember. Read with `ceo-agent-orchestration.md` §6.35 and `auth.md` §1.4.

## 1. Confirmed decisions
- Every agent (CEO, CFO, PI, CMO, CI) has its **own private memory**. There is **one shared memory** that only *important* things are promoted into. Both are per tenant.
- Memory is **context, never evidence.** It can pre-fill a question, give a conversation continuity and let the CEO say "you told me". It is **never a figure source**: no engine result, estimate or money calculation is stored or recalled as a number from memory. Any figure the seller states is kept as the seller's own words, labelled, and is never used as an engine input.
- The LLM never writes memory. Code does, from (a) the seller's own explicit statements, (b) answers the seller confirmed on a decision or input card, and (c) a short fixed note an agent's code writes about its own completed work. A model may not originate a memory.
- The seller can **see, correct and forget** anything remembered. Nothing is remembered silently: the CEO says what it saved, in the same answer.

## 2. Design decisions requiring review
- Embeddings and semantic recall are **not** part of this ledger (kind + key lookup, newest wins). Semantic recall is specified separately in `rag-knowledge.md` (2026-10-12) as a **read-only derived index** over active SHARED rows only: `agent_memory` stays authoritative, PRIVATE / FORGOTTEN / superseded / `AGENT_NOTE` rows are never indexed, and a hit is re-read from this table before use. The ledger's write rules above are unchanged.
- Which statements are auto-remembered is a short closed list (§4.3). Anything outside it is not remembered. Widening it is a product decision.

## 3. Data model — `agent_memory` (append-only, FORCE RLS)
`id, tenant_id, scope (PRIVATE|SHARED), agent_code (CEO|CFO|PI|CMO|CI: the owner, or for SHARED the agent that promoted it), kind, key, value (text, ≤ 500), basis (SELLER_STATED|CONFIRMED_DECISION|AGENT_NOTE), source_ref (jsonb: the message or finding it came from), supersedes_id, status (ACTIVE|FORGOTTEN), created_by, created_at`.
- **Append-only.** A correction is a new row that supersedes the old; forgetting is a `FORGOTTEN` row that supersedes it. The app role has SELECT and INSERT only. "Active" = not superseded by a later row, and `status = ACTIVE`.
- **Database checks (the gate cannot be bypassed from code):** a `SHARED` row must have a kind in the shared set (§4.1) and basis `SELLER_STATED` or `CONFIRMED_DECISION` (an agent's own note is never shared); a `SELLER_STATED` or `CONFIRMED_DECISION` row must carry `source_ref`.
- A `supersedes_id` must belong to the same tenant and the same scope/agent/kind/key (validated in the repository, as for `manual_adjustment`).

## 4. Core rules
1. **Kinds.** `BUSINESS_NAME, NICHE, MARKETPLACES, GOAL, BRAND_TONE, DECISION` may be shared. `PREFERENCE` and `NOTE` are private only.
2. **Promotion to shared** only through `memory.promote`, which accepts a shared kind with a seller-stated or confirmed basis and a source. There is no other write path to `SHARED`.
3. **Auto-capture (CEO, V1):** "my business name is X", "my niche is X", "I sell on A and B" → the CEO saves it shared (basis `SELLER_STATED`, source = the message) and says so. A PI research the seller confirmed saves the brief's category, budget and marketplaces as PI private `NOTE`s to pre-fill next time (basis `CONFIRMED_DECISION`).
4. **Recall.** The shared profile (names, niche, marketplaces, goal, tone; never a money value) is offered to the classifier and composer as quoted context labelled "what the seller told us". An agent reads its own private memory plus the shared memory. A guided question may offer a remembered answer as an option, never fill it silently.
5. **Direct answers.** "What is my business name?" is answered by code from memory (with the date it was told), or says plainly that it has not been told yet; no model.
6. **Control.** `GET /api/v1/ceo/memory` lists active items for the member's tenant; `POST /api/v1/ceo/memory/{id}/forget` forgets one. Both need the CEO permission; tenant comes from the session only.
7. **Untrusted content never becomes memory.** Text from attachments or specialists is not a seller statement and is never captured.

## 5. Authorization and security
Tenant-scoped everywhere; FORCE RLS; no client-supplied tenant; a foreign or unknown id on forget is a plain not-found. Memory values are length-bounded, stored as text and rendered as quoted data (never as instructions) wherever a model sees them.

## 6. Edge cases
Same statement twice → no new row. A new business name → supersedes the old. A statement containing instructions or markup → stored as plain text, quoted when recalled. Seller forgets, then restates → saved again.

## 7. Production-validation blockers
None for V1 beyond the owner's review of the auto-capture list and data-retention wording for the privacy policy.

## 8. Acceptance criteria
AC1 shared rows without a shared kind or a seller/confirmed basis are refused by the database. AC2 another tenant never sees or supersedes this tenant's memory. AC3 correction supersedes and the old value stops being active; forgetting removes it from recall. AC4 a captured statement is acknowledged in the same answer. AC5 no money value enters a model prompt through memory. AC6 an agent note is never shared.

## 9. Test scenarios
Isolation and constraint tests against Postgres; capture and recall through a real CEO turn; direct answer with and without memory; forget then recall; money value excluded from the composer context.

## 10. Explicit open questions
Q1 ~~Should specialist agents be allowed to *propose* a shared fact (for example PI noticing the seller's niche) for the seller to confirm? V1: no.~~ **Resolved 2026-10-10 (owner): yes, as a separate tier.** Agents may record their own findings in a separate append-only table `shared_finding` (trust-labelled `SELLER_STATED` / `ENGINE_VERIFIED` / `AGENT_REPORTED`, source ref required, any number only via an `engine_result_ref` or `estimate_ref`, seller can see, correct and forget). They never enter the seller-stated shared profile: §3, §4.1-§4.2 and the `agent_memory_shared_gate` are unchanged, so an agent's note is still never shared as a seller fact. Spec: `agent-needs-and-shared-knowledge.md` §6. Q2 Retention: how long is memory kept after an account closes? Note: because memory is append-only, a forgotten item's original text stays in the superseded row (it is excluded from every recall and from the seller's view); true erasure on request needs a retention/erasure decision before launch. Q3 Is the auto-capture list (§4.3) right for launch?

## 11. agent-memory.md addendum: C6 (private memory for CFO, CMO and CI)
Status: specified before coding, 2026-10-10. Extends §4.3 and §4.4; changes nothing about PI.

**Decisions.** CFO, CMO and CI each get a short closed list of PRIVATE `NOTE` keys, written exactly like PI's (basis `CONFIRMED_DECISION`, source = the message, by code only) and used only to OFFER a choice next time. They are never filled in, never shared, never a figure source and never contain money or free text.

| Agent | Key | Value (closed form) | Offered as the first option of |
|---|---|---|---|
| CMO | `last_marketplaces` | one or more of AMAZON, FLIPKART, MEESHO, joined by ", " | the marketplace question of CMO titles, hashtags and grounded (description, keywords) |
| CI | `last_competitor` | the label of a tracked competitor (the seller's own label, 120 characters at most) | the competitor question of the price-impact conversation |
| CFO | `last_basis` | INCLUSIVE or EXCLUSIVE | the GST basis question of the price-impact conversation |

**Rules.**
1. *Write only on confirmation.* A key is written only when a session finished with the seller's own answers (the session produced its final inputs and the run was accepted for resolution), in the same place and on the same basis as PI's note, best-effort: a failure is logged and never blocks or alters the turn. A session that is cancelled, blocked or still asking writes nothing.
2. *Offered, never filled.* The remembered value is added as the FIRST option, with the reason "What you chose last time". The field stays unanswered (`collected` does not contain it) until the seller picks or types. The total stays at `MAX_OPTIONS` (3); an existing option with the same text is not repeated, and the existing options otherwise stay in their order.
3. *Validated on read.* A remembered value that is not in its closed form (an unknown marketplace, a basis that is not INCLUSIVE or EXCLUSIVE, a competitor label that is no longer tracked, or a multi-marketplace value for a one-marketplace question) is simply not offered.
4. *Private per agent.* Each key is read and written only under its own agent (`agent_code` CMO, CI, CFO) with scope PRIVATE; one agent's key is never visible to another's lookup, and PI's keys are unchanged. The allowlist of (agent, key) pairs lives in `memory.PRIVATE_KEYS`; any other pair is refused by `memory.note_choice`.
5. *Control.* These items appear in `GET /api/v1/ceo/memory` with plain labels and are forgotten with `POST /api/v1/ceo/memory/{id}/forget`, through the existing mechanism. A forgotten item is no longer offered.
6. *No money.* None of these keys holds a money value. The competitor's captured price is not remembered (it is read fresh from CI, spec 6.38).

**Acceptance (C6).** AC-C6-1 nothing is collected until the seller chooses the offered option. AC-C6-2 CMO, CI and CFO memories are isolated from each other, from PI's, and between tenants. AC-C6-3 forgetting removes the offer. AC-C6-4 an invalid stored value is not offered. AC-C6-5 a note is written only for a finished, confirmed session.
