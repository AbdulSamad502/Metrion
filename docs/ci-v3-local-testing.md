# Local test setup and manual testing (CI V3, CFO, Expense Tracker, P&L)

Everything automated below runs against an **isolated scratch Postgres** (container `ci-v3-pg`, host port **5544**). It never touches the shared development database on 5432.
Port 5544 is not arbitrary: the owner-role test setup (`owner_db.py` in the CI package and calc-engine) refuses to run against any other port.

All commands are PowerShell, run from the repository root (`C:\dev\Metrion`) unless a `cd` says otherwise.

## One-time setup

```powershell
& "C:\Users\zaved\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv-ci    # Python >= 3.12 is required
foreach ($k in "calc-engine","data-foundation","competitor-intelligence","cfo","market-signals","product-intelligence","slim-cmo") {
  .venv-ci\Scripts\python.exe -m pip install -e "packages/$k[dev]"
}
.venv-ci\Scripts\python.exe -m pip install -e "backend[dev]"
.venv-ci\Scripts\python.exe -m pip install "pydantic==2.12.5"      # the request contract is generated per Pydantic version; see docs/git-workflow.md
cd frontend; npm ci; cd ..
```

`.venv-ci` has editable installs that point at *this* checkout. (An older shared interpreter had `competitor_intelligence` installed editable from another directory, which is why imports used to come from the wrong tree.)

## Scratch database

```powershell
docker run -d --name ci-v3-pg -e POSTGRES_USER=metrion -e POSTGRES_PASSWORD=ci_scratch_pw -e POSTGRES_DB=metrion_ci -p 5544:5432 `
  -v "${PWD}\docker\postgres-init:/docker-entrypoint-initdb.d:ro" pgvector/pgvector:pg16
# if it already exists:  docker start ci-v3-pg
```

This container is for tests only, so you may make it fast (not durable): `docker exec ci-v3-pg psql -U metrion -d postgres -c "ALTER SYSTEM SET fsync=off" -c "ALTER SYSTEM SET synchronous_commit=off" -c "select pg_reload_conf()"`.
Never apply that to a database that holds data you care about.

### One database per branch under test

A branch's migrations decide the schema. The P&L branch adds a calc-engine revision (`*_expense_ledger`) that `main` does not have, so give each branch its own database:

```powershell
$db = "metrion_manual"       # any name
docker exec ci-v3-pg psql -U metrion -d postgres -c "CREATE DATABASE $db"
foreach ($f in "01-enable-pgvector.sql","02-roles.sql") { Get-Content docker\postgres-init\$f -Raw | docker exec -i ci-v3-pg psql -U metrion -d $db -q }

$env:DATABASE_URL     = "postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5544/$db"
$env:DATABASE_URL_APP = "postgresql+psycopg://metrion_app:metrion_app_dev_password@localhost:5544/$db"
$py = (Resolve-Path .venv-ci\Scripts\python.exe).Path
# ORDER MATTERS: backend migration 0020 needs slim-cmo's cmo_generation table.
foreach ($d in "packages\calc-engine","packages\data-foundation","packages\competitor-intelligence","packages\cfo","packages\product-intelligence","packages\slim-cmo","backend") {
  Push-Location $d; & $py -m alembic upgrade head; Pop-Location
}
```

The role passwords come from `docker/postgres-init/02-roles.sql` (dev-only values already in the repository). Use the same loop with `downgrade base` then `upgrade head` for the round-trip check, on an **empty** database: the backend downgrade deliberately refuses while approval, billing or PLANNED-turn rows exist.

## Automated checks

Set the placeholders the backend tests expect (no test calls Clerk):

```powershell
$env:CLERK_SECRET_KEY="sk_test_ci_placeholder"; $env:CLERK_WEBHOOK_SECRET="whsec_ci_placeholder"
$env:CLERK_JWT_KEY="-----BEGIN PUBLIC KEY-----\nCIPLACEHOLDER\n-----END PUBLIC KEY-----"; $env:LLM_OPERATOR_CONTROLLED_HOSTS="localhost:11434"
```

```powershell
# Package suites (each from its own folder; DATABASE_URL* as above)
cd packages\competitor-intelligence; ..\..\.venv-ci\Scripts\python.exe -m pytest -q; ..\..\.venv-ci\Scripts\python.exe -m mypy   # 507 tests; strict mypy clean
cd ..\calc-engine; ..\..\.venv-ci\Scripts\python.exe -m pytest -q                                                              # also data-foundation, cfo, product-intelligence, market-signals, slim-cmo
# Backend
cd ..\..\backend; ..\.venv-ci\Scripts\python.exe -m pytest tests\unit -q                                                       # ~40 s
..\.venv-ci\Scripts\python.exe -m pytest tests\integration\test_ci_api.py -q                                                   # run the files you changed
# Frontend
cd ..\frontend; npx tsc --noEmit; npm run lint; npm test; npm run build
```

**The whole backend integration suite** (about 2,400 tests) takes about an hour sequentially, and `test_ceo_safety_gate.py` alone takes about 13. Run it file by file so one slow or hung file cannot block the rest; the sharding that was tried (several databases in parallel) did not help because the database is CPU-bound.
Tests that go through the CEO planner (`test_ceo_cmo_delegation.py`, `test_ceo_cmo_image_handoff.py`) are **intermittent**: a different test fails on some runs and passes on the next. CI has no Ollama; a local one on `localhost:11434` can change what these paths do, so for CI-like runs stop it or point `OLLAMA_HOST`/`CEO_OLLAMA_HOST`/`CMO_OLLAMA_HOST` at an unused port (one test still flaked once with Ollama unreachable, so this is not the whole story).

## Run the app for manual testing

Real Clerk keys are required **only** for sign-in: `backend/.env` needs `CLERK_SECRET_KEY`, `CLERK_JWT_KEY`, `CLERK_WEBHOOK_SECRET`, and `frontend/.env.local` needs `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` (see the `.env*.example` files). Never use production keys, and never commit these files.

`backend/.env` on this machine points `DATABASE_URL*` at the **persistent manual-testing database**: container `metrion-manual-pg`, host port **5544**, database `metrion_manual` (roles `metrion_migrate` for migrations and `metrion_app` for the app; the passwords are in `backend/.env`, never in code).

### Required startup workflow

#### 1. Database — persistent manual-testing database on port 5544

```powershell
Set-Location C:\dev\Metrion

