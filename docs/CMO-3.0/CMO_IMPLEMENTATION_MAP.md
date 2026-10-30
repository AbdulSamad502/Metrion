# CMO 3.0 — Implementation Map

> **Status:** audit and planning only. No production code was changed. Written 2026-10-30 on branch `feat/cfo-2`.
> **Delete this whole folder (`docs/CMO-3.0/`) when CMO 3.0 is finished.**
> Authority for behaviour stays with `docs/specs/slim-cmo-agent.md` and `docs/specs/ceo-cmo-delegation.md`. Any milestone below that changes behaviour needs its spec section written first (CLAUDE.md rule), and spec edits are **not** done here.

**Legend.** **[V]** verified in code or by a test I ran. **[P]** proposed change (not built). **[U]** unknown — could not be verified, needs a check or a human input. Nothing marked [V] was inferred from a document.

---

## 0. What I actually ran

| Check | Result |
|---|---|
| `packages/slim-cmo` unit tests (`tests/unit`) | **2183 passed** (12 s) [V] |
| Backend CMO unit tests (`test_cmo_chat_quality_unit`, `_delegation_unit`, `_description_news_gaps`, `_entitlement`, `_p5_unit`, `_p6_unit`) | **236 passed** [V] |
| Frontend `components/cmo/showcase.test.tsx` (vitest) | **8 passed** [V] |
| Backend CMO/CEO **integration** tests (`tests/integration/test_cmo_*`, `test_ceo_cmo_*`) and `packages/slim-cmo/tests/integration` | **NOT RUN.** They need the shared dev Postgres (running as `metrion-postgres-1`), and the build notes say leftover test rows already break its fixtures. Run them only on a clean scratch database. [U] |
| Live Ollama text/vision generation, live Tavily/YouTube search, a signed-in click-through of the dashboard | **NOT RUN.** No real-model or provider run was possible or attempted. [U] |
| Database contents (are `format_constraint` rows `VERIFIED`? are caps/config rows seeded? is the vision gate open?) | **NOT READ.** Treat as unknown. [U] |

---

## 1. The 20 existing capabilities — real status

Status words follow the plan: IMPLEMENTED / PARTIAL / BLOCKED / MISSING / NOT VERIFIED. "Runtime" is what I could run; mostly unit level only.

