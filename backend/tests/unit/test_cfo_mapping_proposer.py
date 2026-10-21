"""The local-model mapping proposer and the streaming-ingestion config (cfo-data-intelligence.md §6.4, I3, AC-D8). A fake `LlmProvider` stands in for the
model: no model is ever called. What matters here is what the model would be *shown* and what happens to what it *says*."""

from __future__ import annotations

import json
from fractions import Fraction

import pytest

from data_foundation.mapping.masking import mask_sample
from data_foundation.mapping.profile import profile_columns
from data_foundation.mapping.service import MappingProposalFailed, ProposerInput

from backend.services.cfo_mapping_proposer import LlmMappingProposer, build_prompt, extract_json_object

COLUMNS = ("Order ID", "Customer Name", "Phone", "Selling Price", "Notes")
ROWS = [["OD1", "Ravi Kumar", "9876543210", "118.00", "call ravi@example.com GSTIN 07AWOPM5761A1ZG"],
        ["OD2", "Asha Rao", "9123456780", "99.50", "ok"]]


def pinput(rows=ROWS) -> ProposerInput:
    return ProposerInput(report_kind="SALES", marketplace="MEESHO", columns=COLUMNS, masked_sample=tuple(tuple(r) for r in mask_sample(COLUMNS, rows)),
                         profiles=profile_columns(COLUMNS, rows))


class FakeLlm:
    def __init__(self, reply: str | Exception) -> None:
        self.reply, self.calls = reply, []

    def complete(self, *, model: str, prompt: str) -> str:
        self.calls.append((model, prompt))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_the_prompt_never_contains_personal_values_or_a_tenant() -> None:
    prompt = build_prompt(pinput())
    for secret in ("Ravi", "Asha", "9876543210", "9123456780", "ravi@example.com", "07AWOPM5761A1ZG"):
        assert secret not in prompt, secret
    assert "<PII>" in prompt and "tenant" not in prompt.lower()
    assert "Selling Price" in prompt and "118.00" in prompt  # amounts survive: a model cannot tell inclusive from exclusive without them


def test_the_prompt_states_the_closed_vocabulary_and_forbids_invention() -> None:
    p = build_prompt(pinput())
    assert "order_ref" in p and "gross_item_amount" in p and "RUPEES_TO_PAISE" in p and "COMMISSION" in p
    assert "never invent" in p and "unmapped_columns" in p and "UNKNOWN" in p
    assert "e-" not in p.split("negative_share")[0][-5:]  # no scientific/float formatting leaked: shares are rendered as n/d
    assert "numeric_rate=2/2" in p or "numeric_rate=1/1" in p or "numeric_rate=" in p


def test_a_clean_reply_is_returned_as_the_json_object() -> None:
    reply = json.dumps({"fields": [], "unmapped_columns": ["Notes"]})
    out = LlmMappingProposer(FakeLlm(reply), "m")(pinput())
    assert json.loads(out) == {"fields": [], "unmapped_columns": ["Notes"]}


@pytest.mark.parametrize("wrapped", [
    'Sure! Here is the mapping:\n```json\n{"fields": [], "unmapped_columns": []}\n```\nHope that helps.',
    '<think>reasoning...</think> {"fields": [], "unmapped_columns": []} trailing words',
    'prefix {"fields": [], "unmapped_columns": ["a {brace} in a string"]} suffix',
])
def test_json_is_extracted_from_chatty_replies(wrapped: str) -> None:
    assert isinstance(json.loads(extract_json_object(wrapped)), dict)


@pytest.mark.parametrize("bad", ["no json at all", '{"fields": [', '{"fields": [}', ""])
def test_unusable_replies_fail_the_proposal_never_guess(bad: str) -> None:
    with pytest.raises(MappingProposalFailed):
        extract_json_object(bad)
    with pytest.raises(MappingProposalFailed):
        LlmMappingProposer(FakeLlm(bad), "m")(pinput())


def test_a_model_that_is_down_is_a_failed_proposal_not_a_crash_and_not_a_guess() -> None:
    with pytest.raises(MappingProposalFailed) as e:
        LlmMappingProposer(FakeLlm(TimeoutError("connection refused")), "m")(pinput())
    assert "could not be reached" in str(e.value) and "TimeoutError" in str(e.value)


def test_the_configured_model_name_is_what_is_called() -> None:
    llm = FakeLlm('{"fields": [], "unmapped_columns": []}')
    LlmMappingProposer(llm, "qwen3:8b")(pinput())
    assert llm.calls and llm.calls[0][0] == "qwen3:8b"


# -------------------------------------------------------------------------------------------- config
def test_streaming_defaults_and_overrides(monkeypatch) -> None:
    from backend import config

    for name in ("CFO_STREAM_MAX_UPLOAD_BYTES", "CFO_STREAM_MAX_ROWS", "CFO_STREAM_CHUNK_ROWS", "CFO_INGEST_WORKERS", "CFO_MAPPING_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert config.cfo_stream_max_upload_bytes() == 200 * 1024 * 1024 and config.cfo_stream_chunk_rows() == 5000 and config.cfo_ingest_workers() == 2
    assert config.cfo_mapping_model() is None  # automatic mapping is OFF unless a local model is named
    monkeypatch.setenv("CFO_STREAM_CHUNK_ROWS", "1000")
    monkeypatch.setenv("CFO_MAPPING_MODEL", " qwen3:8b ")
    assert config.cfo_stream_chunk_rows() == 1000 and config.cfo_mapping_model() == "qwen3:8b"


@pytest.mark.parametrize("name,value", [("CFO_STREAM_MAX_ROWS", "0"), ("CFO_INGEST_WORKERS", "-3"), ("CFO_STREAM_CHUNK_ROWS", "abc")])
def test_bad_streaming_config_stops_loudly_instead_of_running_with_a_guess(monkeypatch, name: str, value: str) -> None:
    from backend import config

    monkeypatch.setenv(name, value)
    fn = {"CFO_STREAM_MAX_ROWS": config.cfo_stream_max_rows, "CFO_INGEST_WORKERS": config.cfo_ingest_workers, "CFO_STREAM_CHUNK_ROWS": config.cfo_stream_chunk_rows}[name]
    with pytest.raises(ValueError):
        fn()


def test_mapping_thresholds_are_exact_fractions_and_validated(monkeypatch) -> None:
    from backend import config

    for n in ("CFO_MAPPING_MIN_PARSE_RATE", "CFO_MAPPING_MIXED_SIGN_LOW"):
        monkeypatch.delenv(n, raising=False)
    t = config.cfo_mapping_thresholds()
    assert t["min_parse_rate"] == Fraction(98, 100) and isinstance(t["min_parse_rate"], Fraction)  # never a float
    monkeypatch.setenv("CFO_MAPPING_MIN_PARSE_RATE", "95/100")
    assert config.cfo_mapping_thresholds()["min_parse_rate"] == Fraction(19, 20)
    monkeypatch.setenv("CFO_MAPPING_MIN_PARSE_RATE", "3/2")
    with pytest.raises(ValueError):
        config.cfo_mapping_thresholds()
