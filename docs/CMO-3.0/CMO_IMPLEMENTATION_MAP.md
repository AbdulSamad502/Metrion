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

### M6 — Advanced Listing Generation (5) + structured CI evidence (4) — Complexity L — depends on M2, M3, M5 (all done)
**Status (2026-10-31): implemented and tested, uncommitted; not manually verified in a browser; not release-ready. See section 18.** Specified and approved 2026-10-30. Authority: `slim-cmo-agent.md` §6.18 and `ceo-cmo-delegation.md` §6.16. Tests: `CMO_ACCEPTANCE_TESTS.md` §F (50 designed tests). Every decision is approved: Q8, Q26-Q33 (§6.18.10). B1 is relaxed for M6 only (§6.18.11): title steps inside a full-listing request and the listing itself may be generated on a labelled, unverified-rules basis when `listing_unverified_rules_enabled` (default `false`) is on, with `rules_unavailable_bullet_target = 5`; C13 is unchanged for everything else.

**Scope (what the seller gets).** After the seller has an approved title: ONE separate plan card for a complete listing; a coordinated pack (title verbatim, bullets, description, keywords), Amazon backend terms (Amazon only), optional hashtags (off by default); a deterministic keyword map; a free deterministic audit with severity findings; competitor evidence kept apart as "supported" vs "consider adding if true"; section revision (own text free, model rewrite one unit) with re-audit. No publishing, no bulk, no score, no new CI path.

**Dependencies.** M1 (facts), M2 (candidates), M3 (title strategy and hard failures), M5 (question states, readiness), the CEO plan-card/approval machinery, the CI broker (`cmo_ci_inputs.py`); no dependency on M7-M10 or on any CI change. Config: the two keys of §6.18.11 (data, not a migration).

**Reuse (do not rebuild).** `generate_listing_copy` and `service/generate.py` (atomic validation), standalone backend terms and hashtags, claim/forbidden/safety gates, M1 facts, M2 `cmo_keyword_analysis`, M3 per-option strategy and hard failures, M5 question states and readiness, `cmo_ci_inputs.broker/load_inputs`, `CiInputs`, `check_output`, `run_billable`, the CEO plan-card and approval machinery, `ceo_eval/catalog.py` patterns.

**Build order (each step end to end, tests with it).**
1. Pure rules in `slim_cmo` (no I/O): keyword map, the 15 audit checks A01-A15 with thresholds W1-W7 (`audit/limits.py`, `method_version`), claim-gated CI evidence rows, contradiction check, section-edit parser (§6.18.7a), rules-basis resolution (verified row > unverified basis > blocked) and its two config readers. Unit tests first.
2. Generation input: M2 candidates as the only keyword source, "do not claim" list from M5, `SUPPORTED`-only CI themes in the prompt; retry trigger on non-traceable keywords. Fake-provider tests.
3. Service + persistence: `cmo_listing_audit` (slim-cmo tree, `20261030_0007`), orchestration of pack → backend terms → hashtags → audit with per-artefact idempotency keys, partial-outcome handling, revision (`revision_of` in `output_structured`).
4. Backend wiring: closed action `cmo.generate_full_listing` and the revision actions in `registry.py`, `effects.py`, `plans.py`, `input_session.py`, `intent_router.py`, `cmo_delegation.py`, `evidence.py`, `ceo_eval/catalog.py` (thin registrations; logic in new `backend/services/cmo_listing.py`); backend migrations `20261030_0027` (`LISTING` card kind) and `20261030_0028` (`APPROVED` usage event kind); update the guard-count tests in the same change.
5. Frontend: `LISTING` card in the CEO chat (sections with copy buttons, keyword map, audit by severity, CI evidence, three labelled measures, the unverified-rules banner, the "Approve for use" button; the six states shown separately). Dashboard unchanged and read-only.
6. Run §F and the regression set on the scratch DB; report.

**Shared-file risk.** CEO-A/B, CI, PI and CFO plans edit the same CEO files: keep additions to one action family and one card kind, no reformatting, rebase often. CI 4.0 may change the CI→CMO hand-off: M6 consumes only today's `competitor_listing_insight` columns and adds none.

