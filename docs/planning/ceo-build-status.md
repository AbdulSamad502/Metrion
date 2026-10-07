# CEO build status

Authority: `docs/specs/ceo-agent-orchestration.md` (CP1 2026-10-07). This file records what is **built and verified**, what is **registered but not wired**, and what is **deliberately not built yet** — so nothing partial is ever read as complete.

| Checkpoint | State |
|---|---|
| CP1 spec/contract amendment (rounds 1–2) | **Done, approved** |
| **B1 Foundation** | **Done, approved** (this file's detail) |
| B1 privilege hardening | **Done** — migration 0007, see below |
| **B2 Evaluation harness** | **Harness built and tested; baseline NOT completed (no benchmark results exist)** — see `docs/evaluation/ceo-eval-b2-checkpoint.md` |
| **B3 Intelligence** (classifier, plans, parallel legs, composer, gate, API) | **Built and tested on a scratch Postgres with scripted models; not benchmarked against a live model** — see below |
| B4 Orchestration (playbooks, parallel dispatch, API) | Not started |
| B5 Seller surface (CEO Hub UI) | Not started |
| B6 Hardening and manual E2E | Not started |

## B1 Foundation — what exists

| Piece | Where | Notes |
|---|---|---|
| V1-core schema | `backend/migrations/versions/20261007_0006_ceo_foundation.py` | `investigation` lifecycle (`RESOLVED`, `origin`), `investigation_message.kind/turn_id`, new `investigation_turn`, `investigation_finding`, `investigation_agent`; FORCE RLS; CHECKs; app role has **no DELETE** on the three audit tables. Round-trips (downgrade → upgrade) verified. V1-later tables (`ceo_goal`, `situation`, `ceo_decision`, `ceo_open_issue`, `ceo_followup`) deliberately **not** created. |
| `agent_run` repo fixes | `repositories/agent_run_repo.py` | `investigation_id`, `output_refs`, `list_children`, and parent inheritance via `parent_run_scope` (so PI/CMO rows link to the CEO turn without being edited). |
| Investigation repository | `repositories/investigation_repo.py` | Lifecycle, messages (summary window), turns, findings, attachment. Every insert re-checks the parent is visible in the caller's tenant (an FK alone would accept a foreign tenant's id). |
| CEO entitlement | `backend/entitlement.py` | `resolve_ceo_entitlement`, `meter_ceo_turn` (idempotent per turn). No cap seeded → `NO_CAP_CONFIGURED`, stated honestly. |
| Contracts | `backend/ceo/contract.py` | `Ref/Figure/Gap/Fact`, `BusinessStateEntry`, `ActionSpec`, `LegResult`; no WRITE effect exists. |
| Provenance gate | `backend/ceo/provenance.py`, `repositories/provenance_repo.py` | Resolves refs per tenant; engine vs estimate refs never interchangeable; unresolvable/unavailable-as-real figures are dropped with a named gap. |
| Action registry | `backend/ceo/registry.py` | 36 actions; **33 wired**; forbidden (write-class) keys cannot register. |
| Choke point | `backend/ceo/dispatch.py` | Real `AuthContext` only; permission → attachment → entitlement → validated slots → call; child `agent_run` per leg; uniform `DENIED`; no internals leaked. |
| Business State | `backend/ceo/business_state.py`, `derived_reads.py` | 6 entries with verified persisted sources. |

### Registered but NOT wired (absent from every catalog; refuse if forced)
| Key | Why | Wired in |
|---|---|---|
| `cfo.gst_lookup`, `service.gst_lookup` | Route A/B selection and G1–G7 basis-label plumbing | B4 |
| `ci.research_now` | needs a chat-attachment/evidence-upload surface (spec Q8, unresolved) | after Q8 |