| # | Capability | Status | File-level evidence | Runtime |
|---|---|---|---|---|
| 1 | Image upload, normalisation, local Ollama vision | **IMPLEMENTED** (code) | `slim_cmo/imaging/normalize.py`, `providers/ollama_vision.py`, `service/vision.py`, `backend/services/cmo_images.py`, `cmo_attachment.py`, `api/v1/cmo.py` `/images`, `/image-analyses`, `analyze_attachment_for_ceo` | Unit tests pass. Real Ollama run **NOT VERIFIED** |
| 2 | Vision attributes (colour, material, brand, product type, visible text) | **IMPLEMENTED** | `vision/schema.py:15` `ATTRIBUTE_NAMES = color, material, size, brand, product_type, visible_text`; `vision/parse.py` | Unit only |
| 3 | Trust gate, confidence/provenance, seller confirmation | **PARTIAL** | Gate: `vision/trust.py`, table `vision_eval_run`. Confirm API: `post_confirm_image_hint` (`cmo.py:334`). **But no CEO chat code calls `cmo.confirm_image_hint`** — it is only in `registry.py:473`, `effects.py:141` and the eval catalog. In chat the seller re-types facts after `cmo_delegation.observation_text` | Gate open/closed in dev DB **[U]** |
| 4 | CEO asks for missing info; persistent seller facts | **PARTIAL** | Question loop: `ceo/cmo_delegation.py`, `ceo/input_session.py` (`CMO_TITLES` etc.). Facts persist as append-only `seller_fact` rows keyed by `sku`. Carry-forward across turns is **per conversation only** (`carried_facts`, `last_product`: "in THIS conversation"). `postgres_store.load_facts` returns `[]` when `sku` is empty. How the chat flow assigns a `sku` — **[U]** | Unit only |
| 5 | Five titles per marketplace; seller picks marketplace(s) | **IMPLEMENTED** | `generation/titles.py`, `validators.evaluate_title_set`, prompt allows "brand / feature / use-case first" (`prompts.py:100`). Strategy is only a prompt hint; **no strategy label is stored** | Unit only; real LLM **NOT VERIFIED** |
| 6 | Title selection, editing, validation, approval | **PARTIAL** | Backend complete: `service/approve.py`, `cmo_title_approval`, `post_title_approval`. **No CEO chat path calls `cmo.approve_title`** (grep: only registry/effects/eval catalog). The copy pack is grounded in chat via `seller_title` typed by the seller (`input_session.py:460`). So "pick option 1 and edit it" as in Scene 2 is **not wired** | The dashboard shows "Approved" only when an approval row exists, which chat cannot currently create **[V by code read]** |
| 7 | Full listing after separate CEO approval | **IMPLEMENTED** | `cmo.generate_listing_copy` is its own plan card (`cmo_delegation._WHAT`), `generation/copy.py`, atomic pack in `service/generate.py` | Unit only |
| 8 | Standalone description, bullets, keywords | **IMPLEMENTED** | `generation/standalone.py`; `intent_router.py:185-190` | Unit only |
| 9 | Amazon backend terms, optional hashtags | **IMPLEMENTED** | `generate_backend_terms` (Amazon-only, DB check `output_type<>'BACKEND_TERMS' OR marketplace='AMAZON'`), `generate_hashtags`; byte limits in `validators.check_backend_terms` | Unit only |
| 10 | Catalog Q&A with basis labels | **PARTIAL** | Engine: `catalog/resolve.py`, `service/catalog.py`, route `post_catalog_answers`. **No CEO intent rule, input table or orchestrator branch reaches it** (`intent_router.py` has no `catalog` CMO rule; `CMO_SESSIONS` omits it). A seller cannot ask it in chat today | Unit only |
| 11 | Amazon/Flipkart/Meesho constraints and validation | **IMPLEMENTED (code) / BLOCKED (data)** | `constraints.py`, `validators.py`, table `format_constraint`; `scripts/seed_format_constraints.py` loads **human-reviewed** `VERIFIED` rows. Without a `VERIFIED` row production generation fails closed `COUNTING_RULE_UNVERIFIED`. Whether rows exist in any environment **[U]** | Unit only |
| 12 | Unsupported-claim prevention, fact grounding | **IMPLEMENTED** | `claims.py` (eligibility by basis), `forbidden.py`, `generation/safety.py`, `generation/facts.py`; red-team tests `tests/evals/test_redteam.py` | Unit passes |
| 13 | Seven-section source-linked trend report | **IMPLEMENTED** | `trends/*`, `service/trends.py`, `backend/services/cmo_trends.py`; sections/evidence/interpretation columns on `cmo_trend_report` | Unit only; live providers **NOT VERIFIED** |
| 14 | Niche confirmation + external research approval | **IMPLEMENTED** | `service/niche.py`, `cmo_niche_term`, `ceo/input_session.py` (`niche`, `news_kind`), preview/digest `409 PLAN_CHANGED` (`cmo.py:511`), plan card lists exact queries (`cmo_delegation.plan_extras`) | Unit only |
| 15 | CI-informed listing generation | **IMPLEMENTED (not "planned")** | `backend/services/cmo_ci_inputs.py` (`broker`, `load_inputs`), `slim_cmo/ci_inputs.py`, `orchestrator.py:760-763,1034-1038`, `cmo_generation.input_mode`/`ci_inputs_snapshot`, plan-card line `CI_USED_LINE`. Uses derived theme words only; falls back silently to independent. **`CMO_details.md` §1.5-I/§1.11 and `ceo_hub_cmo.py` docstring ("never reads CI data… phase P11") are stale** | Unit only; needs saved CI insight rows to see it work |
| 16 | CEO-first routing, delegation, approval cards, result presentation | **IMPLEMENTED** | `intent_router.py`, `registry.py:464-499`, `cmo_delegation.py`, `ceo/approval*.py`, `ceo/effects.py`, `ceo/evidence.py`; every CMO action also goes through `ceo_hub_cmo.dispatch_cmo` permission check | `test_cmo_delegation_unit` etc. pass |
| 17 | Read-only CMO dashboard | **IMPLEMENTED** | `frontend/app/dashboard/cmo/page.tsx`, `components/cmo/ShowcaseDashboard.tsx`, `lib/cmoShowcase.ts`; routes `api/v1/cmo_showcase.py` (6 GET + 1 POST usage event) | 8 vitest tests pass; **never click-tested signed-in** [U] |
| 18 | Saved generations, approvals, copy/mark-used, history retrieval | **PARTIAL** | Storage and dashboard reads: `cmo_generation`, `cmo_title_approval`, `cmo_result_usage_event` (`event_kind GENERATED/VIEWED/COPIED/MARKED_USED`), `repositories/cmo_showcase_repo.py`. **No chat route reads history back** ("show my previously selected title", Scene 7) | Unit only |
| 19 | Tenant isolation, permissions, quotas, idempotency, audit, recommend-only | **IMPLEMENTED** | `FORCE` RLS + composite `(tenant_id,id)` FKs in `20261003_0001_cmo_tables.py`; `cmo_actions.run_billable`; `cmo_quota_repo`; unique idempotency index `cmo_generation_idempotency_idx`; `agent_run` + `parent_run_id`; no marketplace write path exists | Isolation integration tests **NOT RUN** |
| 20 | Error handling, retries, missing config, fail-closed rules | **IMPLEMENTED** | `CONFIG_MISSING` / `CONFIG_INVALID` (`cmo_delegation.py`), bounded retries (`generation/engine.py`), `R5` stuck-run recovery (`_open_run`) | Unit only |

