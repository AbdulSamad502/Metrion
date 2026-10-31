# CMO 3.0 production-readiness report (M0–M8)

Date: 2026-10-31. Basis: commits `8ab58ea` → `a41ad8a` → `8e59f25` plus one uncommitted fix (§5). Evidence is automated tests on a scratch database with synthetic data, hand-run migration checks, static review, and one real-model evaluation on a local model. **No browser walkthrough, no real seller data, no seller-account access.**

**Decision: NOT PRODUCTION READY.** The engineering is in good shape; the release-blocking items are external (official marketplace evidence, a real-tenant browser run, real seller reports, a production-model evaluation).

## 1. Summary table

| Area | Status | Evidence | Required action |
|---|---|---|---|
| Functionality (M0–M8) | PASS (automated) / PARTIAL (real world) | M6 50/50, M7 70/70, M8 15/16 covered by automated tests; last runs: backend 432 (M8/B8/M7/guards) and 509 (six regression files + M8), slim-cmo 314, frontend 570 | A real-tenant browser run (B7) |
| Security / tenant isolation | PASS | Scratch DB audit: every table with a `tenant_id` column has FORCE RLS (0 exceptions); the one `cmo_*` table without it (`cmo_provider_usage`) holds platform-wide counters only and the app role has no grant on it; M8 tables verified by hand (cross-tenant insert rejected, no UPDATE/DELETE, FK and CHECK rejections); cross-tenant tests in B8/M8/M7 suites | None for engineering; DB role review before go-live is standard |
| Billing / idempotency | PASS (automated) | M8 routes and chat are zero-unit and footprint-tested (generations, units, model calls unchanged); no failed validation saves or bills (real-model eval: 0 units billed on every failure); billed M6 flows keep plan-card approval and request-key idempotency (existing suites) | Re-verify against live billing before go-live |
| Seller workflows | PARTIAL | Every M6–M8 workflow is covered through the real CEO chat in tests; explicit Save, replace-guard and "typing yes saves nothing" tested | Browser walkthrough with a test tenant (B7); real-classifier evaluation of free-text phrasing |
| Model quality | **FAIL for a production experience / PARTIAL evidence** | 6/15 completed on qwen3:8b (pooled 12/23); all failures safe | Stronger model or more repair, then a larger evaluation (B2) |
| Marketplace compliance | NOT ESTABLISHED | Register has one OFFICIAL_PARTIAL Amazon India title rule and no promotable row; every draft carries the unverified-rules banner; audit never says "compliant" | Official evidence (B1) |
| Performance intelligence | PARTIAL | Deterministic, coverage-gated, observational; verified on synthetic rows only | Real reports and real confirmations (B8) |

## 2. Review findings by area (M0–M8)

| # | Area | Finding | Class |
|---|---|---|---|
| 1 | Product facts (M0/M1) | Facts are the seller's own; "not confirmed" answers; sellers' words never invented. No defect found. | — |
| 2 | Keywords (M2) | Evidence-based, with NOT_ASSESSED for unsupported demand; unchanged. | — |
| 3 | Titles (M3) | Quality score and compliance are separate; compliance stays unverified without official rules. | External (B1) |
| 4 | Preview (M4) | Illustrative unless a rule is VERIFIED from an official host with ALL_CATEGORIES scope; none exists, so every preview is illustrative. | External (B6) |
| 5 | Buyer questions / readiness (M5) | Free, code-written; saves only the seller's own statements. | — |
| 6 | Listing (M6) | Generated, audited, approved-for-use, copied, used and published are separate states; approval is a click bound to one version; audit has no "compliant" verdict. Known gaps (documented): the typed-title approval row is written at plan time even if the plan is later declined; an HTTP title request with a bare typed title records no approval. | Engineering, low |
| 7 | History (M7) | Immutable lineage, read-only. M7 compare card still shows the older sales-order block and does not render the M8 `versionAnalysis` (it is on the performance page and in chat). | Engineering, low |
| 8 | Performance (M8) | **Defect found and fixed (uncommitted):** versions were read from the account-wide paged history, so a busy product could push a quiet product's older versions off the first page and hide them from the mapping and before/after views. Products are now read group by group (stub test). Remaining limit: one page (100) of versions per product. | Engineering — fixed |
| 9 | CEO routing | M7/M8 intents are closed regex sets placed before the generic classifier; phrasings outside them go to the normal CEO. A real classifier was never evaluated on CMO phrasing. | Verification gap |
| 10 | DB security | See table row; `cmo_niche_term` and `cmo_quota_reservation` keep UPDATE for the app role by earlier design (cache and reservation state transitions). | By design |
| 11 | Billing | No double-charge path found in review; M8 is free. Billing correctness under real load and real entitlement is not exercised. | Verification gap |
| 12 | Errors / persistence | Every refusal carries a plain `detail`; nothing is saved on a refused import/statement; imports are idempotent by file hash and record key. A wrong import cannot be corrected by the seller (design written, deferred). | Engineering, deferred |
| 13 | Frontend/backend | Request-contract snapshot test passes; UI tested with fakes; **never exercised together in a browser.** | Verification gap (B7) |
| 14 | Docs / release | Blockers, acceptance, rules register and M8 docs aligned with the code; migrations `20261031_0008/0009/0010` (slim-cmo) and `…_0031` (backend) verified up/down/up on scratch databases. Release procedure beyond that is the standard repository procedure. | — |

