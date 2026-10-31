# Version pagination (listing versions of a product)

Status: IMPLEMENTED, AUTOMATED TESTED (unit and component level; see Run results). Not BROWSER VERIFIED.

## What changed
* **No page cap on the data.** The performance code used to read one page (100) of a product's versions. `cmo_history.product_versions(tenant, sku, marketplace)` now returns **every** version of one product on one marketplace, oldest first (stable: lineage number, then id), with one tenant-scoped query for that product only. `cmo_perf_view._products` uses it, so mappings, rankings, the dashboard and the before/after analysis know every version, and go-live overlap checks see every go-live date.
* **Paged output.** `cmo_perf_view.versions(tenant, sku, marketplace, limit, offset, order)` analyses and returns only the requested page. Only that page runs the before/after queries (the expensive part), so cost follows the page size, not the number of versions. The reply carries `total`, `limit`, `offset`, `hasMore` and `order`. `limit` None means every version (kept for the internal callers: the CEO answer and `assess_for`).
* **HTTP**: `GET /api/v1/cmo/performance/versions?sku&marketplace&limit&offset&order` with `limit` 1 to 100 (default 25), `offset` from 0, `order` asc (oldest first, the default) or desc (newest first). The account-wide `GET /listing-history` was already paged (`limit` up to 100, `offset`, `total`, `hasMore`, newest first, stable by date then id) and is unchanged; its comparison endpoint takes any two versions, so comparisons work across pages.
* **Frontend**: the version panel loads 25 at a time, shows "Showing N of TOTAL versions", has "Load more versions" and a "Newest first" switch.

## Limits
`history_rows` still loads the rows of ONE product to number them (numbering depends on the whole lineage); the account-wide history list loads all products' rows before slicing. That is acceptable for the expected sizes; a SQL-level window for very large accounts is future work. `limit` None on the internal callers analyses every version.

## Status
IMPLEMENTED; unit tests written (`backend/tests/unit/test_cmo_m10_and_pagination.py`, `components/cmo/performance/corrections.test.tsx`), the old products stub test updated; RUN, passed (see run results).

## Run results (2026-11-01, scratch database metrion_eval)
* Migrations `20261101_0012` (slim-cmo) and `20261101_0033` (backend) APPLIED (upgrade only; heads now 0012 and 0033). Downgrade-with-data refusal for 0012 was NOT exercised.
* slim-cmo `tests/unit/market` 11 passed; `test_p2_purity.py`, `test_lint_no_float.py` passed.
* Backend unit: `test_cmo_m10_and_pagination.py`, `test_cmo_perf_view_products.py`, `test_cmo_p5_unit.py`, `test_ceo_architecture.py`, `test_request_contract_snapshot.py`, `test_frontend_api_paths_exist.py`: passed after fixing two test-data mistakes and the architecture allowlist (the six files were not re-run together in one final run; the two that failed were re-run and passed, 318 passed).
* Backend integration: `test_cmo_perf_correction.py` + `test_cmo_m9_images.py` + `test_ceo_cmo_m9_images_chat.py`: 39 passed. M8 files `test_cmo_m8_performance.py`, `test_cmo_b8_performance.py`, `test_ceo_cmo_m8_performance_chat.py`: 43 passed (after the daily query moved to the effective view).
* Frontend: market, corrections, pagination, performance and images tests, hub guard and test-support: all passed after fixing a duplicate "Marketplace" label; `ceoHubRestore` timed out once under load and passed alone. The full frontend suite was NOT re-run after these changes.
* NOT run: the full slim-cmo, backend and frontend suites, CFO suites, the full 18-file M5/M6/M7 batch after the M6 typed-title fix (the batch ran once: 260 passed, 1 failed on that now-fixed defect; the six affected M6 files then passed, 57), browser verification. M10 integration tests exist and ran (`backend/tests/integration/test_cmo_m10_market.py`, 20 passed).