### Business State entries
| Entry | State |
|---|---|
| `BS_PNL_LATEST`, `BS_LEAK_OPEN`, `BS_DATA_GAPS`, `BS_HEALTH_BANDS`, `BS_SELLER_CONTEXT` (goal only), `BS_INGEST_STATUS` | **Built, tested against real Postgres** |
| `BS_COMPETITOR_SNAPSHOT`, `BS_PI_REPORT_LATEST`, `BS_CMO_WORKFLOW` | **Deferred**: source exists but the owning package has no tenant-wide read function (a small read function per owner, added with its specialist leg) |
| `BS_GOAL_PROGRESS`, `BS_SITUATIONS` | V1-later (need `ceo_goal`/Brain 1 `goal_progress`; `situation` + detectors) |

## Verification (run 2026-10-07, real Postgres 16 via docker, `metrion_app` role)

| Suite | Tests |
|---|---|
| `tests/unit/test_ceo_dispatch_unit.py` | 38 |
| `tests/unit/test_ceo_registry.py` | 35 |
| `tests/unit/test_ceo_architecture.py` | 43 (AST rules over `backend/ceo`) |
| `tests/unit/test_ceo_figures_and_provenance.py` | 43 |
| `tests/integration/test_ceo_foundation_rls.py` | 32 |
| `tests/integration/test_investigation_repo.py` | 23 |
| `tests/integration/test_ceo_dispatch_integration.py` | 12 |
| `tests/integration/test_ceo_business_state.py` | 32 |

* **Mutation check:** 15 deliberate breakages of the key invariants (attachment, permission, DENIED-vs-FAILED, reserved slot names, fixed params, provenance gate, engine/estimate interchangeability, leak ordering, latest-period selection, state gating, cross-tenant guard, resolve-needs-note, detach-hides-findings, parent inheritance) — **14 caught on the first pass; the one miss (reserved slot names) was a real test gap and is now covered and re-checked.**
* `mypy --strict` clean on every new module.
* **Full backend regression** (`pytest backend/tests`, project `.env` loaded, 2026-10-07): **650 passed, 1 failed, 359 errors.** Every one of the 1 + 359 is in the CMO integration files (`test_cmo_*`, `test_ceo_hub_cmo`) and has one of two causes in the shared dev database: a `ForeignKeyViolation` deleting `format_constraint` `TEST_FIXTURE` rows still referenced by leftover `cmo_generation` rows, or the resulting `UniqueViolation` re-seeding them. **This was already failing before any B1 change** (the first baseline run, before any edit, errored identically on `test_ceo_hub_cmo.py`). All other suites — CFO, CI, PI, entitlement, RLS, auth, the existing CEO-hub tests — pass with the B1 changes to `agent_run_repo` and `entitlement.py`. Reproduce: load `backend/.env`, set `DATABASE_URL`/`DATABASE_URL_APP`, run pytest (six existing modules import `backend.main` and need the `CLERK_*` variables).

## Findings made while building (all handled or recorded)

1. **Default privileges.** `docker/postgres-init/02-roles.sql` grants `metrion_app` full CRUD on every new table; "no DELETE on audit evidence" needs an explicit `REVOKE`. A test caught the gap; the migration now revokes. *Other tables created by earlier migrations may be affected the same way — worth a separate audit.*
2. **Delete-order cycles** (`investigation.summary_covers_through ↔ message`, a pre-existing one; and a new one the design would have introduced) broke tenant cleanup. Both back-pointers are now plain columns.
3. **Stored percent scale.** `metric_result` percentages are on the percent-number scale (12.5 means 12.5%); a formatter that scaled by 100 was caught before use.
4. **Metric code.** The stored code is `CONTRIBUTION_MARGIN_PCT`, not `MARGIN_PCT`; the spec was corrected.
5. **Dev-DB pollution (not CEO).** The shared dev database holds ~80 legacy test tenants; their CMO rows contain a delete cycle (`cmo_generation ↔ cmo_title_option`) that makes the shared test cleanup fail (one CMO integration fixture already errored before B1). Left untouched.

## Known limitations of B1 (stated, not hidden)

