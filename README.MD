# Metrion

**AI profit-optimization OS for Indian e-commerce sellers on Amazon, Flipkart and Meesho.**

Sellers **upload** their marketplace reports (there are no seller-side marketplace API integrations). Metrion turns those files into true contribution profit, finds the leaks, and recommends what to do next. It is **recommend-only**: it never writes back to a marketplace.

The product loop is **ASK → UNDERSTAND → TRUST → DECIDE → ACT**. TRUST is the load-bearing step: every figure shown must be traceable to its source. A number a seller cannot trace is worse than no number.

> Full project rules live in [`CLAUDE.md`](CLAUDE.md). Feature behaviour lives in [`docs/specs/`](docs/specs). **Read the relevant spec before touching a feature.**

---

## Non-negotiable rules

1. **LLMs explain numbers; they never compute them.** All money math lives in the deterministic engine (`packages/calc-engine`, "Brain 1"): Python/SQL, unit-tested, no LLM in the path. An LLM may narrate or caveat a figure, never originate, re-derive or sum one.
2. **Money is signed `BIGINT` paise.** No floats in any calculation path, frontend included. A missing input is `UNAVAILABLE`, never silently zero.
3. **Every displayed figure cites an `engine_result_ref`** (or an `estimate_ref` for estimates; the two are never interchangeable).
4. **Multi-tenancy is existential.** Every tenant-owned table has `tenant_id` and Postgres Row-Level Security (`FORCE`). No endpoint accepts a client-supplied `tenant_id`. Missing tenant context fails closed.
5. **No LangGraph / LangChain orchestration.** Agents are routed by a fixed, hand-written tool catalog; no LLM-generated SQL or Python.

---

## Architecture at a glance

```
Seller (browser)
   │  Next.js frontend  ──(Clerk JWT)──▶  FastAPI backend
   │                                         │
   │                              CEO agent (star topology, fixed tool catalog)
   │                          ┌──────┬───────┼────────┬─────────┐
   │                         CFO     CI      PI      Slim CMO    (specialist agents)
   │                          │      │       │         │
   │                          └──────┴───┬───┴─────────┘
   │                                     ▼
   │                        calc-engine (Brain 1: all money math)
   │                        data-foundation (report ingestion)
   ▼
PostgreSQL 16 + pgvector (RLS)   ·   Redis   ·   Ollama (local LLMs, dev)
```

| Agent | Package | Role |
|---|---|---|
| **CEO** | `backend/src/backend/ceo`, `agents/ceo_hub.py` | Chat entry point. Classifies the question, plans, delegates to specialists, composes the answer behind a provenance gate. Metered/data-sending actions need an explicit Approve on an exact plan card. |
| **CFO** | `packages/cfo` | P&L, leaks, GST, cash reconciliation, financial health bands, period comparison. |
| **CI** (Competitor Intelligence) | `packages/competitor-intelligence` | Competitor price/availability tracking with evidence trail (incl. screenshot vision extraction). |
| **PI** (Product Intelligence) | `packages/product-intelligence` | Product discovery/research, supplier lookup, review insight, reports. |
| **Slim CMO** | `packages/slim-cmo` | Titles, descriptions, keywords, hashtags, market news, image analysis. Recommend-only. |

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind 4, Vitest |
| Backend | Python ≥ 3.12, **FastAPI** (only), SQLAlchemy 2, Alembic, Pydantic |
| Database | PostgreSQL 16 + **pgvector** (RAG), RLS as the isolation boundary |
| Cache / queues | Redis 7 |
| Identity | Clerk (Organizations; one Organization = one tenant) |
| LLM | Local **Ollama** in dev, behind a `LlmProvider` abstraction (text in / text out); separate vision provider |
| Planned | Razorpay (payments), WhatsApp via BSP (Gupshup/Interakt) |

## Repository layout

