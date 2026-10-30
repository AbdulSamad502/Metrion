# CMO 3.0 — Release blockers (recorded at M0 close, 2026-10-30)

These do not block M1 development. They block merging CMO 3.0 to production use.

| # | Blocker | Owner | How it is cleared |
|---|---|---|---|
| B1 | **No VERIFIED marketplace format rules** for Amazon, Flipkart, Meesho in the dev database (`verify_cmo_readiness.py` reports all three BLOCKED). Real generation fails closed (`COUNTING_RULE_UNVERIFIED`). Metrion must not invent limits. | Human (reads each marketplace's seller pages) | Fill `packages/slim-cmo/scripts/format_constraints.template.json`, run `seed_format_constraints.py --apply`, re-run `verify_cmo_readiness.py` until all three are READY |
| B2 | **Live Ollama not tested**: real text generation and real photo reading have only been run against deterministic fakes. | Engineer with Ollama running | Run titles, a photo reading and a listing copy against the local model; record the results |
| B3 | **Live search providers not tested** (Tavily, YouTube) for market-trend reports. | Engineer with provider keys | One real trend run per provider; record sources, dates and cost |
| B4 | **Full cross-agent regression** not yet run on the merged result. 9 backend integration tests and 1 unit test fail on a clean copy of the previous commit (finance action counts, presentation, period tests, request-contract snapshot); they are not from M0. | Before merge | Run the whole suite; fix or re-baseline the pre-existing ones separately |
| B5 | **Keyword research not yet run with real saved competitor insights** (tested with fake themes only). | Engineer with a tracked competitor | Run once for a real product with CI data and review the candidates |
| B6 | **No verified title display rules** (visible length per marketplace and screen). Previews are labelled ILLUSTRATIVE (not an official limit) until `title_display_rules` is configured with an https source and a check date. | Human (reads each marketplace's search results) | Add the `title_display_rules` platform config row (see spec 6.16) and re-run `verify_cmo_readiness.py` |
| B7 | **No real signed-in browser test.** The M4 preview was verified by component tests, a workspace test inside the CEO conversation, and one real-browser render of the real card with AquaNest data on a temporary page (since removed); a real Clerk-signed-in click-through of the CEO chat has not been done. | Engineer with a Clerk test user | Sign in, ask "Show my listing preview", and use every toggle and the photo route once; record the result |
