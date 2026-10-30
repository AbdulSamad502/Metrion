"""CMO 3.0 M6 model rewrite of one section (spec 6.18.7, Q26; acceptance N-15b, N-15c, N-15d): the model may rewrite only the named part to mention a confirmed topic, through exactly the gates a
seller's own edit passes; every other section and the title are carried over; a delivered rewrite is one unit and a new immutable version; anything else is a FAILED row that uses nothing."""

from __future__ import annotations

import uuid

import pytest

from slim_cmo.generation.provider import ScriptedLlmProvider
from slim_cmo.listing import revise
from slim_cmo.service.models import Actor
from slim_cmo.service.rewrite import ListingRewriteService, RewriteRequest
from slim_cmo.types import GenerationStatus as S
from slim_cmo.types import Marketplace as M
from slim_cmo.types import OutputType as O

from ..factories import NOW
from ..generation.helpers import MODEL, j
from ..listing.test_audit import BULLETS, DESC, TITLE, base
from .fakes import ACTOR, GOOD_CONFIG, InMemoryStore, clock

SECTIONS = revise.Sections(title=TITLE, bullets=tuple(BULLETS), description=DESC, keywords=("steel flask", "silver"), backend_terms=("steel flask",))
SRC = uuid.uuid4()


def request(key="rw-1", target="bullet", n=3, topic="wide opening", **kw):
    d = dict(request_key=key, marketplace=M.AMAZON, sku="SKU1", source_generation_id=SRC, target=target, bullet_number=n if target == "bullet" else None, topic=topic, sections=SECTIONS,
             base=base(), structured={"bullets": list(BULLETS), "description": DESC, "keywords": ["steel flask", "silver"], "rules_basis": "UNVERIFIED", "provenance": {"x": 1}},
             approval_id=None, grounding_basis="SELLER_SUPPLIED_TITLE", constraint_ref=None, input_mode="INDEPENDENT", ci_snapshot=None)
    d.update(kw)
    return RewriteRequest(**d)


def make(replies, config=None):
    store = InMemoryStore(config=dict(config or GOOD_CONFIG))
    provider = ScriptedLlmProvider(replies)
    return ListingRewriteService(store, provider, model=MODEL, clock=clock(NOW)), store, provider


def row(store):
    rows = store.rows()
    assert len(rows) == 1
    return rows[0]


def test_a_good_rewrite_changes_only_that_bullet_costs_one_unit_and_is_a_new_version():
    svc, store, p = make([j(text="Wide opening makes filling and cleaning easy.")])
    run = svc.rewrite(ACTOR, request())
    r = row(store)
    assert run.units_to_bill == 1 and run.artefacts[0].status is S.COMPLETE and len(run.delivered_ids) == 1 and p.calls == 1
    s = r.output_structured
    assert s["bullets"][2] == "Wide opening makes filling and cleaning easy." and s["bullets"][:2] == BULLETS[:2] and s["bullets"][3:] == BULLETS[3:]
    assert s["description"] == DESC and s["keywords"] == ["steel flask", "silver"] and s["revision_of"] == str(SRC) and s["revision"]["by"] == "MODEL_REWRITE"
    assert s["previous"]["bullets"][2] == "Holds 1 litre" and s["rules_basis"] == "UNVERIFIED" and s["provenance"] == {"x": 1}  # the earlier text and the basis are kept, not rewritten
    assert r.output_type is O.LISTING_COPY and r.format_constraint_ref is None


def test_the_prompt_names_only_the_part_the_topic_the_title_and_the_facts_and_never_asks_to_change_the_title():
    svc, _s, p = make([j(text="Wide opening makes filling and cleaning easy.")])
    svc.rewrite(ACTOR, request(keywords_allowed=("steel bottle",), do_not_claim=("Leakproof",)))
    prompt = p.prompts[0]
    assert '"part_to_rewrite": "bullet 3"' in prompt and '"must_mention": "wide opening"' in prompt and f'"approved_title": "{TITLE}"' in prompt
    assert "rewrite ONLY the bullet 3" in prompt and '"do_not_claim": ["Leakproof"]' in prompt and "Never state or imply" in prompt


