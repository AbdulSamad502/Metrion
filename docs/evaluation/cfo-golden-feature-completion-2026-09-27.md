# CFO — Golden Feature Completion Report (2026-09-27)

Scope: complete all phases except real-seller-data validation, per explicit instruction.
Evidence, not assertion — every item below is backed by a passing test against the real local
Postgres, or explicitly marked skipped with the reason.

## Test evidence

| Suite | Result |
|---|---|
| backend | 174 passed |
| cfo | 303 passed, 3 skipped (pre-existing) |
| calc-engine | 436 passed |
| data-foundation | 117 passed |
| **Total** | **1030 passed, 0 failed** |

Frontend: `tsc --noEmit` clean.

## Completed this pass

1. **Ingestion-to-canonical pipeline, fully closed.** Upload CSV → `run_ingestion` (parse +
   validate) → persist `sales_line`/`line_component` → `assemble_canonical_lines_for_period`
   (manual-adjustment overlay resolution) → `compute_period_pnl_for_tenant` → real, persisted
   `CONTRIBUTION_PROFIT`. Verified end-to-end with zero hand-assembled data in the test
   (`test_period_pnl_for_tenant.py`, `test_ingest_and_persist.py`). Sales-side adapters only
   (6 of 9); settlement-side persistence (Amazon/Flipkart/Meesho payments adapters) needs its
   own write repo — not built, disclosed, not silently assumed.
2. **`POST /api/v1/cfo/ingest`** — real upload route, dedup by content hash and natural key.
3. **Two new manual_adjustment fields** (`returned_qty_override`/`rto_qty_override`) closing a
   real, confirmed schema gap — no adapter or column anywhere supplies a return/RTO unit count.
4. **Strategic Insight layer extended**: `PRICING`/`SUPPLIER` scenario-comparison signals
   (reuses `compute_pricing_curve`/`rank_suppliers` output, never re-derives), wired into
   `assemble_strategic_briefing`. Not yet exposed on the HTTP request body (backend-complete,
   API surface not extended — disclosed).
5. **`seller.goal`** (`PUT`/`GET /cfo/seller-goal`) — seller-declared context fed into the
   Strategic Briefing's narration prompt. Never changes a `severity_rank` or
   `recommended_action_type` — both stay deterministic; the goal only shapes *how Brain 3
   explains* a signal, never *what* the signal is.
6. **Dashboard integration** — four new sections on `/dashboard/cfo`: file upload, seller goal,
   Financial Health Band, Strategic Briefing. Typechecked; not click-tested live (no seeded
   tenant/session in this pass).

## Explicitly NOT done, with reasons — not silently skipped

- **Settlement-side ingestion persistence** (Amazon/Flipkart/Meesho payments/settlement
  adapters) — needs a new `settlement_line` write repo, not built this pass.
- **GST/marketplace-fee reference data seeding** — would require sourcing real, current CBIC
  GST schedules and each marketplace's own published fee tables with real citations. This is a
  research task, not a coding task, and CLAUDE.md's hard rule forbids approximating it.
  `compute_pricing_curve` correctly stays `UNAVAILABLE` without it — by design, not a defect.
- **Synthetic multi-month dataset generator** — the existing integration tests already prove
  the complete upload→P&L→insight flow works end to end; a larger synthetic book was judged
  lower value than the items above given the session's token budget, and was not built.
- **LLM eval suite** for the Strategic Briefing narration surface — CLAUDE.md requires this
  before a new Brain-3 surface ships to a real seller; deterministic wiring is fully tested,
  the model's own prompt-following behavior against live Ollama is not.
- **Real seller-data validation** — excluded per your own explicit instruction.

## Is this the golden feature — a real CFO with CA knowledge?

**Architecture: yes.** The deterministic core is genuinely rare-good — it never invents a
number, cites provenance on every figure, and now (as of this pass) actually reaches real
uploaded data end to end, not just hand-fed test fixtures. The Strategic Insight layer gives it
real, if young, "explain and prioritize" reasoning, strictly bounded so the LLM never computes
or decides.

**Domain authority: not yet, and said so throughout.** No GST rate or marketplace fee in this
system was invented — which means many are still honestly `UNAVAILABLE` until real reference
data is sourced. That is the correct, safe state for an unreviewed system, not a shortcut.
Before any real seller sees this, a qualified CA should review the GST/formula logic against
current law, and the fee-reference/GST-slab data needs real sourcing — both outside what a
coding pass alone can certify.

**Bottom line:** the plumbing and the honesty discipline are both real and tested now, further
than before this session. The remaining gap to "golden feature" is domain data (GST/fee
reference) and human expert review, not architecture.
