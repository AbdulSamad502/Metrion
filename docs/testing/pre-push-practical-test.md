# Metrion pre-push practical test (prepared 2026-10-12)

Branch `feat/ceo-foundation`, HEAD `2b954c9`, working tree **uncommitted** (nothing here was committed or pushed). This document is the procedure for a human to run Metrion as a product, on a **scratch database**, before pushing. Preparing it is not the same as having passed it: every checklist box in section 9 is yours to fill.

## 0. Absolute rules for this test
1. **Scratch PostgreSQL on port 5544 only.** Never point anything at port 5432 (the development database in container `metrion-postgres-1`). The existing development backend (`:8000`) and frontend (`:3000`) in this checkout are wired to 5432 (`backend/.env`, `frontend/.env.local`): **do not use them for this test.** The procedure below starts a second backend (`:8001`) and a second frontend (`:3001`).
2. Do not read, print or paste secrets (`backend/.env`, tokens). Do not bypass authentication.
3. No real emails, payments, GST filings or marketplace actions exist in Metrion (it is recommend-only). The only outward calls are the optional ones listed in section 3.4: choose them consciously.
4. Keep `CEO_LEG_ABANDON_SECONDS` unset. `ci.research_now` stays unwired; approval is not enabled.

## 1. What exists and is testable (from the code)
Backend routers (`backend/src/backend/main.py`): session, onboarding, ping, Clerk webhooks, CI (23 routes), CFO (32), PI (11), CMO (20), CEO Hub (6), CEO (22). Frontend routes: `/dashboard` (Overview), `/dashboard/ceo-hub` ("Ask Metrion"), `/dashboard/notifications` (Action Center), `/dashboard/agents`, `/dashboard/pi` (Products), `/dashboard/competitors`, `/dashboard/cfo` (Profit & Finance), `/dashboard/cmo` (Listings & Marketing), `/settings`, plus sign-in, sign-up, forgot-password, onboarding. **There is no unauthenticated health endpoint** (`/api/v1/ping` needs a signed-in member); "backend healthy" means: the process answers, `/openapi.json` loads, an unauthenticated call is rejected with 401, and an authenticated `/api/v1/session` works.
CEO catalog: 36 actions, 35 wired, 11 approval-gated (refused from chat with a fixed text), `ci.research_now` unwired. Approval workflow is not built: nothing approval-gated can run.

