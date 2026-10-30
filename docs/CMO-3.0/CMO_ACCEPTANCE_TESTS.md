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
| N-05 | 5 Advanced generation (S11) | Approve title five, then complete listing | A separate approval card; bullets, description, keyword placement and backend terms are consistent with the chosen strategy; every keyword placed traces to a candidate from N-02; audit runs afterwards |
| N-06 | 6 History & compare (S13) | "Compare my old Amazon title with the new one" | Both versions shown with dates; deterministic diff (what moved, what was dropped, length change); explanation cites only the diff. "Has this improved my sales?" ⇒ CEO says it **cannot tell without comparable-period marketplace performance data**; no sales claim |
| N-07 | 9 Image quality (S10) | "Check my image quality" | With no image: "needs the actual uploaded images", status pending. With an image: clarity/composition/missing-shot notes labelled **advisory, not verified** until an evaluation passes; no claim about marketplace image-policy compliance |
| N-08 | 4 CI evidence (S8) | Seller has CI insights; asks what competitors emphasise | CEO gets structured evidence; CMO states differences **only where the seller's confirmed product supports a matching claim**; unsupported themes appear as "consider adding if true"; no competitor text/price reused |
| N-09 | 10 Variants (S12) | Seller adds 500 ml and 750 ml; shared brand/material/colour | One family, three variants; capacity facts kept per variant; generating the 500 ml listing never contains "1 litre" or "750"; changing the family colour asks before applying to all variants |
| N-10 | 11 Buyer questions (S10) | "What will customers ask?" | List of likely questions (insulated? leakproof? dishwasher safe?) each marked **question to investigate**, status confirmed / unknown / unsupported; none becomes a claim; offers to add confirmed answers to the profile |
| N-11 | 11→content | Seller confirms "leakproof: yes, tested" | Question status becomes confirmed with provenance; leakproof is then claim-eligible; before that it is not |
| N-12 | 12 Readiness (S11) | "Is it ready?" | Checklist split into **required blockers**, **missing facts**, **optional improvements**, **next actions**; every unrun check says "not executed", not "pass"; overall status can only be "Draft generated; readiness not verified" until all required gates ran; never says "approved by marketplace" |
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
| M6 | N-05, N-08, R-07 |
| M7 | N-06 |
| M8 | N-09 |
| M9 | N-07 |
| M10 | N-13, NEWS-1…5 |
