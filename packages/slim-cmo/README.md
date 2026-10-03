# slim-cmo

Metrion's Slim CMO agent — the fourth specialist agent, after CI, CFO and PI. Spec:
[`docs/specs/slim-cmo-agent.md`](../../docs/specs/slim-cmo-agent.md) (the contract);
[`docs/specs/ceo-agent-orchestration.md`](../../docs/specs/ceo-agent-orchestration.md) §6.9 for how
CEO hands it work.

**Recommend-only.** Nothing in this package writes to any marketplace (spec §0, AC1). Every
output — titles, listing copy, hashtags, catalog answers, trend reports — is a proposal the
seller copies and pastes themselves.

**Hard rule (CLAUDE.md).** No LLM computes or originates a money figure. The only money value
this package holds is the seller's `TARGET_PRICE`, stored as integer paise, echoed back, never
computed on and never written into generated copy. `scripts/lint_no_float.py` enforces no
floats anywhere under `src/`.

## Build status

| Phase | State |
|---|---|
| **P1 — scaffolding** | done: package, migration #1 (all spec §5 tables), `tenant_scope`, shared enums, RLS / constraint / grant / concurrency tests (152) |
| **P2 — deterministic core** (this checkpoint) | done: constraint resolver, validators, forbidden-content scan, claim eligibility & grounding, billing & idempotency rules, trend evidence (independence, syndication, recency, corroboration), budgets, term screening, tactic risk, interpretation & report checks, narration safety. No LLM, no network, no DB, no clock (enforced by `tests/unit/test_p2_purity.py`) |
| P3 generators · P4 catalog Q&A · P5 routes & metering | not started |
| P6 images & `VisionProvider` · P7 trends · P8 CEO wiring · P9 UI · P10 evals · P11 CI-informed | not started |

The deterministic core (P2) exists; **nothing yet calls a model** (P3). No `format_constraint` row, trend-config key or entitlement cap is
seeded by any migration: absent configuration fails closed (spec C13/C16), it is never defaulted.

## Install order (monorepo — no workspace tool yet)

```bash
pip install -e "packages/calc-engine[dev]"
pip install -e "packages/data-foundation[dev]"
pip install -e "packages/competitor-intelligence[dev]"
pip install -e "packages/cfo[dev]"
pip install -e "packages/product-intelligence[dev]"
pip install -e "packages/slim-cmo[dev]"
pip install -e "backend[dev]"
```

## Database

Two roles are created once by `docker/postgres-init/02-roles.sql`: `metrion_migrate` (owns tables,
runs DDL) and `metrion_app` (what the application and the tests connect as — non-owner,
`NOBYPASSRLS`, so RLS is actually enforced).

```bash
export DATABASE_URL=postgresql+psycopg://metrion_migrate:...@localhost:5432/metrion
export DATABASE_URL_APP=postgresql+psycopg://metrion_app:...@localhost:5432/metrion
cd packages/slim-cmo
python -m alembic upgrade head      # version table: alembic_version_slim_cmo
python -m pytest tests -v           # integration tests skip cleanly when the DB env vars are unset
python scripts/lint_no_float.py
```

## Schema guarantees worth knowing (all proven in `tests/integration/`)

* Every tenant table is `FORCE ROW LEVEL SECURITY`; cross-tenant references are impossible via
  composite `(tenant_id, id)` foreign keys, not just policies.
* Provenance (`cmo_generation`, approvals, title options, image analyses, seller facts, trend
  reports) is **append-only** for the application role.
* `format_constraint`, `vision_eval_run`, `cmo_platform_config` are not writable by the
  application role. `format_constraint.row_kind` separates `VERIFIED` rows (the only ones the
  production path reads) from `TEST_FIXTURE` rows.
* The vision trust gate is a database constraint: an image attribute can only be `EVAL_PASSED` if
  it cites a passing evaluation for the same provider, model and schema version.
* A COMPLETE artefact is unique per `(request_key, output_type, marketplace)`; FAILED attempts
  do not block a retry.