Cross-cutting checks: no model call in any deterministic module (grep of the M8 modules: none); no dashboard action writes data (the dashboard reads; saves are explicit POSTs behind a button); unknown data stays NOT_ASSESSED/UNAVAILABLE and a missing report row is never zero; no marketplace rule or metric is invented. No duplicate infrastructure was found: M8 reuses the B8 tables, the `performance.assess` check and the M7 history.

## 3. Release blockers

| Blocker | Final status | Evidence | Remaining action (who) |
|---|---|---|---|
| B1 marketplace rules | **OPEN (externally blocked)** | Public official pages yield one partial Amazon India title rule (≤200 characters for most categories, effective 2025-01-21, not promoted); Flipkart and Meesho official pages give no readable rule text without a seller login; third-party values stay hints. Register and exact checklist: `CMO_MARKETPLACE_RULES.md` | Seller/owner: supply, from each Seller Central / Seller Hub / supplier-panel account, the category listing templates and style guides listed in the checklist (no passwords: exports or screenshots with the URL and date) |
| B2 real-model quality | **OPEN (evidence extended; result is poor)** | Run of 2026-10-31 on the configured dev model `qwen3:8b` (Ollama, product `OllamaLlmProvider`, 1 internal retry), 3 controlled products x 5 runs: **6 of 15 completed (40%)** - AquaNest 4/5, BrightBeam lamp 1/5, CottonCo T-shirt 1/5. Pooled with the earlier 8 runs of the same pipeline: 12 of 23 (52%). The 9 failures were all SAFE (0 units billed, 0 listing rows saved, 0 failed texts stored); validator categories (runs affected): unsupported feature claim 5, repair shape 4, unsupported number 4, unsupported duration claim 3, unsupported energy claim 2, price claim 1, forbidden content 1. On the 6 completed: every keyword placed, 2 units billed each, audit CHECKED_NOT_VERIFIED, no deterministic claim/number/use-case hit, section rewrite changed only the asked bullet (6/6), unconfirmed-topic rewrite refused before any model call (6/6), soft filler words present in all 6. Meaning: with this model the safeguards hold, but roughly half of listing requests fail validation and need a retry - not acceptable as a production experience, and the sample is small and varies by product. Not evaluated: title generation at scale, other categories, seller-instruction classification (a real classifier), other models. Whether `qwen3:8b` is the intended production model is not recorded in the repository (it is the dev setting). | Owner: name the production model/configuration; run the harness on it over more products/categories and a classifier-level conversation set |
| B6 display rules | **OPEN (externally blocked)** | No marketplace publishes a title display (truncation) limit in readable official documentation; previews stay labelled illustrative | Owner: official documentation or measured, dated, per-marketplace evidence from a real live listing page |
| B7 workflow reliability | **BLOCKED** | No browser run: needs a signed-in test tenant. The standing rule forbids creating records in the shared development tenant; all verification is API/chat/component level | Owner: a dedicated test tenant (Clerk org) with synthetic data and permission to run one walkthrough |
| B8 performance attribution | **PARTIAL (engineering complete for synthetic data; real data missing)** | Seller capture (page + chat), window setting, import, coverage-gated before/after, replace guard, all tested | Seller: real marketplace performance reports (the exact export layouts) and real SKU/go-live confirmations; owner: confirm whether a missing row can mean zero for each marketplace |

Separate lists:
* **Engineering defects:** one fixed in this review (§2 row 8); two low-severity M6 gaps and one M7 display gap (rows 6, 7); imported-record correction deferred.
* **External dependencies:** B1, B6 (official evidence); B7 (test tenant); B8 (real reports); B2 (production model definition).
* **Real-world verification gaps:** browser run, real classifier on CMO phrasing, real billing/entitlement, real data.

## 4. Final programme pass (B1–B8), 2026-10-31

