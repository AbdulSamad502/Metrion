# Expense Tracker — readiness checklist (2026-10-16)

Status below is taken only from the repository (`git log`, the decision record, the specs and the files named). Branch: `feat/pnl-calculator-and-expense-tracker`. Nothing here approves anything; items needing a decision are listed as such. Authority: `docs/decisions/phase1-decisions.md` over the frozen spec (`docs/specs/expense-tracker.md`, frozen at `e91136a`).

## 1. Done (with commits)
| Item | Commit(s) |
|---|---|
| Specs amended for the ledger (engine D7/§5.8/§5.10, CFO, CEO E30/T36, auth, readiness items) | `60ec85b` |
| Canonical Expense Tracker spec and Phase 1 decisions | `bcca43a` |
| Planning documents, review record, `spec-reviewer` restored | `1f43713` |
| Profit Calculator and spec work combined on one branch | merge `e26984e` |
| Engine spec: total profit, allocation bases, ledger feed, trial-result rules | `2e000bf` |
| Four PROPOSED engine items, reconciliation criterion AC17/F7, positioning note | `e91136a` |
| Spec frozen for G1 review, approval table | `9858fc7` |
| Implementation kickoff plan | `1799eaa` |
| G1 approvals recorded (Round 6) | `7c46d9d` |
| Round 6/7 marks in the engine spec, errata to the frozen spec | `ff84d39` |
| ST-01 "Not entered in this calculation" (display only) | `44a39c0`, merged `4e5274b`, recorded `6a5c047` |
| Round 8 approvals (TP tests, §5.18.3) | `e3e5b6b` |
| Engine slices A–E: `is_trial` read exclusion `b772a7b`; allocation bases and outcomes `ce933f6`; total profit and `StorageCosts` (inactive version) `7ece7ac`; ledger feed `a3c4ee0`; expense metric codes and definitions `86d5923` | as listed |
| Engine step notes, results and open questions | `64123cc` |
| Dashboard inspection and Step 3 proposals | `d7e3b87` |
| Unallocated-spend caveats in the consumer specs (cfo-agent §6.7, anomaly-detection §6.2, calculator §14.9) | `03ec7ef` |

Verified results are in `11-engine-step-notes.md` (calc-engine unit 485 passed; full backend integration suite 2013 passed, 3 skipped, 1 xfailed on the scratch database). Nothing in the engine is wired to a route, a table or the default formula path; the new formula versions are inactive and the release date (Q15) is not set.

## 2. Needs the product owner
- **Q1 countersign** of EXP-01…EXP-08 (the line in `phase1-decisions.md` and the spec header is blank).
- **Q15 release date:** defined by event (first production deploy after G7 passes producing `is_trial=false` results); the concrete date is still the placeholder.
- **Approval of the Step 3 proposals** in `13-step3-proposals.md`: categories and the category-to-cost-class mapping (including the "Direct product costs" row marked BLOCKED as written, and whether to add Storage), the X2 bounds approach, the ledger migration owner (recommended calc-engine), and what "True Margin" means.
- **Navigation proposal** in `12-dashboard-inspection.md` §2 (N1 recommended; N2 and N3 alternatives); the permission set in the session response; whether "Cyber-Luxe" is a name for the existing visual direction (it is not defined anywhere in the repo).
- **Engine decision flagged in `11-engine-step-notes.md`:** missing returned quantity for the `UNITS` basis (implemented as unavailable, not zero).
- **Sign convention check:** `data-foundation.md` §1.1 says "revenue positive, deductions negative" (seller perspective) while the engine and its fixtures use positive cost magnitudes that formulas subtract; the approved ledger mapping (cost positive, refund negative) follows the code. Owner/engineering should confirm this reading before the feed is wired.
- **Appendix C of the frozen spec:** `legal-safeguards.md` and `improvement-roadmap.md` do not exist; locate them or strike their citations (G1).
- Approval of the kickoff build order in `09-implementation-kickoff.md`.

## 3. Needs legal or CA
- **Q19** raw expense CSV retention (does the "immutable raw files" principle extend to expense CSVs).
- **Q34 retention** of the accountant export (the export itself is on demand and not stored).
- **G4** retention and storage: the "30-day rule" source (Q10) and any receipt storage.
- **G5** tax wording: GST/ITC fields, TCS (available as a real settlement field for Flipkart only, Q26), and the default treatment of a "taxes" category.

## 4. Needs engineering
- **X2 write-validation bounds proposal:** the legacy route has no numeric bounds; only the 11-digit rupee ceiling and two-decimal rule exist in code. String-length caps and row limits need an engineering proposal (`13-step3-proposals.md` §2).
- **Migrations (Step 3):** the ledger tables, seeding the inactive definitions into `formula_definition`, and closing the `shared_finding` trigger so it does not accept trial results.
- **Cut-over of the legacy tracker** (X1: keep the legacy path until cut-over; mechanics open); the legacy `list_expenses` total is computed in the backend and must not be used for dashboard totals.
- **Wiring:** routes that run `ledger_feed` and mint `EXPENSE_*` results; never persist `CONTRIBUTION_PROFIT.v2` rows before the release (see `11-engine-step-notes.md` note 6).

## 5. Gates G1–G7
| Gate | What it needs now |
|---|---|
| **G1 Design approval** | Q1 countersign; Appendix B items approved or deferred (B.1 and B.4 applied; others per the approval table); X1 decided (done: keep legacy until cut-over); release date defined by event (done); Appendix C citations located or struck |
| **G2 Financial integrity** | Engine functions and tests exist (A1–A7, A9 partly, A10, F1, F5, F6, TP1–TP10, F7 at engine level). Still needed: A8 (tenant isolation/authorization of allocation, needs the ledger tables and routes); the ledger feed wired into the P&L and the dashboard; the historical-result demonstration (old result preserved, version label shown, explicit restatement linked and labelled); a reconciliation worked example per cost class; the F7 reconciliation against real ledger data; the seller-facing release note (AC14/F4); the consumer-spec caveats are documented (`03ec7ef`) but must be implemented in the surfaces before release |
| **G3 Security** | Not started: no write routes yet. Needs S-series and idempotency tests, every-route 401/403 tests, two-tenant isolation, and the documented `financials.adjust` COGS limitation visible to owners |
| **G4 Retention and storage** | Legal/CA decision; storage design; the "30-day rule" located or retired |
| **G5 Tax wording** | CA review of any GST/ITC/TCS field shown; TCS only where the channel supplies it |
| **G6 Draft-from-chat** | Implementation approval of the EXP-03 amendments (spec text already applied); registry key, effect class and classifier route built; evals; update the code and tests that still decline (T36) |
| **G7 Production validation** | 3–5 sellers reconcile output; F2/AC12 pass (trial results never seller-visible); a run producing `is_trial=false` results. Not started |

## 6. Environment prerequisites
- **Scratch Postgres only, never the dev database:** `bash backend/scripts/scratch_db.sh up` (port 5544), then `eval "$(bash backend/scripts/scratch_db.sh env)"`; tear down with `bash backend/scripts/scratch_db.sh down`. `backend/tests/integration/db_guard.py` aborts the session if the URLs point at port 5432 (override `METRION_TESTS_ALLOW_DEV_DB=1`, which must not be used).
- Seven `packages/cfo` unit tests also need `LLM_OPERATOR_CONTROLLED_HOSTS=localhost:11434`.
- The full backend integration suite took about 47 minutes on the scratch database; run vitest and the suite apart.
- All work stays on the combined branch; nothing is pushed, merged to `main` or deployed without a separate instruction.