**Completion criteria.** Every §F test passes or is explicitly deferred in writing; R-15…R-19 green; M0-M5 suites unchanged (backend unit 5575, slim-cmo unit suite, frontend); migrations upgrade and downgrade on the scratch DB; no change to the dev database; blocker list updated honestly. With the rules-unavailable basis, real drafts are possible without verified rules (labelled, nothing claimed as compliant); M6 is "done" for development when the section F tests pass, and "release-ready" for any compliance or readiness claim only after B1, B2, B6, B7 are cleared.

- **Acceptance:** N-05a-x, N-14a-j, N-15a-g, N-16a-c, N-08a-f, R-07, R-08, R-15…R-20 (50 tests in section F).

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
- **Migrations:** all additive, new tables with `FORCE` RLS and `tenant_id`; never alter `cmo_generation` constraints in place (single owner-approved exception, M6 migration `20261030_0007`: the constraint-reference CHECK is replaced, not edited, with a COALESCE-guarded equivalent; see spec 6.18.8); run on scratch DB first, with downgrade tested. Migration head today is `20261021_0024_message_pick_kind.py` (backend) and `20261006_0003` (slim-cmo package); two migration trees exist; ownership follows the convention recorded in spec §6.18.8 (resolved Q8).
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
| Q8 | ~~Which migration tree owns new CMO tables~~ **Resolved 2026-10-30 by repository convention:** tables written by the CMO package's rules and services go in `packages/slim-cmo/migrations` (M2-M5 precedent); CEO-conversation, quota and usage-event tables go in `backend/migrations` (`0020`, `0025`, `0026` precedent). See spec §6.18.8. | M1 |
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

## 15. M4 result (2026-10-30)

Search Result & Mobile/Desktop Preview implemented end to end: pure truncation rules, a free backend card builder over the M3 analysis, a `PREVIEW` card on the CEO answer (migration `20261030_0025`), an authenticated images-only route for the seller's own photo, and an interactive React card in the CEO chat. Authority: `slim-cmo-agent.md` §6.16. Verified display widths do not exist, so previews are labelled illustrative (release note B6).

## 16. M5 result (2026-10-30)

Buyer Questions and Listing Readiness implemented end to end: pure question and readiness rules, two append-only tables (`20261030_0006`), a free card builder reusing M1-M4, a `READINESS` card on the CEO answer (`20261030_0026`), the seller's own answers saved by one fixed sentence, and an interactive React card in the chat. Authority: `slim-cmo-agent.md` §6.17. READY cannot appear while no verified marketplace rule or category taxonomy exists (B1).

## 17. M6 specification result (2026-10-30, final)

M6 is specified and every decision is approved; it is not built. Authority: `slim-cmo-agent.md` §6.18 (rules, audit checks A01-A15, thresholds W1-W7, edit grammar, six-state model, CI evidence, data ownership, rules-unavailable basis), `ceo-cmo-delegation.md` §6.16 (chat), `CMO_ACCEPTANCE_TESTS.md` §F (50 tests), `CMO_RELEASE_BLOCKERS.md` (B1 exception). Decisions recorded: Q8 (migrations `20261030_0007` slim-cmo; `0027` and `0028` backend), Q26-Q33 including `listing_unverified_rules_enabled = false` by default and `rules_unavailable_bullet_target = 5`. Inspection findings that shaped it: the copy pack, backend terms, hashtags, CI broker and originality check already exist; CI supplies only derived single words (no new contract); the title strategy is already stored by M3; `cmo_generation.output_type` needs no new value; keyword-field atomicity forces `NEEDS_FACTS` when M2 has no recommended candidate. The handoff's test IDs already existed here with other meanings, so the new tests use N-05a…, N-14…, N-15…, N-16…, N-08a… (mapping at the top of §F).

## 18. M6 implementation result (2026-10-31; committed 26d5089, gap closure in the following commit)

