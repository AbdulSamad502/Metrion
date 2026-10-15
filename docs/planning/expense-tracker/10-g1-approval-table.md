# G1 approval table — keyword hits in `docs/specs/expense-tracker.md` and every PROPOSED engine item

Generated 2026-10-16 by a mechanical grep (`open` case-insensitive, `TBD`, `placeholder`, `PROPOSED`) of the spec **as of commit `e91136a`**; line numbers refer to that commit. "TBD" has no hits. Register entries are those in `02-decision-register.md`, `phase1-decisions.md` and the spec §13. This table is a planning record, not a review; no tests or reviews were run for it.

## A. Hits in the expense-tracker spec

| Line | Hit | Register entry | Needs your approval |
|---|---|---|---|
| 4 | Header: "an open question" | Structural (legend) | No |
| 14 | Legend `[PROPOSED]` | Structural (legend) | No |
| 17 | Legend `[OPEN: ...]` | Structural (legend) | No |
| 31 | P4 categories: "Contents open" | D4; spec Q5 | Yes: category list |
| 46 | P-row: release date "placeholder, owner to set" | D2 / EXP-02; Q15, Q28 (decided as an event) | No, until the deploy; date recorded then |
| 57 | §2 title `[OPEN]` | Structural | No |
| 58 | "Still open" list (D4, D5, D6, D7, D8, D10, D12, D13, X1, X2, X3, X6, X7, release date) | Register D4–D8, D10, D12, D13, X1–X3, X6, X7 | Yes: each is an open register item |
| 62 | Assumption [A]: imported rows `needs_review` "(proposed default)" | D5, D10; spec Q24 (carried assumption) | Yes |
| 76 | §5 Data model `[PROPOSED]` | D1 / EXP-01 (shape approved; schema proposed) | Yes at G1 |
| 89 | §5.3 Brain 1 contract `[PROPOSED]` | D1; Round 4 / engine §5.17 | Yes (engine items below) |
| 90 | "proposed input contract"; review_status vocabulary open (Q6) | D5; spec Q6; Round 4 | Yes |
| 92 | §5.4 Versioned results `[PROPOSED schema additions]` | D2 / EXP-02 (option B) | Yes: migration shape |
| 93 | "Proposed additions: `input_version`, `supersedes_result_id`, ..." | D2 / EXP-02 | Yes |
| 98 | §6.1 `[APPROVED shape, PROPOSED detail]` | D1 / EXP-01 | Yes: detail |
| 104 | §6.4 Settlement overlap `[PROPOSED]` | D7 | Yes |
| 106 | §6.5 Duplicates `[PROPOSED]` | D6 | Yes |
| 108 | §6.6 Advertising `[PROPOSED]` | D8; Q27, Q29 (decided) | Yes: reconciliation part |
| 114 | §6.9 Edits, voids, history `[PROPOSED]` | D1 (append-only, void instead of delete) | Yes |
| 117 | GST/TCS "[OPEN: CA]" | X6, X7; spec Q11, Q26 | Needs CA |
| 120 | §6.12 CSV import `[PROPOSED]` | D10; spec Q9, Q19 | Yes |
| 121 | CSV "Template columns [OPEN: owner]" | D10; spec Q9 | Yes |
| 125 | §6.13 rule 3: `<RELEASE_DATE: placeholder ...>` | D2 / EXP-02; Q15, Q28 | No, until the deploy |
| 141 | §7.1 vendor "rejected by code if it contains an amount-like pattern (proposed validation)" | **No register entry** (spec Q22 only) | Yes |
| 148 | §7.3 draft expiry "proposed 30 minutes, mirroring C6" | D3 (expiry); spec Q24 (carried assumption) | Yes |
| 167 | §8 `put_expense`-style entitlement check `[PROPOSED]` | **No register entry** (D11 covers permissions, not entitlement) | Yes |
| 174 | §8 item 8: `agent_run` for writes `[OPEN: X3]` | X3; spec Q12 | Yes |
| 184 | G2 row: engine items "PROPOSED items awaiting product owner approval" | Round 4 (this table, section B) | Yes: section B |
| 236 | §13 title "open questions" | Structural | No |
| 241 | Q3 "(Proposed: no)" | D3 | Yes |
| 244 | Q6 "proposed `needs_review`, `confirmed`, `rejected`" | D5 | Yes |
| 251 | Q13 "(proposed: no ...)" | D2 / EXP-02 | Yes |
| 253 | Q15 decided; keeps the placeholder | D2; Q28 | No, until the deploy |
| 257 | Q19 "REMAINS OPEN — legal/CA" | D12 | Needs legal/CA |
| 262 | Q24 "Still open (carried assumptions)": calendar-month period, `needs_review`, draft expiry, recurring materialisation, recurring scope | D5/D10 (needs_review), D3 (expiry); **no register entry for recurring commitments** | Yes |
| 267 | Q30 "details are PROPOSED" | Round 4 (section B) | Yes: section B |
| 268 | Q31 amortization PROPOSED | Round 5 (added with this table) | Yes: section B |
| 269 | Q32 per-order / per-unit templates PROPOSED | Round 5 | Yes: section B |
| 270 | Q33 multi-SKU assignment PROPOSED | Round 5 | Yes: section B |
| 271 | Q34 ledger CSV export PROPOSED | Round 5; D12 (retention) for export retention | Yes: section B |
| 288 | Appendix A: "controlled categories (Proposed)" | D4 | Yes |
| 301 | Appendix A: "11 Open questions" mapping | Structural | No |
| 312 | Appendix A: root "30-day rule": "open gate, not a claim" | D12; spec Q10 | Needs legal/CA |
| 339 | Appendix C: "carried only as a gate or open question" | Structural; spec Q10 | No |

