# Agent needs, shared findings and CEO business Q&A

Status: specified 2026-10-10 (architect, owner-directed). Not built. Authority for (1) how one agent's request for information is served, (2) the shared findings tier, (3) how the CEO answers business questions from stored knowledge. Read with `ceo-agent-orchestration.md` (C1, C3, C4, AC1, AC4, AC22, AC26, §6.11-§6.15, §6.22, §6.35-§6.40, new §6.41), `agent-memory.md` (§3, §4, §10 Q1) and `slim-cmo-agent.md` (C4, C7, §6.9). Money rules: `deterministic-engine.md` and `CLAUDE.md`; nothing here restates a formula.

## 1. Confirmed decisions (owner, 2026-10-10)

| # | Decision |
|---|---|
| N-C1 | **Agents asking each other for information is CEO-brokered.** An agent never calls another agent (C1 and AC1 stand unchanged). A request is a typed **need** from a **closed needs catalog** (code). The CEO fulfils it by running the providing agent's registered action through the one dispatch choke point (§6.15) and shows the result with its source and ref. |
| N-C2 | **No LLM chooses a provider or fills a slot.** Provider, slot sources and what may be passed back are in the catalog. A model may only say, by a closed enum value, that the seller asked for an add-on (e.g. "also give the GST rate"); code validates it against the catalog. |
| N-C3 | **Shared findings tier.** Agents may record their own findings in shared memory as a tier **separate** from the seller-stated profile. Append-only, per tenant, FORCE RLS. Each entry has a trust label (`SELLER_STATED`, `ENGINE_VERIFIED`, `AGENT_REPORTED` = not verified), a source ref, the writing agent and a short text; any number carries an `engine_result_ref` or `estimate_ref`, never a free number. The seller can see, correct and forget entries. Agent-reported entries never enter "what the seller told us" and are never presented as verified. **This reverses the V1 "no" of `agent-memory.md` Q1** (see §6.1). |
| N-C4 | **CEO business Q&A** answers business questions **only** from stored engine results (Business State), shared memory (profile and findings, with trust labels) and the seller's facts, through a **fixed list of question types**. No model-written SQL. No vector search in this slice. Anything not stored: "not stored yet" plus what to upload or which agent to attach. |

## 2. Design decisions requiring review

| # | Decision | Recommendation | Why |
|---|---|---|---|
| D1 | **Findings live in a new table `shared_finding`, not in `agent_memory`.** The "shared memory" then has two tiers: tier 1 `agent_memory` `scope=SHARED` (seller-stated profile, unchanged) and tier 2 `shared_finding`. | Separate table | Leaves the existing `agent_memory_shared_gate` and `memory.profile()` untouched, so no code path that reads "what the seller told us" can ever return agent-reported text. Loosening that CHECK would put the seller-stated guarantee (agent-memory AC1, AC6) one bad query away from failing. |
| D2 | **Finding text is digit-free; numbers live only in `figure_refs`** and are rendered by code through the provenance gate. | Adopt | "Any number carries a ref" becomes a database CHECK instead of a convention. A finding's text is built by code from a template; no model writes it. |
| D3 | **V1 catalog has no same-turn dependency.** Needs run in `PARALLEL` mode (the add-on's slots come from the seller's request or stored data, not from another leg's output) or as an `OFFER` (executed next turn if the seller accepts). `AFTER_RESULT` (provider slots taken from the requester's result, then continue or re-run) is **specified (§5.5) but not built or enabled** in V1. | Ship `PARALLEL` + `OFFER` | Keeps C3, C4 and AC4 literally true. No V1 example needs `AFTER_RESULT`. Building it needs a catalog entry that uses it and an AC4 amendment signed off. The owner may override (about 6 extra hours in S2). |
| D4 | **A provider's result is shown to the seller beside the requester's output. It is not injected into the requester's input or output.** In particular a GST rate is never put inside CMO-written copy. | Adopt | `slim-cmo-agent.md` C7 and §6.9 forbid CMO from stating a GST rate; a number inside specialist free text would break R9. |
| D5 | **Findings are written at the dispatch choke point (V1)**, by a per-agent adapter owned by that agent's package, for the four specialists. Direct (dashboard) runs do not write findings in V1. | Adopt; direct-run writes are a follow-up | One tested path; the CEO already holds the run, finding and tenant context. |
| D6 | **Findings are shown to a member only if they could see that agent's output directly** (agent permission and entitlement), per C17. | Adopt | A finding from CFO engine results must not leak to a member without `agent.cfo` or on a plan without the CFO. |

## 3. Assumptions

1. `dispatch(turn, key, slots, ...)`, `_preflight`, `EvidenceCollector`, `read_entry` and the event log (`log.emit`) are the integration points; the broker adds no second path to a specialist (AC22).
2. `gst_route_key(entitled_registry_keys)` already decides Route A (`cfo.gst_lookup`) or Route B (`service.gst_lookup`) by permission and entitlement, in code (C11).
3. The GST lookup result is a stored `gst_lookup_result` row (`PROVISIONAL`, with `source_url`, `retrieved_at`, `ambiguity_note`, `alternatives`, disclaimer), copied never generated (`gst_lookup.py`). Its figure ref kind is whatever `evidence.py` already uses for it; S1 verifies and reuses it, and adds no new ref kind.
4. `cmo_generation` persists the product text the seller supplied (`seller_title` or product details). S1 verifies; if not, the "this product" reference falls back to a decision card (§8.3).
5. Latest Alembic head at writing is `20261010_0011`; new migrations take the next revisions.
6. Limits are configuration with no default (house convention, §6.12 rule 5; Q32 precedent). Example values appear only in `.env.example`.

## 4. Goals and non-goals

**Goals.** (1) A fixed, auditable way for one agent's information need to be served by another, still a strict star. (2) A shared findings ledger the seller controls, with the trust of each entry on its face. (3) A CEO that answers "what is my profit / what leaks / what did the agents find" strictly from stored, cited data, and says plainly when something is not stored. (4) The Hub shows who asked whom for what.

**Non-goals.** Any agent-to-agent call. A model choosing a provider or a slot. Same-turn data dependencies (D3). Vector search, RAG or embeddings over findings (the pgvector option in `agent-memory.md` §2 stays V2). Model-written SQL. Writing to a marketplace or the seller's books (C21). Findings from direct (dashboard) runs (D5). Writing findings from seller documents or attachments. Proactive situations (V1-later, §6.17).

## 5. Core rules and data model, by part

Template mapping: §5 (needs broker), §6 (shared findings) and §7 (business Q&A) carry the **Data model** and **Core rules** sections of the house template for their part (the `ceo_need` table is in §9.1); §8 is **AI requirements**, §9 **Authorization and security**, §10 **Edge cases**, §11 **Production-validation blockers**, §12 **Acceptance criteria**, §14 **Test scenarios**, §15 **Explicit open questions**; §13 is frontend visibility and Appendix A the build plan.

### Part A: the needs broker

### 5.1 Vocabulary