**Summary:** 14 IMPLEMENTED in code, 5 PARTIAL (3, 4, 6, 10, 18 — all are *missing chat wiring or persistence reach*, not missing engines), and capability 11 is implemented but depends on data a human must supply. Nothing is MISSING. Runtime proof against a real model, real providers and a real database is NOT VERIFIED for every item.

---

## 2. The 12 upgrades + 5 news enhancements — gap analysis

All "Reusable" entries were checked in code. "Missing" means no code, table or route exists today (grep for `variant`, `family`, `readiness`, `objection`, `mobile`, `preview` in CMO code found nothing relevant).

| # | Upgrade | Status today | Reusable | Missing |
|---|---|---|---|---|
| 1 | Smart Product Intelligence (SKU profile, provenance, history) | **MISSING** as a unit; raw material exists | `seller_fact` (append-only, basis-labelled, `sku`), `product_image_analysis`, `cmo_showcase_repo.products` label query | A product-profile read model (latest value per attribute with provenance + history), a stable SKU/product identity in chat **[U how sku is set]**, CEO "I found your saved profile" lookup |
| 2 | Evidence-backed Keyword Intelligence | **PARTIAL (old behaviour only)** | `generate_keywords`, `check_keywords`, CI `keyword_themes`, `cmo_niche_term`, `NOT_ASSESSED`-style vocabulary in trends | Keyword candidate store, relevance/intent/placement rules, confidence, "excluded — unconfirmed" decisions, evidence refs. **No keyword-volume source exists** (spec Q3) — must stay `NOT_ASSESSED` |
| 3 | Five-title + full-listing quality analyzer | **MISSING** | `validators.evaluate_title_set` (length/dupes/forbidden), `claims.py` and `forbidden.py` as the *hard-failure* gates, `char_count`, `constraint_check` JSON per option | A documented scoring method, per-dimension results, a per-option analysis table, listing audit, UI. Title `rank` is explicitly "NOT a quality claim" (migration comment) — must not be reused as a score |
| 4 | CI + CMO integration (structured evidence) | **PARTIAL** | Entire broker/loader (`cmo_ci_inputs.py`), snapshot column, plan-card disclosure, originality check `ci_inputs.check_output` | Structured per-competitor evidence (emphasised features, gaps vs seller facts), "what competitors emphasise" answer, evidence refs in analysis. Competitor prices stay unread |
| 5 | Advanced listing generation (aligned to chosen strategy) | **PARTIAL** | Atomic pack generation, grounding on approved title, shared-text diagnostics | Strategy as an input, keyword-placement plan input, buyer-needs input, post-generation audit step |
| 6 | Listing history, comparison, revisions, performance feedback | **PARTIAL** | Every artefact is saved immutably; usage events; `GENERATED` events | Product-linked snapshot grouping, version compare, revision lineage, "what changed" explanation, link to marketplace performance data (**no performance linkage; separate decision**) |
| 7 | Smart market opportunities | **PARTIAL** | Trend report sections 5 (adjacent) and 6 (interpretation); source classes; corroboration | Product-specific recommendations tied to a profile and listing, each backed by a cited finding |
| 8 | Search result + mobile/desktop preview | **MISSING** | Stored title text, `char_count`, `title_max_chars` | A truncation model (needs **verified** display widths per marketplace/device — not in `format_constraint`), preview component, "actual display may differ" label |
| 9 | Product Image Quality Advisor | **MISSING** | Image store, normaliser (size/pixel checks), vision provider slot | A separate quality schema/prompt, and an **evaluation** before any quality statement is trusted. The current vision schema deliberately excludes quality |
| 10 | Product Variant Intelligence | **MISSING** | `sku` is free text; `seller_fact.sku` | Family/variant model, shared vs variant-specific facts, guard against mixing capacities |
| 11 | Buyer Questions & Objection Intelligence | **MISSING** | Catalog Q&A basis labels, `UNKNOWN` handling | Question generation as "questions to investigate", status per question (confirmed / unknown / unsupported), feed to readiness |
| 12 | Listing Readiness Checklist | **MISSING** | All the gates exist separately (constraints, claims, grounding, image trust) | Aggregator: blockers vs missing facts vs optional improvements vs next actions, with `NOT_ASSESSED` for unrun checks |
| 14.1 | Personalised news feed | **PARTIAL** | Niche confirmation, `news_kind` choice, trend sections | Product/niche/marketplace relevance ranking from the profile |
| 14.2 | Policy & seller alerts | **PARTIAL** | `SourceClass.OFFICIAL_MARKETPLACE` classification (`trends/sources.py:44,140`) and `news_kind=POLICY` | Needs **configured official domains** (empty config ⇒ nothing is ever "official"); verified-change handling; rule that news never alters enforcement rules |
| 14.3 | News-to-action | **MISSING** | Section 6 interpretation with cited items | A suggested-task object routed back through the CEO with approval |
| 14.4 | Follow-up / change tracking | **MISSING** | Reports saved with date and sources | A comparison of two reports for the same niche (new / unchanged / corrected) |
| 14.5 | Ask questions about a news story | **MISSING** | Saved findings with source links | A CEO route that answers from a saved finding **and** the seller's profile. Overlaps CEO-B 3.0 (conversational layer) |

