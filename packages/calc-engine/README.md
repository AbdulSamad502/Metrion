# calc-engine

Metrion's deterministic engine (Brain 1). Implements the formulas and contracts defined in
[`docs/specs/deterministic-engine.md`](../../docs/specs/deterministic-engine.md).

**Hard rule (CLAUDE.md):** no LLM import of any kind belongs in this directory. Money math is
Python/SQL only, unit-tested, deterministic. Enforced by the pre-commit hook at
[`.claude/hooks/pre-commit`](../../.claude/hooks/pre-commit).

Repo layout decision recorded in `docs/planning/phase-1-readiness-review.md` item 2.5.
