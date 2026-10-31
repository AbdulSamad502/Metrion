# CMO 3.0 — Acceptance Tests (old + new seller workflows)

> **Status:** a test *design*. **No test below has been executed against a real model, real providers or a real database.** The "Today" column states what the audit of code and the unit tests supports, nothing more.
> Delete with the rest of `docs/CMO-3.0/` when CMO 3.0 is finished.
> Demo product (from the plan; seller-provided demo facts only): **AquaNest Stainless Steel Water Bottle**, 1 litre, stainless steel, silver, reusable. Insulated = not confirmed. Leakproof = not confirmed. Dishwasher safe = unknown.

**"Today" values:** `UNIT-OK` = covered by passing unit tests; `GAP` = known missing or unwired (see Implementation Map); `UNTESTED` = no evidence either way; `NEW` = feature does not exist yet.
**Every test uses the seller → CEO → CMO → CEO path.** The seller never calls a CMO route directly.
**Evidence rule for all tests:** any number shown must show source, period and status (verified / provisional / estimated / unavailable). Missing input shows "not assessed", never zero.

---

## A. Old workflow (what exists now — must keep working)

| ID | Scenario (Plan scene) | Steps | Pass when | Today |
|---|---|---|---|---|
| O-01 | Image understanding (S1; cap 1-2) | Seller attaches a bottle photo and asks for a listing | A separate small plan card (0 units) names the vision model; after Approve, hints show as *"from your attachment — suggested, not verified"*; EXIF/location removed; nothing used as a claim until confirmed | UNIT-OK; live Ollama UNTESTED |
| O-02 | Bad / non-image attachment | Attach a PDF or corrupt PNG | Plain refusal, nothing sent, 0 units, no guess | UNIT-OK |
| O-03 | Vision gate closed | Run O-01 with no passing `vision_eval_run` | Every observation stays `UNVERIFIED_HINT`; copy never asserts it | UNIT-OK |
| O-04 | Confirm photo hint (S1; cap 3) | Seller confirms "silver" by clicking | A new `SELLER_PROVIDED` fact is recorded; photo/provider does not become trusted | **M0 DONE**: a confirmed or corrected photo detail is also recorded as the seller's statement, linked to the reading, zero units |
| O-05 | Missing info questions (S1; cap 4) | "Write titles for my bottle" with no brand | CEO asks one question per turn, ≤3 options + Other + Cancel; max 8 questions, 2 re-asks; nothing asked twice | UNIT-OK |
| O-06 | Persistent facts (cap 4) | New conversation next day: "improve my AquaNest bottle" | Previously confirmed facts are reused only after the seller re-confirms; not asked again | **M0 DONE**: stable `sku` from the product name; saved facts reused next conversation and shown on the plan card |
| O-07 | Unconfirmed claims excluded (S1) | Seller: "I haven't tested insulation/leakproof, don't mention" | Titles, bullets, description, keywords and backend terms never contain insulated/leakproof/dishwasher | UNIT-OK (claims/forbidden/red-team) |
| O-08 | Five Amazon titles (S2; cap 5) | Ask for 5 titles; approve plan | 5 distinct, constraint-valid options; char counts from code; fewer-than-5 returned short and labelled; 0 valid ⇒ FAILED, 0 units | UNIT-OK; real LLM UNTESTED |
| O-09 | Marketplace choice (S2/S5) | Ask for Amazon + Flipkart | One unit per marketplace delivered; each uses its own constraint; one blocked marketplace does not stop the other | UNIT-OK |
| O-10 | Select / edit / approve a title (S2; cap 6) | "Use option 1" (click, number, or typed), or the seller types their own wording, then it is saved | Edited text re-validated against the *current* constraint; a `cmo_title_approval` row with `edited_by_seller=true`; CEO never chooses for the seller; a bare "yes" is not a title; **CEO-proposed rewording ("move 1 Litre earlier") is NOT part of M0: the seller types the wording** | **M0 DONE** (`test_ceo_cmo_m0_chat.py`, `test_cmo_m0_integration.py`) |
| O-11 | Constraint hard stop (cap 11) | Edit title beyond max length | Rejected with the rule and its source; no silent truncation | UNIT-OK |
| O-12 | Full listing, separate approval (S3; cap 7) | After title approval, ask for full listing | A second plan card (never merged with titles); pack is atomic; description, bullets, keywords all pass or FAILED/NEEDS_FACTS with 0 units | UNIT-OK |
| O-13 | Standalone edit (S4; cap 8) | "Improve only my third bullet" | Only a bullets artefact is produced, 1 unit; no full regeneration | UNIT-OK (bullets); targeted single-bullet edit **UNTESTED** |
| O-14 | Backend terms + hashtags (cap 9) | Amazon backend terms and hashtags | Backend terms only for Amazon; byte limit enforced; hashtags labelled "marketing suggestions, not a listing field" | UNIT-OK |
| O-15 | Catalog Q&A (S4; cap 10) | "Is my bottle dishwasher safe?" | Answer is `UNKNOWN`/"not confirmed", asks for the fact, never invents | **M0 DONE**: details via a planned catalog task (no model); property questions answered from the seller's facts, else 'not confirmed' |
| O-16 | Market trends (S6; cap 13-14) | "Research trends for reusable steel bottles" | Niche confirmation card → exact queries shown → approval → seven sections (a section may be UNAVAILABLE with reason); each finding has source link and date or "date not stated"; attention is never called demand | UNIT-OK; live providers UNTESTED |
| O-17 | Plan changed after preview | Change a niche term after the preview | `409 PLAN_CHANGED`, nothing sent | UNIT-OK |
| O-18 | History + copy/used (S7; cap 17-18) | "Show my selected Amazon title"; click Copy; Mark used | CEO states the approved title; Copy/Mark used only record an event; CEO states it is **not** proof of publication; dashboard shows "Approved" only with an approval row | **M0 DONE** in chat; dashboard unchanged |
| O-19 | CI-informed (cap 15) | Seller has saved competitor listing insights and `agent.ci` | Plan card says themes from N competitors are used (derived words only); output passes originality check; no competitor text or price used; without CI it runs independently with a note | UNIT-OK; with real CI rows UNTESTED |
| O-20 | Tenant isolation (cap 19) | Tenant B requests Tenant A's generation / trend report id | Identical 404; no row visible; `tenant_id` never accepted from client | Integration **NOT RUN** |
| O-21 | Quota & idempotency (cap 19) | Repeat the same request key; exceed cap | Second submission reuses, no second unit; over-cap ⇒ 402, reservation released; a failed artefact costs 0 | UNIT-OK; DB concurrency **NOT RUN** |
| O-22 | Errors & stale config (cap 20) | Remove a required setting; stale constraint row | `CONFIG_MISSING` / `COUNTING_RULE_UNVERIFIED`; nothing asked, run or billed | UNIT-OK |
| O-23 | Permissions | User without `agent.cmo` / `research.market_trends` | 403 for permission, 402 for entitlement; CEO states what is missing | UNIT-OK |
| O-24 | Killed process | Kill the worker mid-generation | `agent_run` left RUNNING is settled INTERRUPTED at start-up; no unit billed | Integration **NOT RUN** |

---

## B. New workflow (CMO 3.0 / 3.1 — every row is NEW unless noted)