- **Need**: a typed request `{need_key, requester, context}` for information another agent's registered action can supply.
- **Requester**: `CMO | PI | CI | CEO` (CFO may be added by a spec edit).
- **Provider**: a registry action, a virtual route (`gst_lookup`, resolved by `gst_route_key`) or a registered playbook id. Never a free string.
- **Mode**: `PARALLEL` (runs in the turn's fan-out because its slots do not depend on any leg's output), `OFFER` (rendered as a chip or confirm card; runs next turn on the seller's acceptance, as a `UI_ACTION`), `AFTER_RESULT` (§5.5, not enabled).

### 5.2 Needs catalog v1 (code: `ceo/needs.py`; reviewed with each owning agent's spec)

```
NeedSpec {
  need_key; requester; mode; provider_kind (ACTION | VIRTUAL_ROUTE | PLAYBOOK); provider_key
  raised_by        -- REQUEST_MODIFIER (closed enum value on the classified/ruled request) | STEP_RESULT (typed adapter on the requester action's result)
  slot_sources     -- per provider slot: SELLER_TEXT | SELLER_SELECTED_REF | STORED_INPUT | RESOLVED_REF (code lookup, tenant-scoped, existence-checked)
                      -- FORBIDDEN: any slot sourced from specialist free text or from another leg's output
  pass_back        -- allowlist of provider result fields and the ref kind each must carry; everything else is dropped
  reusable         -- may an earlier result in this investigation be reused (§5.7)
  metered          -- derived from the provider's effect; metered + not asked for => OFFER only
  ui_label         -- template for the Hub step, e.g. "The CEO asked {provider} for the GST rate"
}
```

| need_key | Requester | Mode | Provider (exact keys) | Slots and where they come from | Passed back (and the ref each must carry) |
|---|---|---|---|---|---|
| `GST_RATE_FOR_PRODUCT` | CMO (also usable by CEO directly) | PARALLEL | virtual route `gst_lookup` (`plans.GST_KEY`): `cfo.gst_lookup` (Route A) if `gst_route_key` returns it, else `service.gst_lookup` (Route B), else the permission wall (`GST_WALL_TEXT`) | `product_title` (`GstSlots`, 1-200 chars) = the seller's own product text: the `seller_title` of the CMO request, or the stored product text of the referenced `cmo_generation` (`SELLER_TEXT` / `RESOLVED_REF`). Over 200 chars: asked about, never truncated (`MAX_PRODUCT_TEXT_CHARS`). | `result` copied from the stored `gst_lookup_result`: rate, `source_url`, `retrieved_at`, status `PROVISIONAL`, `ambiguity_note`, `alternatives`, L5 disclaimer, and `gstLookupResultId` as the ref. A `noMatch` is passed back as a named gap. Never labelled verified unless the record is `SELLER_VERIFIED`. G1-G7 of `slim-cmo-agent.md` §6.9 apply unchanged. |
| `LANDED_COST_FOR_IDEA` | PI | OFFER (PARALLEL when the seller's request already names the idea, e.g. "is #3 worth stocking?") | playbook `NEW_PRODUCT_DECISION`: `cfo.landed_cost`, `cfo.supplier_ranking`, `cfo.batch_size` | The idea name = a seller-selected reference (`#n`) expanded to the PI candidate's name and offered to the SKU parser (6.36); quantity and window from the guided session; `supplier.quote` and `batch.budget` are STORED_INPUT. Missing stored inputs yield the engine's named data request and the 6.36/6.37 collection flow. Nothing is taken from PI's scores or estimates. | The three legs' figures with their `engine_result_ref`s (the existing evidence path). PI's feasibility estimate is **not** relayed (6.36 deferral stands; see Q9). |
| `MARGIN_AT_PRICE` | CI | PARALLEL when the seller named the competitor or price; else OFFER | playbook `COMPETITOR_PRICE_IMPACT`: `ci.request_price_scenario`, `cfo.pricing` | `competitor_url_id` is a tracked competitor of this tenant (`SELLER_SELECTED_REF` / `RESOLVED_REF`); CI's last captured price is **offered as one dated, "not verified" option** the seller must pick (6.38), never filled in; SKU, marketplace, category, fee type, basis, costs per 6.33 / 6.34. | `cfo.pricing` figures (`engine_result_ref`) and CI's observation with its snapshot ref. CI computes no margin (CI C26). |
| `CEO_READ` | CEO | OFFER | A closed topic map to **READ-effect** registry keys only: `HEALTH` -> `cfo.financial_health`; `BRIEFING` -> `cfo.strategic_briefing`; `PI_REPORT` -> `pi.report` (run id by `RESOLVED_REF`); `TREND_PREVIEW` -> `cmo.market_trends_preview` | Per the topic's own `ActionPlan` slots (period/marketplace via the existing resolvers) | The action's normal evidence. COMPUTE_PERSIST and GENERATE_METERED actions are never reachable through this need; they remain ordinary plan actions. |

A need whose requester and provider resolve to the same agent is refused at catalog load (a startup error), which with §5.4 rule 1 makes cycles impossible by construction.

**Adding an entry** is a code change plus an edit to this table in the same change, reviewed with the provider's spec. There is no runtime, tenant or model path that adds one.

### 5.3 How a need is raised

- `REQUEST_MODIFIER`: the classifier (or the `intent_router` rules, which run first) may emit `addons: [<need_key>...]`, a closed enum filtered to needs whose requester equals the chosen action's agent and which the member could run. Example: "give me the GST % along with the description" -> `ACTION cmo.generate_description` + `addons=[GST_RATE_FOR_PRODUCT]`. The model contributes only the enum value; it supplies no product text, slot, provider or route.
- `STEP_RESULT`: a typed adapter `needs_from_result(action_key, payload) -> list[NeedOffer]` registered next to the requester's action. It reads structured fields only, never prose. In V1 it can only produce `OFFER`s (e.g. `pi.report` offers `LANDED_COST_FOR_IDEA` per listed idea as the follow-up chip "Is #n worth stocking?", which already exists).
- A rule or the classifier choosing a need that is not in the catalog for that requester is `CLARIFY`, never executed (AC22 pattern).

### 5.4 Loops, depth, limits, idempotency (all enforced in code)

1. **Depth 1.** Need legs are dispatched in a `NEED` context in which `needs_from_result` and `addons` are not consulted. A provider's result can never raise a need.
2. **No cycles, no duplicates.** At most one need per `(need_key, slot_digest)` per turn; requester agent differs from provider agent (catalog load).
3. **Max needs per turn** = `CEO_NEEDS_MAX_PER_TURN`, **no default**; unset or invalid => no need runs, and the answer names the gap "the CEO's limits for follow-up lookups are not configured" (the primary action still runs; this is the only place a missing bound degrades rather than refuses, because the primary request is independent of the add-on). Parallel needs also count toward `CEO_PLAYBOOK_MAX_LEGS`.
4. **Timeout** per need leg = the existing `CEO_LEG_TIMEOUT_SECONDS` (`runtime.leg_timeout_seconds`); a late leg is a named gap (`TIMED_OUT`) and finishes on its own as today (L9). A timeout never yields a zero or a guessed value.
5. **Idempotency.** Each need leg carries the key `ceo-need-<answering message id>-<need_key>-<n>`; a retry of the same turn or card returns the stored result and meters nothing twice (same pattern as `ceo-<card or message id>`).
6. **Each provider is checked exactly as a direct call**, in this order, by the unchanged `dispatch` (§6.15 R2): `agent.ceo` + the provider agent's key + the action's `required_permissions` (e.g. `service.gst_lookup`), attachment (R13), entitlement resolver (R6), then the route's own gate. The requester's rights grant nothing to the provider. Nothing in the broker evaluates a permission itself.
7. **Metering.** One CEO turn unit for the turn (no extra CEO unit per need); each provider's own meters apply and are stated to the seller (Route A meters CFO and the shared GST cap, Route B the shared GST cap only, G2). Every metered leg in the turn (requester plus parallel needs) is admission-checked **before any leg runs**, all-or-nothing (6.12 rule 3), so a half-billed fan-out cannot occur. If the add-on alone would be refused, the primary action still runs and the add-on is dropped and named; if the primary is refused, the add-on does not run.
8. **Provider denied, detached or not entitled.** The need ends `DENIED`, `NOT_ATTACHED`, `NOT_ENTITLED` or `UNAVAILABLE` (the existing leg statuses), logged as a DENIED child `agent_run` with the failing key named (AC11). The answer still delivers the requester's own output and a plain line: for example "I could not get the GST rate: the CFO is turned off for this conversation (turn it on) / your plan does not include it / you do not have access." The CEO never attaches an agent silently (C22), never substitutes a model-knowledge value and never shows a zero. CFO-class `NOT_ENTITLED` offers `cfo.preview` exactly as C17. Route B needs no attached agent: `gst_route_key` falls to B before a gap is reported.

### 5.5 `AFTER_RESULT` mode (specified, not built in V1; D3)

For a future entry whose provider slots come from the requester's structured result: the broker runs the requester, builds the need from a typed adapter, runs the provider through the same choke point, then either **continues** (the result is added to the answer evidence) or **re-runs the requester once** with a slot filled by code from the provider's stored result (only `RESOLVED_REF` / `STORED_INPUT` slots; the value is copied by code, never retyped, and the re-run is idempotent on its own key). Depth stays 1; the re-run cannot raise a need. Enabling it requires (a) a catalog entry that needs it, (b) an AC4 amendment in `ceo-agent-orchestration.md` naming that entry, (c) owner sign-off.

### 5.6 Provenance and R9

1. A need result is ordinary evidence: every `Figure` passes `provenance.gate_figures` for this tenant before the composer or the seller sees it (R3); an unresolvable figure is dropped and named. `engine_result_ref` and `estimate_ref` are never interchangeable.
2. A GST rate is shown as a labelled provisional **fact** rendered by code from the stored row (rate, source, retrieval date, "provisional lookup, not a ruling"). It is never a `Figure` in the VERIFIED register and the composer receives it only as placeholders (R4); it is never applied to a calculation (G4).
3. **R9 stands.** Specialist free text (CMO copy, PI idea names, CI titles, GST page extracts) is never evidence, never a figure and never a need slot. Slot text comes only from the seller's own words, a seller-selected reference or a stored input (§5.2 `slot_sources`). A PI idea name reaches a slot only because the seller selected `#n`, and only after the same parser/length validation as typed text; it is shown quoted and labelled "from public web sources, not verified".
4. The requester's output and the provider's result are presented as **separate blocks** with their own labels (D4). The CMO artefact keeps its 6.35 label; the GST block keeps its source line.
5. **Nothing a provider returns is fed to a model as an instruction.** Only structured, allowlisted fields pass back.

### 5.7 Multi-turn behaviour

- **Reuse.** A need with `reusable=true` (`GST_RATE_FOR_PRODUCT` only in V1) is served from an earlier finding in the **same investigation** when: same `need_key`, same canonical `slot_digest` (normalised product text), the referenced `gst_lookup_result` still resolves for this tenant, and its age is within `CEO_NEED_REUSE_MAX_AGE_HOURS` (**no default**; unset means no reuse and the provider is called again). The ref is re-resolved through the provenance gate, shown with its `as_of` and "looked up earlier in this conversation", recorded as `status=REUSED` with `reused_from_need_id`; no provider call, no meter, no new `agent_run`.
- **Engine-backed needs are never reused across turns** (`LANDED_COST_FOR_IDEA`, `MARGIN_AT_PRICE`): stored inputs may have changed. Asking to see an earlier figure again re-resolves its ref (§6.14) and shows its `as_of`.
- **"This product".** In a follow-up such as "now give the GST % of this along with the description", "this" is resolved by code to the product of the investigation's latest CMO finding (via the finding's `cmo_generation` ref). Several candidates or none: an `AMBIGUOUS` decision card (6.32), never a guess.
- **Offers are context, not state.** An unaccepted `OFFER` is not stored as work to do; it exists as the chip/card on its message (like 6.32 cards).

## 6. Part B: the shared findings tier

### 6.1 Relation to the existing scopes

| Tier | Table / scope | Holds | Trust | Writers | Read by "what the seller told us"? |
|---|---|---|---|---|---|
| Private | `agent_memory` `scope=PRIVATE` | An agent's own notes | unchanged | unchanged | no |
| Shared tier 1 (profile) | `agent_memory` `scope=SHARED` | Seller-stated facts (name, niche, marketplaces, goal, tone, decision) | `SELLER_STATED` / `CONFIRMED_DECISION` | `memory.promote` only | **yes** (unchanged) |
| Shared tier 2 (findings) | **`shared_finding`** (new) | Agents' own findings | `ENGINE_VERIFIED` / `AGENT_REPORTED` / `SELLER_STATED` (a seller correction) | `shared_findings.record` only (the adapters of §6.4) | **never** |

`agent-memory.md` §3 and §4.1-4.2 are unchanged: the shared profile gate still refuses agent notes. Findings are a different table with their own gate, so nothing in tier 2 can enter tier 1.

### 6.2 Data model: `shared_finding` (append-only, FORCE RLS)

`id uuid pk, tenant_id uuid not null, agent_code text (CEO|CFO|PI|CMO|CI), kind text, subject text null (quoted label, <= 120, may contain digits, always rendered quoted and, for AGENT_REPORTED, labelled "from public web sources, not verified" where applicable), text text (<= 300), trust text, source_ref jsonb not null ({kind, id}: agent_run | investigation_finding | metric_result | pi_research_run | competitor_snapshot | cmo_generation | message), figure_refs jsonb not null default '[]' (array of {label, kind ENGINE_RESULT|ESTIMATE, id}, <= 3), dedupe_key text not null, supersedes_id uuid null, status text (ACTIVE|FORGOTTEN), created_by uuid null, created_at timestamptz`.

`kind` is a closed list, checked: `PRODUCT_IDEA` (PI), `COMPETITOR_CHANGE` (CI), `LEAK_FOUND`, `MARGIN_ISSUE`, `DATA_GAP` (CFO), `CONTENT_READY` (CMO), `SELLER_NOTE` (CEO, the seller's correction). Adding one is a migration plus a table edit here.

**Database gate (CHECK constraints plus one trigger; the app role has SELECT and INSERT only, no UPDATE or DELETE):**
1. `trust IN ('SELLER_STATED','ENGINE_VERIFIED','AGENT_REPORTED')`; `agent_code`, `kind`, `status` enum CHECKs; `char_length(text) BETWEEN 1 AND 300`; `jsonb_array_length(figure_refs) <= 3`.
2. **No free number:** `trust = 'SELLER_STATED' OR text !~ '[0-9]'`. Text of an agent or engine entry contains no digit; any number is in `figure_refs` and rendered at read time from the referenced result. (The writer also NFKC-normalises and rejects non-ASCII digit characters and a short list of number words, because a database CHECK cannot cover those; the DB test proves the ASCII case.)
3. `ENGINE_VERIFIED` requires `jsonb_array_length(figure_refs) >= 1` and every element `kind = 'ENGINE_RESULT'` (expressed with `jsonb_path_exists`; if the engine of the CHECK cannot express it, a `BEFORE INSERT` trigger does, with the same test).
4. `AGENT_REPORTED` may carry `ESTIMATE` refs, never presented as verified; with zero refs it is simply a statement with no number.
5. `source_ref IS NOT NULL` for every trust; `trust = 'SELLER_STATED'` requires `agent_code = 'CEO'`, `kind = 'SELLER_NOTE'`, `source_ref->>'kind' = 'message'` and `supersedes_id IS NOT NULL` (a seller entry is always a correction of an existing finding).
6. A `BEFORE INSERT` trigger verifies that every `ENGINE_RESULT` ref exists in `metric_result` **for the same tenant**; `ESTIMATE` refs and `source_ref` are resolved by the repository against their owning tables for the tenant (defence in depth; the read-time provenance gate re-resolves every ref, R3). A ref that no longer resolves at read time drops the figure and names the gap.
7. `supersedes_id` must reference a row of the same tenant (repository check, as for `agent_memory`). A unique index on `(tenant_id, dedupe_key)` where `supersedes_id IS NULL` makes a repeated finding a no-op.
8. RLS: `ENABLE` + `FORCE`, policy `tenant_id = current_setting('app.current_tenant_id', true)::uuid` for USING and WITH CHECK; `GRANT SELECT, INSERT TO metrion_app`.

"Active" = not superseded by a later row and `status = 'ACTIVE'`. **Correct** = a new `SELLER_STATED` row superseding the entry (the seller's words, <= 300, stored as text, quoted, never a Figure, never an engine input, same as agent-memory §1). **Forget** = a `FORGOTTEN` row superseding it. A forgotten `dedupe_key` is a tombstone: the same source is **never** re-recorded as a new finding.

### 6.3 Reading

- `GET /api/v1/ceo/shared-findings` (active, newest first, bounded), `POST .../{id}/correct`, `POST .../{id}/forget`. Permission `agent.ceo`; tenant from the session only; a foreign or unknown id is a plain 404.
- **Per-agent visibility (D6).** An entry written by agent X is returned only if the member holds X's agent key and X's entitlement passes (CFO-class: `agent.cfo` + CFO entitlement, C17). Hidden entries are counted ("3 findings from the CFO are not shown: no access"), never described, and never carry a figure. A detached agent's earlier findings stay visible as historical evidence (Q23 resolution).
- **Prompts.** Findings reach the classifier or composer only inside a separate delimited block "What the agents have found (labelled by trust; not seller-stated)", most recent N (`CEO_FINDINGS_CONTEXT_MAX`, no default; unset means the block is omitted), `subject` quoted as untrusted data (R9). Figures arrive as placeholders from the gated evidence table, never as text. Findings are never added to the `memory.context_line` "what the seller told us" line (agent-memory §4.4 unchanged).

### 6.4 Writers (V1: at the choke point; D5)

After a leg completes, `shared_findings.record(...)` is called with a **per-agent adapter** (`ceo/findings/{cfo,pi,cmo,ci}.py` in the owning agent's slice of code, reviewed with its spec) mapping the leg's structured payload to zero or more entries. The model never writes a finding; an agent cannot self-assert a trust label: `ENGINE_VERIFIED` is assigned by code only when every figure ref resolved to a `metric_result` of this tenant at write time.

| Agent | Kind | Trust | Written when | Text (template) | Numbers |
|---|---|---|---|---|---|
| PI | `PRODUCT_IDEA` | `AGENT_REPORTED` | a finished `pi.discover`/`pi.report` lists an idea (cap per run, config) | "Product Intelligence listed this idea in its latest research." `subject` = idea name | none (6.35 relays no scores or estimates) |
| CI | `COMPETITOR_CHANGE` | `AGENT_REPORTED` | a stored snapshot differs from the previous one for a tracked competitor | "A tracked competitor's captured listing price changed." `subject` = the seller's own competitor label | none (a captured price is an observation without an engine ref; the margin effect comes from `MARGIN_AT_PRICE`) |
| CFO | `LEAK_FOUND`, `MARGIN_ISSUE`, `DATA_GAP` | `ENGINE_VERIFIED` only if the amount has an `engine_result_ref` (S4 verifies what `leak_finding` and `metric_result` expose); else `AGENT_REPORTED` with no number | `cfo.reconcile`, `cfo.financial_health`, `cfo.strategic_briefing`, `cfo.pricing` legs completing | Fixed sentences, e.g. "Open Leak Shield finding of high severity for the period." | figure refs only |
| CMO | `CONTENT_READY` | `AGENT_REPORTED` | a title/hashtag/description/keywords/trend generation completes | "Listing content was written for this product." `subject` = the seller's own title | none; **the written content is never copied into a finding** |

Rules: a failed or unavailable leg writes nothing; volume is bounded per tenant per agent per day (`CEO_FINDINGS_MAX_PER_AGENT_PER_DAY`, no default; unset means findings are not written and the turn is unaffected); a write failure is logged and never blocks or alters the turn (best-effort, as memory notes).

### 6.5 Do-not-confuse rule

Presenting an `AGENT_REPORTED` finding as verified is a defect. The label text is fixed: `SELLER_STATED` = "You said", `ENGINE_VERIFIED` = "Calculated by the engine", `AGENT_REPORTED` = "Reported by <agent>, not verified".

### 6.6 S3 implementation notes (choices where the spec was silent or ambiguous)

1. **Names.** Migration `20261010_0012`; repository `repositories/shared_finding_repo.py`; service `ceo/findings.py` (`record`, `correct`, `forget`, `list_visible`, `visible_agents`). The per-agent S4 adapters should therefore live beside it under a different name (not a `ceo/findings/` package, which would clash with the module). Routes are `GET /api/v1/ceo/findings` and `POST /api/v1/ceo/findings/{id}/forget` (not `.../shared-findings`). `POST .../correct` is **not** exposed in S3: a `SELLER_STATED` row must cite a `message`, and the panel has no message to cite until S6b decides how a correction is recorded (open question Q13). The service function `correct` exists and is tested.
2. **Trust is derived, never passed.** `record` takes no trust label. Zero refs or any `ESTIMATE` ref gives `AGENT_REPORTED`; at least one ref, all `ENGINE_RESULT`, all resolving to a `metric_result` of the tenant now, gives `ENGINE_VERIFIED`; an `ENGINE_RESULT` that does not resolve is refused (not downgraded). The database trigger re-checks every `ENGINE_RESULT` ref whatever the trust.
3. **Forget and correct rows copy the original's `agent_code`, `kind`, `dedupe_key` (and, for forget, `trust`, `source_ref`, `figure_refs`); forget sets `text` to `(forgotten)`.** The tombstone is the original row (never deleted, `supersedes_id IS NULL`) plus the unique index, and a trigger that also refuses a new ACTIVE root row whose `dedupe_key` has a FORGOTTEN row. `record` returns `None` for a repeated or forgotten source. A correction is attributed to agent `CEO`, kind `SELLER_NOTE`, so it is visible to any member with `agent.ceo`; it repeats none of the original agent's text.
4. **Per-agent visibility (D6)** = the agent's status in `compute_capabilities` with every agent treated as attached: hidden when `NOT_PERMITTED` or `NOT_ENTITLED`, visible otherwise (a detached agent's history stays visible). Forget (and correct) of a finding from a hidden agent is a plain 404. Hidden counts are per agent with a fixed sentence.
5. **Figures.** The list returns each ref as `{label, kind, id, resolvable}` and no value: rendering a value goes through the provenance gate in S5/S6, not the ledger. `resolvable` is re-checked at read time (ENGINE_RESULT against `metric_result`; `ESTIMATE` is reported resolvable as it was verified at write time).
6. **Number words.** The writer rejects Unicode decimal digits (NFKC) and a short word list (not "one"). The database CHECK covers ASCII digits only.
7. **Limits.** The list is bounded by a `limit` query (default 100, max 200); no new configuration was added. The per-agent daily cap (`CEO_FINDINGS_MAX_PER_AGENT_PER_DAY`) belongs to the S4 writers, not the ledger.

## 7. Part C: CEO business Q&A

### 7.1 Principle

The CEO answers a business question only by reading a fixed set of Business State entries chosen from a fixed list of question types. It uses the existing `BUSINESS_STATE` route; `route_key` is a **question type id** that code expands to its entries (the route already allows "a small fixed set" of entries, §6.3). Selection is by the `intent_router` rules first, then the classifier choosing a value from the closed enum; a value outside the enum is `CLARIFY`. No SQL is generated, no vector or free-text search is run, no registry action is run for a question type (a missing result is *offered*, never computed in the answer turn, §6.13 rule 4, AC26).

### 7.2 Question-type catalog v1

| Type id | Example | Entries read | Gate (unchanged order: permission, attachment, entitlement) | If empty / not stored: "not stored yet" plus |
|---|---|---|---|---|
| `QT_PROFIT_BY_PERIOD` | "What was my profit in September?" | **new** `BS_PNL_RECENT` (+ `BS_HEALTH_BANDS`) | `agent.cfo` + CFO entitlement (C17); preview on entitlement denial | "Upload the settlement and order reports for that period on the Finance page" and the chip to run `cfo.pnl_for_tenant` (offered, not run) |
| `QT_LEAKS` | "Where am I losing money?" | `BS_LEAK_OPEN`, `BS_DATA_GAPS` | `agent.cfo` + CFO entitlement | "No leak check has been stored; run the leak check (chip) after the reports are uploaded." |
| `QT_DATA_GAPS` | "What data are you missing?" | `BS_DATA_GAPS`, `BS_INGEST_STATUS` | `agent.cfo` / `files.view` | Lists the named missing inputs and the upload or entry route for each |
| `QT_COMPETITORS_PRICES` | "What are my competitors charging?" | `BS_COMPETITOR_SNAPSHOT` | `agent.ci` + CI entitlement | "No competitor is tracked / captured yet. Add a competitor on the Competitor Intelligence page" or "Attach CI to this conversation" |
| `QT_PRODUCT_IDEAS` | "What product ideas did you find?" | `BS_PI_REPORT_LATEST` (+ the existing `pi.report` re-render read for the list) , `BS_SHARED_FINDINGS` filtered to PI | `agent.pi` | "No product research has been run; start one (chip)" |
| `QT_LISTING_CONTENT` | "What titles did we write?" | `BS_CMO_WORKFLOW`, **new, conditional** `BS_CMO_CONTENT_LATEST` | `agent.cmo` | "Nothing has been written yet; ask for titles (chip)" |
| `QT_GOALS` | "What is my goal?" | `BS_SELLER_CONTEXT`, `BS_SELLER_FACTS` (kind `GOAL`) | `agent.cfo` for the stored goal figure | "No goal is stored. Tell me your goal or set it on the CFO page." Progress against the goal: "not stored yet" (`BS_GOAL_PROGRESS` deferred) |
| `QT_AGENT_FINDINGS` | "What has each agent found?" | **new** `BS_SHARED_FINDINGS` | `agent.ceo`; per-agent visibility (D6) | "No agent has reported anything yet, or the agents that did are turned off for this conversation." |
| `QT_SELLER_FACTS` | "What do you know about my business?" | **new** `BS_SELLER_FACTS` (+ the existing direct answers, which stay first and use no model) | `agent.ceo` | "You have not told me yet. Tell me, for example, 'my niche is ...'" |

`BUSINESS_BRIEFING` (existing playbook) remains the overview. A business question that matches no type and no existing action/playbook is `ADVISORY`: qualitative general guidance labelled "general advice, not derived from your data", with **no number**, or, if it is plainly a question about the seller's own data, the plain "I don't have that stored" answer with the closest type's upload/attach guidance. The model's knowledge is never a source of a business figure (C13).

### 7.3 New Business State entries (extend §6.13; each names a persisted source, or is dropped)

| Entry | Owner | Persisted source | Notes |
|---|---|---|---|
| `BS_PNL_RECENT` | CFO | `metric_result` rows for the last `MAX_ITEMS_PER_ENTRY` periods via `business_state.recent_periods` and `_figure_from_metric_row` | Period selection from the question is done by `periods.py`; a period with no stored row is `UNAVAILABLE`. No computation. Cache sources `("metric_result",)`. |
| `BS_SELLER_FACTS` | CEO | `agent_memory` `scope=SHARED` via `memory.profile` | Seller-stated, labelled "You said", quoted. No money. Cache sources `("agent_memory",)`. |
| `BS_SHARED_FINDINGS` | CEO | `shared_finding` active rows (§6.2) | Applies D6 filtering; figures re-resolved through refs. Cache sources `("shared_finding",)`. |
| `BS_CMO_CONTENT_LATEST` | CMO | `cmo_generation` output text, **only if** the table persists it (S5 verifies; if not, the entry is dropped per §6.13 rule 5 and the answer says content must be regenerated) | Content is shown as the 6.35 quoted artefact with its label, never as a Figure. |

### 7.4 Answer rules

1. **Template-first, composer-bound.** The answer is the deterministic layout carrying the entries' cited figures (as in 6.38); the composer, where used, runs under the existing gates (§6.5, R4): placeholders only, unknown token, numeral literal, unavailable-as-real or dropped disclaimer => `TEMPLATE_FALLBACK`.
2. **Status words are code-written.** `UNAVAILABLE`, `NOT_ATTACHED`, `NOT_ENTITLED`, `NOT_PERMITTED`, `STALE`, `PARTIAL` map to fixed sentences (the guidance column of §7.2). A non-result is never narrated as a result.
3. Every figure shows its `as_of` and register; an `AGENT_REPORTED` finding is worded "reported by <agent>, not verified".
4. A seller-stated number (in `BS_SELLER_FACTS`, `SELLER_STATED` findings) is shown only as "you said ..." text, never as a Figure.

### 7.5 S5 implementation notes (built 2026-10-10; choices made where this part was silent)

1. **Where the catalog lives.** `ceo/question_types.py` (code, closed, deterministic). A question type is read by `business_state.read_entry(ctx, "QT_...")`, which expands it to its entries and merges them into one `BusinessStateEntry`; the orchestrator reads exactly one key per `BUSINESS_STATE` turn, so no orchestrator change was needed and the unchanged gating order applies to every entry (permission, attachment, entitlement, loader, provenance gate). Types are offered in the classifier catalog to every member holding `agent.ceo` (`capabilities.compute_capabilities`); a type whose agent is detached, not permitted or not on the plan is answered by a code-written sentence (attach / no access / not on your plan), never silently absent.
2. **A tenth id, `QT_NOT_STORED`.** The "unknown question" path of section 7.2: a question about the seller's own operational data that no saved result covers (stock, orders, ad spend, customers) is routed here by a rule and answered "Not stored yet. ..." with no entry read. The classifier may also choose it. Without it an unknown own-data question could only reach `ADVISORY`, where a model writes the answer.
3. **Rules.** `intent_router.STATE_RULES` run first, with past-tense / "my ..." phrasings (a "why" or "improve" question and a request to write or find something are not taken), because "what product ideas did you find" would otherwise match the metered `pi.discover` rule. The classifier prompt version is not bumped here: the catalog text changes, the prompt template does not; S1 owns the `ceo-classifier-4` bump with `addons`.
4. **`BS_PNL_RECENT`.** The newest three periods (a presentation bound, not the `MAX_ITEMS_PER_ENTRY` of section 7.3: three periods x three metrics + the three health bands = the 12 figures one answer carries), newest-computed row per metric, every figure labelled with its own period. Older periods are reported as a `TRUNCATED` gap. **The state read takes no period slot** (the orchestrator passes none to a state read), so a question about one month is answered with the recent periods, each named; no period is ever substituted for another without being named (E16). Choosing one period from the question is deferred to the orchestration slice.
5. **`BS_CMO_CONTENT_LATEST` is built** (Q10 resolved): `cmo_generation` persists `output_text` and, for title sets, `cmo_title_option`. A new tenant-scoped read, `generation_repo.list_recent_content_for_tenant` (re-exported through `ceo_reads`), returns the three newest COMPLETE generations that have text. Content is shown as a quoted artefact "Written by Slim CMO: ..., not verified by Metrion", each item clipped at 1,500 characters, never a Figure and never evidence. `BS_CMO_WORKFLOW` is unchanged and still never relays copy.
6. **`BS_SELLER_FACTS`** reads `memory.profile` (shared tier 1 only: business name, niche, marketplaces, goal, brand tone, decision), rendered as `Fact`s labelled "(you said)" with the seller's words quoted. Private notes and, when it exists, the findings tier are never read.
7. **`BS_SHARED_FINDINGS` / `QT_AGENT_FINDINGS`.** Not built here (the findings table is another slice). `QT_AGENT_FINDINGS` lists `BS_SHARED_FINDINGS`; while that key is not in `business_state.ENTRIES` the part is `UNAVAILABLE` with the code-written sentence. Registering the entry is the whole extension: nothing else changes. `QT_PRODUCT_IDEAS` lists only `BS_PI_REPORT_LATEST`; the "findings filtered to PI" part of section 7.2 waits for the same entry.
8. **Merging rules.** An entry that holds a result (AVAILABLE, or PARTIAL/STALE with something to show) contributes its figures, facts, artefacts, conflicts and gaps. An UNAVAILABLE entry contributes the type's fixed "Not stored yet." sentence (or that entry's own override) followed by the entry's own specifics. NOT_PERMITTED / NOT_ENTITLED / NOT_ATTACHED contribute only the fixed sentence naming the agent. Overall status: AVAILABLE if every entry has a result and the type has no always-missing part, PARTIAL if some do, else the most restrictive refusal (permission, then plan, then attachment), else UNAVAILABLE. Offered actions are added only when the missing part is the one the type's own sentence is about.
9. **Offered chips.** `BusinessStateEntry` gained `offers` and `artefacts` (both default empty; `StateRead` gained `artefacts`), which `EvidenceCollector.add_entry` carries into the answer. Every offered key is a registered registry key (pinned by a test). `cfo.pnl_for_tenant` (the profit chip, as written in section 7.2) is registered but is **not** a chat action in `plans.ACTIONS`, so a click would be refused as out of catalog until the orchestration slice adds it; the chip is shown today only as the "[Offered, not run: ...]" line. Pinned by a unit test so the gap cannot become silent.
10. **Evals** (section 8.3 a, b, c, f; d and e belong to S4): `ceo_eval/business_qa.py` + `fixtures/business_qa.jsonl`, deterministic, scripted model, no database: `python -m backend.ceo_eval qa`. The scorer rejects any number or spelled-out quantity not present in the answer's own cited evidence, any non-result worded as a result, and a dropped required sentence or label; five negative controls prove the scorer itself fires. Scripted drafts run through the production `composer.compose`, so the production gate is part of what is measured. The classifier closed-enum case (f) is in `tests/unit/test_ceo_business_qa.py`.

## 8. AI requirements

1. **The hard rule stands.** No model touches a number. Needs, findings and Q&A add no arithmetic: no sum, rank score, conversion or average anywhere in `ceo/needs.py`, `shared_findings` or the new BS loaders (AC22 architecture test extends to these modules).
2. **LLM seams.** Needs add no seam. The classifier gains one closed output (`addons`, plus `route_key` = question type id); prompt version bumps (`ceo-classifier-4`). The composer is unchanged and sees only gated evidence plus the delimited findings block.
3. **Evals required** (CLAUDE.md; add to the §6.18 harness alongside the code, not after): (a) **no ungrounded number:** across needs, findings and Q&A cases, the composed answer never states a number absent from its cited figures/`FigureToken`s; a spelled-out number counts; (b) **no non-result narrated as a result:** `UNAVAILABLE`, `NOT_STORED`, `NOT_ENTITLED`, `NOT_ATTACHED`, a `noMatch` GST lookup, a timed-out or dropped need and an empty findings list are never worded as a finding or a value; (c) **required disclaimers kept:** the GST provisional/"not a ruling" disclaimer, "not verified" on `AGENT_REPORTED`, "general advice, not derived from your data"; (d) **trust wording:** an `AGENT_REPORTED` finding is never described as verified or confirmed; a GST `PROVISIONAL` result is never described as verified; (e) **injection:** a finding `subject`, idea name or competitor label containing instructions or a number is shown quoted and never obeyed or promoted to a figure; (f) **classifier closed-enum:** a request for an add-on not in the catalog, or a question type not in §7.2, yields `CLARIFY`, never a guessed provider or a free-form read; (g) **separation:** the GST rate never appears inside CMO-written copy.
4. Pass bars are not invented here (C20, R17); the harness reports and the owner sets thresholds.

## 9. Authorization and security

1. **No new permission key.** Needs run under the member's own grants; the broker is not a privilege path (C8). No write-class action is reachable by a need (C21): `CEO_READ` is READ-effect only; `LANDED_COST_FOR_IDEA` saving of quotes/budget is the existing 6.36 confirm-card flow with `financials.adjust` + CFO entitlement, unchanged.
2. Tenant comes from the session only. `ceo_need` and `shared_finding` carry `tenant_id`, FORCE RLS, tenant-scoped queries, missing context fails closed; cross-tenant ids are 404 (R10). A need never accepts a client-supplied tenant, provider, slot map or mode.
3. `shared_finding` is append-only for the app role; a finding's refs are verified for the tenant at write and at read.
4. Agent-reported text is data: bounded, stored as text, quoted wherever a model or the seller sees it, never executed or interpreted (R9). Findings never enter the seller-stated profile.
5. The Hub renders trust and permission state; it enforces nothing (R10).

### 9.1 Data model: `ceo_need` (append-only, FORCE RLS)

`id, tenant_id, investigation_id, turn_message_id, need_key, requester_agent, mode, provider_key (the registry key actually dispatched, e.g. service.gst_lookup), slot_digest (sha256 of canonical validated slots), idempotency_key, requester_run_id null, provider_run_id null, finding_id null, status (FULFILLED | REUSED | DENIED | NOT_ATTACHED | NOT_ENTITLED | UNAVAILABLE | FAILED | TIMED_OUT | CONFIG_MISSING | OFFERED), reused_from_need_id null, created_at`. Written once when the need ends (agent_run already tracks RUNNING). `UNIQUE (tenant_id, idempotency_key)`. App role: SELECT, INSERT. It holds no money and no text; the Hub reads it to show who asked whom.

## 10. Edge cases

| # | Case | Behaviour |
|---|---|---|
| E1 | Seller asks for description + GST but has `service.gst_lookup` and not `agent.cfo` | Route B runs; step says "The CEO asked the GST lookup for the rate" |
| E2 | Seller lacks `service.gst_lookup` | Description is produced; GST add-on shows the existing permission wall text; no rate |
| E3 | GST lookup returns `noMatch` | Named gap "no confident match; here is what was searched"; no rate, no model guess |
| E4 | CMO metered quota exhausted, GST available | The primary is refused, so the add-on does not run (§5.4.7); the quota denial is explained |
| E5 | GST cap exhausted, CMO available | CMO output delivered; add-on named as not available (entitlement), never a zero |
| E6 | Same product asked twice in one investigation within the reuse window | Second answer reuses (REUSED), shows the earlier `as_of`; no meter |
| E7 | Product text > 200 chars | Asked to shorten; never truncated |
| E8 | CFO detached, CMO attached, Route A would be chosen | `gst_route_key` falls to Route B if permitted; else gap "turn on the CFO" with a chip; never silent attach |
| E9 | Turn retried after a crash | Idempotency key returns the stored need result; no second meter |
| E10 | Provider times out | `TIMED_OUT` gap; late result finishes on its own and writes its own finding (L9); the answer does not wait |
| E11 | `CEO_NEEDS_MAX_PER_TURN` unset | Primary action runs; add-on gap names the unset limit (§5.4.3) |
| E12 | Finding source ref later superseded or deleted | Read-time gate drops the figure, shows the text and a gap "figure no longer verifiable" |
| E13 | Seller forgets a finding; the agent runs again on the same source | Tombstone: not re-recorded |
| E14 | Seller corrects a finding with a number ("my cost is 120") | Stored as `SELLER_STATED` text, shown "You said ..."; never a Figure; never an engine input |
| E15 | Member without `agent.cfo` opens the findings panel | CFO findings hidden and counted; no figure, no text |
| E16 | Q&A for a period not stored | `UNAVAILABLE` + upload guidance + offered chip; no number from any other period is substituted without naming it |
| E17 | Q&A types overlap ("profit and leaks") | Both types' entries read; each section keeps its own status; a missing one is named |
| E18 | Findings list empty and agents detached | The `QT_AGENT_FINDINGS` empty-state sentence; not "nothing found" as a negative result |
| E19 | Two members correct the same finding | Both rows append; the later one supersedes; both attributable via `created_by` |
| E20 | Idea name contains digits | Allowed in `subject` (quoted); `text` stays digit-free |

## 11. Production-validation blockers

1. Owner values for `CEO_NEEDS_MAX_PER_TURN`, `CEO_NEED_REUSE_MAX_AGE_HOURS`, `CEO_FINDINGS_MAX_PER_AGENT_PER_DAY`, `CEO_FINDINGS_CONTEXT_MAX` (all no-default).
2. Retention and erasure of forgotten findings and `ceo_need` rows (same unresolved question as `agent-memory.md` Q2); decide together before launch.
3. Evals of §8.3 run on the real model pair (qwen3:8b / qwen35-4b-q4) and reviewed by the owner; none has been run.
4. `entitlement.md` confirmation that add-on legs do not consume an extra CEO turn unit (Q4/Q25 neighbours).
5. Verification of the assumptions in §3.3 and §3.4 against the code before S1 starts.

## 12. Acceptance criteria

**Needs.** AC-N1 No agent-to-agent call exists; every need is fulfilled by `dispatch` on a registry key (extends AC1, AC22; architecture test). AC-N2 A need not in the catalog, or whose requester differs from the chosen action's agent, is never executed. AC-N3 Provider, slot sources and pass-back come from the catalog; a model output cannot alter them (test with a hostile classifier output). AC-N4 Each provider leg is permission-, attachment- and entitlement-checked exactly as a direct call; a requester's rights grant nothing. AC-N5 A denied/detached/not-entitled provider leaves the requester's output intact, a DENIED child run, a named gap, and no value. AC-N6 Depth is 1; no cycle or duplicate need can run. AC-N7 Idempotency: replaying a turn or card meters once and returns the same result. AC-N8 Metered legs of one turn are admitted all-or-nothing before any runs. AC-N9 Reuse only within the investigation, within the configured age, for `reusable` needs, via re-resolved refs; unset age means no reuse. AC-N10 Every figure passes the provenance gate; specialist free text never becomes a slot, a figure or evidence. AC-N11 The GST rate appears only as a separate cited block, never inside CMO copy. AC-N12 Unset limits fail as specified (no guessed default). AC-N13 The Hub shows a step for each need (§13) from `ceo_need`/events. AC-N14 `ceo_need` is tenant-isolated, FORCE RLS, append-only.

**Findings.** AC-F1 The database refuses: an agent/engine row with a digit in `text`; `ENGINE_VERIFIED` without `ENGINE_RESULT` refs (or with an `ESTIMATE`); `SELLER_STATED` without a message source or a superseded row; a row with no `source_ref`; a foreign-tenant `ENGINE_RESULT` ref; UPDATE/DELETE by the app role. AC-F2 No `shared_finding` content ever appears in `memory.profile`, `memory.context_line` or any "what the seller told us" text (test with a hostile finding). AC-F3 Cross-tenant read, correct or forget is 404; RLS FORCE verified as `metrion_app`. AC-F4 Correct supersedes; forget removes from every read; a forgotten source is not re-recorded. AC-F5 A hidden-agent finding is neither shown nor described to a member without that agent's permission/entitlement; the count is shown. AC-F6 `AGENT_REPORTED` is never labelled verified anywhere (API, UI, composer). AC-F7 Adapters never copy specialist content (CMO copy, PI scores) into a finding. AC-F8 A write failure never alters a turn.

**Business Q&A.** AC-Q1 Each question type reads only its listed entries; no registry action, computation, write, external call or model call occurs in a state read (AC26 extends). AC-Q2 A value outside the type enum is `CLARIFY`. AC-Q3 Every `UNAVAILABLE`/`NOT_*` status yields the fixed "not stored yet" sentence with upload/attach guidance and (where one exists) an offered, unrun action chip. AC-Q4 Every number in an answer traces to a cited ref that resolves for the tenant. AC-Q5 No SQL generation and no vector/semantic search exists in the Q&A path (architecture test). AC-Q6 `BS_SHARED_FINDINGS` applies D6. AC-Q7 The §8.3 evals exist and run in the harness.

## 13. Frontend visibility (Hub; visual design is not final, structure is)

1. **Flow and canvas step.** For each need the conversation shows a step line and the canvas/flow shows a CEO-to-provider edge labelled with the catalog `ui_label`, for example "The CEO asked the CFO for the GST rate for “<product>”" (Route B: "the GST lookup"). States: asked, working (the provider node shows the action name as today), done (links to the result card), reused ("looked up earlier"), dropped with its reason ("CFO is turned off: turn on"). Edges are always CEO-to-agent (strict star); the label names the requester. Text comes from `ceo_need` + catalog templates written by code.
2. **Result blocks.** The requester's output and the need's result are separate cards, each with its own label (§5.6.4); the GST block shows rate, source link, retrieval date, "provisional" and the disclaimer.
3. **Offers** are chips/cards using the existing decision-card component ("Is #3 worth stocking?" already exists).
4. **Shared findings panel** (beside "What I remember", which keeps listing tier 1 and private notes): findings grouped by agent; each shows a trust badge (§6.5 wording), the quoted `subject`, the text, figures rendered from refs with `as_of`, a link to the source (only where the page exists, 6.35), and **Correct** and **Forget** actions. Hidden-by-permission entries appear only as a count. An empty state explains why (no findings yet vs agents off).
5. **Q&A** answers use the existing answer card; a "not stored yet" answer shows the upload link or an "Add <agent>" control and any offered chip.

## 14. Test scenarios

**Needs.** T-N1 "description + GST" with CFO attached/entitled -> Route A legs, two blocks, separate refs, one CEO unit. T-N2 same with CFO detached but `service.gst_lookup` held -> Route B. T-N3 neither permission -> description delivered, wall text for GST. T-N4 GST cap exhausted -> description delivered, named gap. T-N5 hostile classifier output naming an unknown add-on, a different provider, a slot with injected text -> CLARIFY / ignored. T-N6 duplicate and over-limit needs -> deduped/capped; unset limit -> gap. T-N7 replay of the turn -> one meter, same result. T-N8 reuse inside/outside the age; unset age; changed product text. T-N9 timeout. T-N10 "is #3 worth stocking?" runs `NEW_PRODUCT_DECISION` as a need with the existing confirm card and no PI estimate relayed. T-N11 CI price option requires the seller's pick; margin figures carry `engine_result_ref`. T-N12 `CEO_READ` cannot reach a COMPUTE_PERSIST or write key. T-N13 two tenants: no `ceo_need` visible across tenants. T-N14 architecture test: no agent-to-agent import; no arithmetic on money in the new modules. T-N15 Hub shows the step in each state.

**Findings.** T-F1 DB: each refusal of AC-F1 as `metrion_app` (digit, trust/ref rules, no source, foreign ref, update, delete). T-F2 leak test of AC-F2. T-F3 isolation and 404s. T-F4 correct/forget/tombstone. T-F5 per-agent visibility with and without `agent.cfo` and with CFO not entitled. T-F6 each adapter writes the expected rows from a recorded leg and none from a failed one; no content copied. T-F7 write failure leaves the turn unchanged. T-F8 composer evals (§8.3) for trust wording and injection.

**Q&A.** T-Q1 one case per question type, populated and empty. T-Q2 period stored vs not stored. T-Q3 CFO not entitled -> preview offer, no figure; no `agent.cfo` -> wall. T-Q4 unmatched question -> ADVISORY without a number or "not stored" guidance. T-Q5 evals §8.3 a-d. T-Q6 architecture test (no SQL generation, no embedding call).

## 15. Explicit open questions

| # | Question | Recommendation |
|---|---|---|
| Q1 | Should a GST rate ever be placed inside CMO-written copy (e.g. a listing "GST: x%" line)? This needs an edit to `slim-cmo-agent.md` C7/§6.9. | **No.** Show the rate beside the copy (D4). Re-open only if a marketplace requires a GST field in the listing, and then put it in a structured field CMO is handed by code, not in generated prose. |
| Q2 | Enable `AFTER_RESULT` (same-turn dependency, continue or re-run) in V1? | **No.** Specified, not built (D3); no V1 entry needs it. If the owner wants it, add about 6 hours to S2 and an AC4 amendment. |
| Q3 | Metered step-raised needs: always offer a confirm card, or auto-run when the seller's request implied them? | Auto-run only when the seller asked for that output; otherwise a confirm card stating the units (Q12 precedent). |
| Q4 | Write findings from direct (dashboard) agent runs too (D5)? | Not in V1; add as a follow-up through the same adapters called from each agent's composition function. |
| Q5 | Values for `CEO_NEEDS_MAX_PER_TURN`, `CEO_NEED_REUSE_MAX_AGE_HOURS`, `CEO_FINDINGS_MAX_PER_AGENT_PER_DAY`, `CEO_FINDINGS_CONTEXT_MAX`. | Example config only: 2, 24, 20, 10. The owner decides. |
| Q6 | Do add-on legs consume an extra CEO turn unit? | No (one turn, one unit); each provider's own meter applies. Confirm in `entitlement.md`. |
| Q7 | Are findings tenant-wide to every member with the agent's key, or per member? | Tenant-wide with D6 filtering, matching investigation visibility (C18). |
| Q8 | Retention and erasure of forgotten findings and `ceo_need`. | Decide with `agent-memory.md` Q2 before launch; the append-only tables keep the original text in superseded rows. |
| Q9 | Relay PI's stored feasibility as a labelled estimate inside `LANDED_COST_FOR_IDEA` and as a finding number (`estimate_ref`)? | Defer until PI exposes a read that returns the estimate with its `estimate_ref`; then add as a follow-up slice. |
| Q10 | Does `cmo_generation` persist the generated text (needed for `BS_CMO_CONTENT_LATEST`)? | **Resolved by S5 (2026-10-10):** it does persist `output_text` / `cmo_title_option`; the entry is built (section 7.5 note 5). |
| Q11 | Do CFO `leak_finding` and `metric_result` expose an `engine_result_ref` for the leak amount (so `LEAK_FOUND` can be `ENGINE_VERIFIED` with a number)? | S4 verifies; if not, record `LEAK_FOUND` as `AGENT_REPORTED` with no number. |
| Q13 | How does the panel's **Correct** action obtain the `message` a `SELLER_STATED` row must cite (a new `investigation_message` row, or a relaxed source kind for panel corrections)? | Decide with S6b; S3 ships the service function only (6.6.1). |
| Q12 | Should the seller be told when an agent records a new finding (like the memory acknowledgement), or only see it in the panel? | Panel only in V1 (findings are not seller statements; agent-memory §1 "nothing remembered silently" applies to seller facts); show an unread count on the panel. Owner may prefer an in-answer note. |

---

## Appendix A: Build plan (slices; each independently shippable, hours include tests and docs)

| Slice | Scope | Hours | Depends on |
|---|---|---|---|
| **S1** Needs broker + CMO->GST | `ceo/needs.py` catalog + loader checks; migration + repo for `ceo_need`; `addons` closed enum in classifier (prompt `ceo-classifier-4`) and `intent_router` rule for "along with / also give GST"; PARALLEL fan-out integration with all-or-nothing metered admission; limits config (`CEO_NEEDS_MAX_PER_TURN`); idempotency; reuse (`CEO_NEED_REUSE_MAX_AGE_HOURS`); "this product" resolution; evidence/gap rendering; events `NEED_RAISED/FULFILLED/DROPPED`; evals a-c, g | **16** | none |
| **S2** PI->CFO profit need and the other catalog entries | `LANDED_COST_FOR_IDEA`, `MARGIN_AT_PRICE`, `CEO_READ` as catalog entries over the existing 6.36 / 6.38 flows; `STEP_RESULT` adapters producing OFFERs (`pi.report`); OFFER acceptance as `UI_ACTION`; tests that existing flows are unchanged | **10** | S1 |
| **S3** Shared findings ledger + gate + migration | `shared_finding` migration (CHECKs, trigger, RLS, grants), repository, `shared_findings.record/correct/forget`, tombstones, endpoints, per-agent visibility, DB and isolation tests, leak test (AC-F2) | **12** | none (parallel to S1) |
| **S4** Findings writers | Adapters for PI, CI, CFO, CMO at the choke point; caps; best-effort writes; verification of Q11; adapter tests; composer findings block + eval d, e | **10** | S3 |
| **S5** CEO business Q&A | Question-type catalog; rules + classifier enum; `BS_PNL_RECENT`, `BS_SELLER_FACTS`, `BS_SHARED_FINDINGS`, conditional `BS_CMO_CONTENT_LATEST`; code-written not-stored responses with offered chips; architecture tests; evals a-d, f; harness cases | **18** | `BS_SHARED_FINDINGS` and `QT_AGENT_FINDINGS` need S3; the other types ship without it |
| **S6** Hub UI | **S6a** need steps on flow/canvas, separate result blocks, offer chips (after S1): 5 h. **S6b** shared findings panel with trust badges, correct, forget, hidden count, empty states; not-stored answer controls (after S3 and S5): 7 h | **12** | S1 (6a); S3, S5 (6b) |

Total about 78 hours. Suggested order: S1 and S3 in parallel, then S2, S4, S5, S6. Each slice's acceptance criteria are the ACs of §12 it names: S1 AC-N1-N5, N7-N14 (CMO->GST); S2 AC-N1-N4, N10 for the three entries plus no regression of ACs in 6.36-6.38; S3 AC-F1-F5; S4 AC-F6-F8 and AC-F5 end to end; S5 AC-Q1-Q7; S6 AC-N13 and the panel behaviours of §13. A slice is done when its ACs and §14 scenarios pass and the `ceo-build-status.md` entry states what was and was not verified.

## S1 implementation notes (2026-10-10; what was built, and where it differs from sections 5.3-5.7)

**Built:** `ceo/needs.py` (catalog with the one V1 entry `GST_RATE_FOR_PRODUCT`; requester != provider checked at load; `valid_addons`, `product_text`), `ceo_need` migration `20261010_0013` and `repositories/ceo_need_repo.py` (append-only, FORCE RLS, unique idempotency key), `CEO_NEEDS_MAX_PER_TURN` (no default), `Decision.addons` and `UiAction.addons`, an `intent_router` rule ("a description ... with/along the GST ..."), add-ons carried on the guided-input cards until the session ends, and `_run_needs` in the orchestrator (provider chosen by `gst_route_key`, slot = the seller's own title, every check is the provider's own, a refusal is a named gap, one `ceo_need` row per need with events `NEED_RAISED/FULFILLED/DROPPED`).

**Deviations, stated:** (1) The add-on is raised by the **rules router only**; the classifier `addons` enum (prompt `ceo-classifier-4`) is not built, so a sentence the rules do not recognise will not carry an add-on. (2) The add-on runs **after** the main leg in the same turn rather than in parallel; it never runs when the main leg did not complete (matches 5.4.7 for that case). (3) **Admission is per leg**, not all-or-nothing across the turn: the main leg's own quota is checked first and the add-on's entitlement is pre-flighted before it runs, but a metered add-on refused by quota after the main leg succeeded is dropped and named rather than checked beforehand. (4) **Reuse of an earlier GST result** (5.7) and **"this product" resolution** are not built; the product text is the title the seller gives in the session. (5) The migration is numbered 0013 and is re-pointed after the findings migration (0012) merges.
