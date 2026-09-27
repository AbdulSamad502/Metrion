# migrations

DDL that this package owns exclusively — **`leak_finding` and `agent_data_request` ONLY**
(`docs/specs/cfo-agent.md` §5). This migration history never authors data-foundation DDL
(`sales_line`, `line_component`, ...) or calc-engine DDL (`metric_result`, `manual_adjustment`,
`formula_definition`, ...) — CFO reads and writes those through their own packages'
repositories, never through a migration here.

**`cash_view` is NOT created here.** It is a derived read model (`cfo-agent.md` §5) — not a
store, not manual input — and it depends on `cash_reconciliation()`, an engine function that
does not exist yet (deferred, see the deterministic-engine extension specs). There is no table,
no view, and no placeholder for it in this migration history until that engine function ships.

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
