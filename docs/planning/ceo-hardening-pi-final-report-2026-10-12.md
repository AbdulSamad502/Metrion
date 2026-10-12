# Report A: CEO hardening, public idempotency, leg deadlines, PI evaluation (2026-10-12)

Branch `feat/ceo-foundation` (HEAD `2b954c9`, nothing committed). Scratch PostgreSQL port 5544 only; the development database (5432) was never touched. No paid model call, no external side effect.

## 1. Status

| Item | Status | Evidence |
|---|---|---|
| Fix 1 compound requests | FIXED (rule-based; documented limit: a clause no rule recognises is reported as not handled, never guessed) | `test_ceo_hardening_compound`, `test_ceo_compound` |
| Fix 2 action selection / routing (incl. named-party guard) | FIXED | `test_ceo_hardening_routing*`, `test_ceo_campaign_routing_e2e` |
| Fix 3 resend idempotency, public `clientRequestId` | FIXED (frontend, API, backend, stored replay) | `test_ceo_client_request_id_api` (23 with the verification file) |
| Fix 4 abandoned-RUNNING recovery | FIXED: dead process by ownership (`INTERRUPTED`); live hang by the new deadline policy below | `test_ceo_hardening_recovery` (incl. real process death), `test_ceo_leg_deadline` |
| Fix 5 classifier prompt isolation | FIXED | `test_ceo_hardening_prompt_e2e`, `test_ceo_prompt_boundaries` |
| `ci.research_now` | still intentionally unwired (registry lists it UNWIRED) | registry dump |
| PI image extraction | PARTIALLY FIXED: no accuracy gain demonstrated; candidate prompt rejected | section 4 |

## 2. Public `clientRequestId`
Optional UUID on `POST /investigations/{id}/turns` (camelCase only; `client_request_id`, `requestKey`, `request_key` are ignored). The frontend makes one id per logical submission, **reuses it only when the identical send is repeated after it got no answer**, and makes a new one for any other send (including identical text after an answered send). Server: the id becomes the existing internal `request_key` stored in the turn's `classifier_result` (no migration). Same id + same text: stored outcome returned (`replayed: true`), nothing written or run. Same id + different text: `409 CLIENT_REQUEST_ID_REUSED`. Malformed: `422`. No id: unchanged. Scoped to investigation inside tenant (another tenant gets 404 and learns nothing).
Verified: sequential replay; new id with identical text runs again; conflicting reuse writes nothing; simultaneous duplicates run the action once (per-investigation advisory lock); retry while the original runs is `409 TURN_IN_PROGRESS` with nothing written (or waits and replays when `CEO_TURN_LOCK_WAIT_SECONDS` is set); failed original replays as failed and is not re-run (a deliberate new submission can retry); failure before anything was recorded lets the retry run; **real process death** (child killed mid-leg) then retry with the same id returns the recorded interruption and runs nothing. Frontend: 4 unit tests of the id and fingerprint, 3 component tests of reuse versus new id, request-contract tests.
**Not claimed:** exactly-once external effects. A recorded leg is never re-run for the same id; an interrupted leg may or may not have taken effect, and the system says so rather than "did not happen".

## 3. Hung-leg deadlines and recovery
- `CEO_LEG_TIMEOUT_SECONDS` (soft) is now enforced for a turn with one leg as well (it used to run inline with no deadline). A leg inside it is left running; its finding lands as before.
- `CEO_LEG_ABANDON_SECONDS` (optional hard deadline, never shorter than the soft one): a still-open leg of an already-answered turn is settled FAILED with `TIMED_OUT_REPEATABLE` (read-only/deterministic, no external call or meter: safe to ask again) or `TIMED_OUT_UNCERTAIN` (outside call, meter, generated artefact, recorded choice, or unclassified: may still be running or may already have taken effect; never re-run; never described as "did not happen"). A finding and a plain `SYSTEM_NOTE` record it. Python cannot cancel a thread, so nothing is ever reported "safely cancelled".
- Guarded writes: a late completion cannot overwrite the timeout/recovery state (and writes no contradicting finding; the caller still sees its return value); an unguarded `finish_run` also cannot overwrite `INTERRUPTED`/`TIMED_OUT*`; concurrent settlers give one winner; repeats change nothing; completed sibling legs and findings are preserved; another tenant's legs are never touched.
- Both variables are **unset by default**. No value is chosen: there is no real runtime data (the dev DB is off limits) and the only evidence is config docstrings (CEO model 15-200 s per call, vision 13-160 s) and my vision runs (60-140 s per image, one 900 s timeout). Suggested method for the owner: take p99 of `finished_at - started_at` per `agent_run.trigger_ref` from real runs, set hard >= soft + the longest bounded external call of the slowest uncertain class.
- Evidence labels: 19 simulated tests (blocked handler stands in for a hung call; crafted rows for old legs) and 1 real process-death test (`test_process_death_is_still_an_interruption_not_a_timeout`) in `test_ceo_leg_deadline.py` (20).
- Open decisions (spec 6.42): the two values; showing a late result as a labelled "late result"; refusing a second effectful submission while an earlier one is unresolved.