**Built.** Complete listing (`cmo.generate_full_listing`, `POST /api/v1/cmo/full-listing`): copy pack, Amazon backend terms and optional hashtags, each billed on the proven per-artefact path (`cmo_actions.run_billable`, derived request keys, no change to shared billing). Free after that: the 15-check audit (one immutable row per version, `cmo_listing_audit`), the keyword map, claim-gated competitor evidence, the six distinct states. Seller-written edits (`Change bullet 3 to: ...`, free) and the model rewrite of one bullet or the description (`cmo.rewrite_listing_section`, `POST /api/v1/cmo/listing-rewrite`, owner decision Q26: exactly 1 unit, only when delivered) both create a NEW immutable `LISTING_COPY` version through the same deterministic gates; the earlier version and its approval are untouched and an approval never carries to the new version. "Approved for use" is a click on the card only (append-only `APPROVED` event, 0 units, refused when the audit is BLOCKED). The rules-unavailable basis is server-marked, off by default (`listing_unverified_rules_enabled`), labelled on the card, and never exceeds CHECKED_NOT_VERIFIED. The LISTING card rides on the CEO answer (full listing and rewrite).

**Rewrite specifics.** Before any plan card the CEO checks, by code and free: the seller's latest saved listing for that product and marketplace exists, the section exists (bullet n or description; title, keywords and backend terms are never model-rewritten), and the topic is carried by ONE confirmed, claim-eligible fact (`preconditions.topic_supported`) and is not an unconfirmed buyer-question topic. The plan card shows the 1-unit cost. The candidate must mention the topic, differ from the current text, and pass `revise.check_edit` (unsupported claims, unconfirmed topics, unsupported numbers, contradictions, forbidden content, competitor originality). A rewrite that cannot pass is a FAILED row (no text kept, 0 units).

**Migrations.** slim-cmo `20261030_0007` (`cmo_listing_audit`; the `cmo_generation` constraint-reference CHECK replaced by a COALESCE-guarded equivalent, owner-approved; downgrade refuses safely while unverified-basis artefacts exist). Backend `20261030_0027` (`LISTING` card kind) and `20261030_0028` (`APPROVED` usage kind; downgrade refuses while approvals exist). Upgrade, downgrade and re-upgrade tested on the scratch database. Rewrite needs no migration.

**Tests (scratch DB; shared dev DB untouched).** slim-cmo unit 2537 passed; slim-cmo integration 237 passed; backend unit 5604 passed, 6 xfailed; backend integration `-k cmo`: 614 passed, 1 skipped, 3 failed in the final full run, of which 1 is the pre-existing stale `test_ceo_hub_cmo` guard and 2 are an intermittent pre-existing ordering flake (below); every flaky test passes when rerun; frontend 1081 passed (119 files); `tsc --noEmit` clean; the three no-float lints clean. Rewrite alone: 14 service unit, 38 API integration, 15 CEO chat integration.

**Known pre-existing defects found (not caused by M6, not fixed here).** (1) `tests/integration/test_ceo_hub_cmo.py::test_exactly_the_registered_cmo_actions_are_dispatchable_and_all_are_recommend_only` expects a set that lacks `cmo.keyword_intelligence` and `cmo.analyze_titles` (added in M2/M3). (2) [FIXED in the M6 gap-closure commit, see below] Intermittent CEO input-session loss: `investigation_message` was ordered by `(created_at, id)` and a CEO question and the seller's next message can carry the identical timestamp, so the random id decides which is last and the answer is sent to the classifier. Observed with instrumentation (identical `created_at` on a CEO CLARIFICATION and a USER message). Roughly 1 to 5 failures per 600 integration tests, in M0-M6 chat tests alike. The fix is the monotonic tie-break described under "M6 gap closure".

**Not done / limits.** No real-model LLM eval (R-18) and no complete browser-based manual verification (R-19 colour contrast and keyboard review) were run. (N-15d and the row-by-row traceability, listed here before, are closed below.) The ListingCard has no dedicated rewrite button: a rewrite is asked in chat. Release blockers B1 (relaxed for M6 only), B2, B6, B7 are unchanged.

