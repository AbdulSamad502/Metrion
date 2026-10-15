# Expense Tracker — documentation index (2026-10-15)

**Authority order.** (1) `docs/decisions/phase1-decisions.md` — approved decisions EXP-01…EXP-08 and separate task ST-01. (2) `docs/specs/expense-tracker.md` — the single canonical spec (approved requirements, proposals, deferrals, gates, open questions, reconciliation, dependency map). (3) The files below are **planning evidence**: they never override (1) or (2).

| File | Role | Status after consolidation |
|---|---|---|
| `01-repository-audit.md` | Verified architecture and gaps (planning run) | **Current evidence**, updated: new §0.1 (branch) and §7 (facts verified in the consolidation) |
| `02-decision-register.md` | The 14 decisions + extras | **Current**: D1, D2, D3, D9, D11 (no new key), D14 approved with their EXP ids; others open; superseded recommendations marked |
| `03-architecture-options.md` | Options and candidate design | **Current with overlay**: adopted option B, `financials.adjust` (no new key), draft-from-chat (vendor/category/date only) |
| `04-test-and-risk-matrix.md` | Tests, risks, gates | **Current**: S1a no-new-key test, A-series allocation suite (launch requirement), historical-result and draft tests, ST-01 tests |
| `05-implementation-roadmap.md` | Phases | **Current with overlay**: P5 = allocation engine change; ST-01 separate |
| `01-code-spec-audit.md` | Parallel run: line-level code ↔ draft-v2 audit | **Historical evidence, unmodified.** Its facts were re-verified where cited in `01-repository-audit.md` §6–§7. Its "do-not-assume" notes remain useful; its recommendations are not current. |
| `01-decision-register.md` | Parallel run: verdicts on the draft's 10 questions | **Historical, unmodified.** Superseded by `02-decision-register.md` and the approved decisions (e.g. its N1 "reverse C21 or forms only", Q8 "category blocks the schema" are answered/replaced). |
| `01-blockers.md` | Parallel run: blockers B1–B13 | **Historical, unmodified.** Still a valid risk list; B1 (quick-add vs C21) is now governed by EXP-03, B6/B7 by EXP-01. |
| `archive/expense-tracker.md` (was the root `expense-tracker.md`) | "DRAFT v2" | **Superseded** by the canonical spec (Appendix A); moved here unchanged (it was untracked, so a plain move, not `git mv`). |

**Not present (searched):** `06-architecture-decision-proposals.md`, `07-decision-sheet.md`, `legal-safeguards.md`, `improvement-roadmap.md`. `spec-reviewer.md` was recovered from git history and restored at `.claude/agents/spec-reviewer.md`.

**Recommended cleanup (not performed, needs approval):** move the three parallel-run `01-*` files into `docs/planning/expense-tracker/archive/` and renumber so each prefix is unique. Independent review: see `08-spec-review-2026-10-15.md`.
