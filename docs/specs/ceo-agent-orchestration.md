# Metrion — CEO Agent Orchestration Specification

**Status:** Draft for review — **CP0 amendment 2026-10-03, rounds 2 and 3 applied** (multimodal intake §6.9; CMO workflow routing; GST Route A/B; catalog-seeded niche confirmation and seven-section trend reports)
**Prerequisites:** `auth.md` (execution paths, permission/entitlement chain) · `deterministic-engine.md` (Brain 1) · `competitor-intelligence-agent.md` · `cfo-agent.md` · `product-intelligence-agent.md` · `slim-cmo-agent.md` — this spec is the integration layer over all four and invents no new agent capability of its own.

**CEO routes and composes. It never computes, and it never bypasses another agent's own authorization chain.** Every number in a CEO response still traces to an `engine_result_ref` or `estimate_ref` produced by Brain 1 or a named agent. CEO's own LLM work is intent classification and natural-language composition — nothing else.

---

## 1. Confirmed decisions

| # | Decision | Source |
|---|---|---|
| C1 | **Strict star topology (Q26).** CEO owns all agent-to-agent routing. No agent calls another agent. Every agent may call Brain 1 (and the GST Applicability Lookup) directly as shared services — that is not delegation, it is shared-service access. | readiness §1 — Topology |
| C2 | **Fast path vs AI path is resolved structurally, not by a runtime classifier (Q68).** The **entry point itself** determines the path: a dashboard/button hits a **registered direct execution path** (`agent.X` alone, no CEO, no LLM at all) exactly as each agent spec's §"Registered direct execution paths" defines. A chat message hits **CEO conversationally** (`agent.ceo` + `agent.X`). There is no NLU step that decides "is this simple enough to skip CEO" — the UI/API surface the request arrived on decides that, once, at design time. | `auth.md` §5.2; every agent spec §6.8/§8 |
| C3 | **AI-path control flow is single-shot, never a multi-turn tool loop (Q67).** For every conversational turn: CEO classifies intent **once**, issues the needed reads **in parallel**, then makes **exactly one** LLM call to compose the answer. CEO never runs a sequential chain of LLM→tool→LLM→tool. This is the "hybrid path" the planning document specifies and explicitly contrasts with the "bad architecture" of chained LLM round-trips. | planning doc p.10; OP10 |
| C4 | **Agent delegation is one call per turn.** Where intent requires a named agent (PI/CI/CFO/CMO) rather than a bare Brain 1 read, CEO selects **exactly one** registered action from that agent's own interface (`pi.discover`, `ci.capture_run`, `cfo.reconcile`, `cmo.generate_title`, etc.) and invokes it once. No agent conducts a back-and-forth with CEO mid-run; each returns one structured report (C1's star topology; every agent spec's §6.9/§9 "Output to CEO"). | this spec; §6.4 |
| C5 | **Investigations are the top-level conversational unit (Q27).** Not a flat chat log. Each investigation holds a rolling window of recent messages plus a compressed summary of everything older — the summary, never the full history, is what reaches the LLM context. | Q27=B, this session's decision record |
| C6 | **No automatic investigation-splitting (Q28).** A new investigation is created **only** by an explicit user action. CEO never infers "this is a fresh topic" and silently forks context. **One named exception:** a verified WhatsApp message with no `ACTIVE` investigation for its tenant is itself the explicit action (`whatsapp-integration.md` C7, §6.7) — see §6.7 below. No other surface gets an implicit-creation path. | Q28, confirmed; WhatsApp exception resolves Q6 |
| C7 | **`agent_run` is the single audit and flow-visualization artifact for every agent invocation**, direct or conversational. This is the concrete table every agent spec's "Audit: Yes" column writes to — it did not exist before this spec. | resolves `competitor-intelligence-agent.md` Q9 |
| C8 | **CEO's own routing decision is advisory, never authoritative.** Selecting an agent action does not grant access to it. The target action's own six-step chain (`auth.md` §7.1) runs regardless of how the request arrived, and can still deny it. | `auth.md` §7.1; C4 |
| C9 | **CEO holds no financial formula, no fee rate, and no agent-specific business logic.** Everything numeric in a CEO answer is copied from a Brain 1 result or a named agent's structured report. | Brain-boundary rule, all specs |
| C10 | **Multimodal intake is a CEO surface, vision is not CEO's job.** CEO accepts a product image, product details, target price and marketplace selections as a structured intake (§6.9). The image is stored and handed to CMO by reference; **CEO's classification and composition LLM calls remain text-only and never see image bytes.** | 2026-10-03 decision 1; OP8, OP11 |
| C11 | **Product GST questions are never answered by CMO; CEO handles them by permission, in one of two routes.** **Route A:** member holds `agent.cfo` + `service.gst_lookup` → CEO delegates `cfo.gst_lookup` (CFO's OP13 resolution unchanged). **Route B:** member holds `service.gst_lookup` but not `agent.cfo` → CEO calls the shared GST Applicability Lookup service itself (a shared service per C1/OP9, not delegation), tier 3 only, under safety conditions G1–G7 of `slim-cmo-agent.md` §6.9. The route is chosen by the member's permissions, never by the model. | 2026-10-03 decision 4 + round 2; `slim-cmo-agent.md` C4/§6.9 |

---

## 2. Design decisions requiring review

| # | Decision | Recommendation | Rationale |
|---|---|---|---|
| D1 | Investigation visibility across a team | **Tenant-wide by default** — any member with the relevant `agent.*` permission can view and continue any investigation in the tenant, since the underlying data is tenant data regardless of who asked | Consistent with `auth.md`'s tenant-scoped RLS model; a private-investigation mode is a narrower feature to add later, not a default to invent now |
| D2 | Rolling summary regeneration | Every 10 messages, or when the raw window exceeds a token budget, whichever comes first | Keeps the summary current without regenerating on every single message |
| D3 | Parallel-fetch bundles | A small, named set of common bundles, each a fixed set of Brain 1 calls issued together — see the starter catalog below | Matches the planning doc's explicit "parallel retrieval → one LLM call" pattern; an unbounded ad-hoc fetch list would reintroduce sequential round-trips through classification alone |
| D4 | Ambiguous intent | CEO asks a clarifying question rather than guessing which agent or bundle to invoke | Matches OP1's "ask the seller rather than assume" principle, applied to routing itself |
| D5 | CEO's own metering unit | One `agent_run` (conversational, `agent_id = CEO`) per turn, **regardless of whether a sub-agent was invoked** | CEO does real LLM work (classification + composition) even on a pure Brain 1 read; the free-tier cap (30/month) should count that work honestly. Final unit still owned by the entitlement spec. |

---

## 3. Assumptions

| # | Assumption | Risk if wrong |
|---|---|---|
| A1 | Intent classification can reliably distinguish "needs a named agent" from "needs a Brain 1 read" from stated locked models (`deterministic-engine.md` §7's Ollama scoping) | Medium — misclassification either invokes an unnecessary paid agent run or under-serves a request that needed one |
| A2 | A compressed summary of >10 messages retains enough signal for later turns to stay coherent | Medium — degrades to CEO re-asking for context it should already have |
| A3 | Named parallel-fetch bundles (D3) cover the majority of real financial questions without per-question customisation | Medium — an uncovered question falls back to a slower per-metric fetch, not a failure |

---

## 4. Goals and non-goals

**Goals** — route every request to the correct execution surface (fast path or AI path) without a runtime classifier deciding it; resolve every conversational financial question via parallel Brain 1 reads and one LLM call; delegate to exactly one named agent per turn when intent requires it; maintain investigations as bounded, explicit, resumable conversational units; log every agent invocation — direct or conversational — to one auditable, visualisable record.

**Non-goals (V1)** — any financial calculation (Brain 1's exclusively) · agent-to-agent calls of any kind · multi-turn LLM tool-calling loops · automatic investigation creation or forking · a private/shared visibility toggle on investigations (D1's default stands for V1) · defining what any individual agent's actions do (that is each agent's own spec).

---

## 5. Data model

```sql
investigation (
  id uuid pk, tenant_id uuid not null,
  title text,                             -- auto-generated from the first message, editable
  status text not null,                   -- ACTIVE | ARCHIVED
  created_by uuid not null,
  summary text,                           -- compressed running summary (D2); null until first regeneration
  summary_covers_through uuid,            -- fk to the last investigation_message folded into `summary`
  created_at timestamptz not null, last_message_at timestamptz not null
)

investigation_message (
  id uuid pk, investigation_id uuid not null, tenant_id uuid not null,
  role text not null,                     -- USER | CEO | SYSTEM
  content text not null,
  agent_run_id uuid,                      -- set when this CEO message resulted from an agent/Brain 1 invocation
  created_by uuid,                        -- the member who sent a USER message; null for CEO/SYSTEM
  created_at timestamptz not null
)

agent_run (                               -- C7: the single audit + flow-visualization artifact
  id uuid pk, tenant_id uuid not null,
  agent_id text not null,                 -- CEO | PI | CI | CFO | CMO | BRAIN1
  trigger_type text not null,             -- DIRECT | CONVERSATIONAL
  trigger_ref text not null,              -- e.g. "pi.discover", "cfo.reconcile", "ceo.chat_turn", "brain1.compute_metric"
  investigation_id uuid,                  -- set only for CONVERSATIONAL
  parent_run_id uuid references agent_run(id),  -- null for the CEO's own turn-level row; set to that row's id on every sub-agent/Brain-1 run it fans out to (agent-flow-visualization.md D1)
  requested_by uuid not null,
  permission_check text not null,         -- PASS | DENIED, and which key failed if denied
  entitlement_check text not null,        -- PASS | DENIED
  status text not null,                   -- QUEUED | RUNNING | PARTIAL | COMPLETE | FAILED | DENIED
  output_refs jsonb,                      -- engine_result_ref[] / estimate_ref[] this run produced
  error_reason text,
  started_at timestamptz, finished_at timestamptz
)
```

**Every direct-path invocation defined in any agent spec** ("Audit: Yes" in CI §6.4, CFO §6.8, PI §6.8, CMO §8) **writes exactly one `agent_run` row here.** No agent spec defines its own audit table; this is the one they all resolve into.

---

## 6. Core rules

### 6.1 Topology enforcement
CEO is the only caller of any agent's conversational interface. No code path exists for PI to call CI, CFO to call CMO, or any other agent-to-agent edge (C1). Every agent may call Brain 1 and the GST Lookup directly — that is a shared service, not routing, and CEO is not in that path at all.

### 6.2 Fast path
A direct execution path never touches CEO. The member's client calls the registered trigger (`pi.discover`, `cfo.reconcile`, ...) directly; that action's own six-step chain runs; an `agent_run` row is written with `trigger_type = DIRECT`. **CEO plays no role here** — this is what makes it fast (C2).

### 6.3 AI path — intent classification
A conversational message enters through CEO. CEO's LLM performs exactly one classification pass per turn, choosing one of:

1. **Brain 1 read** — the question is answerable from canonical financial data alone (e.g. "why did my margin drop?").
2. **Named agent delegation** — the question requires PI/CI/CFO/CMO's own capability (e.g. "find profitable products under ₹500," "check my competitor's price").
3. **Clarification needed** — intent is ambiguous (D4). CEO asks, and consumes no further path until answered.

This is the **only** LLM decision point in the turn. Nothing downstream re-classifies.

### 6.4 AI path — execution (C3, C4)

- **Brain 1 read:** CEO issues the fetches for the classified bundle (D3) **in parallel** — multiple simultaneous Brain 1 calls, never sequential. No agent is invoked. **Starter bundle catalog** (D3, incomplete — see Q1):

  | Bundle | Brain 1 calls issued together |
  |---|---|
  | `PROFIT_OVERVIEW` | `compute_metric(NET_REALIZED_REVENUE)`, `compute_metric(CONTRIBUTION_PROFIT)`, period-over-period delta |
  | `LEAK_SUMMARY` | `leak_aggregate`, top-N `reconciliation_exception` rows via `rank_findings` |
  | `CASH_POSITION` | `cash_reconciliation` — expected, received, variance, TCS/TDS |
  | `GST_SUMMARY` | indicative tax summary per `deterministic-engine.md` §8.3 |

  A question that matches none of these falls back to a single-metric `compute_metric` call — still one parallel-eligible read, still one synthesis call. It never becomes a second classification pass.
- **Named agent delegation:** CEO invokes **exactly one** registered action on the target agent, per that agent's own spec. This still passes through the full `auth.md` §7.1 chain for that action (C8) — CEO's classification does not skip it. If denied, CEO explains the wall (permission or entitlement) rather than silently failing or fabricating a result — matching `cfo-agent.md`'s gated-preview precedent for entitlement denials.
- **Never both, and never chained.** One turn is one classification and one execution shape. A follow-up question is a new turn with its own classification.

### 6.5 Response synthesis
Once reads or the agent's structured report return, CEO makes **exactly one** LLM call to compose the natural-language answer. Every number in that answer is copied from an `engine_result_ref`, an `estimate_ref`, or a field on the agent's structured report — never generated, rounded, or adjusted by the model (same rule as `cfo-agent.md` AC2, `product-intelligence-agent.md` AC20).

### 6.6 Investigations and memory (C5, C6)
- A message is appended to the investigation's `investigation_message` list.
- The LLM context for a turn is: the summary (if one exists) **plus** messages since `summary_covers_through` — never the full raw history (C5).
- `investigation.summary` is regenerated per D2's cadence; regeneration folds newly-covered messages in and advances `summary_covers_through`. Regeneration is itself one bounded LLM call, not part of the per-turn classify/synthesize calls in §6.3–6.5.
- A new `investigation` row is created **only** when the user explicitly starts one (C6) — a "New Investigation" action in the UI, **or** the one named WhatsApp exception in §6.7. Both paths write the identical row shape through the identical creation logic; there is no separate WhatsApp investigation type or schema. CEO never creates one on its own inference beyond these two named triggers.

### 6.7 WhatsApp-originated turns

A verified WhatsApp message resolves to exactly one tenant, and to exactly one member (`whatsapp_binding.bound_by`, always the tenant's OWNER in V1 — `whatsapp-integration.md` C8/§6.7) and, once it does, is routed through **the same §6.3–6.5 pipeline as any other conversational message** — one classification, one execution shape, one synthesis call. Nothing about the pipeline itself is WhatsApp-specific.

**Resolved — Q6 (investigation creation on first WhatsApp contact).** `competitor-intelligence-agent.md` §6.9 and `cfo-agent.md` (in its own WhatsApp deferral) both flagged this as pending, correctly, because it was this spec's question to answer, not theirs. `whatsapp-integration.md` C7/§6.5 resolves it: **if a verified destination's inbound message (confirm, decline, or free text) has no `ACTIVE` investigation for its tenant, exactly one is created and the message is appended to it before the reply is otherwise processed.** This is the sole exception to C6's "explicit user action only" rule in the whole system — justified because WhatsApp has no "New Investigation" button, so the inbound message *is* the explicit action. It uses the identical `investigation` creation path defined in §6.6 (same row shape, same `created_by` semantics — `created_by` is the resolved `bound_by` member) — no WhatsApp-specific investigation variant exists. It never fires for an in-app message, and it never fires a second time once an `ACTIVE` investigation already exists for the tenant (§6.7 T13).

No WhatsApp-specific exception to any *other* rule in this spec is needed: classification, execution, synthesis, summary regeneration, and RLS scoping all behave identically to a web-originated turn once the investigation exists.

### 6.8 `agent_run` logging and flow visualization (C7)
Every invocation — direct or conversational, successful or denied — writes one `agent_run` row at start and updates it to a terminal `status` at completion. This is what a flow-visualization surface ("Agents at Work") reads from: agent, trigger, status, timing, and — for conversational runs — the `investigation_id` that requested it. A denied run (`status = DENIED`) is logged with the same fidelity as a completed one; the audit trail must show what was *attempted*, not only what succeeded.

CEO's own turn-level row is written first, with `parent_run_id = NULL`. Every row that turn fans out to — each Brain 1 bundle call, or the one delegated named-agent call (§6.4) — is written with `parent_run_id` set to that CEO row's `id`. This is the reliable grouping key `agent-flow-visualization.md` D1 needed; that spec's diagram is built by selecting the CEO anchor row plus every row where `parent_run_id = anchor_run_id`, not by inferring the group from `investigation_id` and overlapping timestamps.

### 6.9 Multimodal intake and the CMO workflows (C10, C11 — CP0 amendment 2026-10-03)

This section adds **no new agent capability to CEO** (the spec's opening rule stands). It defines how CEO accepts an image and slots, and how it routes the CMO and GST turns without breaking C3/C4.

**Intake.** A seller may attach a product image to a chat message and state product details, a target price and one or more of Amazon / Flipkart / Meesho.
- The attachment goes through an upload endpoint (`files.upload`-gated) that stores it in CMO's `seller_image_asset` (`slim-cmo-agent.md` §5) and returns an `image_asset_id`. **Image bytes never enter an `investigation_message`, the rolling summary, or any CEO LLM prompt** — only the opaque `image_asset_id` and its metadata do. CEO's classification and composition calls therefore stay text-only and need no vision-capable model.
- Classification (§6.3) extracts the declared slots as text: `marketplaces[]`, `niche_text`, `product_name`, `brand`, `category_hint`, `attributes[]`, `target_price_paise`, `image_asset_id`. A price stated in rupees is converted to integer paise **by deterministic parsing, not by the LLM**, and echoed back to the seller for confirmation. **Missing `marketplaces` → CEO asks (D4/OP1); CEO never defaults a marketplace.** Missing optional slots do not block.

**Routing table (each row is ONE registered action — C4 holds):**

| Seller intent | CEO delegates exactly one of | Notes |
|---|---|---|
| "titles for my product" (1–3 marketplaces) | `cmo.generate_title_sets` | One action, N marketplaces → N artefacts, N units. This is *one invocation* with an enumerated list, not N delegations, so C4's one-action-per-turn rule is preserved (`slim-cmo-agent.md` §8.1). |
| "I choose option 3 for Flipkart" | `cmo.approve_title` | 0 units, no LLM in CMO. Option ids come **only** from the seller's message or click; CEO may not choose, default or infer one. |
| "now write the description/bullets/keywords" | `cmo.generate_listing_copy` (or one individual copy trigger) | Needs an approval or a seller-supplied title; otherwise CEO asks (E13). Approval and copy are **separate turns**, each one action, each with its own CEO unit (D5). A UI "Approve & generate copy" button may call the two registered direct paths in sequence — that is the client making two explicit calls, not CEO chaining. |
| "hashtags" | `cmo.generate_hashtags` | Presented as separate marketing suggestions. |
| "what colour / weight / category is this?" | `cmo.catalog_answer` | Basis labels preserved in the composed answer (E15). |
| "what's trending right now?" / "what's happening in e-commerce?" | `cmo.market_trends` (after niche confirmation) | Needs `agent.ceo` + `agent.cmo` + `research.market_trends`. **Niche confirmation is its own step, over separate turns, each one action (C4):** `cmo.suggest_niche_terms` (deterministic catalog-title suggestions, needs `files.view`) → seller confirms/edits/rejects via `cmo.confirm_niche_terms` → `cmo.market_trends`. If confirmed terms already exist, CEO goes straight to the report. **CEO never sends an unconfirmed term, a raw report or any financial/customer data to research** (CMO C15) and shows the exact outbound queries before the first send. A report with no confirmed niche still runs its broader sections (news, tactics, new products); niche-dependent sections show "confirm a niche" (E19 of the CMO spec, E18 here). Seven sections are returned (CMO §6.8.2). |
| "what GST applies to this product?" | **Route A:** `cfo.gst_lookup` · **Route B:** CEO's call to the shared GST lookup | **CMO not invoked.** CEO supplies product name and category text plus each one's basis (`SELLER_PROVIDED` / `ESTIMATED`; an `UNVERIFIED_HINT` image attribute is never passed as a category) read from the stored `cmo_generation` / `product_image_analysis` records. Route A needs `agent.ceo` + `agent.cfo` + `service.gst_lookup` (CFO's full OP13 resolution). Route B needs `agent.ceo` + `service.gst_lookup`, returns a `PROVISIONAL` tier-3 result only, meters the shared GST meter + CEO's turn unit, and can never become a `gst_rate_override` without `agent.cfo` + `financials.adjust` (G1–G7). Neither key → wall (E2/E17). **Neither a `dispatch_cfo_gst_lookup` nor a CEO shared-lookup entry point exists in `agents/ceo_hub.py` today** — both must be built, and Route B must not ship unless G1–G7 are demonstrated by test. |
| "publish this to my listing" / out-of-C3 | none | Declined and explained (recommend-only; V1 scope). |

**Optional CI attachment.** When the seller is discussing listing optimisation, CEO may read the tenant's `competitor_listing_insight` rows through a read-only CI repository function and attach them to the CMO request. This is a **data read, not a CI invocation** — no `agent_run` for CI, no CI unit — and it requires **both** `agent.ci` and a passing CI entitlement check (evaluated, not consumed). CEO never attaches CI data to a request whose subject is not listing optimisation (E4 of the CMO spec). Missing CI data never blocks the CMO call.

**Composition rules (extend §6.5).**
1. Title options, descriptions, bullets, keywords and hashtags are shown **verbatim** from CMO's structured report — CEO may format but must not reword, merge, re-rank or "improve" them. Rewriting approved copy would be an LLM silently changing seller-facing output with provenance attached to the original.
2. Catalog answers keep each attribute's basis label (`SELLER_PROVIDED | IMAGE_OBSERVED | ESTIMATED | SOURCE_DERIVED | UNKNOWN`) in the composed text; an `ESTIMATED` or `UNKNOWN` attribute is never stated as fact.
3. Trend reports keep **all seven sections**, their source links, publication/retrieval dates, corroboration labels and the evidence-and-limitations section. CEO must not convert "attracting attention" into "trending" or "in demand", must not drop the *"CMO's interpretation — not a verified market fact"* label, must not promote a **reported tactic** to advice (tactics with a policy-risk flag stay in the caution group with no suggested action), and must not restate numbers the report deliberately omits (CMO AC33).
4. GST answers carry the rate, source, retrieval date, uncertainty note and L5 disclaimer **copied from the `gst_lookup_result`**, never "verified" unless the record's status is `SELLER_VERIFIED`.
5. Workflow state (current `image_asset_id`, `cmo_generation` ids, approval ids) is carried by `agent_run.output_refs` and the CMO tables, **not** by LLM context or the rolling summary — the summary may mention that titles were generated and which option was approved, but the ids come from the records (resolves the risk in D2).

**Entitlement note.** A three-turn workflow (titles → approval/copy → GST) consumes three CEO turn units (D5) in addition to the CMO artefact units and the CFO/GST meters. This is intended and must be visible to the seller in the usage view; whether it is acceptable at the CEO's free cap is a pricing question (Q6).

---

## 7. AI requirements

| Brain | Role in orchestration |
|---|---|
| **Brain 1** | Every number CEO ever cites. No LLM. |
| **Brain 2** | Consumed only through a named agent's own interface; CEO never calls it directly (spec unwritten — see agent specs' own Q on this). |
| **Brain 3 (CEO's LLM)** | Exactly two jobs per turn: **(1)** classify intent once (§6.3), **(2)** compose the final answer once (§6.5). Nothing else. It never performs arithmetic on a number in its context, never restates a figure with a rounding "improvement," and never decides which fee, rate, or margin applies. |

**The single-shot rule is the whole point of C3.** A model that reasons step-by-step over multiple tool calls is slower, more expensive, and — per the planning document's own "bad architecture" diagram — the exact failure mode this design exists to avoid.

---

## 8. Authorization and security

1. Every action CEO routes to, conversational or not, enters the target's own `auth.md` §7.1 six-step chain in full. CEO adds no bypass and no shortcut (C8).
2. Conversational access to any agent requires `agent.ceo` **plus** that agent's key (and any shared-service key the action needs, e.g. `research.niche_run`) — exactly as each agent spec's §6.8/§8 already states.
3. CEO's own free-tier cap (30/month, provisional) is checked before classification runs at all — an exhausted CEO cap denies the turn outright, before any sub-agent is even considered.
4. `investigation` and `agent_run` rows are tenant-scoped; RLS is the final boundary. A cross-tenant investigation id returns `404`.
5. `investigation_message.content` is seller/member-authored or CEO-composed text — it is not raw marketplace expression and is not subject to CI/PI's review-text transience rules, but it is still tenant-private data under the same RLS model as everything else.

---

## 9. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Intent is ambiguous between two agents | CEO asks a clarifying question; no `agent_run` for either candidate is created until answered (D4) |
| E2 | Classified agent action is denied by permission or entitlement | Explained plainly to the user; `agent_run.status = DENIED` logged with the failing check named (C8, E2 mirrors `cfo-agent.md`'s preview precedent) |
| E3 | A Brain 1 bundle fetch partially fails | Synthesis proceeds with what succeeded; the gap is named in the answer, never silently omitted |
| E4 | Follow-up question needs a different agent than the last turn | Treated as a fresh classification; no memory of "last agent used" biases the new decision |
| E5 | User starts a new investigation mid-topic | Old investigation is simply left `ACTIVE` and unarchived unless the user archives it; no data is lost, no forced closure |
| E6 | Summary regeneration coincides with a new message arriving | Regeneration completes before the new message's classification reads the summary — never a half-written summary in context |
| E7 | CEO's own cap exhausted | Denied before classification; the sub-agent's own entitlement is never even checked (§8 rule 3) |
| E8 | A direct-path action is invoked while the member also has an open investigation | Both are logged as separate `agent_run` rows; a direct action never appears inside `investigation_message` unless the user is also discussing it conversationally |
| E9 | An agent's structured report cannot be summarised in one LLM call (very large PI report) | CEO composes a summary-of-the-report plus a pointer to the full structured data, never a truncated silent drop |
| E10 | Inbound WhatsApp message, no open investigation exists | One `investigation` row is created and the message appended before the reply is otherwise processed (§6.7, resolved via `whatsapp-integration.md` C7) |
| E11 | Inbound WhatsApp message, an investigation is already open | Routes into that investigation's pipeline (§6.7) — no new row created |
| E12 | **(CP0)** Seller attaches an image but names no marketplace | CEO asks which of Amazon / Flipkart / Meesho (D4/OP1); no CMO run, no unit, until answered |
| E13 | **(CP0)** Seller asks for description/bullets/keywords with no approved title and no supplied title | CEO asks for a title or offers a title set first; no copy generated (`slim-cmo-agent.md` E9) |
| E14 | **(CP0)** Trend request needing a niche, none stated or on record | CEO asks for the niche; a `BROAD`-only report may be offered instead |
| E15 | **(CP0)** Composed answer would state an `ESTIMATED`/`UNKNOWN` attribute, or "trending", as fact | Composition must preserve the label / the attention-vs-demand wording (§6.9 rules 2–3); a violating draft fails the narration check rather than being shipped |
| E16 | **(CP0)** Seller's message is both a selection and a copy request ("go with option 2 and write the description") | Two actions are needed; CEO performs the selection (`cmo.approve_title`) this turn and offers the copy next turn — it never chains two delegations (C4). A UI button may call both direct paths in sequence instead |
| E17 | **(CP0)** GST question when the member lacks `service.gst_lookup` (with or without `agent.cfo`) | Explained as a permission wall; `agent_run.status = DENIED` (E2); no fallback to a CMO or model-knowledge answer. A member with `service.gst_lookup` but no `agent.cfo` takes Route B, not a wall |
| E18 | **(Round 3)** Trend request, no confirmed niche terms | CEO offers `cmo.suggest_niche_terms` output (or asks the seller to type a niche); nothing is sent to research until terms are confirmed. Broader sections may run |
| E19 | **(Round 3)** Seller asks CEO to "research my sales report" or to include customer/financial data in a trend search | Refused: only confirmed niche terms leave Metrion (CMO C15, AC30) |
| E20 | **(Round 3)** Marketplace constraint missing/stale for one of the requested marketplaces | CEO reports which marketplace is blocked and why; the other marketplaces' artefacts are delivered and billed per the CMO spec (E5/E16) |
| E21 | **(Round 3)** Required trend configuration missing | CEO relays `CONFIG_MISSING` in plain terms (operator action needed); no unit, no provider call |

---

## 10. Production-validation blockers

| # | Item | Blocks |
|---|---|---|
| V1 | Intent-classification accuracy on the target local model (A1) | §6.3's single-shot guarantee — a wrong classification wastes a turn, not correctness, but affects UX badly at low-VRAM model quality |
| V2 | Named parallel-fetch bundle catalog (D3) is not yet enumerated beyond one example | §6.4's Brain 1 read path |
| V3 | Summary compression quality at scale (A2) | §6.6 |
| V4 | Brain 2 spec does not exist, referenced only through agent interfaces | §7 |

---

## 11. Acceptance criteria

| # | Criterion |
|---|---|
| AC1 | No agent-to-agent call exists anywhere in the system; every cross-agent request passes through CEO. |
| AC2 | A direct execution path never creates a CEO-attributed `agent_run` row and never invokes an LLM. |
| AC3 | A conversational turn performs exactly one classification call and exactly one synthesis call — never more. |
| AC4 | No sequential LLM→tool→LLM chain exists in any code path. |
| AC5 | CEO delegates to at most one named agent action per turn. |
| AC6 | Every number in a CEO answer traces to an `engine_result_ref`, an `estimate_ref`, or a field on a named agent's structured report. |
| AC7 | A target action's six-step authorization chain always runs, regardless of how CEO arrived at selecting it. |
| AC8 | A new investigation is never created without an explicit user action — a "New Investigation" click, or the one named WhatsApp first-contact exception (§6.7). |
| AC9 | LLM context for any turn never contains the full raw message history — only the summary plus messages since `summary_covers_through`. |
| AC10 | Every agent invocation, direct or conversational, produces exactly one `agent_run` row. |
| AC11 | A denied run is logged with the same fields as a completed one. |
| AC12 | **(CP0)** Title options, copy, hashtags and trend sources in a composed answer are verbatim from the agent's structured report; CEO never rewrites, re-ranks or merges them. |
| AC13 | **(CP0)** No image bytes appear in any `investigation_message`, summary, or CEO LLM prompt — only an opaque `image_asset_id`. |
| AC14 | **(CP0)** CEO never selects a title option on the seller's behalf; every `cmo.approve_title` call carries an option id that originated from the seller. |
| AC15 | **(CP0)** A product GST question is handled by Route A (`cfo.gst_lookup`) or Route B (shared lookup) according to the member's permissions, and never by CMO; the composed answer shows source, retrieval date and uncertainty, and never says "verified" unless the lookup record is `SELLER_VERIFIED`. Route B satisfies G1–G7. |
| AC16 | **(CP0)** A multi-marketplace CMO request is exactly one delegated action (`cmo.generate_title_sets`), not one delegation per marketplace. |
| AC17 | **(CP0)** Rupee amounts stated by the seller are converted to integer paise by deterministic code, not by the LLM. |
| AC18 | **(Round 3)** CEO never forwards an unconfirmed niche term, raw report, customer datum or financial figure to a research provider; niche confirmation, suggestion and report are separate single-action turns. |
| AC19 | **(Round 3)** A composed trend answer preserves all seven sections, source dates, corroboration labels, the interpretation label and the policy-risk caution grouping. |
| AC20 | **(Round 3)** A composed copy-pack answer is verbatim from the structured `LISTING_COPY` report, shown per marketplace, with no cross-marketplace blending. |

---

## 12. Test scenarios

| # | Scenario | Expected |
|---|---|---|
| T1 | Dashboard button triggers `cfo.reconcile` | No CEO involvement; `agent_run.trigger_type = DIRECT` (AC2) |
| T2 | "Why did my margin drop?" | One classification, parallel Brain 1 reads, one synthesis call (AC3) |
| T3 | "Find profitable products under ₹500" | Classified as PI delegation; exactly one `pi.discover`-equivalent invocation (AC5) |
| T4 | Ambiguous question spanning PI and CI | CEO asks for clarification; no agent invoked yet (E1) |
| T5 | Member lacks `agent.cfo`, asks a CFO-shaped question | CEO explains the wall; `agent_run.status = DENIED` (E2, AC7) |
| T6 | CEO free-tier cap at 30/30 | Turn denied before classification; sub-agent never checked (E7) |
| T7 | 15-message investigation, then a new question | Context is summary + recent messages only, not all 15 (AC9) |
| T8 | User clicks "New Investigation" | New row created; old one untouched (AC8, E5) |
| T9 | Attempt to construct a PI→CI call in code | Does not exist; no such path (AC1) |
| T10 | Inspect any CEO code path for multi-turn tool use | None found (AC4) |
| T11 | Direct path and conversational request both occur for the same tenant | Two separate `agent_run` rows, correctly attributed (E8) |
| T12 | Cross-tenant investigation id requested | `404` |
| T13 | WhatsApp confirmation with an investigation already open for the tenant | Routed into it via §6.3–6.5, same as a chat message (E11) |
| T13b | Inbound WhatsApp message, no `ACTIVE` investigation exists for the tenant | Exactly one `investigation` row created, `created_by = bound_by`; message appended; then routed via §6.3–6.5 (AC8, E10) |
| T14 | Profit question matching no named bundle | Falls back to one `compute_metric` call; still one classification, one synthesis (D3) |
| T15 | **(CP0)** Image + "titles for Amazon, Flipkart and Meesho" | One classification, one `cmo.generate_title_sets` call with 3 marketplaces, one synthesis; image bytes absent from every prompt (AC13, AC16) |
| T16 | **(CP0)** Seller replies "option 3 for Flipkart" | One `cmo.approve_title` call with the seller's option id; no generation, 0 CMO units (AC14) |
| T17 | **(CP0)** "Go with option 2 and write the description" | Selection performed, copy offered next turn; no two-action chain (E16) |
| T18 | **(CP0)** "What GST applies to this product?" with a CMO-analysed product in the investigation, member holds `agent.cfo` | Route A: delegated to `cfo.gst_lookup` with product name, category and basis labels; CMO not invoked; answer carries source/date/disclaimer, not "verified" (AC15) |
| T18b | **(CP0)** Same, member holds `service.gst_lookup` but not `agent.cfo` | Route B: `PROVISIONAL` shared-lookup result; only the shared GST meter + CEO turn unit consumed; attempt to apply it to a calculation refused (AC15, G1–G7) |
| T19 | **(CP0)** Same GST question from a member without `service.gst_lookup` | `403`, wall explained; `agent_run.status = DENIED`; no model-knowledge answer (E17) |
| T20 | **(CP0)** Seller says "target price 499 rupees" | Parsed deterministically to 49900 paise, echoed for confirmation, never in generated copy (AC17) |
| T21 | **(CP0)** Composition of a catalog answer containing an `ESTIMATED` weight | Label and range preserved; draft that states a point weight fails the narration check (E15) |
| T22 | **(CP0)** Image attached, no marketplace named | CEO asks; no CMO run (E12) |
| T23 | **(Round 3)** "What's trending?" with no confirmed niche, catalog available | Turn 1: suggestions shown; no provider call. Turn 2 (seller confirms): `cmo.confirm_niche_terms`. Turn 3: `cmo.market_trends` with the confirmed terms and the displayed outbound queries (AC18) |
| T24 | **(Round 3)** Composed trend answer where a tactic has a policy-risk flag | Caution group, no suggested action, "check the marketplace's current seller policy" line preserved (AC19) |
| T25 | **(Round 3)** Seller asks to include the sales report in the research | Refused (E19, AC18) |
| T26 | **(Round 3)** Three marketplaces, one with a missing constraint | Two packs delivered, one blocked with reason; units billed for two (E20) |
| T27 | **(Round 3)** Composed copy pack answer | Verbatim per marketplace; no blending (AC20) |

---

## 13. Explicit open questions

| # | Question | Impact |
|---|---|---|
| Q1 | **Named bundle catalog (D3)** has a four-bundle starter set (§6.4) but is not claimed complete. What other common questions deserve their own bundle rather than falling back to a single-metric read? | §6.4, V2 |
| Q2 | **Investigation visibility** (D1) defaults to tenant-wide. Is a private-investigation mode wanted later, and if so, who can grant it? | Future scope |
| Q3 | **Intent-classification model and prompt strategy** on local Ollama models — accuracy at the hardware ceiling is unmeasured (A1, V1). | §6.3 |
| Q4 | **CEO's own metering unit** (D5) — one run per turn regardless of sub-agent use — is a recommendation, not yet confirmed by the entitlement spec. | Entitlement spec |
| Q5 | **Summary regeneration model** — same model as classification/synthesis, or a cheaper one, given it is a bounded, well-defined task? | §6.6, cost |
| Q6 | **(CP0) Cost of a multi-turn CMO workflow at the free caps.** CEO 30/month and CMO 10/month (both provisional) interact: titles (1 turn) + approve/copy (2 turns) + GST (1 turn) = 4 CEO turns for one product on one marketplace. Is that acceptable, or should a CMO workflow's approval turn be exempt from CEO's per-turn unit? | Pricing / entitlement spec |
| Q7 | ~~CMO-only sellers and GST~~ | **Resolved, round 2 — Route B (C11), conditional on G1–G7.** |
| Q8 | **(CP0) Upload surface for the image.** Is the image upload a dedicated CEO-chat attachment endpoint or the existing file-upload surface? `files.upload` is proposed as the gate; the spec set does not say how a chat attachment is authorised relative to report uploads. | `auth.md` §5.2; frontend |
| Q9 | **(CP0) Workflow state in the investigation summary** (`slim-cmo-agent.md` Q12): is ids-via-`output_refs` sufficient, or does D2's summary need a structured "current CMO workflow" field? | §6.6 |
| Q10 | **(Round 3) Niche-confirmation UX in chat vs workspace.** Three single-action turns (suggest → confirm → report) is correct under C4 but slow in conversation. Is a UI-only confirmation panel (direct paths) acceptable as the primary route, with chat falling back to the three-turn flow? | §6.9 |
| Q11 | **(Round 3) Who may confirm niche terms** — any member holding `agent.cmo`, or OWNER only (the terms are derived from tenant catalog data)? | `auth.md` grid |

### Resolved — do not re-flag

| # | Item | Resolution |
|---|---|---|
| R1 | Orchestration topology (Q26) | **Strict star, confirmed.** No agent-to-agent edges; Brain 1/GST Lookup are shared services, not delegation (C1). |
| R2 | Fast-path/AI-path router mechanism (Q68) | **Structural, not runtime-classified.** The entry point (direct trigger vs chat) decides the path at design time (C2). |
| R3 | AI-path control flow (Q67) | **Single-shot: classify once, fetch in parallel or delegate once, synthesize once.** Never a multi-turn LLM tool-calling loop (C3, C4). |
| R4 | Conversation/memory model (Q27) | **Investigations** are the top-level unit; recent messages plus a compressed rolling summary feed the LLM context within one (C5). |
| R5 | Investigation creation trigger (Q28) | **Explicit user action only.** No automatic topic-change detection (C6). |
| R6 | Audit artifact for agent invocations | **`agent_run`**, defined here, resolving the gap each agent spec left open (C7). |
| R7 | WhatsApp turn with no open investigation (was Q6) | **Resolved** — the first inbound message on a verified destination with no `ACTIVE` investigation implicitly opens exactly one, the sole named exception to C6 (§6.7, `whatsapp-integration.md` C7). |