Out of scope and **not to be built**: bulk listing, automatic publishing, language/audience adaptation.

---

## 3. Reusable components (do not rebuild)

- **Gates:** `validators.py`, `claims.py`, `forbidden.py`, `generation/safety.py`, `textnorm.py` (counting rules).
- **Orchestration:** `cmo_delegation.py` loop (question limits, expiry, plan extras), `input_session.py` field tables, `registry.py`, `effects.py`, `plans.py`, `approval_run.py`.
- **Billing/idempotency/audit:** `cmo_actions.run_billable`, `cmo_quota_repo`, `agent_run` linkage, `cmo_result_usage_event`.
- **Evidence engine:** `trends/evidence.py` (independence, recency, corroboration) — the model for how a new analyzer should compute and label confidence.
- **CI broker:** `cmo_ci_inputs.py`.
- **Dashboard:** `ShowcaseDashboard.tsx` and `cmo_showcase_repo.py` (read-only contract must stay).
- **Config pattern:** `cmo_platform_config` + `slim_cmo/config.py` (missing = `CONFIG_MISSING`, never a default).

---

## 4. Bugs, debt, duplicated logic, integration gaps (verified)

1. **Stale documentation (verified contradictions).** `CMO_details.md` says CI-informed generation was not started; `ceo_hub_cmo.py` docstring says CMO "never reads CI data"; code shows it is built and wired. `CMO_details.md` §1.9 says "the frontend no longer calls" direct routes; the direct `POST` routes still exist in `api/v1/cmo.py` (a `CMO_DIRECT_ROUTES_ENABLED` switch is described but I did not verify it exists — **[U]**).
2. **Backend actions with no seller path (dead-in-chat):** `cmo.approve_title`, `cmo.catalog_answer`, `cmo.confirm_image_hint`, `cmo.suggest_niche_terms` as stand-alone. (`confirm_niche_terms` *is* wired, `orchestrator.py:1178`.)
3. **Two parallel call paths** into the same handlers: `ceo_hub_cmo.dispatch_cmo` (old dummy hub, "later the real CEO") and `ceo/registry.py` + `orchestrator.py`. Any new action must be registered in the real registry; keep the old hub in step only if still used **[U whether `ceo_hub_cmo` is still called outside tests]**.
4. **Action lists duplicated in 6+ places** (`CMO_DISPATCH_ACTIONS`, `registry.py`, `effects.py`, `plans.py`, `input_session.CMO_SESSIONS`, `cmo_delegation._WHAT/_TITLE_WHAT`, `ceo_eval/catalog.py`). Adding an action means touching all of them; guard-count tests exist and last commit `078bc0f` noted "guard counts … still to update" for another feature.
5. **"Product" is a free-text `sku`.** The dashboard hides any result with no `sku` (`g.sku IS NOT NULL`), and `load_facts` returns nothing without one. If chat runs leave `sku` empty, memory and the dashboard product filter silently see nothing. **Must be checked first (M0).**
6. **No score vocabulary exists** — the enum for title `rank` is deliberately non-quality; adding scores needs a new table, not a reuse.
7. **`cmo_generation.output_type` is a closed CHECK enum mirrored in `types.py`** and asserted equal by `tests/integration/test_schema_constraints.py`; adding an artefact type means migration + enum + billing event-kind map in lockstep.
8. **Known validation gaps already documented in the spec** (kept, not new): pack meaning vs approved title is unchecked; letter-spaced banned phrases are not caught; Hindi is the only regional language covered.
9. **Entry point for multi-image or image quality** is limited by "one image per request" (spec Q7).

