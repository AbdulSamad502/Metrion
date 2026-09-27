# cfo

Metrion's CFO agent. Implements the real-backed slice of
[`docs/specs/cfo-agent.md`](../../docs/specs/cfo-agent.md) defined in the CFO V1
implementation plan (`twinkly-mapping-canyon.md`) — see that plan's "Verified buildable vs.
blocked" table for what is real against `packages/calc-engine` source today versus deferred
pending nonexistent engine functions.

**Install order.** This package must be installed **before** `backend` (which imports it
directly, the same way it already imports `competitor-intelligence`) and **after**
`calc-engine`, `data-foundation` and `competitor-intelligence`:

```
calc-engine → data-foundation → competitor-intelligence → cfo → backend[dev]
```

See `backend/README.md` and `.github/workflows/ci.yml` for the exact install steps.

**Hard rule (CLAUDE.md):** this package computes no financial figure of any kind — margin,
fee, profit, tax or cost. It assembles inputs and calls the real, unchanged engine function in
`packages/calc-engine` (Brain 1); it never re-derives, re-sums or originates a money value
itself. Any money-touching calculation belongs in the engine, never here.

## Verified buildable vs. blocked (against real `calc-engine` source, 2026-09-23)

| Capability | Status | Real backing / blocker |
|---|---|---|
| Period P&L (NRR + Contribution Profit) | **Buildable** | `compute_net_realized_revenue`, `compute_contribution_profit` (`calc_engine/api/compute_metric.py:67,121`); cost inputs from `cost_components`/`marketplace_fees`/`expense_pools`/`return_rto_losses`; canonical tables `sales_line`/`line_component` exist (`data-foundation .../20260917_0001_sales_side_tables.py:80,120`) |
| Expense entry (manual input) | **Buildable end-to-end** | `manual_adjustment` store (calc-engine migration) + `expense_pools` |
| **Line-level GST analysis** (NOT a period summary) | **Buildable — line-level only** | `normalize_to_exclusive` (`gst/normalization.py:23`) + `check_rate_plausibility` (`gst/slab_reference.py:33`). This is per-line normalization + plausibility only. It is **never called a "period GST summary" and never produces a period GST total** — that (`cfo.gst_summary`, §6.8) is DEFERRED because `gst/summary.py` is a bare stub |
| Leak classification + ranking **logic** | **Buildable as library logic only — NOT a seller-facing finding surface** | `rank_findings` (`formulas/severity.py:109`) is real. `reconcile()` that produces the exception rows **does not exist**. The classification/ranking/persistence logic is built and unit-tested against **synthetic exceptions that are test fixtures ONLY**. **Synthetic findings are never exposed as real seller Leak Shield findings** — a real finding requires a real `reconcile()` output. Category mapping is **Q12-blocked** — mechanism built, table PROVISIONAL |
| Brain-3 Knowledge & Reasoning layer (§7.4) | **Buildable** | LLM narration behind provider abstraction (Ollama dev); narrates real figures only, emits no number |
| Backend integration (routes, CEO dispatch, audit, RLS, migrations) | **Buildable** | Mirrors CI |
| Reconciliation run, cash-flow view, margin curve, landed cost, fee-reference, GST lookup, period delta, anomaly, entitlement gates | **DEFERRED** | Nonexistent engine functions / unwritten Brain-2 & entitlement specs — see the plan's Deliverable B |

Repo layout mirrors `packages/competitor-intelligence/` (the same package structure decision
recorded in `docs/planning/phase-1-readiness-review.md` item 2.5).