| ID | Upgrade | Given / When | Then (pass) |
|---|---|---|---|
| N-01 | 1 Smart Product Intelligence (S8) | AquaNest facts were confirmed earlier. New session: "remember my AquaNest bottle?" | CEO lists the saved profile with **provenance and date per fact** (seller-provided / photo-confirmed), asks to re-confirm anything older than a stated window, and shows history of changed values. A fact from another SKU never appears **M1 DONE** (the re-confirmation window is not applied: no value decided; each fact shows its date) |
| N-02 | 2 Keyword Intelligence (S8) | "Research keywords and tell me what competitors emphasise" | Each candidate shows relevance, intent label, recommended placement, confidence and **evidence reference**. "Insulated water bottle" appears as **Excluded — unconfirmed**. Search volume, demand and competitor occurrence read **NOT_ASSESSED** unless real evidence exists **M2 DONE** (volume, demand and rank always NOT_ASSESSED; verified with fake competitor themes, real saved CI rows still untested) |
| N-02b | 2 no-evidence case | No CI data, no trend report, no volume source | Output is facts-only candidates with "evidence: seller facts only"; no invented counts **M2 DONE** |
| N-03 | 3 Five-title analyzer (S9) | "Give five title strategies with scores" | Five **meaningfully different** strategies, each labelled. For each option: an **overall 0-100 score and band** and the five criterion scores (keyword relevance 25, confirmed-fact accuracy 25, readability 20, buyer intent 15, structure/positioning 15) with the points lost and why, a comparison of all five, and a rule-based recommendation. Method shown. Same input => identical result. Marketplace compliance is shown separately as PASS / FAIL / NOT_ASSESSED. Fictional demo scores (90/91/93) never appear unless computed | **M3 DONE** |
| N-03b | 3 hard failures | A candidate contains "insulated", an invented number or an over-length title | Marked **hard failure** (factual accuracy 0, band NOT USABLE, score shown for reference only), **never recommended whatever its score**; shows which rule/source | **M3 DONE** |
| N-03c | 3 missing evidence | No keyword evidence / no confirmed facts | That criterion shows `NOT_ASSESSED` (not 0, no points) and is removed from earned AND assessable points; the overall score says how many of 100 points were assessable; under 50 assessable => no overall score and no recommendation | **M3 DONE** |
| N-03e | 3 evidence coverage | Any score screen, including options with different coverage | Each title shows its score **with** its assessable points (e.g. 82/100, 85 of 100 assessable); the recommendation only compares options assessed on the same points and says which were not compared | **M3 DONE** |
| N-03d | 3 limits label | Any score screen | States the score is an internal listing-quality assessment, not an Amazon SEO ranking, search position, search volume, conversion rate or sales prediction | **M3 DONE** |
| N-04 | 8 Preview (S9) | Select option five, "show my listing preview" | The CEO answers with the **visual card in the chat** (not a text description): a simulated search result in the chosen marketplace's layout, mobile and desktop, with the title cut at the screen's cut-off, labelled **illustrative simulation**; "Actual marketplace display may differ" | **M4 DONE** |
| N-04a | 8 Toggle | Switch mobile <-> desktop and Amazon <-> Flipkart <-> Meesho | Instant, in the browser: no request, no model call; marketplaces without saved titles are disabled | **M4 DONE** |
| N-04b | 8 Five titles | Pick each of the five saved titles | Each shows its M3 score, its assessable points and its marketplace-compliance status (PASS / FAIL / NOT_ASSESSED); a hard failure is stated in words | **M4 DONE** |
| N-04c | 8 Image | With and without the seller's photo | The seller's own photo read by CMO in this conversation is shown; otherwise a neutral placeholder; no picture is ever generated; a competitor screenshot is never shown as the product | **M4 DONE** |
| N-04d | 8 Truncation | A title longer than the cut-off | Visible and hidden text, keyword visibility, important-detail visibility and suggestions come from computed results only | **M4 DONE** |
| N-04e | 8 Honest limits | No verified display rule | Cut-off is labelled ILLUSTRATIVE (not an official limit); VERIFIED only with a sourced, fresh `title_display_rules` row; no price, rating, review or sales figure is shown | **M4 DONE** (verified rules still absent: B6) |
| N-05 | 5 Advanced generation (S11; expanded in section F as N-05a-t) | Approve title five, then complete listing | A separate approval card; bullets, description, keyword placement and backend terms are consistent with the chosen strategy; every keyword placed traces to a candidate from N-02; audit runs afterwards |
| N-06 | 6 History & compare (S13) | "Compare my old Amazon title with the new one" | Both versions shown with dates; deterministic diff (what moved, what was dropped, length change); explanation cites only the diff. "Has this improved my sales?" ⇒ CEO says it **cannot tell without comparable-period marketplace performance data**; no sales claim |
| N-07 | 9 Image quality (S10) | "Check my image quality" | With no image: "needs the actual uploaded images", status pending. With an image: clarity/composition/missing-shot notes labelled **advisory, not verified** until an evaluation passes; no claim about marketplace image-policy compliance |
| N-08 | 4 CI evidence (S8; expanded in section F as N-08a-f) | Seller has CI insights; asks what competitors emphasise | CEO gets structured evidence; CMO states differences **only where the seller's confirmed product supports a matching claim**; unsupported themes appear as "consider adding if true"; no competitor text/price reused |
| N-09 | 10 Variants (S12) | Seller adds 500 ml and 750 ml; shared brand/material/colour | One family, three variants; capacity facts kept per variant; generating the 500 ml listing never contains "1 litre" or "750"; changing the family colour asks before applying to all variants |
| N-10 | 11 Buyer questions (S10) | "What questions will buyers ask?" | The CEO shows a card of likely questions (insulated? leakproof? dishwasher safe? plus essentials), each marked **a question to investigate**, status CONFIRMED / NOT CONFIRMED / SELLER UNKNOWN; **no answer unless the seller confirmed it**; no claim about how often a question is asked; competitor relevance only from tracked competitors' derived themes | **M5 DONE** |
| N-11 | 11->content | Seller answers "For my bottle, leakproof is: yes, tested" (or "not tested") | Saved as the seller's own statement (append-only, zero units); the question becomes CONFIRMED with its source and date, or SELLER UNKNOWN (never claimed); an unknown topic/product, empty, over-long or forbidden answer saves nothing | **M5 DONE** |
| N-12 | 12 Readiness (S11) | "Is my AquaNest bottle ready to list?" | A checklist for Amazon, Flipkart and Meesho: DONE / MISSING / BLOCKED / NOT ASSESSED per requirement with points, category scores, an explainable 0-100 readiness score **with its assessable points**, missing requirements and next actions; marketplace requirements NOT ASSESSED without verified rules (B1); the verdict is never READY and never "approved by the marketplace" | **M5 DONE** |
| N-12a | 12 Marketplace-specific | Each of the three marketplaces | Each has its own title, chosen title, copy and rule items; shared product facts and questions are identical across them; switching is instant (no request) | **M5 DONE** |
| N-12b | 12 Safety | Billing, tenant, M0-M4 | No unit, reservation, metered event or model call; another tenant's data is never read; the app role cannot change or delete a saved assessment; M0-M4 behaviour unchanged | **M5 DONE** |
| N-13 | 7 Market opportunities (S14) | "What opportunities fit my bottle?" | Each recommendation cites a real saved finding (source, date); with no report: "no supported research yet — run market research first"; no opportunity score; no demand/sales claim |

## C. News enhancements (Plan §4, item 14)