---

## 5. Architectural conflicts and risky changes

| Risk | Why it matters | Mitigation |
|---|---|---|
| **LLM-produced scores.** Plan wants "explainable scores". If a model emits 0-100 numbers, they are invented metrics. | Violates the plan's own "never fabricate metrics" and Metrion's "never invent a number" | Compute every dimension in code from named rules; model may only *explain* a computed result. Show band + rule list, status `NOT_ASSESSED` when an input is missing. **Decision needed from you (Open Q1).** |
| **Plan's example scores (90/91/93).** | They are fictional | Never seed, display or test against them |
| **Truncation preview without verified widths.** | Showing an invented cut-off is a made-up marketplace fact | Config rows with source URL + verified date, like `format_constraint`; unverified ⇒ preview labelled "illustrative", never "what Amazon shows" |
| **Keyword demand.** | No volume source exists | Always `NOT_ASSESSED`; PI 2.0 plan may later add Google-demand evidence — leave an input slot, no invention |
| **Shared CEO files.** | CEO-A 3.0, CEO-B 3.0, CI 4.0, PI 2.0 and CFO 3.0 plans all touch `orchestrator.py`, `intent_router.py`, `input_session.py`, `registry.py` | Keep CMO additions in new modules; make only thin registrations in shared files; rebase often; no reformatting of shared files |
| **Dashboard is read-only by contract.** | Adding score/preview/edit buttons would break "no generate buttons" | New views are read-only; any action stays a CEO chat request |
| **CI 4.0 will also change CI→CMO hand-off** (`CI_4.0_Plan.md` item 12). | Two teams editing the same hand-off | Treat `competitor_listing_insight` columns as the stable interface; do upgrade 4 after reading the CI 4.0 spec |
| **Approval invariants.** | Typed "yes" must never approve; plan hash binds the click | Every new paid/model step is a normal plan card; no new auto-run chain |
| **Coupled enum/migration/billing change** (new artefact types). | Drift fails the build or breaks metering | One migration + one PR per new type, with the schema-constraint test |

---

## 6. Proposed changes by layer (all [P])

