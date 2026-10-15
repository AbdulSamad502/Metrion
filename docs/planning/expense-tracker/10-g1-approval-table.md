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
| Q31 | Refund of an amortized expense | **Decided:** it reduces the remaining schedule **from the refund date forward**; past months are **not** restated. *Whether amortization itself is approved as a feature, and its `AMORTIZATION_INVALID` handling, were not stated: still PROPOSED* |
| Q32 | Per-order / per-unit templates | **Decided:** SKU- or channel-scoped templates attach per order or unit as **direct costs**; business-wide templates become a **business-level pool**; **no automatic spreading**. *Whole-feature approval and `NO_ORDERS_IN_PERIOD` were not stated: still PROPOSED* |
| Q33 | Multi-SKU assignment | **Approved:** bases `EQUAL` and `EXPLICIT_SHARES`, **seller-chosen only**; extends Q29; manual entries stay **flagged manual** |
| Q34 | Ledger CSV export | **Decided:** generated **on demand, not stored**; permission **follows the existing financial read permission**; retention goes to **legal/CA**. *Field list not separately confirmed: still PROPOSED as written* |
| Q22 | Vendor text validation (register X8) | **Decided:** reject vendor text containing a **currency symbol** or an **amount-like number** (such as `1,200.50`); **allow short numerals** (e.g. "3M"); **show an edit prompt** |
| X9 | Entitlement check | **Decided:** reuse the existing CFO entitlement gate |
| X10 | Recurring entries | **Decided:** materialized recurring entries start as `pending_review` |
| X1 | Legacy tracker | **Decided:** keep the legacy `PUT/GET /cfo/expenses` path until cut-over |
| X3 | `agent_run` for expense writes | **Decided:** one `agent_run` row per expense write |
| X2 | Write-validation bounds | **Decided process:** engineering proposes bounds from the legacy validation; **no numbers are invented**. Open until that proposal is made |

### C.3 Left open

Q19 and Q34 retention (legal/CA); G4 (retention and storage); G5 (tax wording); Q15 release date (placeholder until the first production deploy after G7 passes producing `is_trial=false` results). Unchanged: Q1 countersign (below), Q29/Q30 as already decided.

### C.4 Still PROPOSED after this round

Engine items 11, 12 and 14 as whole features (amortization, per-order/per-unit templates, ledger CSV export) and their codes and field list; the engine spec text still carries the PROPOSED labels until it is updated to match section C.1 (not done in this documentation round).
