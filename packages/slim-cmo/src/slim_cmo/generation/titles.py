"""Title-set generation (spec §6.4 step 1, AC8, AC9; P3 decision 1).

* One call chain per marketplace, with that marketplace's own resolved constraint.
* Every candidate passes the prose check (invented numbers, ineligible values, forbidden content)
  and then `validators.evaluate_title_set` (length, duplicates, forbidden, count) - the model never
  reports its own length; `char_count` and `constraint_check` come from the evaluator.
* Valid options accumulate across attempts; each retry asks only for the shortfall. Accepted texts
  are re-submitted with the new candidates so de-duplication and ranks stay consistent.
* Zero valid options after the retry bound -> FAILED. Fewer than `title_option_count` but at least
  one -> DELIVERED, short and labelled, never padded (decision 1: COMPLETE, one unit).
"""

from __future__ import annotations

from slim_cmo.constraints import ResolvedConstraint
from slim_cmo.generation.engine import Evaluation, classify_failure, run_attempts
from slim_cmo.generation.facts import FactContext, is_thin_input
from slim_cmo.generation.outcomes import Delivered, Failed, Outcome
from slim_cmo.generation.parse import Parsed
from slim_cmo.generation.prompts import prompt_facts, title_prompt
from slim_cmo.generation.provider import LlmProvider
from slim_cmo.generation.safety import ProseFinding, feedback_lines, ineligible_names, prose_findings, rule_ids
from slim_cmo.textnorm import clean_generated_text
from slim_cmo.listing.basis import rules_basis_of
from slim_cmo.types import Marketplace, OutputType
from slim_cmo.validators import AcceptedOption, TitleSetEvaluation, evaluate_title_set

SHORT_SET_LABEL = "Fewer title options than the marketplace rule asks for passed the checks; none were invented to fill the gap."


def generate_title_set(
    *,
    provider: LlmProvider,
    model: str,
    marketplace: Marketplace,
    resolved: ResolvedConstraint,
    facts: FactContext,
    retry_bound: int,
) -> Outcome:
    c = resolved.row
    expected = c.title_option_count
    if expected is None:  # the resolver guarantees this; reaching here is a caller bug
        raise ValueError("title_option_count is required to generate a title set")
    pf = prompt_facts(facts)
    accepted_texts: list[str] = []
    state: dict[str, TitleSetEvaluation | None] = {"last": None}

    def make_prompt(feedback: tuple[str, ...]) -> str:
        return title_prompt(
            marketplace=marketplace, facts=pf, constraint=c,
            count=max(expected - len(accepted_texts), 1), existing=tuple(accepted_texts), feedback=feedback,
        )

    def evaluate(parsed: Parsed) -> Evaluation:
        assert parsed.payload is not None
        survivors: list[object] = []
        prose: list[ProseFinding] = []
        for i, raw in enumerate(parsed.payload["titles"]):
            if isinstance(raw, str):
                found = prose_findings([(f"titles[{i}]", clean_generated_text(raw))], facts)
                if found:
                    prose.extend(found)
                    continue
            survivors.append(raw)  # non-strings flow on so the evaluator reports WRONG_TYPE
        ev = evaluate_title_set([*accepted_texts, *survivors], c, allowed_context=facts.allowed_context)
        state["last"] = ev
        accepted_texts[:] = [o.text for o in ev.accepted]
        violations = [v for r in ev.rejected for v in r.violations]
        return Evaluation(
            done=ev.complete,
            feedback=feedback_lines(violations, prose),
            violation_ids=rule_ids(violations, prose),
            ineligible_names=ineligible_names(prose),
        )

    log = run_attempts(
        provider=provider, model=model, retry_bound=retry_bound, make_prompt=make_prompt,
        content_types={"titles": list}, evaluate=evaluate, already_done=lambda: len(accepted_texts) >= expected,
    )
    ev = state["last"]
    if ev is None or not ev.accepted:
        return Failed(OutputType.TITLE_SET, classify_failure(log, what="the title set"), log.attempts)
    options: tuple[AcceptedOption, ...] = ev.accepted
    short = len(options) < expected
    structured = {
        "marketplace": marketplace.value,
        "expected_option_count": expected,
        "delivered_option_count": len(options),
        "short": short,
        "short_label": SHORT_SET_LABEL if short else None,
        "constraint": c.cite(),
        "rules_basis": rules_basis_of(c),
        "count_rule": c.count_rule.value if c.count_rule and rules_basis_of(c) == "VERIFIED" else None,
        "unverified_limits": list(resolved.unverified_limits),
        "attempts": log.attempts,
        "excluded_facts": list(facts.excluded),
        "thin_input": is_thin_input(facts),
    }
    return Delivered(OutputType.TITLE_SET, structured, None, log.attempts, options)