**Hits with no register entry before this table:** line 141 (vendor amount-pattern rule, spec Q22 only), line 167 (entitlement check `[PROPOSED]`), line 262 (recurring commitments and materialisation), and lines 268–271 (Q31–Q34, new). Entries for these were added to `02-decision-register.md` ("Round 5") so every hit now has one.

## B. Every PROPOSED engine item awaiting approval (`deterministic-engine.md`)

| # | Item | Section |
|---|---|---|
| 1 | Total-profit formula: Option A (all overhead; recommended) or B | engine §5.8.1 |
| 2 | Storage term: `StorageCosts` (Option 1, recommended) or fold into other attributed costs; whether packaging and logistics pools enter the period P&L | §5.17 |
| 3 | Allocation basis granularity: per pool (recommended) or per account | §5.10.1 |
| 4 | `UNITS` net of returns (recommended) or gross; `ORDERS` distinct orders per SKU | §5.10.1 |
| 5 | New reason codes `ORDERS_UNAVAILABLE`, `BASIS_DATA_UNAVAILABLE`; details `PERIOD_MISMATCH`, `SCOPE_MISMATCH` | §5.10.1 |
| 6 | Code mapping of signed amounts; cost-class to term mapping; review-state vocabulary dependency (Q6) | §5.17 |
| 7 | `is_trial` read-layer mechanism: repository parameter (recommended) or database view | §9.2 |
| 8 | Trial version name `<CODE>.v<N>-trial` (recommended) or `v<N>-rc<k>` | §9.2 |
| 9 | Ledger watermark in `input_refs` (recommended) or a new column | §9.2 |
| 10 | Metric codes for the expense aggregates and profit lines | §9.3 |
| 11 | Amortization (Q31): shares rule, invalid-input handling `AMORTIZATION_INVALID`, refund of an amortized expense | §5.18.1 |
| 12 | Per-order / per-unit templates (Q32): count definitions, `NO_ORDERS_IN_PERIOD`, business-wide template as pool vs per-order attachment | §5.18.2 |
| 13 | Multi-SKU assignment (Q33): split bases incl. `EQUAL` and `EXPLICIT_SHARES`; extends Q29 beyond one tagged SKU | §5.18.3 |
| 14 | Ledger CSV export (Q34): field list, export permission, retention | §5.18.4 |

## C. G1 approvals recorded 2026-10-16 (supersedes the "Needs your approval" column above)

*Section A's "Needs your approval" column is historical. Frozen spec at `e91136a` and this table as first committed at `9858fc7` are not edited; this section records what was then decided.*

### C.1 Engine items 1–10 (approved as recommended)