**Database (new migrations, `backend/migrations`, RLS `FORCE`, `tenant_id` + composite FKs, append-only where it is provenance):**
- `cmo_product_profile` / read view over `seller_fact` (M1).
- `cmo_keyword_candidate` (M2), `cmo_title_analysis` + `cmo_listing_audit` (M3/M5), `cmo_buyer_question` (M5), `cmo_listing_snapshot` + `cmo_listing_snapshot_item` (M7), `cmo_product_family` / variant columns (M8), `cmo_news_*` link/compare tables (M10). *Names are placeholders; final schema comes from the spec step.* No table exists today for any of these.
- New `cmo_platform_config` keys (never defaulted) for preview widths and official domains.

**Backend (`packages/slim-cmo` for pure logic, `backend/src/backend` for wiring):**
- Deterministic scoring/audit modules in `slim_cmo` (pure, unit-tested, no I/O), services under `slim_cmo/service`, wiring in `backend/services/cmo_*.py`, handlers in `api/v1/cmo.py`.
- Registration in `registry.py`, `effects.py`, `plans.py`, `input_session.py`, `intent_router.py`, `cmo_delegation.py`, `ceo_eval/catalog.py`.

**Frontend:** extend `ShowcaseDashboard.tsx` read-only (analysis breakdown, preview, history compare, readiness), plus CEO chat card types if a pick/preview card is needed (`components/ceo/hub/*`). Dark theme only today; colours per CLAUDE.md (green verified, amber estimate, red risk; status never colour-only; no pulsing/count-up).

**CEO integration:** each new capability = a closed action key, a plan card with an exact "what leaves Metrion" line, `agent.cmo` permission, entitlement meter decision, and a result footer that states evidence status.

---

## 7. Milestones (ordered by technical dependency)

Complexity: S ≈ days, M ≈ 1-2 weeks, L ≈ 2-4 weeks, XL ≈ > 4 weeks (one engineer, including tests). These are rough, unproven estimates.

### M0 — Stabilise and close the verified gaps (CMO 3.0 "Phase 0")  — **BUILD FIRST** — Complexity M
**Why first:** every new feature stands on title selection, product identity and history reads, and three of those are currently unreachable from chat.
- M0.1 Decide and verify product identity (`sku`) in the chat flow; add a test that a chat-generated result appears on the dashboard and its facts are reloaded next conversation.
- M0.2 Wire `cmo.approve_title` into chat: after a title set, a choice step (pick / edit) records `cmo_title_approval`; copy pack then grounds on `APPROVED_TITLE`. Keep "typed yes never approves".
- M0.3 Wire `cmo.confirm_image_hint` so photo hints become `SELLER_PROVIDED` facts by click, not retyping.
- M0.4 Route catalog Q&A (`cmo.catalog_answer`) into chat with an input table and intent rule.
- M0.5 History read in chat (Scene 7), including "copied ≠ approved ≠ live on Amazon" wording.
- M0.6 Run all CMO integration suites on a clean scratch DB; record results.
- M0.7 Correct stale docs (`CMO_details.md`, `ceo_hub_cmo.py` docstring) — after your approval.
- **Blockers (human input, not code):** verified `format_constraint` rows with counting rule per marketplace; trend config values; vision pass-bar decision; provider keys.
- **Acceptance:** test IDs O-04, O-06, O-10, O-18 and the regression set R-01…R-12 in `CMO_ACCEPTANCE_TESTS.md`.
- **Migration:** none expected (all tables exist) — confirm in M0.1.

### M1 — Smart Product Intelligence (Upgrade 1) — Complexity M — depends on M0.1
Product profile read model with per-attribute provenance and history; CEO "I found your saved profile" step; profile stays append-only. Also fixes the variant-ready identity (design only; variants themselves are M8).
- **Acceptance:** N-01 and R-04, R-09.
- **Migration:** small; may be a view over `seller_fact` plus an identity table — decided in the spec step.

### M2 — Evidence-backed Keyword Intelligence (Upgrade 2) — Complexity L — depends on M1
Deterministic relevance (fact match), placement (title / bullet / description / backend), intent label (rule list), confidence, evidence refs (seller fact, CI theme, confirmed niche term). Volume/demand = `NOT_ASSESSED`. Unconfirmed attributes (insulated) are listed as **excluded with reason**.
- **Acceptance:** N-02, N-02b, R-05.
- **Migration:** new candidate table.

