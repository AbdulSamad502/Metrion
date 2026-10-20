# Competitor Intelligence V3 — local test setup

Everything below runs against an **isolated scratch Postgres** (container `ci-v3-pg`, port **5544**, database `metrion_ci`). It never touches the shared dev database on 5432.
Port 5544 is not arbitrary: `packages/competitor-intelligence/tests/integration/owner_db.py` refuses to run owner-role setup against any other port.

## One-time setup (already done in this worktree)

```powershell
cd C:\dev\Metrion   # your repo root
& "C:\Users\zaved\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv-ci   # Python >= 3.12 is required
foreach ($k in "calc-engine","data-foundation","competitor-intelligence","cfo","market-signals","product-intelligence","slim-cmo") {
  .venv-ci\Scripts\python.exe -m pip install -e "packages/$k[dev]"
}
.venv-ci\Scripts\python.exe -m pip install -e "backend[dev]"
cd frontend; npm ci
```

Why the wrong code was imported before: the shared interpreter had `competitor_intelligence` installed editable from `C:\dev\Metrion`. `.venv-ci` has editable installs that point at this worktree only.

## Start the scratch database and migrate

```powershell
cd C:\dev\Metrion   # your repo root
docker run -d --name ci-v3-pg -e POSTGRES_USER=metrion -e POSTGRES_PASSWORD=ci_scratch_pw -e POSTGRES_DB=metrion_ci -p 5544:5432 `
  -v "${PWD}\docker\postgres-init:/docker-entrypoint-initdb.d:ro" pgvector/pgvector:pg16
# (if it already exists: docker start ci-v3-pg)

$env:DATABASE_URL     = "postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5544/metrion_ci"
$env:DATABASE_URL_APP = "postgresql+psycopg://metrion_app:metrion_app_dev_password@localhost:5544/metrion_ci"
$py = (Resolve-Path .venv-ci\Scripts\python.exe).Path
# ORDER MATTERS: backend migration 0020 needs slim-cmo's cmo_generation table.
foreach ($d in "packages\calc-engine","packages\data-foundation","packages\competitor-intelligence","packages\cfo","packages\product-intelligence","packages\slim-cmo","backend") {
  Push-Location $d; & $py -m alembic upgrade head; Pop-Location
}
```

The role passwords above come from `docker/postgres-init/02-roles.sql` (dev-only values already in the repo).

## Run the automated checks

```powershell
# CI package: unit + integration (507 tests, ~3-12 min depending on machine load)
cd packages\competitor-intelligence
..\..\.venv-ci\Scripts\python.exe -m pytest -q
..\..\.venv-ci\Scripts\python.exe -m mypy          # strict, expected: no issues

# Backend (CI placeholders for Clerk; nothing calls Clerk)
cd ..\..\backend
$env:CLERK_SECRET_KEY="sk_test_ci_placeholder"; $env:CLERK_WEBHOOK_SECRET="whsec_ci_placeholder"
$env:CLERK_JWT_KEY="-----BEGIN PUBLIC KEY-----\nCIPLACEHOLDER\n-----END PUBLIC KEY-----"; $env:LLM_OPERATOR_CONTROLLED_HOSTS="localhost:11434"
..\.venv-ci\Scripts\python.exe -m pytest tests -q

# Frontend
cd ..\frontend; npm run lint; npm test; npm run build
```

## Run the app for manual testing

Backend and frontend need real Clerk keys in `backend/.env` and `frontend/.env.local` (see their `.env*.example`); without them sign-in cannot work. Do not reuse production keys.

```powershell
# terminal 1 (env vars from above, plus Clerk keys in backend/.env)
cd backend; ..\.venv-ci\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
# terminal 2
cd frontend; npm run dev
```

## Known caveats

- Backend integration tests are very slow against a scratch database (roughly a minute per test in this setup because of per-test tenant cleanup), so run the files you changed rather than the whole suite.
- lembic downgrade base for the backend refuses to run while the database holds approval, billing or PLANNED-turn rows (a deliberate guard). Use an empty scratch database for the round trip.
- Stopping the scratch DB: `docker stop ci-v3-pg`; remove with `docker rm -f ci-v3-pg` (it holds nothing you need).
- See `docs/git-workflow.md` for branches and updates.

## Manual testing checklist (CI V3)

1. Add a competitor URL; confirm the watchlist limit message appears at the configured limit.
2. Run discovery for a seller product; confirm at most 15 matches are shown and the seller can pick only their free slots (max 5 tracked).
3. Upload a competitor screenshot; confirm the extracted price is held *pending* until confirmed, and declining keeps it out of every read.
4. Upload a duplicate and an unreadable image; confirm nothing is stored and the reason is stated.
5. Confirm a second screenshot with a different price raises exactly one alert and a finding that cites its evidence; repeating the same pair raises no second alert.
6. Set quiet hours; trigger an alert inside them and confirm it is held, then released afterwards with its finding. An alert whose evidence went stale must be withheld, not delivered.
7. Check every figure shows source, period and status; missing inputs read "unavailable", never zero.
8. Check tenant isolation: a second tenant sees none of the first tenant's competitors, evidence or alerts.