| # | Item | Decision | Section |
|---|---|---|---|
| 1 | Total profit | **Option A approved:** total profit includes all business overhead (allocated and unallocated) | engine §5.8.1 |
| 2 | Storage term | **Approved:** add a `StorageCosts` term. **No separate packaging or logistics pools** — those costs enter through the ledger | engine §5.17 |
| 3 | Allocation basis granularity | **Approved:** per pool | engine §5.10.1 |
| 4 | UNITS / ORDERS definitions | **Approved:** `UNITS` is net of returns; `ORDERS` is distinct orders per SKU | engine §5.10.1 |
| 5 | Reason codes and details | **Approved:** `ORDERS_UNAVAILABLE`, `BASIS_DATA_UNAVAILABLE`; details `PERIOD_MISMATCH`, `SCOPE_MISMATCH` | engine §5.10.1 |
| 6 | Signed-amount and cost-class mappings | **Approved as written** in engine §5.17 (ledger cost positive, refund/credit negative; cost-class to engine term mapping). The review-state vocabulary is decided below (Q6) | engine §5.17 |
| 7 | `is_trial` read-layer exclusion | **Approved:** a repository parameter (`include_trial`) that **defaults to excluded**, **plus a test that fails if any read path lacks it** | engine §9.2 |
| 8 | Trial version name | **Approved:** `<CODE>.v<N>-trial` | engine §9.2 |
| 9 | Ledger watermark | **Approved:** in `input_refs` | engine §9.2 |
| 10 | Metric codes | **Approved as proposed** | engine §9.3 |

### C.2 Further decisions

| Ref | Item | Decision |
|---|---|---|
| Q6 | Review states | **Decided:** `draft`, `pending_review`, `confirmed`, `voided`. A correction is a **new linked entry**, never an edit of the old one. This supersedes the earlier proposal in spec §13 Q6 (`needs_review`, `confirmed`, `rejected`) and the spec wording "imported rows `needs_review`" (read as `pending_review`); the frozen spec is not edited |
| Q31 | Refund of an amortized expense | **Decided:** it reduces the remaining schedule **from the refund date forward**; past months are **not** restated. *Approved outright in Round 7 (2026-10-16) including `AMORTIZATION_INVALID` to the review queue; build priority unchanged (kickoff Step 5)* |
| Q32 | Per-order / per-unit templates | **Decided:** SKU- or channel-scoped templates attach per order or unit as **direct costs**; business-wide templates become a **business-level pool**; **no automatic spreading**. *Approved outright in Round 7 (2026-10-16) including `NO_ORDERS_IN_PERIOD`, which means the amount is unavailable, not zero; build priority unchanged* |
| Q33 | Multi-SKU assignment | **Approved:** bases `EQUAL` and `EXPLICIT_SHARES`, **seller-chosen only**; extends Q29; manual entries stay **flagged manual** |
| Q34 | Ledger CSV export | **Decided:** generated **on demand, not stored**; permission **follows the existing financial read permission**; retention goes to **legal/CA**. *Approved outright in Round 7 (2026-10-16): fields = all ledger fields including treatment, review status, void status and source reference; retention stays with legal/CA; build priority unchanged* |
| Q22 | Vendor text validation (register X8) | **Decided:** reject vendor text containing a **currency symbol** or an **amount-like number** (such as `1,200.50`); **allow short numerals** (e.g. "3M"); **show an edit prompt** |
| X9 | Entitlement check | **Decided:** reuse the existing CFO entitlement gate |
| X10 | Recurring entries | **Decided:** materialized recurring entries start as `pending_review` |
| X1 | Legacy tracker | **Decided:** keep the legacy `PUT/GET /cfo/expenses` path until cut-over |
| X3 | `agent_run` for expense writes | **Decided:** one `agent_run` row per expense write |
| X2 | Write-validation bounds | **Decided process:** engineering proposes bounds from the legacy validation; **no numbers are invented**. Open until that proposal is made |

### C.3 Left open

Q19 and Q34 retention (legal/CA); G4 (retention and storage); G5 (tax wording); Q15 release date (placeholder until the first production deploy after G7 passes producing `is_trial=false` results). Unchanged: Q1 countersign (below), Q29/Q30 as already decided.

### C.4 Still PROPOSED after Round 7

Only the TP1–TP10 test list (§5.8.1), the §5.17 function name, and the §5.18.3 mechanics and tests MS1–MS7. Amortization, per-order/per-unit templates and the ledger CSV export are approved (Round 7, 2026-10-16), with the engine spec marked accordingly; section D below lists every engine-spec hit.

