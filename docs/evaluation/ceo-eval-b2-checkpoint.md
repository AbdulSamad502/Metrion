# CEO evaluation harness — B2 checkpoint (2026-10-07)

**Status in one line: the harness is implemented and tested; the model baseline was NOT completed, so there are no benchmark results.**

Authority: `docs/specs/ceo-agent-orchestration.md` §6.18 (CP1-D6). This file records exactly what exists, what was measured, and what was not — so nothing partial is read as a result.

## What is implemented

A model-agnostic classifier/composer evaluation harness in `backend/src/backend/ceo_eval/` (`python -m backend.ceo_eval run|report`). It is a set of measuring instruments; nothing in `backend/ceo` imports it (pinned by a test), and no B3 intelligence has been built.

| Piece | File | Notes |
|---|---|---|
| Model layer | `model.py` | `OllamaEvalModel` (local hosts only, streaming TTFT, constrained JSON, `think` control, deterministic sampling), `ProviderAdapter` (wraps any product `LlmProvider`), `ScriptedModel` (fake for tests). Swapping a model changes one constructor argument. |
| Catalogs | `catalog.py` | Per-scenario closed catalogs (FULL, NO_CFO, NO_CI, NO_PI, NO_CMO, CFO_ONLY, NONE). Action keys, owners and the metered flag come from the live registry; Business State ids from the live module. Descriptions, slot vocabulary and the playbook list are harness candidates (B3/B4 own the real ones). |
| Classifier candidate + scoring | `classifier.py` | Prompt `classifier-v0`; code (not the model) enforces the closed catalog and required slots; raw and effective verdicts are both scored. Counts and rates only. |
| Composer candidate + scoring | `composer.py` | Prompt `composer-v1`; the model sees figure tokens, never values; scores truncation, reasoning leakage, numerals, markers, case rules. |
| Gate measurer | `gate.py`, `render.py` | Numeral/placeholder gate reference (digits, currency, percent, magnitude words, number-word quantities; date-like digits classified separately for the Q13 strictness question) and deterministic placeholder substitution. |
| Latency | `runner.py`, `latency_db.py` | Per-call LLM wall/TTFT/tokens, a cold-start + prefix-cache probe, and a real-Postgres stage timer for turn admission, Business State reads (sequential vs parallel), real dispatch legs and a denied leg. |
| Report | `report.py` | Renders a run record to markdown; no pass/fail verdicts. |

**Fixtures** (`ceo_eval/fixtures/`): **126 classifier cases** (123 scored; 3 `pending` — GST lookup, `ci.research_now`, goal progress — excluded because their capability is not wired) and **43 composer cases**. Classifier categories: STATE, ACTION, PLAYBOOK, ADVISORY, SYNTHESIZE, CLARIFY, OUT_OF_SCOPE, ABSENT_AGENT (20), INJECTION, CONTEXT, PENDING. Composer categories: FIGURES, CONFLICT, NON_RESULT, PARTIAL, ABSENT_AGENT, ADVISORY, VERBATIM, WALL, INJECTION, SYNTHESIZE.

## Tests (run 2026-10-07, after the final documentation edit)

| Suite | Result |
|---|---|
| `tests/unit/test_ceo_eval_harness.py` (fixture validity incl. every expected key offered in its scenario, catalog = live registry, gate, parsing, oracle model scores every case, hostile models caught, prompt never contains a figure value, local-host guard) | 217 passed |
| Existing CEO unit suites (dispatch, registry, architecture, figures/provenance) | 159 passed |
| `tests/integration/test_privilege_boundary.py` + the four B1 integration suites (RLS, investigation repo, dispatch, Business State), real Postgres 16, `metrion_app` | 123 passed |
| **Total** | **499 passed, 0 failed** |

An earlier full backend run on the same scratch database (before the harness): 851 passed.

## What was NOT done — read this before using any number from this project

1. **No baseline exists.** A full 3-model run (`baseline-1`: qwen3:8b, qwen3.5:4b, qwen3:4b; classifier + composer + DB latency) was started and **intentionally terminated**. The host is CPU-only (i5-12450H, 15.7 GB RAM, ~2.4 GB free) and calls took 15–200 s each; no model had finished, so **no run record was written** and nothing is claimed about accuracy, safety or latency.
2. **The partial progress log is not a result.** `%TEMP%\baseline1.log` lists qwen3:8b progress lines (probe, then 99 classifier cases with ok/MISS and wall time). It has no raw outputs, no composer data and no completed run record. It is preserved only as evidence of what ran. The five smoke JSONs in `%TEMP%\smokeout\` are likewise preserved and are not benchmark data.
3. **The DB latency stage was not run.**
4. **No pass bars or thresholds exist** (spec §6.18: a human decision after a measured run). **No model is selected or ranked.**
5. **No B3 work has started.** There is no production classifier, composer, gate, or orchestration.

## Smoke observations (a handful of cases, not benchmark results)

Recorded because they affected the harness, not because they measure anything:

- Throughput on this host: qwen3:4b classifier calls ~15 s when the prefix was warm, ~80 s cold; composer calls 45–80 s. qwen3:8b classifier calls 25–200 s with visible paging (the weights exceed free RAM). These are infrastructure facts about this machine, separate from model quality.
- `composer-v0` made qwen3:4b print its reasoning instead of an answer. `composer-v1` (one worked example, chat endpoint with a system/user split) was introduced for that reason, before any accuracy run and without tuning on results. qwen3:4b still leaked reasoning under v1 in 3 of 3 smoke cases; qwen3:8b and qwen3.5:4b produced short, format-following drafts in 2 of 2 smoke cases each (qwen3:8b reused the example's wording).
- Two harness defects were found and fixed by the smoke runs: a truncated draft was scored as a pass (now `TRUNCATED` and `REASONING_LEAKED` are case violations), and JSON `\b` escapes turned into backspace characters in regexes (now guarded by a test).

## To obtain model-selection evidence later

The harness is ready; only compute is missing. On a machine with a GPU or enough RAM to hold the model, run:

```bash
python -m backend.ceo_eval run --models <model ...> --suites probe classifier composer --run-id <id>
# DB latency separately, against a scratch Postgres only (it seeds and purges a synthetic tenant):
python -m backend.ceo_eval run --suites latency --db-ok --merge-into docs/evaluation/ceo-runs/<id>.json
python -m backend.ceo_eval report docs/evaluation/ceo-runs/<id>.json --output docs/evaluation/ceo-eval-baseline-<id>.md
```

Model quality and infrastructure latency must be read separately: latency on this CPU host says nothing about the model on suitable hardware. Do not select a production model on speed alone or accuracy alone; the report shows both.

## Addendum (2026-10-08): live smoke is not a baseline

A single end-to-end smoke of the production CEO path against `qwen3.5:4b` was run after B3 (see `docs/planning/ceo-build-status.md`, "B3.1"). It verifies the integration seam only. It does not change anything above: **there is still no baseline, no pass bar and no model comparison**, and no model has been selected.