### M3 — Five-Title Quality Analyzer (Upgrade 3, titles) — Complexity L — depends on M2
Store the strategy label per option; per-dimension results (keyword relevance, buyer intent, positioning, readability) computed in code; hard failures reuse claims/forbidden/format gates; `NOT_ASSESSED` when evidence is missing; recommendation = rule-based tie-break, explained. Methodology document written and approved **before** coding (Open Q1, Q2).
- **Acceptance:** N-03, N-03b, N-03c, R-05, R-06.
- **Migration:** analysis table; no change to `rank`.

### M4 — Search Result & Mobile Preview (Upgrade 8) — Complexity S–M — depends on M3 data only for display; can run in parallel with M3 after the config decision
Truncation model from **verified** width config; read-only preview component; always labelled simulated.
- **Blocker:** verified display-width source per marketplace/device (**[U]**; not in any table today).
- **Acceptance:** N-04.

### M5 — Buyer Questions (11) + Readiness Checklist (12) + full listing audit (3) — Complexity L — depends on M1, M3
Questions framed as "to investigate"; checklist aggregates blockers / missing facts / optional / next actions; unrun checks show `NOT_ASSESSED`; final status can only say "Draft generated; readiness not verified" unless every required gate ran.
- **Acceptance:** N-10, N-12, N-11, R-06.

### M6 — Advanced Listing Generation (5) + structured CI evidence (4) — Complexity L — depends on M2, M3, M5
Pack generated from selected strategy, keyword placement plan and buyer needs; competitor differentiation only through the existing CEO broker, and only for features the seller confirmed; audit runs after generation. Re-read the CI 4.0 spec first.
- **Acceptance:** N-05, N-08, R-07, R-08.

### M7 — Listing History & Optimization (6) — Complexity L — depends on M0.2, M6 (CMO 3.1)
Product-linked snapshots, version compare with a deterministic diff and an explanation of changes, revision lineage. **No improvement claim without performance data**; store a slot for future comparable-period feedback.
- **Acceptance:** N-06.

### M8 — Product Variant Intelligence (10) — Complexity L — depends on M1 (CMO 3.1)
Family with shared facts, variant facts kept separate, hard guard against mixing (500 ml vs 1 L), tests that a variant fact never leaks into a sibling.
- **Acceptance:** N-09 (the fact-leak tests are the key ones).

### M9 — Product Image Quality Advisor (9) — Complexity XL — depends on M0.3 (CMO 3.1, riskiest)
Separate quality schema, local vision model, **evaluation before trust** (same discipline as the existing gate). Until an evaluation passes, output is "advisory hint". No image ⇒ "pending, needs actual images".
- **Blockers:** vision model quality bar (spec Q4 still open); multi-image decision (Q7).
- **Acceptance:** N-07.

