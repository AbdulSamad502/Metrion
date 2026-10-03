"""The trust gate (spec §6.2.1; P6 decisions 3, 4), the vision prompt and the provider seam."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from slim_cmo.claims import Attribute, EligibilityReason, assess
from slim_cmo.generation.facts import build_fact_context, image_attributes
from slim_cmo.vision import prompts
from slim_cmo.vision.parse import parse_analysis
from slim_cmo.vision.provider import ImageInput, ScriptedVisionProvider, VisionUnavailable
from slim_cmo.vision.schema import ATTRIBUTE_NAMES, SCHEMA_VERSION
from slim_cmo.vision.trust import EvalRunRef, decide_gate, effective_attributes, latest_run, stamp_attributes

T0 = datetime(2026, 10, 5, 12, tzinfo=UTC)
GOOD = '{"color": "blue", "material": "steel", "size": "large", "brand": "AquaKeep", "product_type": "bottle", "visible_text": "Stay hydrated"}'


def run(passed, minutes=0, provider="ollama", model="m1", schema=SCHEMA_VERSION, rid=None):
    return EvalRunRef(rid or uuid.uuid4(), provider, model, schema, passed, T0 + timedelta(minutes=minutes))


class TestLatestRunAndGate:
    def test_no_run_means_a_closed_gate(self):
        d = decide_gate(latest_run([], "ollama", "m1", SCHEMA_VERSION))
        assert (d.passed, d.gate_ref) == (False, None)

    def test_a_passing_latest_run_opens_the_gate_and_is_cited(self):
        r = run(True)
        d = decide_gate(latest_run([r], "ollama", "m1", SCHEMA_VERSION))
        assert (d.passed, d.gate_ref) == (True, r.id)

    def test_a_failing_latest_run_closes_it_even_if_an_older_one_passed(self):
        runs = [run(True, 0), run(False, 10)]
        assert decide_gate(latest_run(runs, "ollama", "m1", SCHEMA_VERSION)).passed is False

    def test_a_later_pass_reopens_it(self):
        runs = [run(True, 0), run(False, 10), run(True, 20)]
        assert decide_gate(latest_run(runs, "ollama", "m1", SCHEMA_VERSION)).passed is True

    @pytest.mark.parametrize("other", [dict(provider="hosted"), dict(model="m2"), dict(schema="cmo-vision-v2")])
    def test_a_passing_run_for_a_different_provider_model_or_schema_never_counts(self, other):
        assert latest_run([run(True, **other)], "ollama", "m1", SCHEMA_VERSION) is None

    def test_ties_on_run_at_are_broken_deterministically(self):
        a, b = run(True, 0, rid=uuid.UUID(int=1)), run(False, 0, rid=uuid.UUID(int=2))
        assert latest_run([a, b], "ollama", "m1", SCHEMA_VERSION) == latest_run([b, a], "ollama", "m1", SCHEMA_VERSION)


class TestStamping:
    def parsed(self):
        return parse_analysis(GOOD, SCHEMA_VERSION)

    def test_a_closed_gate_stamps_every_observation_as_an_unverified_hint(self):
        stamped = stamp_attributes(self.parsed(), decide_gate(None))
        assert all(a["trust_state"] == "UNVERIFIED_HINT" and a["basis"] == "IMAGE_OBSERVED" for a in stamped)

    def test_an_open_gate_stamps_observations_eval_passed_and_unknowns_never(self):
        parsed = parse_analysis('{"color": "blue", "material": null, "size": "large", "brand": null, "product_type": "bottle", "visible_text": null}', SCHEMA_VERSION)
        stamped = {a["name"]: a for a in stamp_attributes(parsed, decide_gate(run(True)))}
        assert stamped["color"]["trust_state"] == "EVAL_PASSED"
        assert stamped["material"] == {"name": "material", "value": None, "basis": "UNKNOWN", "trust_state": "UNVERIFIED_HINT"}

    def test_only_the_two_vision_bases_are_ever_emitted(self):
        assert {a["basis"] for a in stamp_attributes(self.parsed(), decide_gate(run(True)))} == {"IMAGE_OBSERVED"}
        assert {a["basis"] for a in stamp_attributes(parse_analysis('{"color": null}', SCHEMA_VERSION), decide_gate(run(True)))} == {"UNKNOWN", "IMAGE_OBSERVED"} - {"IMAGE_OBSERVED"}

    def test_the_claim_layer_agrees_closed_gate_is_ineligible_open_gate_is_eligible(self):
        closed = image_attributes(stamp_attributes(self.parsed(), decide_gate(None)))
        opened = image_attributes(stamp_attributes(self.parsed(), decide_gate(run(True))))
        ctx_closed, ctx_open = build_fact_context([], closed), build_fact_context([], opened)
        assert ctx_closed.eligible == () and {r for _a, r in ctx_closed.ineligible if r is EligibilityReason.UNVERIFIED_IMAGE_HINT}
        assert {a.name for a in ctx_open.eligible} == {"color", "material", "size", "brand", "product_type", "visible_text"}

    def test_weight_and_dimensions_are_ineligible_even_if_a_forged_passed_attribute_names_them(self):
        for name in ("weight", "dimensions", "item dimensions", "net weight", "price", "rating", "certification"):
            assert assess(Attribute(name, "x", "IMAGE_OBSERVED", "EVAL_PASSED")).eligible is False


class TestEffectiveTrustAtReadTime:
    STORED = [{"name": "color", "value": "blue", "basis": "IMAGE_OBSERVED", "trust_state": "EVAL_PASSED"},
              {"name": "size", "value": None, "basis": "UNKNOWN", "trust_state": "UNVERIFIED_HINT"}]

    def test_a_still_passing_gate_leaves_trust_alone(self):
        assert effective_attributes(self.STORED, True) == self.STORED

    def test_a_revoked_gate_downgrades_without_modifying_the_stored_row(self):
        before = [dict(a) for a in self.STORED]
        out = effective_attributes(self.STORED, False)
        assert out[0]["trust_state"] == "UNVERIFIED_HINT" and out[0]["value"] == "blue"
        assert self.STORED == before and out[0] is not self.STORED[0]

    def test_nothing_is_ever_promoted(self):
        hint = [{"name": "color", "value": "blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}]
        assert effective_attributes(hint, True)[0]["trust_state"] == "UNVERIFIED_HINT"


class TestPromptCarriesNoTenantData:
    def test_the_prompt_builder_takes_only_the_schema_version(self):
        assert list(inspect.signature(prompts.vision_prompt).parameters) == ["schema_version"]

    def test_the_prompt_is_fixed_closed_and_digit_free(self):
        text = prompts.vision_prompt(SCHEMA_VERSION)
        assert all(n in text for n in ATTRIBUTE_NAMES) and not any(c.isdigit() for c in text.replace(SCHEMA_VERSION, ""))
        assert "notable" not in text.lower() and text == prompts.vision_prompt(SCHEMA_VERSION)
        assert "target" not in text.lower() and "seller" not in text.lower() and "{" in text  # the reply shape only

    def test_an_unsupported_schema_version_raises(self):
        with pytest.raises(ValueError):
            prompts.vision_prompt("cmo-vision-v9")

    def test_the_vision_modules_cannot_reach_facts_or_prices(self):
        import ast
        import pathlib

        import slim_cmo.vision as pkg

        for path in pathlib.Path(pkg.__file__).parent.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            assert not names & {"FactInput", "FactContext", "TARGET_PRICE", "target_price_paise", "build_fact_context"}, path.name


class TestScriptedProvider:
    def test_records_calls_and_replays(self):
        p = ScriptedVisionProvider([GOOD, VisionUnavailable("down")])
        img = ImageInput("image/png", b"x")
        assert p.describe(model="m", schema_version=SCHEMA_VERSION, image=img) == GOOD
        with pytest.raises(VisionUnavailable):
            p.describe(model="m", schema_version=SCHEMA_VERSION, image=img)
        with pytest.raises(VisionUnavailable):
            p.describe(model="m", schema_version=SCHEMA_VERSION, image=img)  # script exhausted
        assert p.calls == 3 and p.models == ["m"] * 3 and p.images[0] is img