| ID | Feature | Pass when |
|---|---|---|
| NEWS-1 | 14.1 Personalised feed | For an AquaNest seller, reusable-drinkware and Amazon-listing-policy items rank above unrelated fashion news; relevance is a stated rule, never a made-up "impact score" |
| NEWS-2 | 14.2 Policy alerts | An item is labelled **official** only if its domain is in configured official domains; a news article alone never changes CMO's enforcement rules; with no configured domains nothing is labelled official |
| NEWS-3 | 14.3 News-to-action | A supported finding yields a suggested task as a **plan card** needing approval; no listing change is applied without the seller approving |
| NEWS-4 | 14.4 Change tracking | Second report on same niche shows **new / unchanged / corrected** items with dates; old headlines are not shown as fresh |
| NEWS-5 | 14.5 Ask about a story | "Does this news affect my water bottle?" is answered from the saved finding **and** the seller's profile, with the original link; unsupported ⇒ says so |

## D. Regression and safety set (run after every milestone)

| ID | Check |
|---|---|
| R-01 | All `packages/slim-cmo/tests/unit` (2183 today) green |
| R-02 | All backend CMO unit tests (236 today) green |
| R-03 | `frontend/components/cmo/showcase.test.tsx` (8 today) green; dashboard still has no generate/approve controls and calls no CMO `POST` except `usage-events` |
| R-04 | Cross-tenant: tenant B cannot read or reference tenant A's profile, keyword, analysis, snapshot or variant (RLS integration, run on scratch DB) |
| R-05 | No LLM output contains a number not computed by code (eval: every figure traces to a computed field) |
| R-06 | Unsupported-claim red-team set still passes with new features on (insulated, leakproof, dishwasher safe, BPA-free, certifications, "best", "No. 1") |
| R-07 | No competitor text, price, GST rate, fee, or demand/sales claim appears anywhere in CMO output |
| R-08 | A typed "yes" never approves a plan; only the click bound to plan id + hash does |
| R-09 | `NOT_ASSESSED` / `UNAVAILABLE` is displayed as such, never as 0, 100 or a default |
| R-10 | Copied, approved and marketplace-live remain three separate statuses; "live" is never set by CMO |
| R-11 | No marketplace write path exists (no credential, no publish call) — static scan |
| R-12 | Schema-drift test passes; every new table has `tenant_id`, `FORCE` RLS and composite FKs; migration upgrade + downgrade works on a scratch DB |
| R-13 | Accessibility: AA contrast; status never colour-only; reduced-motion respected; no pulsing or count-up |
| R-14 | LLM eval for each new narration surface: states no number outside cited figures, keeps required disclaimers, does not narrate a non-result as a result |

## E. Milestone → tests

| Milestone | Must pass |
|---|---|
| M0 | O-04, O-06, O-10, O-15, O-18, R-01…R-12 and the O-20/O-21/O-24 integration set run on a clean DB |
| M1 | N-01, R-04 |
| M2 | N-02, N-02b, R-05 |
| M3 | N-03 (a–d), R-05, R-06 |
| M4 | N-04 |
| M5 | N-10, N-11, N-12 |
| M6 | N-05a-x, N-14a-j, N-15a-g, N-16a-c, N-08a-f (section F), R-07, R-08, R-15 to R-20 |
| M7 | N-06 |
| M8 | N-09 |
| M9 | N-07 |
| M10 | N-13, NEWS-1…5 |


## F. M6 detailed acceptance tests (Advanced Listing Generation + CI Evidence)

> **Status:** designed and approved 2026-10-30 (all owner decisions Q8, Q26-Q33 recorded). **Implemented 2026-10-31; N-15d implemented in the gap-closure commit; all 50 rows traced to tests in CMO_M6_TRACEABILITY.md (50 COVERED, 0 PARTIAL, 0 MISSING); not manually verified in a browser; see CMO_IMPLEMENTATION_MAP.md section 18.** 50 tests: 47 for the approved scope plus 3 (N-16a-c) added to cover the Q32 title-step exception and its boundary. Authority: `docs/specs/slim-cmo-agent.md` §6.18 and `docs/specs/ceo-cmo-delegation.md` §6.16. Every test uses seller → CEO → CMO → CEO. Real-model quality is not tested here (blocker B2); tests use the deterministic fake `LlmProvider`, a scratch Postgres (`backend/scripts/scratch_db.sh`, never the dev DB) and `TEST_FIXTURE` format rows (production has no `VERIFIED` rows, B1).
> **Handoff ID → repo ID.** The IDs N-05, N-08, R-07 and R-08 already exist in this document with other meanings and are kept unchanged. The four M6 scenarios requested in the handoff map as: *complete listing generation* → **N-05a…**; *listing audit* → **N-14…** (new); *CI evidence integration* → **N-08a…**; *CI evidence safety* → **N-08c…N-08f** plus global **R-07** (no competitor text/price) and **R-08** (typed yes never approves), which M6 must keep green.

**Standard fixture "F6" (unless a row says otherwise).** Tenant A (role may use `agent.cmo`; `agent.ci` and CI entitlement pass), product *AquaNest Stainless Steel Water Bottle*: confirmed brand AquaNest, material stainless steel, capacity 1 L, colour silver, "reusable"; insulated = NOT_CONFIRMED, leakproof = SELLER_UNKNOWN, dishwasher safe = NOT_CONFIRMED. Amazon title set saved, M3 analysis saved, **option 5 approved** (strategy label stored). M2 analysis saved with `RECOMMENDED` candidates ("steel water bottle", "1 litre", "silver", "reusable"), "insulated" excluded. Test `TEST_FIXTURE` Amazon/Flipkart/Meesho rows with a count rule and byte cap. One fresh saved competitor insight with derived themes `reusable`, `insulated`, `bpa`; `differentiation_opportunities` = `insulated`. Fake provider returns a valid pack unless stated. "Units" = `cmo_generation.billable_units`. **Rules basis:** unless a row says otherwise F6 includes `TEST_FIXTURE` format rows (normal, enforced mode); rows marked "RU" use the *rules-unavailable basis* of spec §6.18.11 (no usable marketplace row, flag `listing_unverified_rules_enabled = true`, `rules_unavailable_bullet_target` set). Approved configuration for RU rows: `listing_unverified_rules_enabled = true` for the test (the shipped default is `false`), `rules_unavailable_bullet_target = 5`. **State vocabulary:** generation approved · generated · audited · approved for use (`APPROVED` event) · copied · marked used; "published/live" is never set by CMO.

### F1. N-05 family — complete listing generation, approval, billing

