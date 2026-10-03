"""Marketplace-specific listing copy pack (spec §6.4 step 4, AC10, AC23, AC25).

* Inputs are ONLY: the approved (or seller-supplied) title for THIS marketplace, THIS marketplace's
  resolved constraint, and claim-eligible facts. No other marketplace's output exists in scope.
* ATOMIC: delivered only if description, bullets AND keywords all pass `check_listing_copy` and
  the prose check. The whole pack is regenerated on any violation; fields from different attempts
  are never stitched together. No partial pack is ever returned.
* Flipkart's structured attribute fields cannot be filled: no field taxonomy is verified (Q5). The
  pack says so explicitly (`structured_fields.state = NEEDS_SELLER_INPUT`) instead of pretending.
* Known limitation (decision 12): semantic contradiction with the approved title is not detected.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from slim_cmo.claims import shared_text_findings
from slim_cmo.constraints import ResolvedConstraint
from slim_cmo.generation.engine import Evaluation, classify_failure, run_attempts
from slim_cmo.generation.facts import FactContext
from slim_cmo.generation.outcomes import Delivered, Failed, Outcome
from slim_cmo.generation.parse import Parsed
from slim_cmo.generation.prompts import pack_prompt, prompt_facts
from slim_cmo.generation.provider import LlmProvider
from slim_cmo.generation.safety import feedback_lines, ineligible_names, prose_findings, rule_ids
from slim_cmo.types import Marketplace, OutputType
from slim_cmo.validators import ListingCopyCheck, check_listing_copy

STRUCTURED_FIELDS_UNVERIFIED = {
    "state": "NEEDS_SELLER_INPUT",
    "reason": "the marketplace's required attribute-field list for this category is not verified, so no structured fields were filled or enforced",
    "fields": [],
}


def generate_listing_copy(
    *,
    provider: LlmProvider,
    model: str,
    marketplace: Marketplace,
    resolved: ResolvedConstraint,
    facts: FactContext,
    anchor_title: str,
    retry_bound: int,
) -> Outcome:
    c = resolved.row
    pf = prompt_facts(facts)
    delivered: dict[str, ListingCopyCheck | None] = {"pack": None}

    def make_prompt(feedback: tuple[str, ...]) -> str:
        return pack_prompt(marketplace=marketplace, facts=pf, anchor_title=anchor_title, constraint=c, feedback=feedback)

    def evaluate(parsed: Parsed) -> Evaluation:
        assert parsed.payload is not None
        p = parsed.payload
        check = check_listing_copy(p["description"], p["bullets"], p["keywords"], c, allowed_context=facts.allowed_context)
        items = [("description", check.description)]
        items += [(f"bullets[{i}]", t) for i, t in enumerate(check.bullets)]
        items += [(f"keywords[{i}]", t) for i, t in enumerate(check.keywords)]
        prose = prose_findings(items, facts, extra_allowed=[anchor_title])
        if check.valid and not prose:
            delivered["pack"] = check
            return Evaluation(done=True)
        return Evaluation(
            done=False,
            feedback=feedback_lines(check.violations, prose),
            violation_ids=rule_ids(check.violations, prose),
            ineligible_names=ineligible_names(prose),
        )

    log = run_attempts(
        provider=provider, model=model, retry_bound=retry_bound, make_prompt=make_prompt,
        content_types={"description": str, "bullets": list, "keywords": list}, evaluate=evaluate,
        already_done=lambda: delivered["pack"] is not None,
    )
    pack = delivered["pack"]
    if pack is None:
        return Failed(OutputType.LISTING_COPY, classify_failure(log, what="the listing copy pack"), log.attempts)
    structured: dict[str, Any] = pack.structured()
    structured.update(
        {
            "marketplace": marketplace.value,
            "constraint": c.cite(),
            "count_rule": c.count_rule.value if c.count_rule else None,
            "description_type": c.description_type,
            "unverified_limits": list(resolved.unverified_limits),
            "attempts": log.attempts,
            "excluded_facts": list(facts.excluded),
        }
    )
    if marketplace is Marketplace.FLIPKART:
        structured["structured_fields"] = dict(STRUCTURED_FIELDS_UNVERIFIED)
    return Delivered(OutputType.LISTING_COPY, structured, None, log.attempts)


def shared_text_diagnostics(packs: Mapping[Marketplace, Delivered]) -> list[dict[str, str]]:
    """DIAGNOSTIC only (decision 10): identical description or bullet text across marketplaces'
    packs delivered in one request. Separation is structural (isolated prompts); a hit never fails
    or regenerates a pack by itself and no cross-marketplace rule is invented."""
    view = {mp: (str(d.structured["description"]), list(d.structured["bullets"])) for mp, d in packs.items()}
    return [{"a": f.a.value, "b": f.b.value, "kind": f.kind} for f in shared_text_findings(view)]