### M10 — Market Opportunities (7) + News enhancements 14.1–14.5 — Complexity L–XL — depends on M1, M7; coordinate with CEO-B 3.0 (CMO 3.1)
Order inside: 14.1 relevance filter → 14.4 change tracking → 14.2 policy alerts (needs official domains) → 14.3 news-to-action → 14.5 conversational Q&A (last; overlaps the CEO-B conversational layer — build on its interface, don't duplicate).
- **Acceptance:** N-13, NEWS-1 … NEWS-5.

### Dependency picture
`M0 → M1 → M2 → M3 → M5 → M6 → M7`; `M4` after M3's config decision; `M8` after M1; `M9` after M0.3; `M10` after M1 + M7. M3 and M4 can overlap; M8 and M9 can run alongside M7.

---

## 8. Regression risks and migration requirements

- **Schema drift test:** `tests/integration/test_schema_constraints.py` compares enums to DB CHECKs — every new artefact type must update both.
- **Billing:** a new artefact type needs an entry in `billing.EVENT_KIND_BY_OUTPUT_TYPE`, `ACTION_OUTPUT_TYPE`, an entitlement meter decision, and idempotency semantics. Decide whether analyses are *free* (derived from an already-paid artefact) or metered **before** writing code (Open Q3).
- **CEO guard-count tests** (`test_ceo_registry`, `test_ceo_effects`, `test_ceo_architecture`) count registered actions — update them in the same change.
- **Migrations:** all additive, new tables with `FORCE` RLS and `tenant_id`; never alter `cmo_generation` constraints in place; run on scratch DB first, with downgrade tested. Migration head today is `20261021_0024_message_pick_kind.py` (backend) and `20261006_0003` (slim-cmo package); note two migration trees exist — decide which tree owns new CMO tables in the spec step **[U]**.
- **Frontend:** keep `?fixture=1` fixture out of production builds (`NODE_ENV` guard).
- **Existing 2183 + 236 + 8 tests must stay green after every milestone.**

---

## 9. Blockers and open questions (decisions are yours, not mine)

| # | Question | Needed by |
|---|---|---|
| Q1 | May dimension "scores" be computed by deterministic rules in code (my recommendation), shown as bands plus rule lists? Or do you want numeric 0-100? If numeric, who signs off the methodology? | M3 |
| Q2 | Is an LLM allowed to *classify* buyer intent into a fixed label set (validated, no numbers), or rules only? | M2/M3 |
| Q3 | Are analyses/audits free, or do they use CMO units? | M3 |
| Q4 | Source of truth for mobile/desktop truncation widths per marketplace | M4 |
| Q5 | Official policy domains for Amazon India / Flipkart / Meesho | M10 |
| Q6 | Verified `format_constraint` rows and trend config values (spec Q15, Q21) | M0 / launch |
| Q7 | Vision pass-bar and image-quality criteria (spec Q4); multiple images (Q7) | M9 |
| Q8 | Which migration tree owns new CMO tables | M1 |
| Q9 | Where listing "performance feedback" will come from (Data foundation / analytics), since CMO has none | M7 |

---

## 10. Verified vs proposed vs unknown — one-line summary

- **Verified:** the engine, gates, billing, CI broker, trends and read-only dashboard exist and their unit tests pass; five capabilities lack chat wiring; none of the 12 upgrades beyond partial CI/keyword/history pieces exists.
- **Proposed:** M0–M10 above, deterministic scoring, additive tables.
- **Unknown:** live model behaviour, live providers, database contents/config, SKU assignment in chat, integration-test results, preview widths, official domains.

---

## 11. M0 result (2026-10-30, branch `feat/cmo-3-m0`, nothing committed)

M0.1 product identity, M0.2 title choice, M0.3 photo-hint recording, M0.4 catalog Q&A + property questions, M0.5 history, M0.6 integration run + readiness check, M0.7 stale docs: **done and tested**. Authority: `docs/specs/ceo-cmo-delegation.md` §6.12. The final report in the conversation lists files and test counts.

**One external blocker remains and is not code:** the development database has **no `VERIFIED` marketplace rule rows** (`verify_cmo_readiness.py` reports AMAZON, FLIPKART and MEESHO blocked). Real generation fails closed (`COUNTING_RULE_UNVERIFIED`) until a human loads rules read from the marketplaces' own seller pages with `seed_format_constraints.py`. Tests use `TEST_FIXTURE` rows. Metrion must not invent these limits.

## 12. M1 result (2026-10-30)

Smart Product Intelligence is implemented as a read model over `seller_fact` (no table, no migration). Authority: `ceo-cmo-delegation.md` §6.13. Open decision: whether an "older than N days, please re-confirm" window is wanted, and its value.

## 13. M2 result (2026-10-30)

Keyword Intelligence implemented: pure rules + one append-only table (`cmo_keyword_analysis`, migration `20261030_0004`), zero units, no model. Authority: `slim-cmo-agent.md` §6.14. Open: metering decision, retention, a demand source. Release blocker B5 added: a real run with saved competitor rows.

## 14. M3 result (2026-10-30)

Five-Title Quality Analyzer with a deterministic **0-100 Title Quality Score** (keywords 25, confirmed facts 25, readability 20, buyer intent 15, structure 15; bands 80/65/50), implemented as pure integer rules + one append-only table (`cmo_title_analysis`, migration `20261030_0005`), zero units, no model. Authority: `slim-cmo-agent.md` §6.15 (full scoring rules there). Marketplace compliance is separate (PASS / FAIL / NOT_ASSESSED); unsupported claims are hard failures never recommended; missing evidence is NOT_ASSESSED and left out of the score, never zero. Open question Q1 is resolved by the owner's instruction: numeric 0-100.
