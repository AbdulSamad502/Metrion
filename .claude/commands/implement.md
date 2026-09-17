---
description: Implement code against an existing spec
argument-hint: <feature-name>
---

1. Resolve `$ARGUMENTS` to a spec file in `docs/specs/`. **If no matching spec exists, refuse to proceed** and tell the user to run `/spec-feature <feature-name>` first — do not improvise the spec inline.
2. Read the spec fully. Its **Data model**, **Core rules**, **Authorization and security**, **Edge cases**, **Acceptance criteria**, and **Test scenarios** sections are binding, not suggestions.
3. Before writing any code that touches money, re-read `CLAUDE.md`'s hard rule: all such arithmetic lives in the deterministic engine (Brain 1) — Python/SQL, unit-tested, no LLM in the path.
4. If the spec introduces a tenant-owned table, implement `tenant_id` and RLS following the exact pattern in `docs/specs/auth.md` §7.3 — not a one-off variant.
5. Implement to the spec's acceptance criteria and test scenarios directly. If the code needs something the spec doesn't define, stop and say so — that belongs in the spec first, not invented while coding.