* `STALE` is never emitted (no configured max age exists); `as_of` is always shown.
* Leak figures cite the `leak_finding` row; whether each finding's own `engine_result_ref` resolves in `metric_result` is checked in the B6 E2E.
* For specialists that write their own `agent_run` (CMO, PI) the finding's `agent_run_id` is null; the link is `parent_run_id`.
* `default_extract_refs` collects only refs a specialist's payload reports under `...EngineResultRef` / `...EstimateRef` keys; a specialist that reports none yields none.
* `read_entries` and `dispatch` are sequential; parallel legs, the per-tenant cache and streaming are B4.
* The old dummy-hub modules (`agents/ceo_hub.py`, `agents/ceo_hub_cmo.py`) and `/api/v1/ceo-hub/*` routes still exist unchanged and are **not** the CEO; a parity test pins the registry's CMO permissions to the hub's table until the hub is removed.
* No API route, classifier, composer, playbook, or UI exists yet.

## B1 privilege hardening (2026-10-07)

`docker/postgres-init/02-roles.sql` gives `metrion_app` full CRUD on every new table, so a table is app-deletable unless its migration revokes. Migration `20261007_0007`: `investigation_finding` is now append-only (no UPDATE, no DELETE) and DELETE is revoked on `investigation`, `investigation_message` and `agent_run`; the three B1 tables already had no DELETE. `tests/integration/test_privilege_boundary.py` (24 tests; 6 fail if the migration is reverted) pins this and adds a drift guard so a new table cannot silently become app-deletable.

**Reported, not changed (other owners):** `metrion_app` still holds DELETE on ~70 earlier tables including `auth_audit`, `metered_event`, `metric_result`, `leak_finding`, `ingestion_run`, `whatsapp_message` and the `alembic_version*` tables (listed in `KNOWN_APP_DELETABLE` in that test). Needs its own decision/migration per owning spec.

**CMO integration failures** are not caused by B1: all 87 CMO tests pass on a clean database with B1 + 0007 applied (full backend suite 851/851 there). The dev database's fixture contamination is recorded separately and untouched. Note the dev database is at backend revision 0004; 0005–0007 have not been applied to it.

## B2 Evaluation harness — state (2026-10-07)

* **Built:** the model-agnostic harness in `backend/src/backend/ceo_eval/` — 126 classifier fixtures (123 scored, 3 pending) and 43 composer fixtures; 217 harness tests pass (499 across the CEO suites including integration).
* **Not done:** the 3-model baseline was intentionally terminated (CPU-only host, hours per model, no model completed); **no run record, no accuracy/safety/latency result and no model comparison exist**; the partial progress log is not a result; the DB latency stage was not run. No pass bars or model choice are claimed.
* **B3 has not started.** Model-selection evidence needs a run on suitable hardware (commands in the checkpoint document).

## B3 first end-to-end CEO turn — state (2026-10-07)

* **Built:** `POST /api/v1/ceo/investigations`, `GET .../investigations`, `GET .../{id}`, `POST .../{id}/turns` (the full turn), `GET .../{id}/findings` (polling seam), `POST .../{id}/resolve`. The turn: admission -> one classification -> deterministic plan validation (closed catalog, slots, periods) -> per-leg pre-flight -> parallel CFO legs + Business State reads with findings emitted as each completes -> evidence table via refs -> one composition -> numeral/provenance gate or fixed template -> persisted messages, turn, findings, timings. Details and decisions: spec §6.29.
* **Supported:** BUSINESS_STATE, ACTION (5 CFO actions), PLAYBOOK (`PROFIT_DIAGNOSIS`, `CASH_AND_LEAK_CHECK`, `BUSINESS_BRIEFING`), ADVISORY, SYNTHESIZE, CLARIFY, OUT_OF_SCOPE. **Not supported:** the other registry actions, `COMPETITOR_PRICE_IMPACT`, `NEW_PRODUCT_DECISION`, GST routes, goals, proactive detection, UI, SSE.
* **Not done / honest limits:** no live-model run (B2 benchmark was intentionally abandoned; the model is configuration, none is chosen); turns are not serialized per investigation; no rolling-summary regeneration; capability/entitlement lookups are uncached (~0.3 s/turn on the scratch DB).
