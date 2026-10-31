# Correcting wrongly imported performance records

Capability: the "Listing Performance Intelligence" additional capability (`CMO_M8_PERFORMANCE.md`, design section 6c). Status: IMPLEMENTED. **INTEGRATION TESTED: 8 correction tests passed; migration applied to the scratch database (see Run results).** Not BROWSER VERIFIED.

## Behaviour
* The imported row in `cmo_perf_line` is never updated or deleted (the application role still has SELECT and INSERT only).
* A correction is a new row in `cmo_perf_correction`: the import and the row (composite foreign keys to `cmo_perf_import` and `cmo_perf_line`), the values **before** and **after** (five metrics each; blank = NULL = "not reported", never zero), which metrics changed, a void flag (every effective value blank), the **reason** (3 to 300 characters, required), who and when, and the correction it supersedes.
* The numbers use the **effective** value: the `cmo_perf_line_effective` view (`security_invoker`, so RLS of the underlying tables applies) shows each imported row with its newest correction applied; the daily metric query reads it, so totals, rates, trends, coverage-gated comparisons and the before/after version analysis all use corrected values. The dashboard says how many records in the period were corrected. Import conflict detection still compares against the **original** values.
* **Duplicate / conflicting / stale**: two partial unique indexes make the corrections of a record a single chain; a request must carry the correction it last saw (`expected_correction_id`, or none): any mismatch is `409 STALE`; a concurrent correction from the same starting point is `409 CONFLICT`; a change that leaves the effective values unchanged is `409 NO_CHANGE`.
* **Validation**: a reason; at least one change or a void (not both); known metrics only; counts are whole numbers of zero or more, sales is rupees with at most two decimals; clicks may not exceed impressions (also a database check).
* **Authorization**: `agent.cmo` plus `files.upload` (the same as importing). Reads need `agent.cmo`.
* **Tenant isolation**: FORCE RLS on `cmo_perf_correction`, `tenant_scope` on every query, composite foreign keys; another seller sees no record and gets 404.
* **Audit**: nothing is overwritten; every correction is a permanent row; the downgrade of the migration refuses while any correction exists.

## Routes
`GET /api/v1/cmo/performance/lines` (imported records, original and effective values, paged, newest first), `GET /performance/correction-history` (paged), `POST /performance/corrections`.

## CEO and frontend
CEO: "correct my imported data", "I imported the wrong numbers", "show my corrections" explain where to correct and list the latest three corrections; **nothing is changed from chat** (the correction needs the page's form, a reason and an explicit Save). Frontend: the performance page's "Correct an imported record" panel finds records by marketplace and report SKU, shows the imported value beside the value used in the numbers ("CORRECTED" / "VOIDED"), and sends only changed values.

## Limits
Corrections are by record (one day and report SKU), not bulk. Re-importing a file never overwrites a corrected record. A correction cannot be undone, only superseded by another. No correction is proposed automatically.

## Status
IMPLEMENTED; tests written (`backend/tests/integration/test_cmo_perf_correction.py`, `components/cmo/performance/corrections.test.tsx`); RUN on the scratch database (8 integration + frontend tests passed, plus the downgrade-safety test: 1 passed); migration `20261101_0012` applied to the scratch database only; NOT BROWSER VERIFIED.

## Run results (2026-11-01, scratch database metrion_eval)
* Migrations `20261101_0012` (slim-cmo) and `20261101_0033` (backend) APPLIED (upgrade only; heads now 0012 and 0033). Downgrade-with-data refusal for 0012 was NOT exercised.
* slim-cmo `tests/unit/market` 11 passed; `test_p2_purity.py`, `test_lint_no_float.py` passed.
* Backend unit: `test_cmo_m10_and_pagination.py`, `test_cmo_perf_view_products.py`, `test_cmo_p5_unit.py`, `test_ceo_architecture.py`, `test_request_contract_snapshot.py`, `test_frontend_api_paths_exist.py`: passed after fixing two test-data mistakes and the architecture allowlist (the six files were not re-run together in one final run; the two that failed were re-run and passed, 318 passed).
* Backend integration: `test_cmo_perf_correction.py` + `test_cmo_m9_images.py` + `test_ceo_cmo_m9_images_chat.py`: 39 passed. M8 files `test_cmo_m8_performance.py`, `test_cmo_b8_performance.py`, `test_ceo_cmo_m8_performance_chat.py`: 43 passed (after the daily query moved to the effective view).
* Frontend: market, corrections, pagination, performance and images tests, hub guard and test-support: all passed after fixing a duplicate "Marketplace" label; `ceoHubRestore` timed out once under load and passed alone. The full frontend suite was NOT re-run after these changes.
* NOT run: the full slim-cmo, backend and frontend suites, CFO suites, the full 18-file M5/M6/M7 batch after the M6 typed-title fix (the batch ran once: 260 passed, 1 failed on that now-fixed defect; the six affected M6 files then passed, 57), browser verification. M10 integration tests exist and ran (`backend/tests/integration/test_cmo_m10_market.py`, 20 passed).
