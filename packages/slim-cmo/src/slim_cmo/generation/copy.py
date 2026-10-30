"""Marketplace-specific listing copy pack (spec §6.4 step 4, AC10, AC23, AC25).

* Inputs are ONLY: the approved (or seller-supplied) title for THIS marketplace, THIS marketplace's
  resolved constraint, and claim-eligible facts. No other marketplace's output exists in scope.
* ATOMIC: delivered only if description, bullets AND keywords all pass `check_listing_copy` and
  the prose check. Any structural violation regenerates the whole pack. When the ONLY problems are
  unsupported claims (attempt 1), attempt 2 is a short targeted repair: it writes replacements for
  just the affected units (never sent the rejected text), the units that already passed are kept,
  and the ASSEMBLED pack is re-validated in full before it can be delivered. No partial pack is
  ever returned and an unsupported claim is never accepted.
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
from slim_cmo.generation.facts import FactContext, is_thin_input
from slim_cmo.generation.outcomes import Delivered, Failed, Outcome
from slim_cmo.generation.parse import Parsed
from slim_cmo.generation.prompts import pack_prompt, pack_repair_prompt, prompt_facts
from slim_cmo.generation.provider import LlmProvider
from slim_cmo.generation.safety import REPAIR_HINTS, feedback_lines, ineligible_names, prose_findings, rule_ids
from slim_cmo.listing.basis import rules_basis_of
from slim_cmo.listing.context import ListingContext, untraceable
from slim_cmo.types import Marketplace, OutputType
from slim_cmo.validators import ListingCopyCheck, Violation, ViolationCode, check_listing_copy

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
    listing: ListingContext | None = None,
) -> Outcome:
    c = resolved.row
    pf = prompt_facts(facts)
    extra = listing.prompt_extra() if listing is not None else None
    vocab = listing.keyword_vocab if listing is not None and listing.keyword_vocab else None
    delivered: dict[str, ListingCopyCheck | None] = {"pack": None}
    repair: dict[str, Any] = {}  # set after attempt 1 when the only problems are unsupported claims

    def make_prompt(feedback: tuple[str, ...]) -> str:
        if repair:
            return pack_repair_prompt(
                marketplace=marketplace, facts=pf, anchor_title=anchor_title, constraint=c,
                description_rules=repair["description"], bullet_rules=[repair["bullets"][i] for i in repair["bad_bullets"]],
                keywords_rules=repair["keywords"], kept_bullets=[t for i, t in enumerate(repair["pack"].bullets) if i not in repair["bad_bullets"]],
            )
        return pack_prompt(marketplace=marketplace, facts=pf, anchor_title=anchor_title, constraint=c, feedback=feedback, listing_extra=extra)

    def judge(description: Any, bullets: Any, keywords: Any) -> tuple[ListingCopyCheck, tuple[Any, ...]]:
        check = check_listing_copy(description, bullets, keywords, c, allowed_context=facts.allowed_context)
        items = [("description", check.description)]
        items += [(f"bullets[{i}]", t) for i, t in enumerate(check.bullets)]
        items += [(f"keywords[{i}]", t) for i, t in enumerate(check.keywords)]
        return check, prose_findings(items, facts, extra_allowed=[anchor_title])

    def verdict(check: ListingCopyCheck, prose: tuple[Any, ...]) -> Evaluation:
        # M6: on a full-listing request the keywords field may only hold researched candidates (spec 6.18.4). Position/counts only; never the seller's text.
        loose = tuple(Violation(ViolationCode.NOT_TRACEABLE, f"keywords[{i}]") for i in untraceable(check.keywords, vocab)) if vocab is not None else ()
        if check.valid and not prose and not loose:
            delivered["pack"] = check
            return Evaluation(done=True)
        violations = (*check.violations, *loose)
        return Evaluation(
            done=False,
            feedback=feedback_lines(violations, prose),
            violation_ids=rule_ids(violations, prose),
            ineligible_names=ineligible_names(prose),
        )

    def start_repair(check: ListingCopyCheck, prose: tuple[Any, ...]) -> None:
        """Attempt 1 failed ONLY on unsupported claims: plan a targeted repair of the affected units."""
        by_field: dict[str, list[str]] = {}
        for f in prose:
            by_field.setdefault(f.field, []).append(REPAIR_HINTS.get(f.rule, "no claims beyond the listed facts"))
        bad_bullets = [i for i in range(len(check.bullets)) if f"bullets[{i}]" in by_field]
        kw = [h for field, hints in by_field.items() if field.startswith("keywords[") for h in hints]
        repair.update(
            pack=check, bad_bullets=bad_bullets, description=sorted(set(by_field.get("description", []))), keywords=sorted(set(kw)),
            bullets={i: sorted(set(by_field[f"bullets[{i}]"])) for i in bad_bullets},
        )

    def evaluate(parsed: Parsed) -> Evaluation:
        assert parsed.payload is not None
        p = parsed.payload
        if repair:  # attempt 2: splice the replacements into the kept units, then judge the WHOLE assembled pack
            base = repair["pack"]
            new_bullets = p["bullets"]
            # A small model often ignores "only the new ones": extra units are DISCARDED (never used); too few is a failed repair.
            if not isinstance(new_bullets, list) or len(new_bullets) < len(repair["bad_bullets"]):
                return Evaluation(done=False, violation_ids=("REPAIR_SHAPE",))
            bullets = list(base.bullets)
            for idx, text in zip(repair["bad_bullets"], new_bullets, strict=False):
                bullets[idx] = text
            description = p["description"] if repair["description"] else base.description
            keywords = p["keywords"] if repair["keywords"] else list(base.keywords)
            if (repair["description"] and not description) or (repair["keywords"] and not keywords):
                return Evaluation(done=False, violation_ids=("REPAIR_SHAPE",))
            check, prose = judge(description, bullets, keywords)
            return verdict(check, prose)
        check, prose = judge(p["description"], p["bullets"], p["keywords"])
        result = verdict(check, prose)
        if not result.done and not check.violations and prose and all(f.kind == "UNSUPPORTED_CLAIM" for f in prose) and (vocab is None or not untraceable(check.keywords, vocab)):
            start_repair(check, prose)
        return result

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
            "rules_basis": rules_basis_of(c),
            "count_rule": c.count_rule.value if c.count_rule and rules_basis_of(c) == "VERIFIED" else None,
            "description_type": c.description_type,
            "unverified_limits": list(resolved.unverified_limits),
            "attempts": log.attempts,
            "excluded_facts": list(facts.excluded),
            "thin_input": is_thin_input(facts),
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