## 4. PI evaluation (real model: llava via local Ollama; no inference was repeated)
Re-scored all 8 combinations (full and 12-image subset x baseline/candidate replies x original/current extractor) offline: identical to the stored score files. Full set, 34 priced images (the 2 excluded have the price cropped out, scored as unreadable handling):

| | price exact /34 | wrong | missed | false extraction /220 | extraction failures /36 |
|---|---|---|---|---|---|
| A baseline prompt, original extractor | 8 | 26 | 0 | 98 | 0 |
| B baseline replies, validator | 8 | 26 | 0 | 89 | 0 |
| C candidate prompt, original extractor | 12 | 20 | 2 | 92 | 3 |
| D candidate replies, validator | 12 | 20 | 2 | 71 | 3 |

Subset (12 images, 11 priced): A 1, B 1, C 3, D 3 exact; false extraction 40, 38, 17, 14 of 74. MRP exact 0/32 (A) vs 1/32 (C) but MRP wrong 2 vs 18. Timeout accounting: C/D have 3 failures: 2 unparseable pseudo-XML replies on priced images (counted missed) and 1 900 s timeout on a cropped image (an extraction failure, not "handled as unknown"): genuine unreadable handling is 0 of 2 (A/B) and 0 of 1 answered (C/D). Paired test of the +4: both right 5, only baseline 3, only candidate 7, exact McNemar p = 0.34 (one run per condition: not distinguishable from noise).
**Decisions:** candidate prompt REJECTED (artifacts preserved). Validator rules, audited per rule against the labelled replies: zero rating (0 correct / 1 wrong / 3 unsupported removed on baseline; 0/0/6 candidate), zero rating_count (0/1/2; 0/0/6), discount <= 0 or >= price (0/0/4; 0/0/9): **kept**, no correct value lost. `price > MRP`: never fired (0 of 3 baseline and 0 of 20 candidate replies with both fields), and when it would fire the MRP is the field most often misread: **disabled by default** (`OPTIONAL_RULES`, opt-in per call; tests updated to say so). Percent cross-check: removed earlier, absent from production code. Real-model accuracy improvement: **none demonstrated**; safety improvement: placeholder values no longer stored, no correct value lost. Mocked tests: `test_vision_validation.py` and `test_vision_extractor.py` (no model). Real-model: only the scripts.

## 5. Commands, exit codes, results (after the last code change)
| Suite | Command (cwd) | Exit | Result |
|---|---|---|---|
| backend unit | `pytest tests/unit -q` (backend) | 0 | 4350 passed, 6 xfailed |
| backend integration (scratch 5544) | `pytest tests/integration -v` (backend) | 0 | **1866 passed, 3 skipped, 1 xfailed** in 46:30 |
| competitor-intelligence | `pytest tests -q` | 0 | 337 passed |
| product-intelligence | `pytest tests -q` | 0 | 279 passed |
History: a first full integration run had 1 failure (`test_agent_run_guarded_transitions::test_a_leg_that_finishes_after_its_row_was_settled_does_not_overwrite_it`, an existing test pinning "the caller still sees what its call returned"); root cause was my dispatch change returning FAILED to the caller; fixed to keep the return value while writing no finding; rerun green. A later run I killed at 42% was not hung: running vitest/tsc/browser at the same time stretched the 700-turn test (see the integration runbook); the clean rerun finished normally.
Frontend commands are in Report B.

## 6. Remaining limitations and blocked decisions
Deadline values (owner, needs runtime data); late-result display; refusing a second effectful submission; real seller screenshots and a different vision model/OCR for the digit-loss problem (dependency or provider decision); approval workflow (B1/B2) unchanged and out of scope.
Safety: no commit or push; both stashes present; `ci.research_now` unwired; approval gates, authorization and tenant isolation unchanged (their tests are inside the green integration run); no financial-campaign work; marketing code untouched.