Scope decision recorded: no further model benchmarking was run in this pass (owner chose to skip it), so no new model evidence exists beyond §3 (B2). No marketplace research was repeated (the register and checklist in `CMO_MARKETPLACE_RULES.md` stand). No code, migration or test changed in this pass.

### B2 inspection facts (no benchmark)
Host: 15.7 GB RAM, 12 cores, no GPU/VRAM identified, so inference is CPU-only. Installed Ollama models: `qwen3:8b` (5.2 GB, the dev model), `qwen3:4b`, `qwen3.5:4b`, `llava`, `nomic-embed-text`. The product provider passes no temperature or context size (Ollama defaults) and uses `think=false` for qwen3. A tuned variant (`cmo-qwen3-8b-t02`: temperature 0.2, top_p 0.9, num_ctx 8192) was created locally but **never evaluated**; other families (`qwen2.5:7b-instruct`, `llama3.1:8b`) were **not downloaded or tested**. No model is recommended on evidence. B2 stays OPEN.

Provisional (unevidenced) allocation to test next: one shared 7–8B instruction model for CMO generation; the same model for CEO/PI/CI/CFO narration (single resident model on a 16 GB CPU host); `nomic-embed-text` for embeddings; all numbers, claim checks and keyword placement stay in code.

### External dependencies
| Blocker | Missing evidence | Resource / document | Who provides | Engineering can continue? |
|---|---|---|---|---|
| B1 | Official title/bullet/description/search-term/attribute rules per category for Flipkart and Meesho; per-category Amazon India templates | Seller Hub / Supplier panel / Seller Central listing templates and style guides (checklist in `CMO_MARKETPLACE_RULES.md`); exports or screenshots with URL and date; no passwords | Seller / owner | Yes (rules register and gates already built; drafts carry the unverified banner) |
| B2 | Intended production model and configuration; larger multi-product evaluation on it | Decision on hardware (GPU or CPU) and model; an owner-approved download of candidate models | Owner | Yes (harness exists: `eval_cmo_real_model.py`) |
| B6 | Official or measured title display/truncation per marketplace, device and category | Official docs, or dated measurements, listing URL and device from an authorized live test listing | Owner / seller | Yes (previews stay illustrative) |
| B7 | Browser walkthrough of the 15 workflows | A dedicated signed-in test tenant (Clerk org) with synthetic data, plus permission to run it | Owner | Yes, but cannot be marked verified without it |
| B8 | Real report layouts and real confirmations | Authorised Amazon India / Flipkart / Meesho performance exports; real SKU-to-product and go-live confirmations; each marketplace's statement on whether a missing row means zero | Seller / owner | Yes (importer built for synthetic layouts; native support not claimed) |

### Final blocker status
B1 OPEN (externally blocked); B2 OPEN (poor evidence: 12/23 pooled, 6/15 latest; no new run); B6 OPEN (externally blocked); B7 BLOCKED; B8 PARTIAL. **Decision: NOT PRODUCTION READY.**

## 5. Closure pass for B1, B6, B7, B8 (B2 excluded and unchanged)

| Blocker | Status | Completed engineering | Official evidence | Browser | Real seller data | Remaining dependency |
|---|---|---|---|---|---|---|
| B1 | OPEN (externally blocked) | Register, validator and promotion gate already in place; exact per-marketplace requests written (`CMO_EVIDENCE_REQUESTS.md`); a test typo that made the Meesho promotion check vacuous was fixed | one Amazon India partial title rule (not promoted); no new pages readable | n/a | n/a | seller-account templates and style guides |
| B6 | OPEN (externally blocked) | New measurement register, validator and candidate summary with 4 new tests; previews unchanged and still labelled illustrative | none | none | n/a | official display docs, or ≥5 observations of ≥3 authorized live listings per marketplace/category/device/surface |
| B7 | BLOCKED | 15-workflow walkthrough prepared (`CMO_B7_BROWSER_WALKTHROUGH.md`); no new engineering defect found | n/a | **not performed** | n/a | a dedicated test tenant and the owner's permission |
| B8 | PARTIAL | Reviewed: CSV/XLSX import, synonyms, duplicates, conflicts, overlap, coverage, equal windows, replace guard, observational wording are all covered by existing M8/B8 tests; no gap found; exact export requirements written | n/a | not performed | none used | real Amazon/Flipkart/Meesho exports, real confirmations, missing-row semantics; native support is NOT claimed |

Tests this pass: slim-cmo unit suite (full) and `test_marketplace_rules.py` 11 passed. No migration changed (none needed). Decision unchanged: **NOT PRODUCTION READY**.