**M6 gap closure (2026-10-31).** (1) **N-15d implemented**: a saved listing is flagged "built from a previous title" only after the seller APPROVES a different title for the same product and marketplace (read-only rule `slim_cmo.listing.title_currency`, on demand; nothing stored, regenerated or relabelled; a typed or missing title is UNKNOWN, never OUTDATED; the card, the CEO title-approval fact and the approval response carry it). (2) **Message-order race fixed**: root cause proved with instrumentation (a seller message and the CEO reply share one app-stamped `created_at`, the random id decided the order); backend migration `20261031_0029` adds an identity column `seq` and an index, messages are read by `(created_at, seq)`. (3) **Traceability**: `CMO_M6_TRACEABILITY.md` traces all 50 section F rows to tests (42 COVERED, 8 PARTIAL, 0 MISSING after the second pass) and lists two defects it found and fixed (a typed title showed an M3 strategy; a title-less pack with missing facts was not refused). Tests added: slim-cmo unit 2547 passed (final M6 closure run); backend unit 5605 passed, 6 xfailed; frontend 1081 then 1101 passed after M7; full backend integration on a scratch database: 3212 passed, 7 skipped, 14 failed and 1 intermittent error. **All 14 failures fail identically at commit 26d5089 on a clean database** (existing, not from M6 or the closure: the stale `test_ceo_hub_cmo` guard, CEO availability/campaign-safety/presentation/period/inventory tests, `test_ci_end_to_end_flow`, the accounting downgrade timeout); the single error (`test_planner_ledger_answers_are_tenant_isolated`, a dropped DB connection) passed on rerun. Browser: the real signed-in CEO Hub was reached; the previous-title warning could not be shown because the development tenant has no saved listing (it was not created, to avoid writing to the seller's records); the card is verified by component tests only.


## 19. M7 implementation result (2026-10-31, uncommitted)

**Status: implemented and automatically tested; browser verification: see "Browser" below; not release-ready (B1, B2, B6, B7, B8 remain).** Authority: `slim-cmo-agent.md` §6.19 and `ceo-cmo-delegation.md` §6.17. Acceptance: `CMO_ACCEPTANCE_TESTS.md` §G (M7-01 … M7-70, traced row by row).

**What M7 is.** A read-only, free, deterministic layer over the M6 versions: listing history, revision lineage, an exact comparison of any two versions, keyword movement, new-claim and audit changes, evidence-based suggestions and a performance-integrity block, reachable in the CEO chat and in a history card. It creates no listing, calls no model, uses no unit and adds **no table**.

**Backend.**
- Pure rules `packages/slim-cmo/src/slim_cmo/history/`: `diff.py` (word/list/sentence/term differences), `lineage.py` (numbers, parents, source, invalid links), `compare.py` (comparison, keyword movement, audit diff, new claims, attribute changes, repetition), `recommend.py` (deterministic suggestions), `performance.py` (NOT_ASSESSED / OBSERVED_COMPARABLE / INCOMPARABLE), `ask.py` (the closed set of chat requests).
- Service `backend/src/backend/services/cmo_history.py` (history, version detail, compare, recommendations; reads the saved audits, saves the free M6 audit only for a version never opened) and read queries appended to `repositories/cmo_chat_repo.py` (`history_rows`, `latest_keyword_analysis`).
- API (all `GET`, `agent.cmo`): `/api/v1/cmo/listing-history`, `/listing-history/{id}`, `/listing-history/compare`, `/listing-history/{id}/recommendations`.
- CEO: `ceo/cmo_history_chat.py` + one step in `ceo/orchestrator.py` after the M6 listing step. No registry action, effect, plan, input session or evaluation-catalog entry (same as the M4/M5/M6 reads).

**Database.** Backend migration `20261031_0030` only (widens the card-kind constraint to allow `LISTING_HISTORY`; downgrade deletes nothing and adds the older constraint `NOT VALID` because FORCE RLS hides existing rows from the migration role). Reused: `cmo_generation`, `cmo_listing_audit`, `cmo_result_usage_event`, `cmo_keyword_analysis`, `cmo_title_approval`. Verified on a scratch Postgres: upgrade, downgrade, re-upgrade, M6 card kinds untouched, no M6 table altered.

**Frontend.** `ListingHistoryCard.tsx` (timeline with product/marketplace filters, paging, version details, two-version picker, suggestions, one-question prompt, loading / empty / one-version / error with retry / unauthorised / missing states) and `ListingCompareView.tsx` (title, bullets, description, keyword table, audit changes, new claims, performance block; every change is a word and a mark, never colour alone). Wired through `Conversation.tsx`, `CeoHubWorkspace.tsx`, `lib/ceo.ts` (`historyApi`), `test-support/fakeCeo.ts`.

**Decisions and limits (so nobody over-reads M7).**
- The fourth revision source in the brief ("subsequent optimised version") has no producer in M6, so no version is ever labelled optimised; an unrecognised stored marker is shown as "a revision, source not recorded".
- Metrion records how and where a version changed, not why; "why was this revised" says so.
- M7 never says a revision helped. Performance is `NOT_ASSESSED` in the product: no uploaded sales or traffic report is wired to listing versions (new blocker B8), and Metrion cannot see when a change went live. The comparable / incomparable rules are implemented and unit-tested only.
- Buyer-question and keyword evidence come from the same M1/M2/M5 sources the M6 audit uses (the newest saved M2 analysis when there is one; else computed from the confirmed facts, with no candidate id).
- Recommendations use no model; there is no LLM reasoning in M7.
- Looking at a version that was never opened saves its free M6 audit (the same row opening its card saves); nothing else is written.

**M7 tests and browser.** slim-cmo unit: 34 new engine tests (2602 pass in total, mutation-checked: moved-as-removed, claim detection, reorder and cycle checks each make tests fail); backend unit 5616 pass, 6 xfailed (route-surface and request-contract guards updated for the four read routes; the architecture guard declares the new CEO module's seam); backend integration on a scratch database: M7 API 24, M7 CEO chat 15, M7 migration 2, and the whole `cmo` selection 698 passed with 1 failure, the existing `test_ceo_hub_cmo` guard; frontend 121 files, 1101 tests pass (15 card tests + 2 hub tests new), `tsc --noEmit` and eslint on the changed files clean. Browser: the signed-in dev CEO Hub answered "Show my listing history" with the empty-history message and "what can you do?" normally; history, version, comparison and suggestion views were inspected only on a temporary fixture page. Not browser-verified: the card against real saved versions, keyboard walk-through, colour contrast.

**M6 + M7 second coverage pass (2026-10-31).** M6 Section F: 42 COVERED, 8 PARTIAL, 0 MISSING (N-05j now covered end to end; N-05g, N-05l, N-14g gained assertions but keep their stated gaps: no WEAK-candidate fixture, `NEEDS_SELLER_INPUT` and the side-by-side M3/M5 card are not implemented; N-05b, N-15g, N-16a, N-16c are unimplemented chat features). M7 Section G: **68 COVERED, 2 PARTIAL, 0 MISSING (70)**; the earlier "47 / 23" figure in a status message was wrong, the document itself had 58 / 12 before this pass. The 10 rows raised (M7-06, 14, 15, 18, 35, 38, 41, 42, 46, 57) are backed by `test_cmo_m7_history_more.py` and one added CEO chat test; M7-51 and M7-52 stay PARTIAL. One behaviour fix: a stored parent that belongs to another product or marketplace is now reported as `CROSS_PRODUCT` / `CROSS_MARKETPLACE` (it used to read as `MISSING_PARENT`). **B8 investigation:** `sales_line` (uploaded settlement/sales data) holds a marketplace SKU, order date, quantity and amounts, but nothing maps that marketplace SKU to the CMO product identity (`sku` slug), and Metrion does not know the date a listing version went live; any join would be a guess, so performance stays NOT_ASSESSED and B8 stays open. **Revision source:** no producer exists for an "optimised" version; the history shows only ORIGINAL, SELLER_EDIT, AI_REWRITE and "source not recorded".

**Browser verification status (2026-10-31, real signed-in dev session, manual dev database; stopped by the owner before completion).** VERIFIED: empty history answer; normal CEO question; refusal before any plan when confirmed facts are missing (nothing charged); a real-model title set written through the CEO (qwen3:8b, 1 unit, after one earlier run failed because the model timed out at 120 s); title choice saved; the itemised full-listing plan card (cost up to 2 units, audit free) with Approve bound to the card and Decline spending nothing. BLOCKED / NOT RUN: the generated LISTING card and 15-check audit display, seller edit, rewrite request and its topic refusal, rewrite approval, approve for use, copy, the previous-title warning, history timeline, product and marketplace filters, version details, comparison, keyword and audit differences, suggestions, CEO history and compare requests against real saved versions, loading and error states against a real server, keyboard walk-through, colour contrast. Earlier and separate: the history card was seen on a temporary fixture page at the pane width and at 375 px (no horizontal overflow), which is not real-data verification. **Open observation (not fixed, not confirmed as a defect):** after typing "1" at the title question the plan card read "Your title: 1"; whether the written listing then used the approved title or "1" was not checked. A parser change to refuse a bare number was tried and reverted because the typed number never reached that parser (the orchestrator maps it to the option first), so the real cause is unknown. **Side effects in the dev tenant:** saved facts and one approved title for "AquaNest 1 Litre Stainless Steel Water Bottle", one completed and two failed title sets, 1 CMO unit used, and one approved full-listing plan whose generation had not been seen to finish.

**Readiness, stated separately.** M6: implemented; unit tested; integration tested; database verified (scratch DB, upgrade/downgrade/re-upgrade of 0029); frontend tested; browser verified only in part (above); acceptance 42/50 covered; not production ready (B1, B2, B6, B7). M7: implemented; unit tested; integration tested; database verified (0030 up/down/up, RLS, tenant isolation on the scratch DB); frontend tested; not browser verified on real data; acceptance 68/70 covered; not production ready (B8, B7, B1, B2, B6; no producer for an optimised revision source).

**M6 + M7 final closure (2026-10-31).** M6 Section F is now **47 COVERED, 3 PARTIAL, 0 MISSING (50)**; M7 Section G stays **68 COVERED, 2 PARTIAL (M7-51, M7-52)**. Closed: N-05g (WEAK candidate fixture), N-05l (Flipkart card shows `NEEDS_SELLER_INPUT`), N-14g (the card shows title check, audit and readiness as three separate measures; NOT_ASSESSED carries no value), N-15g (an edit naming neither product nor marketplace asks which when more than one listing exists; loose requests such as "make bullet 2 shorter" are never guessed and the seller is told the exact words), N-16c (a title over a verified limit is refused naming the limit and the title's length, in the API and in chat before any plan card). **Defect fixed:** a bare number typed at the title question was stored as the title "1"; it now selects the Nth listed choice's real text, a number with no such choice or a choice that is no longer current is refused and re-asked, and the plan and the generated listing carry the real title. The title question also says when no title is approved yet. **Still PARTIAL (need a design decision, not built):** N-05b / N-16a (title set, selection and approval run inside the listing request through the chat) and N-05t (an approval row for a typed title, which would need a title-set generation to hang from). **M7-51 / M7-52 / B8:** unchanged, no mapping or go-live date exists; performance stays NOT_ASSESSED. **Tests:** backend unit 5614 passed; slim-cmo 2917 passed; CMO/CEO integration selection 733 passed (one run after all changes) plus the new chat edit/limit file 7 passed; frontend 1104 of 1105 with the timeout raised (one timing-dependent test, `piShowcase`, passes alone); at the default 5 s timeout 12 to 23 unrelated tests time out under machine load. Frontend unhandled rejection: root cause is `components/cfo/ImportHistory.tsx` updating state after a test ended (CFO code, left alone). TypeScript clean; ESLint errors only in earlier code (`ListingPreviewCard.tsx`, `ceoHub.test.tsx`). **Migrations** (fresh database in the scratch container, full package chain then backend and slim-cmo): up to `20261031_0030` / `20261030_0007`, down to `0026` / `0006`, up again, all clean; the temporary database was dropped. The two tests that hardcoded port 5544 now use the configured scratch database. **Baseline:** the non-CMO remainder of the integration suite was started again but stopped at 72% (a hang in the known baseline area); the 13 baseline failures recorded earlier (identical at 26d5089 on a clean database) were not re-verified in this pass. No browser verification was done: BLOCKED — real-data browser verification not requested.

**M6 + M7 acceptance completion (2026-10-31).** M6 Section F: **49 COVERED, 1 PARTIAL (N-05t), 0 MISSING (50)**; M7 Section G: **68 COVERED, 2 PARTIAL (M7-51, M7-52)**. Built: the title steps inside the complete-listing request (N-05b, N-16a): title question option → title-set plan card (1 unit, server-frozen marker, unverified-rules sentence) → seller approves the plan → seller chooses a title (separate record, 0 units) → the request continues with its remaining questions → listing plan from the approved title (approval bound to the plan). Generation, selection and approval stay separate states and a typed title is never auto-approved: it must be confirmed as typed (N-05t). Wiring: `input_session` (sentinel option, confirmation field), `cmo_chat.title_step_inputs` / `listing_continuation` / `title_step_scope`, `orchestrator` (Done → title plan; continuation after `cmo.approve_title`), `approval_run` (runs the frozen title leg inside `full_listing_workflow()`); no migration, no new action key. **Not done:** an approval row for a typed title (needs a title-set generation or a data-model decision); M7-51 / M7-52 and B8 (still no product-to-marketplace-SKU mapping or listing go-live date; performance stays NOT_ASSESSED). Browser verification: BLOCKED — real-data browser verification not requested.

**M6 N-05t and M7 disposition (2026-10-31, static pass: nothing was executed).** *N-05t*: migration `packages/slim-cmo/migrations/versions/20261031_0008_typed_title_approval.py` (not yet run on any database) makes `cmo_title_approval.generation_id` nullable, adds `title_source` (`GENERATED` default for every existing row, `SELLER_TYPED`), `sku` and `marketplace`, one CHECK (`cmo_title_approval_source_check`) tying the kinds together, and an index for typed rows; downgrade refuses while a typed approval exists. Code: `approval_repo.insert_typed_approval` / LEFT-JOIN load, `PostgresStore.save_typed_approval`, `ApprovalService.approve_typed_title` (shared `_checked_text`, so the edited-title path is unchanged), `cmo_chat.record_typed_title_approval` (reuses an identical approved title), orchestrator step before the listing plan, `cmo_chat_repo` queries now COALESCE product/marketplace from the approval, `cmo_listing._typed_title` (a typed approval has no M3 strategy or title check). Consumers reviewed by reading: approved-titles list, current approval (N-15d), approval reference, listing history (LEFT JOIN already), readiness (reads approval text), showcase repo (joins through an option or `grounding_approval_id`, so typed rows do not appear in option views and do not break them). Not changed: generated-title approvals, the HTTP approval route, FORCE RLS, grants. *M7-51 / M7-52*: re-read the criteria and the code; nothing can be built without data that does not exist (SKU mapping, go-live date), so they stay PARTIAL and B8 stays open; the exact dependencies are in the acceptance rows. **Verification status:** N-05t's migration and tests have not been executed; M6 is 50/50 implemented, 49/50 verified.

**Final closure (2026-10-31).** *N-05t verified.* Migration `20261031_0008` on a fresh scratch database (full package chain, then backend): up to `20261031_0008`; six invalid rows rejected by `cmo_title_approval_source_check` (typed with a generation, typed without a sku, typed with an unknown marketplace, typed not worded by the seller, generated without a generation, unknown source); one valid typed row accepted; downgrade REFUSED while the typed row existed (`cannot downgrade: approvals of seller-typed titles exist…`, head stayed `0008`, row intact); after the test removed its own row, downgrade to `0007` removed the three columns and restored `generation_id NOT NULL`, and upgrade restored them. Focused tests (executed on a scratch database): `test_cmo_m6_typed_approval.py` 5 passed; `test_ceo_cmo_m6_title_chain.py` + `test_ceo_cmo_m6_title_pick.py` 13 passed; `test_ceo_cmo_m6_chat.py` + `test_ceo_cmo_m0_chat.py` + `test_cmo_m6_title_currency.py` + the architecture guard 311 passed; generated-title approval tests (`test_cmo_api.py -k approv` 4, slim-cmo approval unit tests 28, `test_m6_listing_audit_store.py` incl. the migration round trip 33) passed, so existing generated approvals are unchanged. One test-data defect was found and fixed in the new test file (a mismatched product identity). *Result:* M6 **50 of 50 implemented and verified**. *M7:* unchanged at 68 COVERED, 2 PARTIAL (M7-51, M7-52): no verified marketplace-SKU-to-product mapping, no seller-confirmed go-live date per listing version and no comparable equal-length periods exist; nothing safe can be built without them, so performance stays NOT_ASSESSED. Not run in this pass (by instruction): the full backend, frontend, slim-cmo and integration suites, and any browser check.
