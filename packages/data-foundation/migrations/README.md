# migrations

DDL for the tables data-foundation.md defines: `report_file`, `ingestion_run`, `sales_line`,
`line_component`, `report_period`, `validation_finding` (the last is a Category C amendment —
see `docs/specs/data-foundation.md` §4.4).

**Scope.** This migration covers sales-side ingestion only. `settlement_line`,
`reconciliation_run`/`reconciliation_match`/`reconciliation_exception`, and
`sales_document`/`settlement_document` are named in data-foundation.md §1.2's entity tree but
have no schema defined anywhere in that spec — they are not created here, and
`line_component.settlement_line_id` is left as a bare UUID column (no FK) until
`settlement_line` exists.

**Wired to Alembic**, same pattern as `packages/calc-engine/migrations/`: `env.py` reads
`DATABASE_URL` from the environment, connects as `metrion_migrate`. Because this package
shares one Postgres database with `calc-engine` but is a structurally independent migration
history, it tracks its own revisions in `alembic_version_data_foundation` (not the default
`alembic_version`, which calc-engine already owns) — see `env.py`'s docstring.

Run locally:

```bash
export DATABASE_URL=postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5432/metrion
python -m alembic upgrade head
```

`tests/integration/` connects as `metrion_app` (`DATABASE_URL_APP`) to verify RLS is enforced
against the actual runtime role, same convention as calc-engine's integration tests.
