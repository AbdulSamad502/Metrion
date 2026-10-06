# Market-signal extraction plan (P7a, document only)

**Status: DRAFT for approval (readiness-review H8 / spec R9). No code has moved. Product Intelligence (PI) is untouched until this is approved.**
Spec refs: `slim-cmo-agent.md` §6.8, R9, V9; `docs/planning/market-signals-provider-capabilities.md` (P7-0 evidence).

## 1. Why extract at all

CMO trend research needs the same three things PI already has: a Tavily client, a YouTube client, and the query cache + per-source rate limiter. Three options:

| Option | Verdict |
|---|---|
| A. CMO imports `product_intelligence.sources` | **Rejected.** Couples two agents; breaks the star topology intent ("CMO never calls PI") and makes any PI refactor a CMO risk. |
| B. Copy the clients into `slim_cmo` | **Rejected.** Two diverging copies of a rate limiter and quota-sensitive HTTP code. |
| C. New neutral package `market-signals`, both agents depend on it; PI keeps import-compatible shims | **Proposed.** |

## 2. What moves (and what does not)

Current PI layer `product_intelligence/sources/` (645 lines):

| File | Lines | Used by | Action |
|---|---|---|---|
| `tavily_client.py` | 198 | `discovery_run`, `candidate_synthesis`, `pi_discover`, `pi_supplier_lookup`, backend `pi_actions` | **Move** to `market_signals.tavily_client` |
| `youtube_client.py` | 200 | `discovery_run`, `candidate_synthesis`, `pi_discover`, backend `pi_actions` | **Move** to `market_signals.youtube_client` |
| `cache.py` | 101 | `discovery_run`, `pi_discover`, backend `pi_actions` | **Move** (`QueryCache`, `InProcessQueryCache`, `normalize_query_text`) |
| `rate_limiter.py` | 79 | `discovery_run`, `pi_supplier_lookup` | **Move** (`throttle`) |
| `keyword_demand_client.py` | 67 | **nothing** (no importer in src or backend) | **Stays in PI, untouched.** Not needed by CMO; moving unused code adds risk for no benefit. |

PI domain logic (`discovery/`, `supplier/`, `direct_path/`, DB, ranking, synthesis) does **not** move. `market-signals` has no database, no tenant data and no dependency on PI, CMO or backend.

## 3. Target shape

```
packages/market-signals/            (import name: market_signals)
  src/market_signals/{tavily_client,youtube_client,cache,rate_limiter}.py
  tests/                            (moved + new characterization tests)
packages/product-intelligence/src/product_intelligence/sources/
  tavily_client.py  = shim         (aliases the market_signals module object)
  youtube_client.py = shim
  cache.py          = shim
  rate_limiter.py   = shim
```

