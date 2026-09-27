# data-foundation

Metrion's file-understanding / ingestion layer — see `docs/specs/data-foundation.md`.

Turns seller-uploaded Amazon/Flipkart/Meesho marketplace report files into the canonical
`sales_line`/`line_component` model `packages/calc-engine` (Brain 1) consumes. This is **not**
"Brain 2" — that name is already reserved in this repo's vocabulary for the future statistical
anomaly-detection layer (see `docs/planning/phase-1-readiness-review.md`).

**Scope:** primarily sales-side ingestion, plus `meesho.payments.v1` — the first
settlement-side adapter, covering only the Payments workbook's "Order Payments" tab, and only
its two spec-confirmed columns (`docs/specs/data-foundation.md` §5.6/§1.4) — and its backing
`settlement_line` table (§5.6). `amazon.settlement.v2` and the reconciliation tables
(`reconciliation_run`/`match`/`exception`, calc-engine-owned per §5.7) remain deferred — no
schema for them exists in this package.

**Column coverage is honest, not exhaustive.** Every adapter's `column_map` includes only
columns `data-foundation.md` actually names verbatim. Every other column in a real file is
structurally unknown and correctly raises `V-COL-001` until a real export is inspected
(§9's validation procedure) — see `src/data_foundation/adapters/base.py`'s module docstring
for the full reasoning.

```bash
pip install -e ../calc-engine -e .
export DATABASE_URL=postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5432/metrion
export DATABASE_URL_APP=postgresql+psycopg://metrion_app:metrion_app_dev_password@localhost:5432/metrion
python -m alembic upgrade head
pytest tests/
python scripts/trace_meesho_return.py
```
