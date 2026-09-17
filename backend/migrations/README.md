# migrations

DDL that this package owns exclusively: `tenant`, `app_user`, `membership`,
`whatsapp_binding`, `auth_audit` (`docs/specs/auth.md` §5.1), `investigation`,
`investigation_message`, `agent_run` (`docs/specs/ceo-agent-orchestration.md` §5), and
`whatsapp_template`, `whatsapp_message`, `whatsapp_pending_action`,
`whatsapp_alert_subscription` (`docs/specs/whatsapp-integration.md` §5). This directory never
authors DDL for tables owned by `data-foundation.md` or `deterministic-engine.md` — those
live in `packages/data-foundation/migrations` and `packages/calc-engine/migrations`
respectively.

**Wired to Alembic**, same convention as the other two packages. `env.py` reads its
connection string from the `DATABASE_URL` environment variable only (never committed to
`alembic.ini`) and connects as `metrion_migrate` — the table-owning role, per `auth.md`
§7.3; `metrion_app` never runs DDL. Migrations are hand-written SQL (`op.execute(...)`)
rather than declarative ORM models, for the same reason as the sibling packages: Alembic's
autogenerate has no support for `FORCE ROW LEVEL SECURITY` or policy definitions.

`tenant`, `app_user`, and `whatsapp_template` are the three tables in this history that carry
no `tenant_id` column and get no RLS policy — they are identity/shared-registry roots, not
tenant-owned data (see the comments in `20260917_0001_auth_tables.py` and
`20260917_0003_whatsapp_tables.py`). Every other table here follows the standard
`tenant_isolation` policy.

Run migrations locally with:

```bash
export DATABASE_URL=postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5432/metrion
python -m alembic upgrade head
```

`tests/integration/` connects as `metrion_app` (`DATABASE_URL_APP`) to verify RLS is actually
enforced against the role the application runs as — connecting as the owning role would make
every policy here decorative.