| ID | Preconditions / data | Seller action | Expected CEO | Expected CMO | Persisted | Billing | Safety assertion | Pass / fail |
|---|---|---|---|---|---|---|---|---|
| N-05a Complete listing (Amazon) | F6 | "Create my complete Amazon listing using approved option 5", then click Approve | One plan card (separate from title approval) → `LISTING` card with title, bullets, description, keywords, backend terms, keyword map, audit | Pack uses the approved title verbatim; sections consistent with the confirmed facts and the title strategy; keywords only from M2 `RECOMMENDED` candidates; audit runs after | 1 `LISTING_COPY` + 1 `BACKEND_TERMS` rows (COMPLETE), 1 `cmo_listing_audit`, 1 `agent_run` tree | 2 units total, as shown on the card | No marketplace write path; nothing says "live" | Title text equals approved text; all sections present; every keyword in the map is a recommended candidate; audit row exists |
| N-05b No approved title | Product with no approved title | "Write my full listing" | Says a title must be approved first and runs the title steps inside this listing request (title set, selection, approval); **no listing plan card until a title is approved** | No model call | Nothing saved | 0, no reservation | No title chosen for the seller | No `cmo_generation` row, no plan card, no `agent_run` for generation |
| N-05c Plan before charge | F6 | Request, do not click | Plan card lists title, marketplace, each artefact with units, total, CI line, "what leaves Metrion", "nothing sent to a marketplace" | None | Plan record only | **0 charged and no reservation before the click** | Typed "yes" does not approve (R-08) | Card fields all present; units and meters unchanged until Approve |
| N-05d Rejects approval | F6 | Request, click Decline (or ignore until expiry) | Confirms nothing was generated | None | Plan marked declined/expired in the conversation only | 0 | Expired or declined plan can never be approved later | No generation rows; later click on the old card is refused |
| N-05e Approve + duplicate / retry | F6 | Click Approve twice quickly; replay the same request | One result shown; second click returns the same cards | Per-artefact idempotency keys derived from the plan's request key | Exactly one row per artefact | Charged once | No duplicate paid generation | Row and unit counts equal the single-run case |
| N-05f No M2 candidates | Facts so thin M2 has zero `RECOMMENDED` | Request | Asks for the missing facts by name (`NEEDS_FACTS`); no plan card | Free M2 analysis may run (0 units); no keyword is invented | M2 analysis row only | 0 | No manufactured candidate | No pack, no placed keyword, message names facts |
| N-05g Weak / missing-evidence candidate | A candidate with `WEAK` or `NOT_ASSESSED` evidence | Complete N-05a | Card lists it under "not used" with the reason | Candidate not placed anywhere | Map shows `NOT_PLACED` + reason code | As N-05a | No weak keyword presented as strong | Weak candidate absent from all sections and backend terms |
| N-05h Missing product facts | Material or capacity not confirmed | Request | Asks which facts to supply before any plan card | None | None | 0 | No padding with guesses | No pack; CEO lists exactly the missing facts |
| N-05i Contradictory facts | Current capacity facts 500 ml (older) and 1 L (newer) for the same product name, or two different colours both current | Request | Asks which value is right; offers to record the correction; no plan card | None | None (history kept by M1) | 0 | Never picks one silently | Generation refused until one current value remains |
| N-05j Unanswered buyer questions | M5: leakproof SELLER_UNKNOWN, insulated NOT_CONFIRMED | Complete N-05a | Card lists unanswered topics as "not claimed" | Neither topic is asserted in any section; confirmed answers used | Audit A04/A10 pass | As N-05a | "Do not claim" list enforced in code | Neither claim appears; confirmed answer present in bullets or description (or a NOTE) |
| N-05k Backend terms Amazon only | F6, then repeat on Flipkart and Meesho | Full listing for each | Amazon card has backend terms; Flipkart/Meesho card says backend terms are Amazon-only | No `BACKEND_TERMS` request for Flipkart/Meesho | Rows per marketplace as expected | Amazon 2 units, others 1 | DB check Amazon-only still holds | Zero backend-terms rows for Flipkart/Meesho |
| N-05l Non-Amazon generation | Flipkart approved title | Full listing | `LISTING` card in Flipkart shape; structured fields show `NEEDS_SELLER_INPUT` | Pack built from Flipkart title and row only; nothing copied from the Amazon pack | Flipkart pack row | 1 unit | No cross-marketplace derivation | Pack differs in shape; no field marked filled that is not |
| N-05m RU: marketplace rules unavailable | RU: no `VERIFIED` row for Amazon, flag on, bullet target set; F6 facts and M2 candidates | Full listing, Approve | Plan card says the rules basis is unverified; `LISTING` card shows the banner *"Marketplace rules are not verified for Amazon. Lengths and field limits were measured, not checked. Check them on the marketplace before you use this listing."* | Pack generated from confirmed facts and M2 candidates only; lengths measured (both counts) and shown, no limit enforced or guessed; the non-limit gates all still enforced | Pack rows with `rules_basis = UNVERIFIED`, no `source_url`/`verified_at`; audit with A03/A12/A13 `NOT_ASSESSED` | Normal units for delivered artefacts | No sentence says compliant, verified, accepted or ready; verdict never above CHECKED_NOT_VERIFIED; M3 compliance and M5 readiness stay NOT_ASSESSED / not READY | Banner present; measured lengths shown; unsupported claim still fails; no compliance wording anywhere |
| N-05u RU flag off (default) | RU conditions but `listing_unverified_rules_enabled` is `false`, absent or any value other than `true` | Full listing | Says generation is blocked because marketplace rules are not verified and unverified drafts are not enabled (a safe default, not a fault); no plan card | None | None | 0 | Default is off | No generation row, no model call; no `CONFIG_MISSING` is reported for the flag |
| N-05v Verified row wins; stale and fixture handling | (a) a fresh `VERIFIED` row exists and a draft would exceed its bullet limit; (b) the row is stale; (c) only a `TEST_FIXTURE` row in a production-mode run | Full listing | (a) normal mode, limits enforced, banner absent; (b) RU banner; (c) RU banner (fixture ignored) | (a) over-limit text repaired or the pack FAILS, never delivered over limit; (b)(c) RU rules | `rules_basis` VERIFIED in (a), UNVERIFIED in (b)(c) | As N-05a | RU never overrides verified data; fixtures never read in production | Basis recorded correctly in all three |
| N-05w Misconfiguration still blocks | RU with the flag on but `rules_unavailable_bullet_target` missing or not a positive integer, or `format_constraint_max_age_days` invalid | Full listing | Blocked with `CONFIG_MISSING` / `CONFIG_INVALID` naming the key | None | None | 0 | A configuration fault is not "missing marketplace data"; no hidden default for the target | No output; reason names the key; with the key = 5 the pack targets 5 bullets and the plan card says "draft target: 5 bullets (not a marketplace requirement)" |
| N-05x Approved for use | N-05a result | Click "Approve for use" on the card; separately try typing "approve this listing", and try the dashboard | Click: confirms *"approved for use in Metrion; not published"* (repeating the RU banner when the basis is unverified); typed text: not an approval, CEO explains the click; dashboard offers no approve control | Records one `APPROVED` event bound to the immutable pack row | Append-only `APPROVED` usage event (tenant, actor, time, surface `CHAT`, generation id) | **0 units, no metered event, no reservation** | Not published, not live; refused when the audit verdict for that row is `BLOCKED`; a later revision starts unapproved; app role cannot UPDATE/DELETE | Event exists only from the click; billing and quota counters unchanged; no "live" status anywhere |
| N-05n Backend terms fail after pack | Fake provider fails the backend-terms call | Approve | Shows pack ready, backend terms not generated, with the reason | Pack stays COMPLETE; terms row FAILED | Pack COMPLETE, terms FAILED, audit of the pack | 1 unit (pack), terms 0 | No half-saved pack | Overall result labelled partial; no recharge on retry |
| N-05o Generation fails safely | Provider error / timeout / oversized reply | Approve | Plain reason; offers retry | Bounded retries then FAILED | FAILED row with failure code, no partial text | 0 | No partial text delivered | Row FAILED, units 0, no `metered_event` |
| N-05p Hashtags optional | F6, `hashtag_set_size` set / unset | Full listing with the box ticked / unticked; and ticked with the key unset | Ticked: extra line and unit on the card, labelled "marketing suggestions, not a listing field"; unset key: `CONFIG_MISSING` stated, rest proceeds | Hashtags only when ticked and configured | HASHTAGS row only then | +1 unit only then | Never implied a marketplace supports hashtags | Defaults off; label present |
| N-05q Six states distinct | N-05a result | Walk the card: generated, audited, then Approve for use, copy, mark used | Each state shown as its own labelled item; copying works before approval; none is called live or published | None | Events `GENERATED`, `APPROVED`, `COPIED`, `MARKED_USED`; audit row | 0 | A clean audit ≠ approved ≠ copied ≠ used ≠ live (R-10) | No action sets another state; no field for published/live exists |
| N-05r Cross-tenant | Tenant B ids for title, insight, pack, audit | As tenant A, reference B's ids | "Not found" wording identical to a missing id | No read of B's data | None | 0 | RLS + app scoping (R-04) | Responses indistinguishable from not found; B's rows unchanged |
| N-05s Billing totals | F6, three marketplaces | Full listing for each (hashtags ticked once) | Each card shows its total | As N-05a/p | Rows per artefact | Sum equals the shown totals; failed artefacts 0 | No unit without a delivered artefact | Meter equals delivered artefacts |
| N-05t Custom title | Seller typed their own title (no M3 row) | Full listing | Card shows "custom title: strategy not assessed" | Title validated by the same gates; generation proceeds | Approval row for the custom title | As N-05a | Strategy never invented | Strategy field NOT_ASSESSED; pack grounded on the custom title |