## 2. Prerequisites (verified on this machine 2026-10-12)
Python 3.12.7 in `.venv` (system `python` is 3.11.0: do not use it), Node v24.18.0, npm 11.16.0, Docker 29.7.2. Containers present: `metrion-verify-pg` (scratch, **5544**), `metrion-postgres-1` (development, **5432**, do not touch), `metrion-redis-1` (6379). Ollama has `qwen3:8b`, `qwen3.5:4b`, `qwen3:4b`, `llava:latest`, `nomic-embed-text:latest`. Scratch DB is at migration head `20261011_0017`. Redis is not used by anything in the test.
**Missing/decisions for you:**
- **Clerk**: two real Clerk development users in two different organizations (the app's own `/sign-up` + `/onboarding` creates the org and tenant), because tenant-isolation tests need a second tenant. Keys already in `backend/.env` / `frontend/.env.local` (names only: `CLERK_SECRET_KEY`, `CLERK_WEBHOOK_SECRET`, `CLERK_JWT_KEY`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`). Local users are reconciled at login (spec D6), so no webhook tunnel is needed.
- **Vision model**: `CI_VISION_MODEL`/`CI_REVIEW_VISION_MODEL` in `backend/.env` are `qwen2.5vl-manual`, which is **not installed** in Ollama. Competitor screenshot reading will fail honestly (manual entry) until you install it or override with `llava:latest` (section 3.2).
- **`CEO_MAX_CANDIDATE_PRICES` is not set in `backend/.env`.** Without it the "what happens to my margin at a competitor's price" conversation refuses honestly ("investigation limits have not been configured", nothing run). Add it to the scratch backend's environment (`export CEO_MAX_CANDIDATE_PRICES=5`; the example file calls 5 "a suggestion only", so it is your decision) before case B4b.
- **CMO generation needs platform configuration that is not seeded**: `format_constraint_max_age_days`, `internal_retry_bound` and VERIFIED marketplace format constraints (the title/copy run ends `FAILED ... CONFIG_MISSING`, nothing billed). The repository has no seed utility, so CMO generation and market trends are **not testable** until you provide that configuration and (for trends) provider keys.
- **Tavily / YouTube** keys are set in `backend/.env` (Google Places empty). PI discovery and CMO market trends call them (your real quota). Section 3.2 blanks them for the scratch stack by default.
- **Synthetic financial files**: the repository ships no synthetic marketplace report or GST fixtures (the `data/` folder is gitignored uploads, treat as real, do not reuse). CFO populated-state tests need synthetic files you create per `docs/specs/data-foundation.md`; until then CFO is testable in empty/error/manual-entry states only.

## 3. Start Metrion on the scratch database
Run in Git Bash from the repo root. Nothing below touches 5432.

### 3.1 Scratch database (verify target first)
```bash
docker ps --format '{{.Names}} {{.Ports}}' | grep -E 'metrion-verify-pg'      # expect 0.0.0.0:5544->5432
# optional clean reset of the SCRATCH container only (removes only container metrion-verify-pg and re-migrates):
#   bash backend/scripts/scratch_db.sh up
eval "$(bash backend/scripts/scratch_db.sh env)"     # exports DATABASE_URL / DATABASE_URL_APP for 5544 + placeholder Clerk values
python - <<'EOF'
import os, sqlalchemy as sa
for k in ("DATABASE_URL","DATABASE_URL_APP"):
    print(k, "port", sa.engine.make_url(os.environ[k]).port)          # both MUST print 5544
EOF
cd backend && ../.venv/Scripts/python.exe -m alembic current           # expect 20261011_0017 (head)
```
Positive proof that host 5544 is the scratch container (compare to `docker inspect -f '{{.State.StartedAt}}' metrion-verify-pg`): `select pg_postmaster_start_time()` over that connection must match the scratch container, not `metrion-postgres-1`. **If the port is not 5544, stop.**
Migrations are already at head. Only if you recreate the container, `scratch_db.sh up` applies every package's migrations in CI order.

### 3.2 Backend on :8001 (real Clerk keys, scratch DB)
`backend/scripts/run_dev.py` loads `backend/.env` with `load_dotenv` (it never overrides variables already exported), so exporting the overrides first is enough. Open a **new** terminal:
```bash
cd backend
export DATABASE_URL="postgresql+psycopg://metrion_migrate:metrion_migrate_dev_password@localhost:5544/metrion"
export DATABASE_URL_APP="postgresql+psycopg://metrion_app:metrion_app_dev_password@localhost:5544/metrion"
export FRONTEND_ORIGIN="http://localhost:3001"  PORT=8001
export TAVILY_API_KEY= YOUTUBE_API_KEY=          # blank = no outward discovery calls (optional: remove to use your quota knowingly)
# export CI_VISION_MODEL=llava:latest CI_REVIEW_VISION_MODEL=llava:latest   # only if you want screenshot reading with an installed model
python -c "import os,sqlalchemy as sa;print(sa.engine.make_url(os.environ['DATABASE_URL_APP']).port)"   # MUST print 5544
../.venv/Scripts/python.exe scripts/run_dev.py
```
Leave `CEO_LEG_ABANDON_SECONDS` unset (not in `.env`). `.env` already sets `CEO_LEG_TIMEOUT_SECONDS=30`, `CEO_LLM_MODEL=qwen3:8b`, `CEO_CLASSIFIER_MODEL=qwen3.5:4b`, `CEO_OLLAMA_HOST=http://localhost:11434`. Make sure Ollama is running (`ollama list`).
Health checks (new terminal):
```bash
curl -s -o /dev/null -w "openapi %{http_code}\n" http://127.0.0.1:8001/openapi.json          # 200
curl -s -o /dev/null -w "session-unauth %{http_code}\n" http://127.0.0.1:8001/api/v1/session  # 401
curl -s -o /dev/null -w "ceo-unauth %{http_code}\n" http://127.0.0.1:8001/api/v1/ceo/investigations   # 401
```

### 3.3 Frontend on :3001 talking to :8001
Next gives process environment priority over `.env.local`, so the existing file is not edited:
```bash
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 npm run dev -- -p 3001
```
Open `http://localhost:3001`. In the browser console: `fetch` calls must go to `127.0.0.1:8001` (Network tab). If sign-in is refused for the new origin, add `http://localhost:3001` in the Clerk dashboard allowed origins. **Never use `:3000`/`:8000` for this test.**

### 3.4 Outward calls that can happen (decide before testing)
Local Ollama only (free): CEO classifier/composer, CFO narration, CMO, PI text. Public web reads: GST lookup fetches public GST reference pages (read-only). Your quota: Tavily/YouTube (blanked above). No message, email or marketplace write exists anywhere.

### 3.5 Database inspection helper (read-only, scratch container only)
```bash
q() { docker exec metrion-verify-pg psql -U metrion -d metrion -c "$1"; }   # superuser on the SCRATCH container: for reading only
q "select id, route, route_key, status, classifier_result->>'model' as model, classifier_result->>'requestKey' as req_key, created_at from investigation_turn order by created_at desc limit 5"
q "select agent_id, trigger_ref, status, left(coalesce(error_reason,''),60) as reason, parent_run_id is not null as is_leg from agent_run order by started_at desc limit 8"
q "select role, kind, left(content,70) from investigation_message order by created_at desc limit 6"
```
Never run these against 5432; the container name pins them to scratch.

## 4. Getting a token for API checks
Sign in at `:3001`, then in the browser console: `await window.Clerk.session.getToken()` (a secret: do not share or commit it). `export T="<token>"; export API=http://127.0.0.1:8001/api/v1/ceo`. Tokens expire in about a minute; refetch as needed.

## 5. Ordered manual test cases
Each case: steps, expected result, evidence to check. "Rule" = decided by explicit code rules with no model (verify `classifier_result.model = 'rules'` in the turn row); "model" = needs Ollama and can vary in wording (judge the route and honesty, not the exact words). Routes below are asserted by the repository's own integration tests.

### A. Startup and authentication
- **A1** Section 3.2/3.3 health checks all as stated. Frontend loads `/sign-in` with no red console errors.
- **A2** Unauthenticated: `curl -i $API/investigations` gives 401 and a body without stack trace/secret.
- **A3** Sign up user 1 (use a Clerk test address), complete `/onboarding` (business name). Expect redirect to `/dashboard`. DB: one `app_user` and one `tenant` row, plus a `membership` row (`q "select count(*) from app_user"`, same for `tenant`, `membership`).
- **A4** Sign up user 2 in a *different* browser profile/incognito, own business name (tenant B).
- **A5** Cross-tenant: user 1 creates a conversation (CEO Hub or `POST $API/investigations`). With user 2's token `GET $API/investigations/<id of user 1>` must be **404** (not 403, not data). Forged id `GET $API/investigations/00000000-0000-0000-0000-000000000000` gives 404.
- **A6** Client claims: add `"tenant_id"`, `"role":"OWNER"` to a POST body (`/investigations`): the extra fields are ignored (the request body only declares `title`) and the tenant is still yours (`select tenant_id from investigation ...`).
- **A7** Stop Ollama, send a model-dependent question (case B1): the UI shows a plain failure text, no stack trace/hostnames/keys; the turn row is FAILED/terminal, no run left RUNNING (`agent_run`).

### B. CEO Hub ("Ask Metrion") conversations
Start a new conversation, send the text, then check the turn row (`route`, `route_key`, `status`, `model`) and `agent_run` legs.
| # | Text | Expected route / status | Expected user-visible |
|---|---|---|---|
| B1 | `Where am I losing money?` (rule) | BUSINESS_STATE / QT_LEAKS / DELIVERED, no leg | a saved-results answer or an honest "nothing saved yet"; never invented figures |
| B2 | `Find trending products in the mens shoes niche under 2000 on Amazon` (rule) | ADVISORY / DENIED, **no leg run** | fixed text that the action needs an approved plan; Activity shows "Needs an approved plan" |
| B2b | `What product ideas did you find?` (rule) | BUSINESS_STATE / QT_PRODUCT_IDEAS / DELIVERED | previously found ideas or honest none |
| B3 | `What are my competitors charging?` (rule) | BUSINESS_STATE / QT_COMPETITORS_PRICES / DELIVERED | tracked competitors' saved prices or honest none |
| B4 | `Show me the latest product research report` (rule) | CLARIFY / CLARIFIED | asks, does not invent a report (none exists) |
| B4b | `Acme dropped to Rs 499, what happens to my margin?` (rule) | CLARIFY / CLARIFIED | asks which tracked competitor; no figure |
| B5 | `What GST rate applies to steel water bottles and also where am I losing money?` (rule split) | ACTION gst_lookup / DELIVERED, **one** `cfo.gst_lookup` leg | answer starts "Your message asked for more than one thing, and I handle one request per message", lists "Handled" and "Not handled: ... not started ... own message" |
| B6 | `Where am I losing money and also upload my sales file` | BUSINESS_STATE / DELIVERED, no leg | "Handled" for the first, "Not handled: ... could not match" for the unrecognised clause (the honest reporting of a clause no rule knows) |
| B7 | `Write hashtags for my steel water bottle on Amazon` (rule) | ADVISORY / DENIED, no leg | approval-required text, nothing run, nothing charged |
| B7b | `Run research now on my uploaded screenshots` | must NOT run (`ci.research_now` unwired) | no leg; clarification/out-of-scope; `select * from agent_run where trigger_ref='ci.research_now'` is empty |
| B8 | `What GST rate applies to steel water bottles?` (rule routes it; the lookup fetches public GST pages and then uses Ollama) | ACTION gst_lookup / DELIVERED, one leg COMPLETE | with the public pages reachable: the lookup result with its disclaimer. With the pages blocked (as in the assistant's run): "No GST rate could be found for that product from the public sources ... ask your accountant", leg COMPLETE, turn SUCCEEDED (the product cannot tell "pages unreachable" from "pages had no answer": defect D4 in the engineering report). Never a rate that was not found |
| B9 | stop Ollama then B8 | turn FAILED or leg UNAVAILABLE; the Hub shows a failure, not success | honest message; start Ollama again and resend (new send): works |
| B10 | stop the backend, send a message | Hub shows "Not sent" (or "received but reply lost" if it was recorded); no duplicate question after restart + resend of identical text | after restart a resend is a **new** turn unless it reuses the same id (case C) |
Malformed specialist result: not reproducible from the UI (requires a faulty specialist); covered by automated test `test_ceo_hardening` dispatch cases: **mark N/A (automated only)**.
Check always: the answer never claims an action ran when `agent_run` has no leg; a FAILED leg is never shown as "Completed" (Task status shows Failed or Partly completed).

### C. Idempotency and interruption (API; use your token)
```bash
INV=$(curl -s -X POST $API/investigations -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d '{}' | python -c "import sys,json;print(json.load(sys.stdin)['investigationId'])")
KEY=$(python -c "import uuid;print(uuid.uuid4())")
post() { curl -s -X POST $API/investigations/$INV/turns -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d "{\"message\":\"$1\",\"clientRequestId\":\"$2\"}"; }
```
- **C1** `post "Where am I losing money?" $KEY` twice. Second response has `"replayed":true` and the same `turnId`/`answer`; `q "select count(*) from investigation_turn where investigation_id='$INV'"` is 1.
- **C2** `post "Where are my competitors charging?" $KEY` (same key, different text): HTTP 409 `CLIENT_REQUEST_ID_REUSED`; turn count still 1.
- **C3** concurrent: two `post ... $KEY2 &` at once: result is one `replayed:false` plus either `replayed:true` or `409 TURN_IN_PROGRESS`; turn count 1.
- **C4** retry while running: send `What GST rate applies to steel water bottles?` with `$KEY3`, and while it runs send it again with `$KEY3`: second is `409 TURN_IN_PROGRESS` (nothing written) or waits and replays; one `cfo.gst_lookup` leg total.
- **C5** interruption (real process kill): send the GST text with `$KEY4`; within the first seconds hard-stop **only the 8001 backend** (PowerShell: `Get-NetTCPConnection -LocalPort 8001 -State Listen | % { Stop-Process -Id $_.OwningProcess -Force }`, then its `--reload` parent if still listed; never touch :8000), restart it (3.2), then `post` the same text with `$KEY4`. Expected: `replayed:true`, status FAILED, answer begins "That request was interrupted and did not finish"; DB: the turn is FAILED, the leg row is FAILED with reason starting `INTERRUPTED`, **no second `cfo.gst_lookup` leg**. Whether the public lookup had run is unknown: the system must not say it did not happen.
- **C6** new submission after C5 with a **new** key re-runs (deliberate retry).
- **C7** tenant isolation of keys: user 2 sends text with user 1's `$KEY` on user 2's own conversation: `replayed:false`, own turn; on user 1's conversation id: 404.
- **C8** (UI) In the Hub, stop the backend during a send and restart: the Hub's identical re-send within the same unanswered attempt reuses its id (Network tab: same `clientRequestId`); a different text or an answered send gets a new id.
- **C9/C10** timeout/late-result/uncertain-vs-repeatable classes are **not practically reproducible** (the hard deadline is unset by design and a thread cannot be made to hang from the UI): automated only, `backend/tests/integration/test_ceo_leg_deadline.py` (20 tests).

### D. Memory
- **D1** `my business name is Zyquora Test` then `what is my business name?` in the same conversation: the first answer acknowledges the remembered fact (written by code); the second answers "Your business name is Zyquora Test" without a model (rule).
- **D2** Refresh the page, open a **new** conversation, ask `what is my business name?`: same answer (persisted in the database: `q "select * from agent_memory order by created_at desc limit 5"`).
- **D3** Restart the backend (stop :8001, start), ask again: same answer.
- **D4** Supersession: `my business name is Zyquora Two`; ask again: the new name; the old value is not shown as current.
- **D5** `I sell only on Flipkart` then `where do I sell?`: answers Flipkart; `my niche is steel bottles` then `what is my niche?`.
- **D6** Tenant isolation: user 2 asks `what is my business name?`: "You have not told me ... yet" (never user 1's value).
- **D7** Stop the database container? **No**: do not stop shared containers. Memory-failure behaviour is automated only (`test_memory_campaign_*`): mark N/A.
- No retention/deletion guarantee is claimed: the Memory panel's "forget" hides the item per the implemented rules; do not treat it as erasure.

### E. Pages (what each can show now)
The assistant's real-backend sweep found no horizontal overflow at 360 and 768 px on any signed-in page, and fixed the defects listed in `acceptance-execution-report-2026-10-12.md` (idle-after-refresh, busy-send shown as failure, raw labels). Re-check these by hand: **refresh the Hub while an answer is being written** (expect "Answering your last question..." and Task status Running, then the answer); **send a second message while the first runs** (expect a notice, not a red Failed).
| Page | Empty | Error | Populated | Notes |
|---|---|---|---|---|
| Overview | New tenant: "No saved profit results yet", agents roster | Stop the backend: "We could not check everything" (never an all-clear), Retry | needs CFO results/CI data | no invented headline profit |
| Action Center | no alerts/requests | feed errors named | needs CI alerts or CFO data requests | |
| Agents | roster | error with Retry | roster | |
| CEO Hub | section B | section A7/B9 | after B | |
| Products (PI) | forms and 5-step strip | 503 shows plain text | niche brief lifecycle (local, free); discovery needs Tavily/YouTube (blanked: shows not-configured, restore keys only if you accept quota use) | |
| Competitors (CI) | empty workspace | plain errors | add a competitor (URL is never fetched), submit a screenshot (needs a vision model, section 2) or type values | |
| CFO (Profit & Finance) | forms; seller goal | plain errors | needs synthetic reports (none in repo) and `financial_health_config` platform rows (the test fixture inserts them: scratch only) | |
| CMO (Listings & Marketing) | tabs | plain errors | titles/copy use local Ollama; market trends need Tavily/YouTube | metered actions refused from chat, allowed on this page |
| Settings | sign-in methods, business | | | |
For each page record Loading, Empty, Error (stop :8001 or block the request), Retry, Populated (or "blocked: fixture X"). A page whose populated state could not be exercised is **not** fully tested.

### F. Responsive, console, keyboard
At 360x800, 390x844, 768 wide and 1440 wide on `/dashboard`, `/dashboard/ceo-hub`, each specialist page and `/settings`: no horizontal scrollbar on the page; navigation drawer works below 1024; tables scroll inside their own box; long text wraps; Hub Conversation/Activity tabs work below 1024; composer stays visible. Browser console: no errors; Network: no failed `/api/v1/*` requests except those you caused. Keyboard: Tab reaches every control with a visible focus ring, Escape closes the drawer and dialogs, Enter sends and Shift+Enter adds a line in the composer. **Screen-reader testing is not performed here: mark unperformed.**

### G. Security and failure boundaries
- **G1** B2/B7 never create a leg; `select trigger_ref from agent_run where trigger_ref in ('pi.discover','cmo.generate_title_sets','cmo.generate_hashtags')` shows only rows for runs you made through the Products/CMO pages, none from chat.
- **G2** B7b: `ci.research_now` has no runs.
- **G3** A5-A6 isolation and forged ids.
- **G4** Provoke failures (A7, B9, B10): messages contain no stack traces, file paths, hostnames, keys or SQL.
- **G5** The UI never shows success after a failed request (B9, B10, Overview with backend stopped).
- **G6** After every failure above no `agent_run` stays RUNNING for a turn that ended: `q "select count(*) from agent_run where status='RUNNING'"` is 0 when idle (the live leg of a still-running turn excepted).

## 6. Fixtures and dependencies summary
Two Clerk dev users (two orgs); Ollama running with `qwen3:8b`, `qwen3.5:4b`, `nomic-embed-text`; optionally a vision model; optionally Tavily/YouTube quota; for CFO populated tests, synthetic reports you create; for CFO health bands the three `financial_health_config` platform rows (see `backend/tests/integration/test_ceo_turn.py`, fixture `health_config`: tenant NULL, version 9999) inserted into the **scratch** DB only.

## 7. Safe cleanup (test-owned data only)
Stop `:8001` and `:3001` (Ctrl+C in their terminals). Scratch data may simply stay. To reset the scratch database completely, `bash backend/scripts/scratch_db.sh down` removes only the container `metrion-verify-pg` (named for scratch use; it does not touch `metrion-postgres-1`) and `scratch_db.sh up` recreates and migrates it. Do not run any delete against 5432. Clerk test users are in your Clerk dashboard; delete them there if wanted.

## 8. Known limitations and what cannot be tested here
- No unauthenticated health endpoint; no seed utility or test accounts in the repo; Clerk users must be created by you.
- Live-model behaviour (wording, model routing for non-rule phrases, composition) varies; rule-routed phrases above are deterministic. The automated suites use scripted or fake models and fake Clerk: they prove logic, not live-model quality.
- Real process interruption is practical only via C5; deadline/late-result/uncertain classes are automated only (hard deadline intentionally unset; no real runtime measurements exist to justify values).
- CFO/GST populated flows need synthetic fixtures (none provided; the financial correctness campaign is postponed).
- Vision extraction needs an installed model; PI discovery/CMO trends need provider keys; approval workflow does not exist.
- Accessibility: keyboard checks only if you perform them; no screen-reader audit.
- Redis is provisioned but unused by the tested paths.

## 9. Pass/fail checklist (fill in)
| ID | Result (P/F/N-A) | Evidence / notes |
|---|---|---|
| A1 ... A7 | | |
| B1 ... B10 (incl. B2b, B4b, B7b) | | |
| C1 ... C8 | | |
| D1 ... D6 | | |
| E: each page: loading / empty / error / retry / populated | | |
| F: 4 widths x pages; console; keyboard | | |
| G1 ... G6 | | |

## 10. Automated verification on the final tree
All rows below were executed **fresh on the final working tree** on 2026-10-12 (after the last code change), scratch database 5544 only (a guard aborted the chain if either URL was not port 5544).
| Command (cwd) | Exit | Result | Duration |
|---|---|---|---|
| `pytest tests/unit -q` (backend) | 0 | 4350 passed, 6 xfailed | 20 s |
| `pytest tests/integration -v -rsx` (backend; **full, started 07:01:52 after every code change**) | 0 | **1885 passed, 3 skipped, 1 xfailed** | 34:26 |
| `pytest tests -q` (calc-engine) | 0 | 471 passed, 1 skipped (pandas not installed) | 42 s |
| `pytest tests -q` (data-foundation) | 0 | 135 passed | 9 s |
| `pytest tests -q` (competitor-intelligence) | 0 | 337 passed | 34 s |
| `pytest tests -q` (cfo) | 0 | 322 passed, 3 skipped (documented blockers) | 17 s |
| `pytest tests -q` (market-signals) | 0 | 14 passed | 0.3 s |
| `pytest tests -q` (product-intelligence) | 0 | 282 passed | 7 s |
| `pytest tests -q` (slim-cmo) | 0 | 2428 passed | 60 s |
| `npx vitest run --maxWorkers=4` (frontend) | 0 | 65 files, 444 tests passed | 87 s |
| `npx tsc --noEmit` | 0 | clean | |
| `npx eslint` | 0 | clean (no output) | |
| `npx next build` | 0 | compiled, 18 static pages | |
Migration round trip (CI order: calc-engine, data-foundation, competitor-intelligence, cfo, product-intelligence, slim-cmo, backend; each upgrade head, downgrade base, upgrade head) on a throwaway database `metrion_roundtrip` inside the scratch container (dropped afterwards): **21 of 21 steps exit 0**, all components end at head (backend `20261011_0017`). Run after the migration fix described in the engineering report; the migration files have not changed since.
Opt-in downgrade tests (`METRION_ALLOW_DOWNGRADE_TESTS=1`, `test_accounting_cutover.py`, `test_ceo_turn_status_vocabulary.py`): 11 passed, 0 skipped, run on the scratch database before the last small edits (those tests do not touch the changed files); the final full integration run skips them as designed.
Integration skips (3) and xfail (1): two are the opt-in downgrade tests above (run separately and passing); one is a control ("every field of this request is optional" for the seller-goal PUT); the xfail is `test_class3_known_gap_quantity_words_are_not_yet_caught` (spec Q13: quantity words without digits, such as "doubled", pass the narration gate: a documented gap, **not** evidence that this is safe).
Not run: nothing in the list above was skipped for time. Not covered by any automated suite: real Clerk, live providers, populated CFO imports, screen readers.


## 11. GO / NO-GO for pushing
GO only if: all section 10 commands exit 0 on the final tree (integration included); sections A, B, C1-C8, D, G have no F; every E/F failure is understood; no secret or stack trace reached the UI; `git status` shows only intended changes; and you accept the limitations in section 8. NO-GO if any cross-tenant read, any approval-gated or `ci.research_now` execution, any false success after a failure, or any 5432 contact occurred.
