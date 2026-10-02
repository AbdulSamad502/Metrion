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
pip install -e ../packages/product-intelligence      # required — see note below
pip install -e .[dev]
uvicorn backend.main:app --reload --app-dir src --port 8000
```

**Why the extra install lines:** `backend` imports `competitor_intelligence`, `cfo` and (as of
PI's Phase 2 wiring) `product_intelligence` directly (`api/v1/ci.py`, `api/v1/cfo.py`,
`api/v1/pi.py`, `services/pi_actions.py`, `backend/entitlement.py`'s `resolve_niche_run_
entitlement`) but does not declare any of them in `pyproject.toml` — a relative `file:`
dependency specifier was tried and reverted because pip resolves it against the *current
working directory at install time*, not against this file's own directory, making it silently
break depending on where `pip install` is run from (see the comment in `pyproject.toml`).
Until this monorepo adopts a workspace-aware tool (uv/hatch workspaces), install
`competitor-intelligence`, `cfo` and `product-intelligence` explicitly first, exactly as
`.github/workflows/ci.yml` already does — install order is
`calc-engine → data-foundation → competitor-intelligence → cfo → product-intelligence → backend[dev]`.

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

### Request-body limits (uploads)

Two routes accept file uploads: `POST /api/v1/cfo/ingest` (CSV) and `POST /api/v1/ci/evidence`
(screenshot). Limits, from the inside out:

| Layer | What it does | Status |
|---|---|---|
| Route (`uploads.read_upload_capped`) | Rejects a file over `CFO_MAX_UPLOAD_BYTES` (default 20 MB) / `CI_MAX_EVIDENCE_BYTES` (default 10 MB) with **413** before it is loaded, ingested or written | **Implemented** |
| ASGI middleware (`request_limits.RequestBodyLimitMiddleware`) | Rejects an oversized **request body** with **413** before auth, multipart parsing or temp-file spooling — by `Content-Length` when present, and by counting streamed bytes when it is absent (chunked). Allows 64 KiB of multipart envelope above the file limit | **Implemented** |
| Reverse proxy / ingress | Stops the body at the edge, before it reaches the app server at all | **DEPLOYMENT CONFIGURATION REQUIRED** — this repo has no deployment layer (`docker-compose.yml` is Postgres + Redis for local dev only; the API runs as bare `uvicorn`, which has no body-size option) |

Whatever fronts the API in production must cap the request body itself, at the file limit plus
the 64 KiB envelope. For the defaults above:

```nginx
location = /api/v1/cfo/ingest   { client_max_body_size 20m; proxy_pass http://api; }   # CFO_MAX_UPLOAD_BYTES + envelope
location = /api/v1/ci/evidence  { client_max_body_size 10m; proxy_pass http://api; }   # CI_MAX_EVIDENCE_BYTES + envelope
client_max_body_size 1m;                                                                # everything else
```

Caddy: `request_body { max_size 21MB }` per route. Traefik: the `buffering` middleware's
`maxRequestBodyBytes`. Kubernetes ingress-nginx: the `nginx.ingress.kubernetes.io/proxy-body-size`
annotation. Keep any proxy limit at or above the app limit plus envelope, so the app's own clear
413 message is what a normal user sees.

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