## D. Engine spec keyword table — every `PROPOSED` / `APPROVED` hit in `deterministic-engine.md` (2026-10-16)

Generated by a mechanical grep (case-insensitive `PROPOSED|APPROVED`) of the engine spec in this commit; line numbers refer to that commit. One row per hit line. "Register entry" is the decision-register / `phase1-decisions.md` item the hit belongs to. No review or test was run for this table.

| Line | Status | Excerpt | Register entry |
|---|---|---|---|
| 101 | generic "approved" (not a Round status) | ts an attribution. Effective for calculations from the approved release date (placeholder, owner to set); results befo | EXP-06 / D9; Q15 (generic "approved release date") |
| 364 | APPROVED (Round 6, 7c46d9d) | al-profit formula. It is written in §5.8.1 (Option A APPROVED (Round 6, 7c46d9d)). Required invariant (stated in 'expense-tracker.md' | Round 6 item 10 (§9.3) and Q27/Q30 (`phase1-decisions.md`); register D9 |
| 368 | mixed: APPROVED part and PROPOSED part | located lines (Q27). The formula below (Option A) is APPROVED (Round 6, 7c46d9d); the test list at the end of this section is still | Round 6 item 1 (total profit Option A); Q30; register Round 4/6 |
| 372 | APPROVED (Round 6, 7c46d9d) | Definitions (APPROVED (Round 6, 7c46d9d), Option A). For a period and channel scope, let each | Round 6 item 1 (total profit Option A); Q30; register Round 4/6 |
| 388 | APPROVED (Round 6, 7c46d9d) | Option A (APPROVED (Round 6, 7c46d9d)): TotalProfit includes all business overhead (alloca | Round 6 item 1 (total profit Option A); Q30; register Round 4/6 |
| 392 | PROPOSED (still open) | Tests (PROPOSED; G2 — the test list is not covered by the Round 6 appr | Round 6 item 1 (total profit Option A); Q30; register Round 4/6 |
| 398 | APPROVED (Round 6, 7c46d9d) | reason 'INVALID_BASIS' with detail 'PERIOD_MISMATCH' (APPROVED (Round 6, 7c46d9d) code); 'TotalProfit' unchanged \| | Round 6 item 1 (total profit Option A); Q30; register Round 4/6 |
| 442 | APPROVED (Round 6, 7c46d9d) | n-code additions and per-pool granularity below were APPROVED (Round 6, 7c46d9d). | Round 6 items 3, 4, 5 (basis per pool, UNITS/ORDERS, reason codes); Q29; register D9 |
| 446 | APPROVED (Round 6, 7c46d9d) | r 'cost_class' and scope) — granularity per pool is APPROVED (Round 6, 7c46d9d) (the alternative, one basis for the whole account, w | Round 6 items 3, 4, 5 (basis per pool, UNITS/ORDERS, reason codes); Q29; register D9 |
| 450 | APPROVED (Round 6, 7c46d9d) | AILABLE' → pool unallocated, 'BASIS_DATA_UNAVAILABLE' (APPROVED (Round 6, 7c46d9d) code) \| | Round 6 items 3, 4, 5 (basis per pool, UNITS/ORDERS, reason codes); Q29; register D9 |
| 451 | APPROVED (Round 6, 7c46d9d) | nits sold − units returned/RTO'd (net of returns is APPROVED (Round 6, 7c46d9d); gross units were not adopted) \| a quantity on ev | Round 6 items 3, 4, 5 (basis per pool, UNITS/ORDERS, reason codes); Q29; register D9 |
| 452 | APPROVED (Round 6, 7c46d9d) | (an order containing two SKUs counts once for each — APPROVED (Round 6, 7c46d9d)) \| order id on every in-scope line \| any in-scope li | Round 6 items 3, 4, 5 (basis per pool, UNITS/ORDERS, reason codes); Q29; register D9 |
| 454 | APPROVED (Round 6, 7c46d9d) | D_BASIS', detail 'PERIOD_MISMATCH' / 'SCOPE_MISMATCH', APPROVED (Round 6, 7c46d9d)). A business-wide pool queried for a single channel is | Round 6 items 3, 4, 5 (basis per pool, UNITS/ORDERS, reason codes); Q29; register D9 |
| 458 | APPROVED (Round 6, 7c46d9d) | OR', 'UNITS_UNAVAILABLE', 'INVALID_BASIS'. Additions APPROVED (Round 6, 7c46d9d): 'ORDERS_UNAVAILABLE', 'BASIS_DATA_UNAVAILABLE', and | Round 6 items 3, 4, 5 (basis per pool, UNITS/ORDERS, reason codes); Q29; register D9 |
| 904 | generic "approved" (not a Round status) | ce band and outliers — 'compute_price_band' (NEW — the approved amendment resolving 'competitor-intelligence-agent.md' | n/a — a different, earlier amendment (price band) |
| 973 | mixed: APPROVED part and PROPOSED part | orageCosts' term and the review-state vocabulary are APPROVED (Round 6, 7c46d9d); the function name remains PROPOSED. Not built. | Round 6 items 2, 6 (StorageCosts term, signed-amount and cost-class mappings), Q6/D5, Q21, Q24; register D1 |
| 987 | APPROVED (Round 6, 7c46d9d) | ion is a new linked entry; only 'confirmed' counts — APPROVED (Round 6, 7c46d9d). (6) Treatment: 'incremental' rows count; 'alre | Round 6 items 2, 6 (StorageCosts term, signed-amount and cost-class mappings), Q6/D5, Q21, Q24; register D1 |
| 989 | APPROVED (Round 6, 7c46d9d) | d amounts, both directions (Q21; the code mapping is APPROVED (Round 6, 7c46d9d)). The ledger stores 'amount_paise' signed: a cost | Round 6 items 2, 6 (StorageCosts term, signed-amount and cost-class mappings), Q6/D5, Q21, Q24; register D1 |
| 993 | APPROVED (Round 6, 7c46d9d) | Cost-class mapping (APPROVED (Round 6, 7c46d9d)). The ledger's 'cost_class' maps to engine terms: ad | Round 6 items 2, 6 (StorageCosts term, signed-amount and cost-class mappings), Q6/D5, Q21, Q24; register D1 |
| 997 | mixed: APPROVED part and PROPOSED part | r-unit templates) and 5.18.4 (ledger CSV export) are APPROVED (Round 7, 2026-10-16) (build priority unchanged: kickoff Step 5). 5.18.3 ( | Round 6/7 approvals for Q31–Q34 (register X11–X14) |
| 1008 | APPROVED (Round 7, 2026-10-16) | #### 5.18.1 Amortization (APPROVED (Round 7, 2026-10-16)) | Q31 / X11 (APPROVED Round 7; refund rule Round 6) |
| 1015 | APPROVED (Round 7, 2026-10-16) | o the review queue with reason 'AMORTIZATION_INVALID' (APPROVED (Round 7, 2026-10-16) code); it is never counted whole and never as zero. 'A | Q31 / X11 (APPROVED Round 7; refund rule Round 6) |
| 1016 | APPROVED (Round 6, 7c46d9d) | - Refunds (APPROVED (Round 6, 7c46d9d), Q31). A refund of an amortized expense is a separat | Q31 / X11 (APPROVED Round 7; refund rule Round 6) |
| 1017 | APPROVED (Round 7, 2026-10-16) | - Tests (APPROVED (Round 7, 2026-10-16)). AM1 ₹12,000 over 12 → ₹1,000 × 12; AM2 ₹1,000.01 o | Q31 / X11 (APPROVED Round 7; refund rule Round 6) |
| 1019 | APPROVED (Round 7, 2026-10-16) | #### 5.18.2 Per-order and per-unit cost templates (APPROVED (Round 7, 2026-10-16)) | Q32 / X12 (APPROVED Round 7; scoped vs business-wide Round 6) |
| 1025 | APPROVED (Round 7, 2026-10-16) | at all in scope, the result is 'NO_ORDERS_IN_PERIOD' (APPROVED (Round 7, 2026-10-16) code), which means the amount is unavailable, not ze | Q32 / X12 (APPROVED Round 7; scoped vs business-wide Round 6) |
| 1026 | APPROVED (Round 6, 7c46d9d) | emplates attach per order or unit as direct costs (APPROVED (Round 6, 7c46d9d), Q32). A business-wide template becomes a business-l | Q32 / X12 (APPROVED Round 7; scoped vs business-wide Round 6) |
| 1027 | APPROVED (Round 7, 2026-10-16) | - Tests (APPROVED (Round 7, 2026-10-16)). PT1 ₹5 × 200 orders = ₹1,000 exactly; PT2 missing | Q32 / X12 (APPROVED Round 7; scoped vs business-wide Round 6) |
| 1029 | mixed: APPROVED part and PROPOSED part | i-SKU assignment (bases and seller-chosen assignment APPROVED (Round 6, 7c46d9d); remaining mechanics and tests PROPOSED) | Q33 / X13 (bases APPROVED Round 6; mechanics and tests still PROPOSED) |
| 1033 | APPROVED (Round 6, 7c46d9d) | nd 'EXPLICIT_SHARES', chosen by the seller only, are APPROVED (Round 6, 7c46d9d) (Q33). | Q33 / X13 (bases APPROVED Round 6; mechanics and tests still PROPOSED) |
| 1036 | APPROVED (Round 6, 7c46d9d) | ed SKU on the form; assigning several SKUs extends it (APPROVED (Round 6, 7c46d9d), Q33); manual entries stay flagged manual. | Q33 / X13 (bases APPROVED Round 6; mechanics and tests still PROPOSED) |
| 1037 | PROPOSED (still open) | - Tests (PROPOSED). MS1 equal split of an odd paise amount over 3 SKUs | Q33 / X13 (bases APPROVED Round 6; mechanics and tests still PROPOSED) |
| 1039 | APPROVED (Round 7, 2026-10-16) | .18.4 Ledger CSV export for the seller's accountant (APPROVED (Round 7, 2026-10-16)) | Q34 / X14 (APPROVED Round 7; permission and on-demand Round 6; retention open, Q19/D12) |
| 1045 | APPROVED (Round 6, 7c46d9d) | The export is generated on demand and not stored (APPROVED (Round 6, 7c46d9d), Q34); its permission follows the existing financial | Q34 / X14 (APPROVED Round 7; permission and on-demand Round 6; retention open, Q19/D12) |
| 1046 | APPROVED (Round 7, 2026-10-16) | - Tests (APPROVED (Round 7, 2026-10-16)). EX1 every field present, header order stable; EX2 | Q34 / X14 (APPROVED Round 7; permission and on-demand Round 6; retention open, Q19/D12) |
| 1417 | generic "approved" (not a Round status) | Decision (approved). A curated, hardcoded allowlist of trusted domains | n/a — GST lookup allowlist decision, unrelated |
| 1605 | APPROVED (Round 6, 7c46d9d) | d-layer mechanism and the ledger-watermark field are APPROVED (Round 6, 7c46d9d). | Round 6 items 7, 8, 9, 10 (§9.2/§9.3); Q28, Q30; register D2 |
| 1610 | APPROVED (Round 6, 7c46d9d) | y seller-facing read at the read layer. Mechanism APPROVED (Round 6, 7c46d9d): every repository read that can reach a seller, a c | Round 6 items 7, 8, 9, 10 (§9.2/§9.3); Q28, Q30; register D2 |
| 1611 | APPROVED (Round 6, 7c46d9d) | 3. Trial formula version name (APPROVED (Round 6, 7c46d9d)). Current convention: '<METRIC_CODE>.v<N>' (e.g. 'CO | Round 6 items 7, 8, 9, 10 (§9.2/§9.3); Q28, Q30; register D2 |
| 1614 | APPROVED (Round 6, 7c46d9d) | 6. Ledger input version (APPROVED (Round 6, 7c46d9d)). 'metric_result' has no ledger-input version. Appr | Round 6 items 7, 8, 9, 10 (§9.2/§9.3); Q28, Q30; register D2 |
| 1616 | APPROVED (Round 6, 7c46d9d) | 3 Metric codes for the expense dashboard aggregates (APPROVED (Round 6, 7c46d9d)) | Round 6 items 7, 8, 9, 10 (§9.2/§9.3); Q28, Q30; register D2 |

**Still PROPOSED after this round (6 lines contain PROPOSED: 368, 392, 973, 997, 1029, 1037):** the TP1–TP10 test list (§5.8.1), the §5.17 function name, and the §5.18.3 mechanics and tests MS1–MS7. Everything else listed above is APPROVED in Round 6 (`7c46d9d`) or Round 7 (2026-10-16). Hits with no register entry: none (two unrelated generic "approved" lines are marked n/a).