### F2. N-14 family — post-generation listing audit

| ID | Preconditions / data | Seller action | Expected CEO | Expected CMO | Persisted | Billing | Safety assertion | Pass / fail |
|---|---|---|---|---|---|---|---|---|
| N-14a Audit runs after generation | N-05a | (none) | Audit block with checks A01-A15, findings by severity, verdict | Deterministic, no model, no network | 1 `cmo_listing_audit` per (pack, content hash) | **0 units** | No numeric audit score exists | Row exists; verdict in {BLOCKED, NEEDS_ATTENTION, CHECKED_NOT_VERIFIED}; never READY/compliant |
| N-14b Unsupported claims found | Seller-typed bullet "keeps drinks cold for 24 hours" (insulated not confirmed) | Revise bullet with own text | Refused or flagged with the finding and correction | A04 BLOCKER (also hot/cold, "BPA free", certifications, "best", "No. 1") | New row only if the gates pass; else nothing saved | 0 | Red-team set (R-06) still passes | Claim never reaches a saved pack; finding names the section |
| N-14c Contradictions | Description says "750 ml" while confirmed capacity is 1 L | Seller edit | Finding with section and fix | A05/A06 BLOCKER | As N-14b | 0 | Facts never overwritten by text | Contradiction detected in the bullet and the description |
| N-14d Keyword stuffing / repetition | Candidate repeated beyond the Q28 limits; identical bullets | Seller edit | WARNING with the repeated term | A08 | Audit row | 0 | Limits are internal, not marketplace rules (stated) | WARNING present, not BLOCKER; message says no ranking claim |
| N-14e Keyword traceability | Keywords field contains a word that is not an M2 recommended candidate; or an excluded candidate ("insulated") | Seller edit / provider returns it | BLOCKER finding | A07 | Audit row (and generation retries/fails) | 0 | No invented keyword | Non-traceable word never accepted in a saved pack |
| N-14f Unknown rules → NOT_ASSESSED | RU, or no display widths | Complete N-05a / N-05m | Marketplace checks show "not checked against marketplace rules"; A15 shows "style not assessed" | A03 (limits), A12 (cap), A13, A15 = `NOT_ASSESSED` | Checks JSON keeps `NOT_ASSESSED` | 0 | Unknown is never a pass or a zero (R-09) | Verdict CHECKED_NOT_VERIFIED at best; no COMPLIANT wording |
| N-14g M3/M5 reuse, not duplication | N-05a | (none) | Three separately labelled measures: M3 title score, audit verdict, M5 readiness | A02 reuses M3 hard failures; M5 recomputed by its own rules | M3 and M5 rows unchanged by the audit | 0 | No new or merged score | M3/M5 numbers equal their pre-M6 values for the same inputs |
| N-14h Audit of CI differentiation | Pack using a `SUPPORTED` theme; test with an unsupported theme injected | Complete N-05a | CI evidence rows with support status | A11: used themes have a supporting fact; originality check passes | Snapshot lists the used attributes | 0 | Unsupported theme in text = BLOCKER | Injected unsupported theme fails the audit |
| N-14i Buyer-question coverage | Mixed M5 states | Complete N-05a | Coverage list with NOTEs for confirmed facts not shown | A10 | Audit row | 0 | Unanswered topics listed, never guessed | Each essential question has a stated outcome |
| N-14j Repetition thresholds W1-W7 | Table-driven: for each rule one text at the threshold and one just below (spec §6.18.5a examples: W1 "stainless steel" 3× vs 1× in a bullet; W2 "reusable" in 4 vs 3 bullets; W3 "water bottle" 4× vs 3× in the description; W4 total 8 vs 7; W5 identical bullets; W6 bare list of 5 vs 2 items; W7 duplicate backend term); plus the longest-first counting case | Seller edit / generated text | WARNING with the term and the section at threshold, nothing below | A08 counts non-overlapping whole-word matches, longest candidate first | Audit row; `method_version` recorded | 0 | WARNING only, never BLOCKER; message states it is not a marketplace or ranking rule | Every rule fires exactly at its threshold and not below; "stainless steel water bottle" counts once |

### F3. N-15 family — review, revision and regeneration

| ID | Preconditions / data | Seller action | Expected CEO | Expected CMO | Persisted | Billing | Safety assertion | Pass / fail |
|---|---|---|---|---|---|---|---|---|
| N-15a Seller edits one bullet | N-05a result | `Change bullet 3 to: <own text>` (grammar §6.18.7a) | New `LISTING` card with the change and a fresh audit | Same deterministic gates; only bullet 3 differs | New pack row with `revision_of`, new audit row; previous rows intact | **0 units**, no model | Approved title and facts unchanged | Other sections byte-identical; old row unchanged |
| N-15b Model rewrite of one section | N-05a result | "Rewrite bullet 3 to mention the lid type" (lid type confirmed) | Plan card (1 unit), then the new card | Only bullet 3 may change; grounded in the same facts; audited | New `LISTING_COPY` row with `revision_of` | 1 unit, only on delivery | Typed yes does not approve | Other sections identical; unsupported rewrite fails and charges 0 |
| N-15c Rewrite that needs an unconfirmed fact | Lid type not confirmed | Same request | Asks the seller to confirm the fact first; no plan card | None | None | 0 | A revision never creates a fact | No generation until the fact is confirmed |
| N-15d Seller changes the approved title | N-05a result | Approve a different title | Says the existing pack was built from the previous title and offers a new full listing plan | None | New `cmo_title_approval` row; old pack and audit unchanged | 0 | Old pack not edited or relabelled | Old pack flagged "built from a previous title"; no auto-regeneration |
| N-15e Revision re-audit | N-15a | (none) | Findings reflect the new text | Audit rerun on the new content hash | New audit row | 0 | Fixed finding disappears; new one appears | Audit rows count = revisions + 1 |
| N-15f Immutability and lineage | After N-15a/b | Open history of the pack | Shows the original and the revision as separate saved items | None | Rows only inserted; app role cannot UPDATE/DELETE | 0 | Append-only | Direct UPDATE/DELETE as the app role is denied |
| N-15g Edit-sentence grammar (spec §6.18.7a) | Packs for Amazon and Flipkart; two saved products; table-driven | The four valid examples; then each refused example (bullet 7 of 5, empty text, unsupported claim, non-candidate keyword, title target, backend terms on Flipkart, 501-character bullet); then `make bullet 2 shorter`, `Change bullet 2`, and an ambiguous product/marketplace | Valid: a new card with the change and a fresh audit. Refused: the reason naming the rule and section, nothing saved. Not an edit: routed normally; CEO offers a rewrite (plan card, 1 unit) or asks for exact text. Ambiguous: asks which | Deterministic parse and gates; no model | Valid: new pack row (`revision_of`) + audit; refused / not-an-edit: nothing | 0 units in every case | The sentence never approves a plan or the listing, never records a fact, never changes the title | Each example behaves exactly as listed; mutation checks show only the named section changed |