def test_a_repeated_request_is_served_free_with_no_model_call():
    svc, store, p = make([j(text="Wide opening makes filling easy."), j(text="other")])
    first = svc.rewrite(ACTOR, request())
    again = svc.rewrite(ACTOR, request())
    assert p.calls == 1 and len(store.rows()) == 1 and again.units_to_bill == 0 and again.artefacts[0].reused and again.artefacts[0].generation_id == first.artefacts[0].generation_id


@pytest.mark.parametrize("bad", [
    "Keeps drinks cold with a wide opening.",  # an unsupported claim
    "A wide opening, 12 years of use.",  # an unsupported number
    "Wide opening in plastic.",  # a contradiction with the confirmed material
    "Easy to carry.",  # does not mention the topic
    "Holds 1 litre",  # unchanged
    "",  # empty
])
def test_a_rewrite_that_breaks_a_gate_is_retried_and_never_saved(bad):
    svc, store, p = make([j(text=bad), j(text=bad)])
    run = svc.rewrite(ACTOR, request(topic="wide opening" if bad != "Holds 1 litre" else "1 litre"))
    r = row(store)
    assert run.units_to_bill == 0 and run.artefacts[0].status is S.FAILED and run.delivered_ids == () and r.status is S.FAILED and r.output_text is None
    assert "bullets" not in (r.output_structured or {}) and r.failure_reason  # nothing partial is kept


def test_a_second_attempt_that_passes_is_accepted_after_a_first_that_did_not():
    svc, store, p = make([j(text="Keeps drinks cold with a wide opening."), j(text="A wide opening makes cleaning simple.")])
    run = svc.rewrite(ACTOR, request())
    assert run.units_to_bill == 1 and p.calls == 2 and row(store).output_structured["bullets"][2] == "A wide opening makes cleaning simple."
    assert "UNSUPPORTED_CLAIM" in p.prompts[1] and "Keeps drinks" not in p.prompts[1]  # the retry says which rule failed, never the rejected text


def test_the_description_can_be_rewritten_and_the_bullets_are_untouched():
    svc, store, _p = make([j(text="The AquaNest water bottle has a wide opening and holds 1 litre.")])
    run = svc.rewrite(ACTOR, request(target="description", n=None, topic="wide opening"))
    s = row(store).output_structured
    assert run.units_to_bill == 1 and s["description"].startswith("The AquaNest water bottle has a wide opening") and s["bullets"] == list(BULLETS) and s["revision"]["section"] == "DESCRIPTION"


def test_missing_retry_configuration_is_a_failed_row_with_no_model_call_and_no_unit():
    svc, store, p = make([j(text="x")], config={"format_constraint_max_age_days": 30})
    run = svc.rewrite(ACTOR, request())
    r = row(store)
    assert run.units_to_bill == 0 and p.calls == 0 and r.status is S.FAILED and r.output_structured["failure_code"] == "CONFIG_MISSING"


def test_a_provider_failure_is_a_failed_row_that_uses_nothing():
    class Boom:
        calls = 0

        def complete(self, *, model, prompt):
            Boom.calls += 1
            raise RuntimeError("boom-secret")

    store = InMemoryStore(config=dict(GOOD_CONFIG))
    svc = ListingRewriteService(store, Boom(), model=MODEL, clock=clock(NOW))
    run = svc.rewrite(ACTOR, request())
    assert run.units_to_bill == 0 and row(store).status is S.FAILED and "boom-secret" not in str(row(store).output_structured)


def test_another_tenant_has_no_access_through_the_request_key():
    svc, store, _p = make([j(text="Wide opening makes filling and cleaning easy."), j(text="Wide opening makes filling and cleaning easy.")])
    svc.rewrite(ACTOR, request())
    other = Actor(uuid.uuid4(), uuid.uuid4())
    svc.rewrite(other, request())  # the same key under another tenant is its own request
    assert len(store.rows()) == 1 and len(store.rows(other.tenant_id)) == 1
