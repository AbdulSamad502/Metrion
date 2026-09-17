# data-foundation

Metrion's file-understanding / ingestion layer — see `docs/specs/data-foundation.md`.

Turns seller-uploaded Amazon/Flipkart/Meesho marketplace report files into the canonical
`sales_line`/`line_component` model `packages/calc-engine` (Brain 1) consumes. This is **not**
"Brain 2" — that name is already reserved in this repo's vocabulary for the future statistical
anomaly-detection layer (see `docs/planning/phase-1-readiness-review.md`).

**Scope:** sales-side ingestion only, this pass. Settlement-side adapters
(`amazon.settlement.v2`, `meesho.payments.v1`) and the reconciliation tables
(`settlement_line`, `reconciliation_run`/`match`/`exception`) are deferred — no schema for
them exists anywhere in `data-foundation.md`.

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