docker stop metrion-verify-pg 2>$null
docker start metrion-manual-pg
```

- `metrion-manual-pg` is the persistent database used for manual testing.
- `metrion-verify-pg` must be stopped first if it is running because both containers use host port `5544`.
- Verify that `metrion-manual-pg` starts successfully and becomes ready to accept connections (`docker exec metrion-manual-pg pg_isready -U metrion -d metrion_manual`).
- Do not delete, recreate, reset, or replace either container or its data.

#### 2. Supporting services

- **Redis**: Ensure the local Redis container is running on host port `6379`:
  ```powershell
  docker start metrion-redis-1 2>$null
  ```
- **Ollama**: Ensure Ollama is running on `http://localhost:11434` with required models (`qwen3.5:4b` or `qwen3:8b`, `nomic-embed-text`, etc.):
  ```powershell
  ollama list
  ```

#### 3. Backend — port 8000

Run in the same PowerShell terminal after starting the database:

```powershell
Remove-Item Env:DATABASE_URL,Env:DATABASE_URL_APP -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe backend\scripts\run_dev.py          # PORT=8010 to use another port; then set NEXT_PUBLIC_API_BASE_URL in frontend/.env.local
```

- The backend reads its configuration from `backend/.env`.
- Ensure inherited `DATABASE_URL` and `DATABASE_URL_APP` environment variables cannot override the intended local database configuration.
- Verify that the backend connects to the persistent manual-testing database on port `5544`, not a verification database or another database.
- Confirm the backend starts successfully on port `8000`.
- Do not automatically run migrations or seed data during ordinary startup unless the current repository explicitly requires this and the operation has been verified as safe.

**Why the two variables are cleared.** `run_dev.py` loads `backend/.env` but, by design, never overrides a variable already set in your shell (that is how a run is pointed at the scratch database). So a leftover `DATABASE_URL` or `DATABASE_URL_APP` from an earlier session silently wins over the file. Clearing them makes the file the only source. If one is still set, `run_dev.py` now says so at startup, e.g. `WARNING: DATABASE_URL is set in this shell (...) and overrides backend/.env (...)`, and always prints where each URL points (`role@host:port/database`, never the password):

```
[run_dev] DATABASE_URL -> metrion_migrate@localhost:5544/metrion_manual
[run_dev] DATABASE_URL_APP -> metrion_app@localhost:5544/metrion_manual
```

**Expected container.** `docker ps` shows `metrion-manual-pg` with `0.0.0.0:5544->5432/tcp`. Its data lives in the Docker volume it was created with (the former `ci-v3-pg` volume), so stopping or restarting the container loses nothing; never `docker rm` it or remove that volume.