### F4. N-08 family — CI evidence (extends the existing N-08 row)

| ID | Preconditions / data | Seller action | Expected CEO | Expected CMO | Persisted | Billing | Safety assertion | Pass / fail |
|---|---|---|---|---|---|---|---|---|
| N-08a Supported theme informs | F6 (`reusable` is a confirmed fact) | Full listing | Plan card has the existing "competitor themes used" line naming the saved insights; evidence row `reusable` = SUPPORTED, "shared by n of m" | Only `SUPPORTED` themes enter the prompt; text may use the theme in its own words | `ci_inputs_snapshot` holds ids + derived words; `input_mode = CEO_BROKERED_CI` | No CI unit; CI entitlement checked, not consumed | Ids reached CMO only via the CEO broker | Snapshot present; no new route or CI call in a static scan |
| N-08b Unsupported theme is a suggestion | `insulated` is a competitor theme, not a confirmed fact | Full listing | Card shows "Consider adding if true for your product" with the question that would confirm it | Theme never given to the model, never in the text | Snapshot has no claim | As N-05a | Competitor feature never becomes a seller claim | "insulated" absent from all sections; shown only in the suggestion list |
| N-08c No competitor text, image or price | Saved insight has competitor title, bullets and a price in its source row | Full listing | Card shows derived words only | `references` used for originality only | No competitor text, price or image in any output, snapshot or audit | As N-05a | R-07 | Scan of outputs and stored JSON finds none; a close copy of a competitor sentence fails originality |
| N-08d CI unavailable / not entitled / stale | `agent.ci` missing, or CI entitlement failing, or insight older than the freshness limit, or DEGRADED | Full listing | One plain line "Competitor themes were not used: <reason>" | Independent generation completes | Snapshot empty; `input_mode = INDEPENDENT` | As N-05a (no CI charge) | CI failure never blocks ordinary generation | Listing delivered; reason shown |
| N-08e Missing evidence cannot create claims | No competitor insights at all | Full listing | Independent mode, no CI section | No differentiation text | None | As N-05a | Absence of CI evidence is not evidence | No "differentiation" wording appears |
| N-08f Foreign or unknown insight id | Insight id belonging to tenant B | Plan carrying that id (forced in a test) | Behaves as not found; independent mode | `load_inputs` rejects it | None | As N-05a | Foreign id indistinguishable from unknown | No data from tenant B in any output |

### F6. N-16 family — title steps on the rules-unavailable basis (Q32)

| ID | Preconditions / data | Seller action | Expected CEO | Expected CMO | Persisted | Billing | Safety assertion | Pass / fail |
|---|---|---|---|---|---|---|---|---|
| N-16a Title steps inside a full-listing request | RU, no approved title, no `VERIFIED` row, flag on | "Create my complete Amazon listing" → pick or type a title → Approve → continue | Title set, selection and approval happen inside the listing request, each marked `workflow = FULL_LISTING`; banner present | Title set generated without a length or option-count limit (lengths measured); gates still enforced; M3 compliance `NOT_ASSESSED` | Title set and approval rows with `rules_basis = UNVERIFIED` and the workflow marker | Title set per existing billing (1 unit per marketplace delivered); approval 0 | No title is called compliant or verified; M4 preview stays ILLUSTRATIVE | Full chain reaches an approved title and a pack with no verified row; banner on every artefact |
| N-16b C13 unchanged outside the workflow | Same RU conditions, flag on | Ask on their own: "write 5 titles for my bottle", "write a description", "write bullets", "keywords", "backend terms", "hashtags", a catalog question, a trend report | Each behaves exactly as before M6 (blocked with the existing reason where C13 applies; unaffected where it does not) | No call made on the rules-unavailable basis | No `rules_basis = UNVERIFIED` row from any of them | As before | The exception cannot be reached without the workflow marker | Compare against the M0-M5 baseline: identical results for every action |
| N-16c Verified row appears later | N-16a done; then a fresh `VERIFIED` row is added whose title limit is shorter than the approved title | Full listing again | Normal mode; refuses with the verified limit and the approved title's length, asks the seller to approve a shorter title; earlier approval, title set and packs untouched | Pack not generated | None new | 0 | Verified data always wins; nothing silently truncated | Refusal names the limit; old rows unchanged; a shorter approved title then generates a normally enforced pack |

### F5. Regression additions for M6

| ID | Check |
|---|---|
| R-15 | M0-M5 behaviour unchanged: M3 scores, M4 preview, M5 readiness and the existing per-artefact actions give the same results for the same inputs; their test suites stay green. |
| R-16 | New table `cmo_listing_audit` has `tenant_id`, composite FK, `FORCE` RLS, `SELECT, INSERT` only; the schema-drift test passes; upgrade and downgrade work on the scratch DB (R-12 extended). |
| R-17 | Static scan: no new publish/credential path, no new CI query or route, no direct CI-to-CMO call outside `cmo_ci_inputs.py`. |
| R-18 | LLM eval for the new generation prompt: no number outside the cited facts, no unsupported claim, no competitor sentence, "do not claim" topics not asserted (R-14 extended). |
| R-19 | `LISTING` card: AA contrast, status never colour-only, reduced motion respected, no pulsing or count-up, copy buttons keyboard-reachable (R-13 extended); frontend typecheck and tests green. |
| R-20 | Migration ownership follows the repository convention: `cmo_listing_audit` only in `packages/slim-cmo/migrations` (`20261030_0007`), the `LISTING` card kind (`0027`) and the `APPROVED` event kind (`0028`) only in `backend/migrations`; each upgrades, downgrades and re-upgrades on the scratch DB; no cross-package foreign key is added to the slim-cmo tree. |


---

## G. M7 detailed acceptance tests (Listing History, Version Intelligence and Optimisation)

