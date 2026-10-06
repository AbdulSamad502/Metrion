# Slim CMO build status (living record)

**Last updated 2026-10-04.** Nothing in this branch is committed or pushed. Auto mode off.

## Phase status

| Phase | State | Evidence |
|---|---|---|
| P1 scaffolding, P2 deterministic core | done, independently verified | 1387 tests at the time; mutation-checked |
| P3 generators, P4 catalog Q&A, P5 routes + quota reservations (partner's work) | done; verified on a clean scratch database | slim-cmo + backend suites |
| **P6 images / vision / evaluation harness** | **UNVERIFIED** (see below) | clean-DB evidence only |
| P7-0 provider probe, 7a plan, 7b pins, 7c extraction (`market-signals`), 7d niche flow | done | `docs/planning/market-signals-*.md` |
| 7e templates, egress guard, retrieval, daily counter | done | spec §6.8.5.1 |
| 7f trend report (service, routes, two meters, persistence) | done | spec §6.8.10 |
| P8 CEO hub dispatch + GST routes A/B (G1-G7) | done | `agents/ceo_hub_cmo.py`, `test_ceo_hub_cmo.py` |
| P9 frontend workspace (`/dashboard/cmo`) | built; type-check, lint, production build and request-contract checks pass; **not click-tested** (sign-in required) | `frontend/components/cmo/` |
| P10 evals, red team, static security, independent review | done | `docs/evaluation/slim-cmo-evals.md` |
| P11 CI-informed generation | **not started** | eval 8 is DEFERRED until then |
| P12 close-out | not started | |

## P6 (image intake, storage, vision provider, evaluation harness): **UNVERIFIED**

P6 stays explicitly UNVERIFIED until the owner's condition is met: the package integration suite and the backend CMO suites must
pass, one suite at a time, on the **development database** after its cleanup.

* **Why it is not verified:** the development database (`metrion`) contains leftover test rows from two interrupted test runs
  (two "Test Tenant" tenants' CMO rows and 46 `TEST_FIXTURE` format-constraint rows, plus 32 `vision_eval_run` rows). They make the
  shared test fixtures fail there (unique and foreign-key violations at setup/teardown).
* **Cleanup is postponed by the owner.** The reviewable script is `packages/slim-cmo/scripts/cleanup_test_tenants.sql`. It has NOT
  been run, and no development-database record has been deleted. Do not run it or delete rows without the owner's instruction.
* **Evidence that exists (not a substitute):** the same suites pass on a clean, separate scratch database (`metrion_verify`, every
  migration applied from empty).
* **Return to P6 before any production release.**

## Development database state

* Applied there: slim-cmo up to `20261005_0002`, backend up to `20261004_0005`. Migration `20261006_0003` (provider-usage counter)
  is applied only to the scratch database.

## Launch blockers (owner inputs and gates)

1. Verified marketplace format constraints with `count_rule` and `format_constraint_max_age_days` (H1) - without them production generation is blocked.
2. Trend configuration still unset: `max_sources_per_report`, `max_findings_per_section`, `fresh_window_days`, `recent_window_days`,
   `moderate_min_independent_sources`, `strong_min_independent_sources` (plus the starting values in spec §6.8.5.1 must be written as config rows).
3. **Per-tenant monthly trend cap must be seeded before launch** (`scripts/seed_trend_report_cap.sql`): a tenant with no cap is unlimited and could exhaust the shared daily provider ceiling.
4. Tactic risk pattern set (H6): until it exists every tactic is UNASSESSED with no suggested action.
5. Vision pass-bar (H3), image limits and retention (H4).
6. Legal review of the search providers for trend research (H9).
7. Provider keys (`TAVILY_API_KEY`, `YOUTUBE_API_KEY`) and the CMO model settings in the deployment environment.
8. A real-model (Ollama) run of generation and one trend report, and a signed-in click-through of the workspace; neither was possible in the build environment.
9. The daily provider ceiling (20, launch-week) counts CMO searches only; Product Intelligence shares the same keys.
10. P6 verification on the development database (above).
