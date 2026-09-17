---
description: Create or update a spec for a named feature before implementation begins
argument-hint: <feature-name>
---

**Refuse and stop** if `$ARGUMENTS` names no feature — ask which feature before doing anything else.

1. Check whether the feature already maps to a file in `docs/specs/` (e.g. "whatsapp" → `docs/specs/whatsapp-integration.md`). If it exists, this is an update — read it fully first, don't overwrite blind.
2. Read `CLAUDE.md` for the mandated spec section template and the hard rules (money math only in the deterministic engine; every tenant table RLS-scoped).
3. Read `docs/planning/phase-1-readiness-review.md` for decisions of record relevant to this feature, plus `docs/specs/auth.md` and `docs/specs/deterministic-engine.md` for the constraints every spec must respect.
4. Never infer behavior from code or mockups — only from specs and the readiness review. Anything genuinely undecided goes in the spec's own **Explicit open questions**, never filled with a guess.
5. Write or update the file in `docs/specs/`. If this surfaces a contradiction with another existing spec, list it and ask before touching that other file.