### Correction found in this pass
Earlier reports quoted "slim-cmo 314 passed", which was a subset. The **full** slim-cmo suite had 3 failing tests, none a product defect: two guard tests had not been updated for M8 (the money-module allowlist lacked `history/metrics.py` and `history/report_import.py`, both checked to contain no multiplication, division or modulo on a paise/price name; the async-handler list lacked the three M8 upload routes, which read the body asynchronously and hand the work to `run_in_threadpool`, the same pattern as `post_image`), and one M6-era prompt test asserted that the word "insulated" never appears anywhere in the prompt although the fixed instructions use it as an example claim (it now checks the competitor-theme list only). **Full slim-cmo suite after the fixes: 2729 passed, 237 skipped.** Other full suites (backend integration, frontend) were not re-run in this pass; their last results are the ones quoted above.

## 6. M9 Product Image Quality Advisor (2026-11-01)

IMPLEMENTED; analyzer AUTOMATED TESTED (slim-cmo 2775 passed, 237 skipped); backend M9 and chat INTEGRATION TESTED (30 passed, before the duplicate-detection change; the resized-copy integration test is NOT RUN); frontend component level AUTOMATED TESTED (1166 passed). **NOT TESTED:** browser end-to-end, and the M6/M7/M8 backend regression batch after M9. **PARTIAL:** text, logo and watermark detection (low-confidence heuristic). Marketplace image compliance: **NOT_ASSESSED** (no verified official rule). Readiness photo points unchanged at 10. Decision unchanged: NOT PRODUCTION READY.

## 7. M9 completion, M10, corrections and version pagination (2026-11-01)

* **M9:** documentation completed (`CMO_M9_IMAGE_QUALITY.md`, section 9 lists each status). Earlier recorded evidence stands (slim-cmo 2775 passed; frontend 1166 passed; backend M9 and M5 integration passed before the duplicate-detection change). Text/watermark detection PARTIAL (heuristic, low-confidence). Browser verification NOT TESTED. Marketplace image compliance NOT_ASSESSED.
* **M10 market opportunities and news, imported-record corrections, version pagination:** IMPLEMENTED. **Tests written, NOT RUN. Not BROWSER VERIFIED. Migrations `20261101_0012` (slim-cmo), `20261101_0033` (backend) reviewed statically and NOT applied to any database.** The correction change also alters the daily-metrics query (it now reads the effective view), so the M8 performance behaviour must be re-verified by running its suites before release.
* Decision unchanged: **NOT PRODUCTION READY.**

**Update 2026-11-01 (after running them):** migrations `20261101_0012` and `0033` applied on the scratch database; M10 unit tests, correction integration tests (8), M9 integration (39 with the chat file) and the M8 backend files (43) passed; frontend market, corrections, pagination and performance tests passed. Not run: M5/M6/M7 regression, full suites, browser. Decision unchanged: NOT PRODUCTION READY.


### M6 fix - typed-title over-limit wording (N-16c) (2026-11-01)
- **Root cause:** a title the seller typed and confirmed in a complete-listing request is approved first (`record_typed_title_approval` -> `approve_typed_title`), which runs the marketplace title check and returned only the generic `TITLE_INVALID` ("does not meet this marketplace's current rules"). The specific over-limit message (`_check_title_limit` in `cmo_listing.py`) sits in the later pre-flight and was never reached. The numbers were already in the refusal's violation (`title: TOO_LONG (27>20)`) but were not shown.
- **Fix:** `record_typed_title_approval` (`backend/src/backend/ceo/cmo_chat.py`) now turns a `TOO_LONG` violation into the specific wording: the verified limit, the title's own length, "give me a shorter title", and that nothing was approved, saved, cut or charged. Every other refusal (unverified rules, other title violations) keeps the generic message. The marketplace validator, `approve.py` and `cmo_listing.py` are unchanged.
- **Test:** `test_ceo_cmo_m6_edits_chat.py::test_n16c_in_chat_a_title_over_the_verified_limit_is_refused_before_any_plan_card` now also asserts directly in the database that no approval row (`cmo_title_approval`, none with `title_source = 'SELLER_TYPED'`), no listing audit and no quota reservation exists, besides the existing no plan card, no generation and no CMO billing event, and that the seller sees the specific wording.
- **Result (2026-11-01, scratch database):** the six focused files (`test_ceo_cmo_m6_edits_chat`, `test_cmo_m6_typed_approval`, `test_ceo_cmo_m6_title_pick`, `test_ceo_cmo_m6_title_chain`, `test_cmo_m6_title_currency`, `tests/unit/test_cmo_m6_unit`): 57 passed, 0 failed, 0 skipped. The earlier 18-file M5/M6/M7 batch (260 passed, 1 failed on this defect) has NOT been rerun since the fix; the other M5/M7 files in it were not touched by the fix.
