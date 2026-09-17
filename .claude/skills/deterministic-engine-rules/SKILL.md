---
name: deterministic-engine-rules
description: The hard rule that money math never runs through an LLM in Metrion — with concrete before/after examples. Use before writing or reviewing any code path where an LLM (CEO's classifier/composer, or any agent) touches a figure that is or derives from money.
---

# The rule

From `CLAUDE.md`: **any calculation that touches money lives in the deterministic engine (Brain 1) — Python and SQL, unit-tested, no LLM in the path.** An LLM may narrate, explain, rank-by-judgement, or caveat a figure. It may never originate one, re-derive one, or sum a set of them.

This isn't style guidance — it's the architectural boundary the whole product rests on. If you're about to write arithmetic on money anywhere outside the engine, stop; it belongs in the engine.

## Example 1 — composing an answer from engine output

**Before (wrong):** CEO's LLM receives three `reconciliation_exception` rows and writes: *"Your total leak across these three issues is ₹4,820."* — the model added the numbers.

**After (correct):** Brain 1 (or CFO's own deterministic aggregate) computes the sum as an `engine_result_ref`-backed figure first. CEO's synthesis call is handed that pre-computed total and only narrates it: *"Your total leak is ₹4,820 across three issues [ref]."* Per `ceo-agent-orchestration.md` §6.5: "Every number in that answer is copied from an `engine_result_ref`... never generated, rounded, or adjusted by the model."

## Example 2 — GST rate lookup

**Before (wrong):** An agent asks the LLM to "figure out the likely GST rate" for a product from its title and applies that rate directly to a calculation.

**After (correct):** The GST Applicability Lookup is a structurally isolated research feature. An LLM may extract and structure a *cited* result (`source_url`, `retrieved_at` mandatory), but the result is stored `PROVISIONAL` and **never enters a calculation automatically** — it requires explicit seller acceptance, which creates a labelled manual input first (`deterministic-engine.md` §8.4, rules L1–L7, especially L7: "An LLM may extract and structure the result. It may not originate a rate.").

## Example 3 — a "missing" input

**Before (wrong):** COGS is missing for a SKU, so the model estimates a plausible cost from category averages and quietly fills it in so the margin calculation completes.

**After (correct):** A missing input is `UNAVAILABLE`, flagged, never a silent default (`CLAUDE.md`, `deterministic-engine.md` §7). The engine reports the gap explicitly rather than producing a number built on a guess; if the seller supplies the real COGS, it enters as a tracked manual input (§7.1) with its own confidence level — never as invisible engine behavior.

## Quick check before writing code

- Is this touching `paise`, a fee, a margin, a profit figure, or anything derived from one? → it belongs in the engine, `BIGINT` paise, no floats.
- Is an LLM about to sum, round, average, or re-derive a number it was handed? → stop, that's the violation.
- Is a number missing? → `UNAVAILABLE` and flagged, never zero, never estimated silently.