**Shim mechanism:** each shim replaces itself with the real module (`sys.modules[__name__] = market_signals.<mod>`), so the old import path yields the *same module object*: identical classes (`isinstance` and `except` clauses keep working), identical module state (the rate limiter's semaphores and any test that patches `product_intelligence.sources.rate_limiter.X` still hits the one real attribute). Re-exporting names with `from … import *` is **not** used because it would copy names and break patching.

## 4. Behaviour changes (kept out of the move)

Extraction commits change **no behaviour**. CMO's needs are added afterwards as separate, additive commits, each with a test that proves PI's default request is byte-identical:

1. Tavily `search(...)`: optional keyword-only `topic`, `time_range`, `days`, `country` (all default `None` ⇒ omitted from the request body). Probe evidence: news mode is the only mode that returns dates.
2. YouTube `search_videos(...)`: optional `region_code`, `order`, `published_after` (default `None` ⇒ omitted); `YoutubeVideo` gains `channel_id: str | None = None` (last field, default) populated from `snippet.channelId`.
3. Nothing else (no new transport, no new retry logic, no caching change).

## 5. Gates (nothing proceeds without all of these)

**7b — Regression pinning, before any move (CP7b).** On current code, add and pass:
- Characterization tests for `HttpTavilyClient` and `HttpYoutubeClient` using `httpx.MockTransport`: exact request body/params, parsing of real-shaped responses (including `published_date` RFC-2822 strings, missing fields, non-dict entries), and every failure path raising `TavilyUnavailable`/`YoutubeUnavailable`. **These do not exist today** — the Http clients are currently exercised only through fakes.
- A baseline record of the suites: PI package suite, backend PI tests (`test_pi_discover_api.py` etc.) — counts and pass state captured in the checkpoint report before the move.

**7c — Extraction (CP7c):**
- Create `packages/market-signals` (own `pyproject.toml`, mypy strict, no-float lint), `git mv` the four files (history preserved), install shims.
- PI `pyproject.toml` depends on `market-signals`; `slim-cmo` will depend on it in 7e (not in 7c).
- `.github/workflows/ci.yml`: install `market-signals` **before** `product-intelligence`, run its tests; otherwise unchanged.
- **Exit criteria:** every 7b test and the full PI and backend suites pass with *no test edited* (a test that must change is a regression and stops the phase); a new test asserts each shim's module `is` the market_signals module; mypy strict clean on both packages.

**7c-ii — Additive CMO parameters (separate commit):** §4 items with the byte-identical-default tests.

## 6. Rollback

All of 7c is one commit (plus the additive one). `git revert` restores the four files in PI and removes the package; because PI's import paths never changed, nothing else needs touching. If the PI suites differ in any way after 7c, the commit is reverted rather than patched forward.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Shared module state (rate-limit semaphores) now shared across agents in one process | Intended: one limit per external source protects the free-tier quota. Per-source limits unchanged; documented in the package README. |
| Hidden dependence of a PI test on module path/name | Shim aliases the module object; the 7c exit criterion forbids editing any test. |
| Editable-install ordering in CI / dev | `market-signals` installed first; CI step order change reviewed in the diff. |
| Two agents burning one provider quota | Quotas are budgeted per CMO report by `trend_*` config (H5); no cross-agent coordination is claimed in V1. |
| Scope creep into PI behaviour | §4: behaviour changes are separate commits and default-identical. |

## 8. Out of scope
Moving `keyword_demand_client`, any PI domain code, a shared DB-backed cache, new providers, retry/backoff changes.

## 9. Decision requested
Approve (or amend) sections 2–6. On approval the next step is **7b only** (tests, no moves); 7c starts only after the 7b checkpoint is reviewed.

## 10. 7b result and behaviours that cannot be tested without live access

Added (no production code touched): `packages/product-intelligence/tests/unit/test_sources_http_clients.py` (70 tests, real clients against canned httpx responses) and `test_sources_callsite_pins.py` (16 tests: cache/throttle/quota behaviour at the `discovery_run` call sites, cache edge cases, limiter edge cases). Mutation check: 15 of 16 deliberate bugs killed by these files alone; the 16th (semaphore release in `finally`) is killed by the existing `test_rate_limiter.py`.

**Not testable without live credentials/provider access (stated, not faked):**
- the providers real response shape drifting from the canned shapes (re-probe per `market-signals-provider-capabilities.md`);
- real quota exhaustion and real rate-limit responses (only status-code handling is pinned);
- real latency and timeout behaviour, and real concurrency limits under provider latency (the limiter is pinned as a pure bounded-concurrency gate);
- Tavily server-side semantics of `search_depth`, `include_image_descriptions`, `topic`, `time_range`, `country`; YouTube `regionCode`/`order` effects;
- cross-process behaviour: cache and limiter are in-process by design (documented limitation, not tested as shared).

**Proposed extraction verification criteria (7c exit):** (1) all 7b tests and the full PI package suite (272 incl. 7b) and backend PI tests (14) pass with NO test edited; (2) shim test: each `product_intelligence.sources.<mod>` object `is` the `market_signals.<mod>` object; (3) a monkeypatch of `product_intelligence.sources.rate_limiter` internals still affects `market_signals.rate_limiter`; (4) mypy strict + no-float lint clean on both packages; (5) CI workflow installs `market-signals` first and runs its tests; (6) `git diff -M` shows the four files as renames with no content change other than package-relative imports; (7) one-commit revert restores the baseline.
