"""Standalone artefacts: DESCRIPTION, BULLETS, KEYWORDS, BACKEND_TERMS, HASHTAGS (spec §8.1.1, AC26).

Each is its own artefact with its own prompt, validation and unit; none touches a pack row.
DESCRIPTION / BULLETS / KEYWORDS / BACKEND_TERMS are grounded on an approved or seller-supplied
title and validated against their marketplace's resolved constraint. BACKEND_TERMS is Amazon only.

HASHTAGS (decisions 8, spec C12/§6.6) is a separate marketing artefact: NO marketplace format
constraint is applied, NO title grounding, and its size limit is the REQUIRED configuration value
`hashtag_set_size` passed in by the caller (a maximum; absent configuration means the caller returns
CONFIG_MISSING before reaching here). It always carries the label that it is not a listing field.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from slim_cmo.constraints import ResolvedConstraint
from slim_cmo.generation.engine import Evaluation, classify_failure, run_attempts
from slim_cmo.generation.facts import FactContext, is_thin_input
from slim_cmo.generation.outcomes import Delivered, Failed, Outcome
from slim_cmo.generation.parse import Parsed
from slim_cmo.generation.prompts import component_prompt, hashtag_prompt, prompt_facts
from slim_cmo.generation.provider import LlmProvider
from slim_cmo.generation.safety import feedback_lines, ineligible_names, prose_findings, rule_ids
from slim_cmo.types import Marketplace, OutputType
from slim_cmo.listing.basis import rules_basis_of
from slim_cmo.listing.context import ListingContext, untraceable
from slim_cmo.validators import (
    Violation,
    ViolationCode,
    check_backend_terms,
    check_bullets,
    check_description,
    check_hashtags,
    check_keywords,
)

HASHTAG_LABEL = "marketing suggestions - not a listing field on any marketplace"


def _meta(c: ResolvedConstraint, marketplace: Marketplace, attempts: int, facts: FactContext) -> dict[str, Any]:
    return {
        "marketplace": marketplace.value,
        "constraint": c.row.cite(),
        "rules_basis": rules_basis_of(c.row),
        "count_rule": c.row.count_rule.value if c.row.count_rule and rules_basis_of(c.row) == "VERIFIED" else None,
        "unverified_limits": list(c.unverified_limits),
        "attempts": attempts,
        "excluded_facts": list(facts.excluded),
        "thin_input": is_thin_input(facts),
    }


def _run_component(
    *,
    kind: OutputType,
    key: str,
    key_type: type,
    provider: LlmProvider,
    model: str,
    marketplace: Marketplace,
    resolved: ResolvedConstraint,
    facts: FactContext,
    anchor_title: str,
    retry_bound: int,
    check: Callable[[Any], tuple[Any, tuple[Violation, ...], list[tuple[str, str]]]],
    build: Callable[[Any, dict[str, Any]], tuple[dict[str, Any], str]],
    prompt_kind: str,
    what: str,
    listing: ListingContext | None = None,
) -> Outcome:
    pf = prompt_facts(facts)
    extra = listing.prompt_extra() if listing is not None else None
    done: dict[str, tuple[dict[str, Any], str] | None] = {"v": None}

    def make_prompt(feedback: tuple[str, ...]) -> str:
        return component_prompt(
            kind=prompt_kind, marketplace=marketplace, facts=pf, anchor_title=anchor_title,
            constraint=resolved.row, feedback=feedback, listing_extra=extra,
        )

    def evaluate(parsed: Parsed) -> Evaluation:
        assert parsed.payload is not None
        value, violations, items = check(parsed.payload[key])
        prose = prose_findings(items, facts, extra_allowed=[anchor_title])
        if not violations and not prose:
            done["v"] = build(value, {})
            return Evaluation(done=True)
        return Evaluation(
            done=False, feedback=feedback_lines(violations, prose),
            violation_ids=rule_ids(violations, prose), ineligible_names=ineligible_names(prose),
        )

    log = run_attempts(
        provider=provider, model=model, retry_bound=retry_bound, make_prompt=make_prompt,
        content_types={key: key_type}, evaluate=evaluate, already_done=lambda: done["v"] is not None,
    )
    if done["v"] is None:
        return Failed(kind, classify_failure(log, what=what), log.attempts)
    structured, text = done["v"]
    structured.update(_meta(resolved, marketplace, log.attempts, facts))
    return Delivered(kind, structured, text, log.attempts)


def generate_description(
    *, provider: LlmProvider, model: str, marketplace: Marketplace, resolved: ResolvedConstraint,
    facts: FactContext, anchor_title: str, retry_bound: int,
) -> Outcome:
    def check(raw: Any) -> tuple[Any, tuple[Violation, ...], list[tuple[str, str]]]:
        r = check_description(raw, resolved.row, allowed_context=facts.allowed_context)
        return r.text, r.violations, [("description", r.text)]

    return _run_component(
        kind=OutputType.DESCRIPTION, key="description", key_type=str, provider=provider, model=model,
        marketplace=marketplace, resolved=resolved, facts=facts, anchor_title=anchor_title, retry_bound=retry_bound,
        check=check, build=lambda v, _m: ({"description": v, "description_type": resolved.row.description_type}, v),
        prompt_kind="DESCRIPTION", what="the description",
    )


def generate_bullets(
    *, provider: LlmProvider, model: str, marketplace: Marketplace, resolved: ResolvedConstraint,
    facts: FactContext, anchor_title: str, retry_bound: int,
) -> Outcome:
    def check(raw: Any) -> tuple[Any, tuple[Violation, ...], list[tuple[str, str]]]:
        r = check_bullets(raw, resolved.row, allowed_context=facts.allowed_context)
        return list(r.items), r.violations, [(f"bullets[{i}]", t) for i, t in enumerate(r.items)]

    return _run_component(
        kind=OutputType.BULLETS, key="bullets", key_type=list, provider=provider, model=model,
        marketplace=marketplace, resolved=resolved, facts=facts, anchor_title=anchor_title, retry_bound=retry_bound,
        check=check, build=lambda v, _m: ({"bullets": v}, "\n".join(v)), prompt_kind="BULLETS", what="the bullet points",
    )


def generate_keywords(
    *, provider: LlmProvider, model: str, marketplace: Marketplace, resolved: ResolvedConstraint,
    facts: FactContext, anchor_title: str, retry_bound: int,
) -> Outcome:
    def check(raw: Any) -> tuple[Any, tuple[Violation, ...], list[tuple[str, str]]]:
        r = check_keywords(raw, resolved.row, allowed_context=facts.allowed_context)
        return list(r.items), r.violations, [(f"keywords[{i}]", t) for i, t in enumerate(r.items)]

    return _run_component(
        kind=OutputType.KEYWORDS, key="keywords", key_type=list, provider=provider, model=model,
        marketplace=marketplace, resolved=resolved, facts=facts, anchor_title=anchor_title, retry_bound=retry_bound,
        check=check, build=lambda v, _m: ({"keywords": v}, ", ".join(v)), prompt_kind="KEYWORDS", what="the keywords",
    )


def generate_backend_terms(
    *, provider: LlmProvider, model: str, marketplace: Marketplace, resolved: ResolvedConstraint,
    facts: FactContext, anchor_title: str, retry_bound: int, listing: ListingContext | None = None,
) -> Outcome:
    if marketplace is not Marketplace.AMAZON:
        raise ValueError("backend search terms exist only for Amazon")
    vocab = listing.keyword_vocab if listing is not None and listing.keyword_vocab else None

    def check(raw: Any) -> tuple[Any, tuple[Violation, ...], list[tuple[str, str]]]:
        r = check_backend_terms(raw, resolved.row, allowed_context=facts.allowed_context, allow_unstated_cap=rules_basis_of(resolved.row) == "UNVERIFIED")
        loose = tuple(Violation(ViolationCode.NOT_TRACEABLE, f"backend_terms[{i}]") for i in untraceable(r.terms, vocab)) if vocab is not None else ()
        return r, (*r.violations, *loose), [(f"backend_terms[{i}]", t) for i, t in enumerate(r.terms)]

    def build(r: Any, _m: dict[str, Any]) -> tuple[dict[str, Any], str]:
        return (
            {"backend_terms": list(r.terms), "joined": r.joined, "byte_count": r.byte_count,
             "max_bytes": resolved.row.backend_terms_max_bytes},
            r.joined,
        )

    return _run_component(
        kind=OutputType.BACKEND_TERMS, key="terms", key_type=list, provider=provider, model=model,
        marketplace=marketplace, resolved=resolved, facts=facts, anchor_title=anchor_title, retry_bound=retry_bound,
        check=check, build=build, prompt_kind="BACKEND_TERMS", what="the backend search terms", listing=listing,
    )


def generate_hashtags(
    *, provider: LlmProvider, model: str, facts: FactContext, hashtag_set_size: int, retry_bound: int,
) -> Outcome:
    if type(hashtag_set_size) is not int or hashtag_set_size < 1:
        raise ValueError("hashtag_set_size must be a positive integer (required configuration)")
    pf = prompt_facts(facts)
    done: dict[str, list[str] | None] = {"v": None}

    def make_prompt(feedback: tuple[str, ...]) -> str:
        return hashtag_prompt(facts=pf, set_size=hashtag_set_size, feedback=feedback)

    def evaluate(parsed: Parsed) -> Evaluation:
        assert parsed.payload is not None
        r = check_hashtags(parsed.payload["hashtags"], allowed_context=facts.allowed_context)
        violations = list(r.violations)
        if len(r.items) > hashtag_set_size:
            violations.append(Violation(ViolationCode.TOO_MANY, "hashtags", f"{len(r.items)}>{hashtag_set_size}"))
        prose = prose_findings([(f"hashtags[{i}]", t.lstrip("#")) for i, t in enumerate(r.items)], facts)
        if not violations and not prose:
            done["v"] = list(r.items)
            return Evaluation(done=True)
        return Evaluation(
            done=False, feedback=feedback_lines(violations, prose),
            violation_ids=rule_ids(violations, prose), ineligible_names=ineligible_names(prose),
        )

    log = run_attempts(
        provider=provider, model=model, retry_bound=retry_bound, make_prompt=make_prompt,
        content_types={"hashtags": list}, evaluate=evaluate, already_done=lambda: done["v"] is not None,
    )
    tags = done["v"]
    if tags is None:
        return Failed(OutputType.HASHTAGS, classify_failure(log, what="the hashtag suggestions"), log.attempts)
    structured: dict[str, Any] = {
        "hashtags": tags, "label": HASHTAG_LABEL, "listing_field": False,
        "max_set_size": hashtag_set_size, "attempts": log.attempts, "excluded_facts": list(facts.excluded),
    }
    return Delivered(OutputType.HASHTAGS, structured, " ".join(tags), log.attempts)
