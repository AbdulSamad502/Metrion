# backend

Metrion's FastAPI application — agents, orchestration, auth, and API surface, per
[`CLAUDE.md`](../CLAUDE.md)'s stack decision. Consumes `packages/calc-engine` for all
money calculation; never reimplements it.

**Phase 3 Step 2 (database schema):** `migrations/` owns the DDL for `tenant`, `app_user`,
`membership`, `whatsapp_binding`, `auth_audit` (`docs/specs/auth.md` §5.1),
`investigation`, `investigation_message`, `agent_run`
(`docs/specs/ceo-agent-orchestration.md` §5), and `whatsapp_template`, `whatsapp_message`,
`whatsapp_pending_action`, `whatsapp_alert_subscription`
(`docs/specs/whatsapp-integration.md` §5) — see `migrations/README.md`. Tenant isolation
(RLS) for these tables is verified in `tests/integration/test_rls_isolation.py`.

**Phase 3 Step 3 (auth):** `src/backend/` implements the rest of `auth.md` — Clerk JWT
verification (`auth/clerk_verify.py` -> `auth/context.py`'s `require_auth()`, the six-step
chain from §7.1), the business-name onboarding endpoint (§6.2), Clerk webhook sync (D6,
`webhooks/clerk.py`), and the permission grid (§5.2, `auth/permissions.py`).

### Running locally

```bash
cp .env.example .env   # fill in CLERK_SECRET_KEY (copy from frontend/.env.local),
                        # CLERK_WEBHOOK_SECRET, FRONTEND_ORIGIN
pip install -e ../packages/competitor-intelligence   # required — see note below
pip install -e ../packages/cfo                       # required — see note below
pip install -e .[dev]
uvicorn backend.main:app --reload --app-dir src --port 8000
```

**Why the extra install lines:** `backend` imports `competitor_intelligence` and `cfo`
directly (`api/v1/ci.py`, `api/v1/ceo_hub.py`, `agents/ceo_hub.py`, and CFO's analogous
routes/dispatch) but does not declare either in `pyproject.toml` — a relative `file:`
dependency specifier was tried and reverted because pip resolves it against the *current
working directory at install time*, not against this file's own directory, making it silently
break depending on where `pip install` is run from (see the comment in `pyproject.toml`).
Until this monorepo adopts a workspace-aware tool (uv/hatch workspaces), install
`competitor-intelligence` and then `cfo` explicitly first, exactly as `.github/workflows/ci.yml`
already does — install order is
`calc-engine → data-foundation → competitor-intelligence → cfo → backend[dev]`.

### Vision extraction (Ollama)

Screenshot evidence upload (`evidence/vision_extractor.py`) reads a competitor listing's
price/availability/title off an uploaded image via a local Ollama model. This needs Ollama
installed and running, with a vision-capable model pulled:

```bash
ollama serve                      # if not already running as a background service
ollama pull qwen2.5vl-manual      # or any other vision-capable model you prefer
```

Then set `OLLAMA_HOST`/`CI_VISION_MODEL`/`CI_REVIEW_VISION_MODEL` in `.env` to match
whatever you actually pulled — see `.env.example`'s comments. **The code-level defaults
assume a model name (`llava`) that may not exist on your machine**; if you skip this and the
env vars aren't set, screenshot uploads fail with an Ollama "model not found" error that
doesn't obviously point back to a missing env var. No model choice is locked by the CI spec
(§1a item 4 / Q7 remains open) — pick whatever vision model you have.

### Webhook (local dev)

Clerk needs a public URL to deliver webhooks to. Use the Clerk CLI's own relay:

```bash
clerk webhooks token                     # generate a stable relay token once
clerk webhooks listen --token "<that token>" --forward-to http://localhost:8000/webhooks/clerk
```

The command prints the relay URL to register — put it in Clerk Dashboard -> Webhooks ->
your endpoint, subscribed to `user.*`, `organization.*`, `organizationMembership.*`, and
copy its **Signing Secret** into `.env`'s `CLERK_WEBHOOK_SECRET`.

### Tests

```bash
export DATABASE_URL=postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5432/metrion
export DATABASE_URL_APP=postgresql+psycopg://metrion_app:metrion_app_dev_password@localhost:5432/metrion
pytest tests
```
