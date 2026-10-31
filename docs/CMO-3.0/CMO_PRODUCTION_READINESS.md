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
