"""Brain 2 — statistical anomaly detection. docs/specs/anomaly-detection.md.

A small, pure, statistics layer sitting between Brain 1 (deterministic money arithmetic,
`calc_engine.formulas`/`calc_engine.api`) and Brain 3 (LLM narration, owned elsewhere). This
subpackage is deliberately NOT nested inside `calc_engine.formulas` (D1) — it is not money
arithmetic, and its determinism contract is weaker by design (§6.7): a flag is reproducible
for a *fixed* `(series, config_version, as_of_date)` tuple, not part of `canonical_data_version`.

No function in this subpackage performs a database query of any kind (B8/AC12) — every
function here accepts an already-assembled `Sequence[SeriesPoint]` (and, where a threshold
is required, an already-resolved config mapping) supplied by its caller. Config resolution
lives in `calc_engine.repositories.config_repo.resolve_anomaly_detection_config`, a separate
concern (§8 rule 4/5).
"""

from __future__ import annotations