**If it does not work**
- `docker start metrion-manual-pg` fails with "port is already allocated": another container holds 5544 (usually the disposable `metrion-verify-pg` from `scratch_db.sh`). Stop it first: `docker stop metrion-verify-pg`.
- The container is not running: `docker ps -a --filter name=metrion-manual-pg`, then `docker logs --tail 30 metrion-manual-pg`. Check it accepts connections: `docker exec metrion-manual-pg pg_isready -U metrion -d metrion_manual`.
- The backend starts but says `connection refused` / `password authentication failed` / `database "metrion_manual" does not exist`: read the two `[run_dev]` lines. A different host, port or database means a stale shell variable (clear it as above) or an edited `backend/.env`. A missing database means the wrong container is on 5544 (`docker ps`).
- To confirm the app is on the manual database: `docker exec metrion-manual-pg psql -U metrion -d metrion_manual -c "select usename, datname, count(*) from pg_stat_activity where datname='metrion_manual' group by 1,2"` shows `metrion_app` connected.
- The schema is behind the code (an error about a missing table or column): apply the pending migrations deliberately and after a backup, as in "One database per branch under test". The startup commands never run migrations.

#### 4. Frontend — port 3000

Run in a second PowerShell terminal:

```powershell
Set-Location C:\dev\Metrion\frontend
npm run dev
```

- Ensure the frontend starts without missing dependencies, configuration errors, or port conflicts.
- Confirm it is available on port `3000`.
- Confirm that required dev dependencies, including UI or chart libraries used by current routes (e.g. `recharts`), are installed locally.

(Do not start the backend with a bare `uvicorn backend.main:app`: that does not load `backend/.env`, so Clerk would reject every request.)

A scratch database has no tenant. A tenant is created by Clerk's `organization.created` webhook, which needs a public URL; for local use run the Clerk CLI relay described in `backend/README.md` ("Webhook (local dev)"), then sign up and create the business in the app. Without the relay you can sign in but have no tenant, so tenant-scoped pages show nothing useful.
Screenshot evidence upload and the CEO/CMO/PI answers need Ollama running with the models named in `backend/.env` (`CI_VISION_MODEL`, `CEO_LLM_MODEL`, ...); everything else works without it.

To point at the shared dev database instead, run the migrations for your branch against it **yourself and deliberately**; nothing in this guide does that.

## Known caveats

- `slim-cmo` has one failing eval, `test_eval_08_competitor_gap_themes_are_never_asserted_as_claims_about_the_sellers_product`. It asserts that CI-informed generation (`ci_inputs`) does not exist, but that feature has since been built. The eval needs rewriting to test the real guard; this is a product decision, so it is left failing.
- Stopping the scratch DB: `docker stop ci-v3-pg`; remove with `docker rm -f ci-v3-pg` (it holds nothing you need).
- See `docs/git-workflow.md` for branches and updates.

## Manual testing checklist

**Sign-in and navigation**
1. Sign up / sign in with a development Clerk instance and confirm the dashboard loads for the signed-in user (a signed-out visitor should not see tenant data).
2. Sidebar shows Overview, CEO Hub, Action Center, Products, Competitors, Profit & Finance, Listings & Marketing, Agents, Settings (plus Profit Calculator on the P&L branch); Profit & Finance stays highlighted on `/dashboard/cfo/expenses`.

**CFO (Profit & Finance)**
3. Upload a settlement/order report; confirm figures show their source, period and status (verified / provisional / estimated / unavailable). A missing input reads "unavailable", never zero.
4. The "Open the Expense Tracker →" link goes to `/dashboard/cfo/expenses`. *(P&L branch only.)*

**Expense Tracker** *(P&L branch only)*
5. Add an expense; it appears in the list with a status. Correct, refund, void and mark paid on separate expenses: each keeps its history and nothing is deleted.
6. The summary shows period totals from the ledger, and unallocated spend is called out rather than hidden; with no expenses it must not invent a figure.

**Profit Calculator (P&L)** *(P&L branch only)*
7. Enter price, cost and fees; the result is presented as a what-if, never as a verified result. A missing required input reads as not yet calculable, never as zero.
8. Advertising spend left blank reads "Not entered in this calculation", not 0.

**Competitor Intelligence (CI V3)**
9. Add a competitor URL; confirm the watchlist-limit message appears at the configured limit.
10. Run discovery for a seller product; at most 15 matches are shown and the seller can pick only their free slots (max 5 tracked).
11. Upload a competitor screenshot; the extracted price is held *pending* until confirmed, and declining keeps it out of every read. A duplicate or unreadable image stores nothing and says why.
12. A second confirmed screenshot with a different price raises exactly one alert and a finding that cites its evidence; repeating the same pair raises no second alert.
13. Quiet hours: an alert inside them is held, then released later with its finding. An alert whose evidence went stale is withheld, not delivered.
14. Isolation: a second tenant sees none of the first tenant's competitors, evidence or alerts.

**General**
15. Colour is never the only status signal (verified green, estimate amber, risk red come with a text label); reduced-motion setting removes animation.
