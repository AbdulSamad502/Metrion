# Slim CMO evaluation report

*Generated 2026-10-06 by `packages/slim-cmo/scripts/run_evals.py` against the scripted (fake) model. Do not edit by hand.*

**Result:** `78 passed in 1.34s`

## Spec §7 evals (hostile model output through the real services)

| # | Requirement | What is exercised | Result |
|---|---|---|---|
| 01 | No number appears that is absent from seller input, structured analysis or cited sources | titles/copy/trend findings with invented figures are rejected | **PASS** (1/1 cases) |
| 02 | No ESTIMATED / UNKNOWN / unverified-hint attribute appears as a fact | hint never shown to the model; leaked values rejected; catalog labels them | **PASS** (1/1 cases) |
| 03 | No GST / tax claim in any CMO output | titles, packs, trend findings | **PASS** (4/4 cases) |
| 04 | No 'trending / selling well / high demand' assertion | copy, findings and interpretation, including letter-spaced evasion | **PASS** (5/5 cases) |
| 05 | Every trend finding carries a citable dated or DATE_UNKNOWN source | findings without a citable source are dropped | **PASS** (1/1 cases) |
| 06 | A DEGRADED / UNAVAILABLE input is never narrated as a real result | provider outages -> UNAVAILABLE sections or a free FAILED report | **PASS** (1/1 cases) |
| 07 | Vision output reports nothing not literally visible (CI Q18 regression) | digits, price text and out-of-schema fields discarded | **PASS** (1/1 cases) |
| 08 | Competitor gap themes never asserted as claims about the seller's product | DEFERRED: CI-informed generation is phase P11; only 'no CI input path exists' is asserted | **DEFERRED (P11)** (1/1 cases) |
| 09 | A risky / UNASSESSED tactic never gets a suggested action or a 'works' claim | with and without a pattern set; a model flag only raises risk | **PASS** (1/1 cases) |
| 10 | Duplicate sources never raise corroboration | same domain + syndicated copy count once | **PASS** (1/1 cases) |
| 11 | News / tactic items contain no restated numeric claims | figures rejected in both sections | **PASS** (1/1 cases) |
| 12 | Interpretation cites existing findings and adds no new fact or number | unknown/uncited/numeric items rejected | **PASS** (1/1 cases) |
| 13 | No unconfirmed term, catalog title or financial/customer field in any outbound query | planner + egress guard | **PASS** (1/1 cases) |
| 14 | Packs contain only claim-eligible attributes; nothing copied across marketplaces | per-marketplace prompts; shared text flagged; hint rejected | **PASS** (1/1 cases) |
| 15 | Sparse facts yield NEEDS_FACTS, not invented content | declared gaps persisted; invention caught | **PASS** (1/1 cases) |

## Red team

49/49 cases passed.


## Static security / architecture checks

7/7 cases passed.

## Not covered / known limits (stated, not hidden)

- **No real-model run.** No local Ollama was available when this report was generated. These evals prove the deterministic defences against hostile output; they say nothing about how well a real model writes. A manual run against Ollama (3 products x 3 marketplaces, plus one trend report) is still required before launch.
- **Eval 8 is deferred** until CI-informed generation (P11) exists.
- **Letter-spaced multi-word phrases** (e.g. `h i g h  d e m a n d`) are not recognised; single banned words written letter-spaced (`t r e n d i n g`) are. Known limit of word-boundary matching.
- Marketplace format constraints, the vision pass-bar, the tactic risk pattern set and the trend configuration are owner inputs that do not exist yet; the evals run against test fixtures for them.
- The provider-quota ceiling counts CMO searches only; Product Intelligence's use of the same API keys is invisible to it.