> **Status:** designed and implemented 2026-10-31; **automated coverage traced row by row below; not yet signed off in a real signed-in browser except where the status line says so.** Authority: `docs/specs/slim-cmo-agent.md` §6.19 and `docs/specs/ceo-cmo-delegation.md` §6.17. 70 tests numbered **M7-01 … M7-70**, in the order of the M7 handoff brief (A history 1-10, B lineage 11-18, C comparison 19-29, D keywords 30-36, E content and audit 37-43, F recommendations 44-49, G performance 50-53, H CEO and frontend 54-65, I security and regression 66-70). The IDs are new and do not collide with N-/R- IDs. Standard fixture: the M6 "F6" product on the rules-unavailable basis (`ru_env`), with a real Postgres (scratch DB, never the dev DB) and a deterministic fake provider; every test is read-only and asserts no unit, no metered event, no model call and no new row was created by looking.
> **Test files.** Pure engine: `packages/slim-cmo/tests/unit/history/test_history_engine.py` (U). API + Postgres: `backend/tests/integration/test_cmo_m7_history.py` (A). CEO chat: `backend/tests/integration/test_ceo_cmo_m7_history_chat.py` (C). Second pass: `backend/tests/integration/test_cmo_m7_history_more.py` (A2). Migration: `backend/tests/integration/test_cmo_m7_migration.py` (M). Frontend: `frontend/components/ceo/hub/listingHistoryCard.test.tsx` (F). **COVERED** = a test asserts the behaviour; **PARTIAL** = only part, or only at unit level, with the gap named.

| ID | Behaviour | Status | Where |
|---|---|---|---|
| M7-01 | Initial version is the original, no parent | COVERED | A `m7_01_to_05`; U `lineage_example_four_versions` |
| M7-02 | Multiple revisions are all kept, numbered 1..N | COVERED | A `m7_01_to_05`, `m7_11_13_17` |
| M7-03 | All versions retrievable, newest first | COVERED | A `m7_01_to_05`; C `m7_54`; F timeline |
| M7-04 | Latest version retrieved; not assumed approved | COVERED | A `m7_01_to_05`, `approval_state_belongs_to_one_version_only`; C `m7_55`; F |
| M7-05 | Previous version retrieved | COVERED | C `m7_55` (previous, original, version N) |
| M7-06 | Product-specific history | COVERED | A2 `m7_06_18_two_products_have_separate_histories_numbers_and_are_never_compared` (two real products: filter by sku returns 3 and 1, numbering per product, other tenant sees none); A `m7_06_07` |
| M7-07 | Marketplace-specific history, numbering per marketplace | COVERED | A `m7_06_07` |
| M7-08 | Empty history | COVERED | A `m7_08`; C `one_version_and_no_version`; F empty |
| M7-09 | Missing / foreign version | COVERED | A `m7_09`, `m7_66`; F missing version |
| M7-10 | Pagination | COVERED | A `m7_10` (limit, offset, hasMore, caps); F `pages the history: Show more…` (the button asks for offset 2 and keeps the versions shown) |
| M7-11 | Seller-written revision source | COVERED | A `m7_11_13_17`; U `source_of_reads_what_was_stored` |
| M7-12 | AI-assisted rewrite source (billed once; viewing free) | COVERED | A `m7_12` |
| M7-13 | Parent-child relationship from stored `revision_of` | COVERED | A `m7_11_13_17` (checks the stored rows) |
| M7-14 | Invalid relationship handled | COVERED | A2 `m7_14_15_18_a_stored_parent_that_cannot_be_trusted_*`: owner-role writes a missing parent, a foreign-product parent and a foreign-marketplace parent; history reports MISSING_PARENT / CROSS_PRODUCT / CROSS_MARKETPLACE, parentId null, compare still 200; U lineage tests |
| M7-15 | Circular relationship prevented | COVERED | A2 same test: `v1.revision_of = v3` is stored; history reports CYCLE/NOT_EARLIER and no parent; the honest v3→v2 link is still followed; U self-loop |
| M7-16 | Duplicate version request is idempotent | COVERED | A `m7_16` |
| M7-17 | Historical content preserved | COVERED | A `m7_11_13_17`, `m7_19_to_27` (older text still readable) |
| M7-18 | Cross-product / cross-marketplace comparison refused | COVERED | A2 `m7_06_18_*`: compare of AquaNest v1 with NovaFlask returns 422 `DIFFERENT_PRODUCT`; A `m7_18` cross-marketplace 422; U `validate_pair` |
| M7-19 | Compare two versions | COVERED | A `m7_19_to_27`; C `m7_56` |
| M7-20 | Added content | COVERED | U `list_diff`, `sentence_diff`, `compare_two_versions`; F |
| M7-21 | Removed content | COVERED | U `list_diff`, `term_diff` |
| M7-22 | Modified content (word-level diff) | COVERED | A `m7_19_to_27`; U `text_diff`; F |
| M7-23 | Unchanged content | COVERED | A `m7_19_to_27` (2 unchanged bullets); U |
| M7-24 | Reordered bullets | COVERED | U `list_diff_classifies_*`; the card shows "Moved" (F renders it only through the shared item list) |
| M7-25 | Title length change | COVERED | U `text_diff`; A (unchanged title = 0); F shows the length line |
| M7-26 | Description length change | COVERED | A `m7_19_to_27` |
| M7-27 | Non-consecutive versions | COVERED | A `m7_19_to_27` (1 vs 3); F |
| M7-28 | Identical versions; order asked for | COVERED | A `m7_28`; U; F |
| M7-29 | Missing section handling | COVERED | A `m7_29`; U `missing_sections_*`, `term_diff` |
| M7-30 | Added keywords | COVERED | U `keyword_movement_*` |
| M7-31 | Removed keywords (only if in no section) | COVERED | U; A `m7_30_to_36` invariant |
| M7-32 | Retained keywords | COVERED | U |
| M7-33 | Keywords moved between sections (not "removed") | COVERED | U; A invariant; C `follow_ups` |
| M7-34 | Traceable to the saved M2 candidate | COVERED | A `m7_34`; U `keyword_trace_*` |
| M7-35 | Historical keyword no longer a candidate | COVERED | A2 `m7_35_*`: after the saved M2 analysis loses a candidate (owner-role edit) the compare row for that keyword is `NOT_IN_CURRENT_CANDIDATES`, no candidate id, evidence UNAVAILABLE; U |
| M7-36 | Missing evidence shown as unavailable | COVERED | U; A `m7_30_to_36`; F "(no saved evidence)" |
| M7-37 | Newly introduced unsupported claim (section, claim, why, fact reference, audit) | COVERED | A `m7_37_40`; U; F |
| M7-38 | Removed confirmed attribute | COVERED | A2 `m7_38_*`: with confirmed Opening = wide, dropping the word in a later edit puts it in `attributes.removed`, adding it shows `introduced`, and a `REVISION_REMOVED_CONFIRMED_INFO` suggestion names it; U |
| M7-39 | Repeated content | COVERED | A `m7_38_39` (duplicate bullet); U |
| M7-40 | New audit issue | COVERED | A `m7_37_40`; U |
| M7-41 | Resolved audit issue | COVERED | A2 `m7_41_42_*`: bullet 2's unsupported claim fixed in the next version is in `audit.resolved`; U `audit_changes_*` |
| M7-42 | Unresolved audit issue | COVERED | A2 `m7_41_42_*`: bullet 3's claim and the FACT_NOT_GIVEN note present in both versions are `audit.unresolved`, not new, not an introduced claim, and produce an `ISSUE_NOT_RESOLVED` suggestion |
| M7-43 | Historical audit preserved, never replaced | COVERED | A `m7_41_42_43` (audit rows unchanged by looking again) |
| M7-44 | Missing supported keyword | COVERED | U `recommendations_cover_*` |
| M7-45 | Missing confirmed attribute | COVERED | U |
| M7-46 | Unanswered buyer question | COVERED | A2 `m7_46_*`: a product with no confirmed colour gets exactly the M5 question "What colour is it?" as `UNANSWERED_BUYER_QUESTION` (evidence names the M5 question bank); after the seller confirms it the suggestion disappears; the F6 product (all essential topics confirmed) gets none |
| M7-47 | Evidence-based audit recommendation | COVERED | A `m7_44_to_49`; U |
| M7-48 | Unsupported recommendation prevented (weak candidate, no promise) | COVERED | U `never_use_weak_candidates_or_promise_results`; A |
| M7-49 | No evidence available | COVERED | U `no_evidence_is_said_plainly`; A `m7_49`; F |
| M7-50 | Performance unavailable = NOT_ASSESSED with what is missing | COVERED | U; A `m7_50_53`; F |
| M7-51 | Comparable performance data available | COVERED (API level) | A `test_cmo_b8_performance.py::test_m7_51_…` and `…comparable_windows…`: with an operator window length, a seller-confirmed SKU link, seller-confirmed go-live dates for two versions and uploaded sales rows covering both windows, the compare answer returns `OBSERVED_COMPARABLE` with equal-length periods per version (distinct orders), `attribution NOT_ATTRIBUTED`, no claim of impact. **Synthetic rows in a scratch database. A seller cannot reach this yet: the SKU link and go-live date can only be posted to the API (`/api/v1/cmo/performance/*`); no chat or screen captures them (B8 open).** |
| M7-52 | Incomparable periods refused | COVERED (API level) | A `test_m7_52_…` and `test_overlapping_windows_…`: windows that overlap are returned `INCOMPARABLE` with `OVERLAPPING_PERIODS` named; uncovered data, rows without an order reference, a missing link, a single go-live date or no operator window keep it `NOT_ASSESSED` with each missing item named (`test_uncovered_data_…`). Same API-level limit as M7-51. |
| M7-53 | No sales, ranking or conversion claim | COVERED | A `m7_50_53` (phrase scan), U, F |
| M7-54 | CEO history retrieval | COVERED | C `m7_54` |
| M7-55 | CEO latest version retrieval | COVERED | C `m7_55` |
| M7-56 | CEO version comparison (and what changed) | COVERED | C `m7_56` x2, `follow_ups` |
| M7-57 | Ambiguous / unknown product | COVERED | C `m7_57_two_products_*`: two products with listings get one "Which product" question with both as options, the answer "AquaNest" continues the request (version 2), "Show my latest NovaFlask listing" resolves; C `m7_57_an_unknown_product` |
| M7-58 | Ambiguous marketplace, answer continues the request | COVERED | C `m7_58` |
| M7-59 | Ambiguous / missing version | COVERED | C `m7_59` x2 |
| M7-60 | CEO optimisation request | COVERED | C `m7_60` |
| M7-61 | Frontend history timeline | COVERED | F `multi-version timeline`, `one-version`, `keyboard reachable` |
| M7-62 | Frontend version details | COVERED | F `opens an older version in full` |
| M7-63 | Frontend comparison | COVERED | F `compares any two ticked versions`, `identical`, `no new claims` |
| M7-64 | Frontend recommendations | COVERED | F `shows recommendations` |
| M7-65 | Loading, empty, error, retry, unauthorised, missing | COVERED | F `loading… retry`, `missing version and unauthorised`, `refused comparison`, `empty` |
| M7-66 | Cross-tenant denial | COVERED | A `m7_66`; C `m7_66` |
| M7-67 | Unauthorised access | COVERED | A `m7_67` |
| M7-68 | Duplicate requests / no write route | COVERED | A `m7_16`, `m7_68` |
| M7-69 | Migration compatibility (up, down, re-up, M6 untouched) | COVERED | M both tests |
| M7-70 | M0-M6 regression | COVERED | see the implementation map §19 for the run |

