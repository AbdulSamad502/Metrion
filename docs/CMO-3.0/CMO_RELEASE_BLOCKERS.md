# CMO 3.0 — Release blockers (recorded at M0 close, 2026-10-30)

These do not block M1 development. They block merging CMO 3.0 to production use.

| # | Blocker | Owner | How it is cleared |
|---|---|---|---|
| B1 | **No VERIFIED marketplace format rules** for Amazon, Flipkart, Meesho in the dev database (`verify_cmo_readiness.py` reports all three BLOCKED). Real generation fails closed (`COUNTING_RULE_UNVERIFIED`). Metrion must not invent limits. | Human (reads each marketplace's seller pages) | Fill `packages/slim-cmo/scripts/format_constraints.template.json`, run `seed_format_constraints.py --apply`, re-run `verify_cmo_readiness.py` until all three are READY |
| B2 | **Live Ollama not tested**: real text generation and real photo reading have only been run against deterministic fakes. | Engineer with Ollama running | Run titles, a photo reading and a listing copy against the local model; record the results |
| B3 | **Live search providers not tested** (Tavily, YouTube) for market-trend reports. | Engineer with provider keys | One real trend run per provider; record sources, dates and cost |
| B4 | **Full cross-agent regression** not yet run on the merged result. 9 backend integration tests and 1 unit test fail on a clean copy of the previous commit (finance action counts, presentation, period tests, request-contract snapshot); they are not from M0. | Before merge | Run the whole suite; fix or re-baseline the pre-existing ones separately |
| B5 | **Keyword research not yet run with real saved competitor insights** (tested with fake themes only). | Engineer with a tracked competitor | Run once for a real product with CI data and review the candidates |
