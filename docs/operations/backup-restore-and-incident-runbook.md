# Backup, restore, rollback and incident runbook (verified on scratch only, 2026-10-12)

What was actually executed: a custom-format dump of the scratch database (`metrion-verify-pg`, port 5544) and a restore into a throwaway database inside the same container, then dropped. **No production backup system, schedule, off-host copy or monitoring exists in this repository; none is claimed.** Item "What is missing" lists what a real-seller review needs.

## Backup (PostgreSQL)
```bash
docker exec <container> pg_dump -U <superuser> -d metrion -Fc -f /tmp/metrion.dump
```
## Restore (verified)
Restore **as the superuser**, into an empty database, without `--role` or `--no-owner` overrides:
```bash
docker exec <container> psql -U <superuser> -d postgres -c "create database metrion_restore_test"
docker exec <container> pg_restore -U <superuser> -d metrion_restore_test /tmp/metrion.dump
```
Result on scratch: 0 errors. Row counts matched (2 tenants, 43 agent runs), `alembic_version_backend` = `20261011_0017`, 77 FORCE-RLS tables and 78 policies in both. Connected as `metrion_app` to the restored copy: 0 rows without tenant context, 43 with it (RLS intact).
Failure mode seen: restoring with `--role=<non-superuser>` produced 734 errors (tables not created, GRANTs failed). Do not do that.
After any restore: check `alembic current` for each component, count FORCE-RLS tables, and confirm `metrion_app` is not superuser / BYPASSRLS (`test_privilege_boundary`).

## Migration rollback
Each component has its own `alembic_version_*` table. Downgrade in the reverse of the CI order (backend, then slim-cmo, product-intelligence, cfo, competitor-intelligence, data-foundation, calc-engine); the round trip (upgrade, downgrade to base, upgrade) passes on scratch. Several downgrades refuse when rows exist (data protection); take a dump first.

## Incident: a run stuck RUNNING
1. Look first: `GET /api/v1/ops/runs` (header `X-Ops-Token`, see "Operations endpoints"). `running.ownerless` > 0 means rows with nobody working on them; `withLiveOwner` rows are being worked on, however long they take.
2. Ownerless rows settle by themselves: every backend settles them at start-up and then every `RECOVERY_SWEEP_INTERVAL_SECONDS` (default 300 s; 0 turns the periodic pass off) as `FAILED` / `INTERRUPTED`, fails orphaned PI research runs, and tells the seller a turn was interrupted. Nothing is re-run and nothing is charged. Restarting any backend triggers a pass at once.
3. A run with a live owner that is merely slow is never touched. A hung one needs the opt-in `CEO_LEG_ABANDON_SECONDS`, which has no recommended value yet.
4. Covered tables: `agent_run` (all agents, including CMO from its first model call), `pi_research_run`, `reconciliation_run`, `ci_capture_run`. Do not edit rows by hand.

## Incident: database unavailable
Behaviour now (verified on scratch with a forwarder that stalls, refuses and resets connections): a stalled database fails the request within `DB_CONNECT_TIMEOUT_SECONDS` (default 10) instead of hanging it; a refused one fails at once; pooled connections killed by a restart are detected by `pool_pre_ping` so the first request after the restart succeeds; a saturated pool fails a caller after `DB_POOL_TIMEOUT_SECONDS` (default 30). The same process serves again when the database returns. Earlier (before these settings) a stopped database hung every request, `/ping` included.
`/api/v1/ops/ready` answers 503 within 5 s when the database is down and uses its own single connection, so it never waits behind the application's pool; `/api/v1/ops/live` never touches the database.

## Operations endpoints
`OPS_TOKEN` (24+ characters) turns on `/api/v1/ops/live`, `/ready` and `/runs`; unset, they answer 401 like any unauthenticated call. Send the token as `X-Ops-Token` (constant-time comparison). Responses are counts and statuses only (no tenant id, run id, text or configuration). Point an orchestrator's liveness probe at `/live` and its readiness probe at `/ready` with that header. **No monitoring service or alert receiver exists in this repository or was set up: nothing watches these endpoints until you connect one.**

## Diagnosing a seller report
Every response carries `X-Request-ID` (the caller's own plain id is echoed) and every error body carries `error.requestId` with the same value, plus `error.kind` (validation, authentication, permission, entitlement, not_found, conflict, too_large, rate_limited, configuration, unavailable, server). Log lines written while handling the request end with `[req=<id>]`. Messages are redacted for bearer tokens, JWTs, `key=`/`token=`/`secret=`/`password=` pairs and known key shapes.

## Configuration that changes behaviour (all optional; defaults shown)
| Setting | Default | Effect |
|---|---|---|
| `METRION_ENV` | unset (development) | `production`/`prod`/`staging` (or a live Clerk key) makes `FRONTEND_ORIGIN` mandatory and https-only (loopback excepted) |
| `FRONTEND_ORIGIN` | `http://localhost:3000` in development | the one CORS origin; scheme+host(+port) only; an invalid value always stops start-up |
| `API_MAX_BODY_BYTES` | 1048576 | largest non-upload request body; 413 before parsing; `0` = no application limit |
| `DB_CONNECT_TIMEOUT_SECONDS` / `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT_SECONDS` | 10 / 5 / 10 / 30 | per engine (seven engines per process); the pool numbers are SQLAlchemy's own defaults and are NOT tuned for production |
| `RECOVERY_SWEEP_INTERVAL_SECONDS` | 300 | periodic recovery pass; `0` = start-up only |
| `OPS_TOKEN` | unset | enables the operations endpoints |
| `API_DOCS_ENABLED` | unset | serves `/docs`, `/redoc`, `/openapi.json` |
| `CEO_MAX_CANDIDATE_PRICES` | unset (no default by design) | unset: the price-impact conversation refuses honestly with CONFIG_MISSING; set it deliberately (the example file suggests 5) |
| `LLM_OPERATOR_CONTROLLED_HOSTS` | unset | every model endpoint must be listed (exact `host:port`, e.g. `localhost:11434`) or model calls are refused |
| `CI_VISION_MODEL` / `CI_REVIEW_VISION_MODEL` | `llava` | if the model is not installed the screenshot flow says so ("the model 'x' is not installed on the local model server") and falls back to manual entry; it never pretends to extract |

## Loading configuration and reference data
The application role cannot write fees, GST rates, formulas, plans, entitlement caps, thresholds or tolerances (migration 20261012_0018). An operator loads them with the owner role: `python backend/scripts/config_admin.py template <table>` shows the columns, `load <table> rows.json` is a dry run that prints the target database first, `--apply` inserts (all rows or none, append-only). The values are yours; the specs deliberately seed none. `python backend/scripts/tenant_data_inventory.py <tenant-id>` is the read-only inventory of what is stored for a tenant.

## What is missing (not built, not claimed)
Scheduled and off-host backups, restore drills against production-sized data, point-in-time recovery, any monitoring service, alert receiver or paging, a decided retention/erasure policy, a measured pool size, and a real-CI run of the workflow.
