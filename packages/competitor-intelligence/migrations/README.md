# migrations

DDL that this package owns exclusively (`competitor_url`, `competitor_snapshot`,
`competitor_price_event`, `competitor_review_insight`, `competitor_listing_insight`,
`ci_tenant_config`, `ci_capture_run` — see `docs/specs/competitor-intelligence-agent.md` §5).
This directory never authors DDL for tables owned by other packages — it never touches
`metric_result`/`formula_definition` (owned by `calc-engine`) or `sales_line`/`line_component`
(owned by `data-foundation`), and it never writes an `estimate_ref`/`competitor_estimate`
table, since that feature is deferred pending a Brain-1 extension spec (§1a).

**Wired to Alembic.** `env.py` reads its connection string from the `DATABASE_URL`
environment variable only (never committed to `alembic.ini`) and connects as
`metrion_migrate` — the table-owning role, per `auth.md` §7.3; `metrion_app` never runs DDL.
Migrations are hand-written SQL (`op.execute(...)`) rather than declarative ORM models,
because Alembic's autogenerate has no support for `FORCE ROW LEVEL SECURITY` or policy
definitions, and those are exactly the lines that matter here.

Two roles are created once, at the Postgres container level, by
`docker/postgres-init/02-roles.sql` — not by a migration in this directory, since a role
isn't owned by a single package's schema. Run migrations locally with:

```bash
export DATABASE_URL=postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5432/metrion
python -m alembic upgrade head
```

`tests/integration/` connects as `metrion_app` (`DATABASE_URL_APP`) to verify RLS is actually
enforced against the role the application runs as — connecting as the owning role would make
every policy here decorative.
