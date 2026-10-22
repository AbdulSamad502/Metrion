---
name: "source-command-status"
description: "Summarize what's built against the current MUST-HAVE scope"
---

# source-command-status

Use this skill when the user asks to run the migrated source command `status`.

## Command Template

1. **Locate the authoritative scope document — don't assume.** Check `docs/planning/` for anything named or shaped like a MUST-HAVE / V1 scope list before treating anything else as authoritative. As of the last check, no file is literally titled that; `docs/planning/phase-1-readiness-review.md` §1 (Resolved decisions) and its Verdict section are the current decisions-of-record per `AGENTS.md`'s own pointer. If a more specific scope doc has since been added, use that instead and say so.
2. Cross-reference each spec in `docs/specs/` against what actually exists in the codebase — implementation and tests, not just files with matching names.
3. Report per spec: **not started / spec only / partial / done** (acceptance criteria actually met, not just code present).
4. Flag anything implemented without a backing spec — that's a process violation per `AGENTS.md`, not extra credit.