| Path | What it holds |
|---|---|
| `backend/` | FastAPI app: auth, API routes, CEO orchestration, repositories, migrations, tests |
| `frontend/` | Next.js app: marketing site, dashboard, CEO Hub, CFO/CI/PI/CMO surfaces, settings |
| `packages/calc-engine` | Deterministic engine (Brain 1), **no LLM imports allowed** |
| `packages/data-foundation` | Parses Amazon/Flipkart/Meesho reports into the canonical sales model |
| `packages/cfo`, `competitor-intelligence`, `product-intelligence`, `slim-cmo` | Specialist agents |
| `packages/market-signals` | Shared market-signal source layer (used by PI and Slim CMO) |
| `docs/specs/` | One spec per feature; the authority for that feature |
| `docs/planning/` | Decisions of record (`phase-1-readiness-review.md`), build status, reports |
| `docs/design/` | Design status. Branding/UI is **not final**: keep it configurable |
| `docker/postgres-init/` | Bootstraps pgvector extension and DB roles |
| `.github/workflows/ci.yml` | CI: lint, migrations round-trip, all test suites |

---

## Current status (as of 2026-10-14)

Branch: `feat/ceo-first-cmo`.

| Area | State |
|---|---|
| Auth (Clerk JWT, onboarding, webhook sync, permission grid) | Built |
| Deterministic engine, data-foundation ingestion | Built |
| CFO agent (P&L, leaks, GST lookup, health bands, strategic narration) | Built (backend + dashboard); some sourcing items deferred, see specs |
| Competitor Intelligence | Built (direct path + CEO chat actions) |
| Product Intelligence | Built; PI research flow driven from CEO chat with approval |
| Slim CMO | Built; read-only showcase dashboard, CEO → CMO delegation |
| CEO orchestration | Foundation, classifier, composer, provenance gate, approval workflow, run recovery, attachments built; some playbooks and hardening (B6) still open. See [`docs/planning/ceo-build-status.md`](docs/planning/ceo-build-status.md) |
| Frontend | Marketing site, dashboard shell, full-screen CEO Hub, agent dashboards. UI redesign ongoing |
| WhatsApp, billing (Razorpay) | Specified, not built |

Partial or stubbed work is labelled as such in the docs. For the honest per-area detail, read `docs/planning/*-build-status.md` and the "Explicit open questions" section of each spec.

---

## Getting started

### Prerequisites