**Browser verification** is recorded separately in `CMO_IMPLEMENTATION_MAP.md` §19; none of the rows above is claimed browser-verified by the automated tests.

### Production-readiness phase (2026-10-31)
Counts unchanged: **M6 50/50, M7 68/70** (M7-51 and M7-52 still need the B8 data). New automated evidence: `test_marketplace_rules.py` (5; the rules register and its promotion gate), `test_ceo_cmo_m6_title_chain.py::test_when_rules_are_unverified_and_drafts_are_off_the_title_step_is_refused_before_any_plan_card`. Real-model evaluation (B2) is recorded in `CMO_RELEASE_BLOCKERS.md`; it is an opt-in harness, not an acceptance test. Browser-dependent checks remain `BLOCKED — real-data browser verification not requested`.

### Final production-readiness closure (2026-10-31)
**M6 50/50 implemented and verified. M7 70/70 covered, of which M7-51 and M7-52 are covered at API level only** (synthetic rows; no seller-facing capture of the SKU link or go-live date exists, so B8 stays open and a real seller still sees NOT_ASSESSED with what is needed). Executed in this closure: the six listed regression files **106 passed** (`test_cmo_m4_integration`, `test_cmo_m7_history`, `test_cmo_m7_history_more`, `test_cmo_m6_integration`, `test_cmo_m6_rewrite_integration`, `test_cmo_m7_migration`); `test_cmo_b8_performance.py` 10 passed; slim-cmo: `test_claim_repair.py` 12, the marketplace-rules/preview/purity/no-float group 274, prompt/generation/copy/repair unit selection 356; backend route-surface, request-contract and architecture unit tests 344; frontend history tests 20 and TypeScript clean; migrations `0008` and `0009` up/down/up on scratch databases. Browser-dependent checks remain `BLOCKED — real-data browser verification not requested`.

### M8 - Listing Performance Intelligence (2026-10-31)
Sixteen M8 criteria are tracked in `CMO_M8_PERFORMANCE.md` section 9: **13 PASS, 3 PARTIAL** (M8-11 insights are deterministic text with no model-written layer; M8-12 suggested actions name M2/M3/M5/M6 but are not one-click and their routing was not exercised; M8-14 no browser run, API and UI are tested separately with fakes). M6 50/50 and M7 70/70 are unchanged; M7-51 and M7-52 are now also reachable through seller-facing capture (still synthetic data).

New automated evidence: `test_cmo_m8_performance.py` (20), `test_ceo_cmo_m8_performance_chat.py` (10), slim-cmo `tests/unit/history/test_m8_performance.py` (report validation, metric maths, insights), frontend `components/cmo/performance/performance.test.tsx` (27).

Run: Backend (scratch database, port 5545): the six listed regression files + test_cmo_b8_performance.py + test_cmo_m8_performance.py (20) + test_ceo_cmo_m8_performance_chat.py (10) + test_ceo_cmo_m7_history_chat.py + test_cmo_p5_unit.py + test_ceo_architecture.py = 509 passed in 4m29s (run once; the M8 chat file was re-run after the last card change: 10 passed); request-contract snapshot 2 passed. slim-cmo history + marketplace rules + purity + no-float = 280 passed. Frontend: tsc --noEmit clean; eslint clean on the new files; components/cmo/performance 27 passed; lib/noClientMath and the history card tests passed; components/ceo + lib together 516 passed and 2 timed out at the 5 s limit only under full parallel load (ceoDecide price-impact, ceoAttach chips) and pass alone (25/25). Migrations 20261031_0010 and 20261031_0031 verified by hand on a fresh scratch database (up; app-role RLS, check, unique, foreign-key and no-UPDATE/DELETE rejections; downgrade refused while rows exist; down/up with FORCE RLS true). Not run: full backend, frontend, slim-cmo or integration suites; no browser verification; no real data.
