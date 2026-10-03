# migrations

DDL owned exclusively by this package: `seller_image_asset`, `product_image_analysis`,
`vision_eval_run`, `format_constraint`, `cmo_platform_config`, `cmo_generation`,
`cmo_title_option`, `cmo_title_approval`, `seller_fact`, `cmo_niche_term`, `cmo_trend_report`
(see `docs/specs/slim-cmo-agent.md` §5). It never authors DDL for tables owned by other
packages and holds no cross-package foreign keys (`agent_run` is backend-owned;
`market_signal_run_ref` targets a shared service that does not exist yet).

`env.py` reads its connection string from `DATABASE_URL` only (never committed) and connects as
`metrion_migrate`. The version table is `alembic_version_slim_cmo`, so this history stays
independent of every sibling package's. Migrations are hand-written SQL: autogenerate cannot
express `FORCE ROW LEVEL SECURITY`, policies, grants or the CHECK/jsonpath constraints that
matter here.

```bash
export DATABASE_URL=postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5432/metrion
python -m alembic upgrade head
python -m alembic downgrade base     # CI also round-trips: upgrade, downgrade, re-upgrade
```

**Seeding.** No migration seeds a `format_constraint` row, a `cmo_platform_config` key or any
entitlement cap. Verified marketplace rules and trend configuration are data supplied by people
with sources (spec C13/C16, blockers V8/V11); until they exist the product reports
`CONFIG_MISSING` / "constraint unavailable" instead of guessing.

`tests/integration/` connects as `metrion_app` so RLS and the grants are verified against the
role the application actually runs as; connecting as the owner would make every policy
decorative.