- **Git**
- **Docker Desktop** (Postgres + Redis)
- **Python 3.12+**
- **Node.js 20.9+** and npm
- **Ollama** (optional but needed for any LLM/vision feature): https://ollama.com
- A **Clerk** account/application with Organizations enabled (https://dashboard.clerk.com)

### 1. Clone and configure

```bash
git clone <repo-url> Metrion
cd Metrion
cp .env.example .env                              # root: Docker + DB role URLs
cp backend/.env.example backend/.env              # backend secrets and feature config
cp frontend/.env.local.example frontend/.env.local  # frontend Clerk keys
```

Fill in (never commit `.env` files or paste keys in chat/PRs):

- `frontend/.env.local`: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` (Clerk Dashboard → API Keys).
- `backend/.env`: the same `CLERK_SECRET_KEY`, `CLERK_WEBHOOK_SECRET`, `CLERK_JWT_KEY` (Dashboard → API Keys → Advanced → JWT public key), `FRONTEND_ORIGIN=http://localhost:3000`.

### 2. Start Postgres and Redis

```bash
docker compose up -d
```

This starts `pgvector/pgvector:pg16` and `redis:7`, and on first start runs `docker/postgres-init/` to enable pgvector and create the two DB roles:

- `metrion_migrate`: table owner, runs migrations only.
- `metrion_app`: runtime role, `NOBYPASSRLS`. RLS is enforced against this role.

### 3. Install the Python packages (order matters)

The monorepo has no workspace tool yet, so install in dependency order from the repo root, using a virtualenv:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate

pip install -e "packages/calc-engine[dev]"
pip install -e "packages/data-foundation[dev]"
pip install -e "packages/competitor-intelligence[dev]"
pip install -e "packages/cfo[dev]"
pip install -e "packages/market-signals[dev]"
pip install -e "packages/product-intelligence[dev]"
pip install -e "packages/slim-cmo[dev]"
pip install -e "backend[dev]"
```

> `backend` imports these packages directly but cannot declare them in `pyproject.toml` (a relative `file:` dependency resolves against the current directory, not the file). Skipping the explicit installs causes import errors.

### 4. Run database migrations

Each package owns its own tables and migration history. Set the owner-role URL and run Alembic in each (same order as CI):

```bash
export DATABASE_URL=postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5432/metrion
# PowerShell: $env:DATABASE_URL = "postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5432/metrion"

for d in packages/calc-engine packages/data-foundation packages/competitor-intelligence \
         packages/cfo packages/product-intelligence packages/slim-cmo backend; do
  (cd "$d" && python -m alembic upgrade head)
done
```

### 5. Pull local models (optional, for LLM features)

```bash
ollama serve
ollama pull qwen3:8b            # text: CEO, CFO narration, PI
ollama pull nomic-embed-text    # embeddings (RAG, PI)
ollama pull qwen2.5vl-manual    # or any vision-capable model (CI screenshots, CMO photos)
```

Then in `backend/.env` set the model names you actually pulled (`CEO_LLM_MODEL`, `CFO_NARRATION_MODEL`, `CI_VISION_MODEL`, `CMO_LLM_MODEL`, ...) and `LLM_OPERATOR_CONTROLLED_HOSTS=localhost:11434`. Unset required settings make the matching routes answer `503 ..._NOT_CONFIGURED` rather than guessing. **`backend/.env.example` documents every variable**, including which have no default on purpose.

### 6. Run the app

Backend (loads `backend/.env`, hot reload, port 8000):

```bash
python backend/scripts/run_dev.py
```

Frontend (port 3000):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. API docs at http://localhost:8000/docs (when `API_DOCS_ENABLED` is not disabled).

Sign up, complete the business-name onboarding step, and you land on the dashboard. Clerk webhooks need a public URL locally; see [`backend/README.md`](backend/README.md#webhook-local-dev).

---

## Testing

```bash
# Backend (needs Postgres running and migrated, plus CLERK_* vars from backend/.env)
export DATABASE_URL_APP=postgresql+psycopg://metrion_app:metrion_app_dev_password@localhost:5432/metrion
cd backend && python -m pytest tests

# Any package, e.g. the engine
cd packages/calc-engine && python -m pytest tests

# Lint: no floats in money paths
python packages/calc-engine/scripts/lint_no_float.py

# Frontend
cd frontend && npm test && npm run lint
```

Integration tests connect as `metrion_app` so RLS is genuinely exercised. Run migration **downgrade** tests only against a disposable database (`METRION_ALLOW_DOWNGRADE_TESTS=1`, set in CI).

## Workflow and conventions

- **Spec first.** Read `docs/specs/<feature>.md` before implementing. If none exists, write one. Anything undecided goes in the spec's *Explicit open questions*, never silently guessed.
- **Done means** the spec's acceptance criteria and test scenarios pass, money paths have deterministic unit tests, and tenant isolation is verified.
- **Branches:** `type/short-description` (e.g. `feat/margin-curve`). **Commits:** `type(scope): imperative summary` (types: `feat`, `fix`, `spec`, `docs`, `test`, `refactor`, `chore`).
- Never commit directly to `main`. A pre-commit hook (`.claude/hooks/pre-commit`) blocks LLM imports in `calc-engine`.
- Branding/colours/typography are not final; keep them configurable and never couple business logic to them.
- New LLM narration surfaces need evals (no invented numbers, required disclaimers kept, non-results not narrated as results).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ModuleNotFoundError: competitor_intelligence` / `cfo` / `product_intelligence` | Skipped the explicit package installs (step 3) |
| Backend refuses to start | Missing `CLERK_*` vars, or `FRONTEND_ORIGIN` not set in a production-like env |
| `503 CEO_NOT_CONFIGURED` / `CMO_NOT_CONFIGURED` | Required model/limit settings unset in `backend/.env` (intentional, no defaults) |
| Ollama "model not found" | Env var names a model you have not pulled; run `ollama list` |
| "Clerk token timing rejected" | System clock drift; resync the clock (Windows: `w32tm /resync`) |
| RLS tests pass trivially / see all rows | Connected as `metrion_migrate` instead of `metrion_app` |

## More documentation

- [`backend/README.md`](backend/README.md): backend run notes, upload limits, webhooks
- [`frontend/README.md`](frontend/README.md): frontend notes
- [`docs/planning/phase-1-readiness-review.md`](docs/planning/phase-1-readiness-review.md): decisions of record
- [`docs/planning/ceo-build-status.md`](docs/planning/ceo-build-status.md): CEO agent build state
- [`docs/operations/backup-restore-and-incident-runbook.md`](docs/operations/backup-restore-and-incident-runbook.md): operations
