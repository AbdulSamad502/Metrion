---
description: Code review pass for Metrion's three core invariants
argument-hint: "[path or PR — defaults to current diff]"
---

Review `$ARGUMENTS` (or the current diff if empty) for exactly these three things, in this order. Do not restate the whole diff — report findings only.

1. **No money calculation outside the deterministic engine.** Any code outside the engine's own module that computes, re-derives, sums, or rounds a money/paise/fee/margin/profit figure — rather than narrating a value the engine already produced — is a finding. Reference: `CLAUDE.md` "The hard rule," `docs/specs/deterministic-engine.md` §4 (Determinism contract).
2. **Tenant isolation on any new tenant-owned table.** Every new table needs `tenant_id` plus `ENABLE`/`FORCE ROW LEVEL SECURITY` and the `tenant_isolation` policy, matching the exact pattern in `docs/specs/auth.md` §7.3 — not a one-off variant.
3. **No contradiction against `docs/specs/`.** Check whether the change asserts, implements, or documents something a spec already resolves differently. A genuine spec gap gets flagged, never silently filled in code.

Report by severity. If nothing is wrong in a category, say so briefly — don't pad the report.
