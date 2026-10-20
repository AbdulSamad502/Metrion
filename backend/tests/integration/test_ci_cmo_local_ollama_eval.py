"""Eval (opt-in, LOCAL Ollama only): does the real small writing model, given competitor MARKET CONTEXT, ever copy a competitor, name its brand, or claim volume / ranking / sales?

Run with `CMO_LOCAL_OLLAMA_EVAL=1` (and a local model in `CMO_EVAL_MODEL`, default `qwen35-4b-q4`). It never calls a paid or cloud model. The assertions are about the PIPELINE's
guarantees: whatever the model writes, a delivered result passes the originality / claims check, and when the model fails it the task falls back to independent mode with a note
(so the seller never sees a copy). The tally of how often the informed draft was usable is printed for the record; it is a quality measure, not a pass/fail threshold."""

from __future__ import annotations

import os

import pytest

from slim_cmo.ci_inputs import check_output
from slim_cmo.providers.ollama import OllamaLlmProvider
from tests.integration.test_ceo_cmo_delegation import approve, ask_for_titles, chat  # noqa: F401
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_ci_p3 import CASPIAN_TITLE, COMP_BULLETS, THEMES, _generation, seed_competitor

pytestmark = pytest.mark.skipif(os.environ.get("CMO_LOCAL_OLLAMA_EVAL") != "1", reason="opt-in: needs a local Ollama model (set CMO_LOCAL_OLLAMA_EVAL=1)")

RUNS = 3


def test_real_local_model_never_delivers_a_copy_a_competitor_brand_or_a_market_claim(chat):
    c, e = chat, chat.env
    insight = seed_competitor(e)
    ollama = OllamaLlmProvider(host=os.environ.get("CMO_OLLAMA_HOST", "http://localhost:11434"), timeout_seconds=240, think=False)
    eval_model = os.environ.get("CMO_EVAL_MODEL", "qwen35-4b-q4")
    e.provider.complete = lambda *, model, prompt: ollama.complete(model=eval_model, prompt=prompt)  # the fake CMO model is replaced by the local one
    from backend.services import cmo_ci_inputs

    ci = cmo_ci_inputs.load_inputs(type("C", (), {"tenant_id": e.tenant, "role": "OWNER", "permissions": {}})(), [insight])
    assert ci is not None and "caspian" not in ci.themes()
    informed = 0
    for _ in range(RUNS):
        inv, planned = ask_for_titles(c)
        r = approve(c, inv, planned["plan"])
        assert r.status_code == 200, r.text
        mode, _snapshot, structured = _generation(e)
        rows = e.q("SELECT t.title_text FROM cmo_title_option t JOIN cmo_generation g ON g.id = t.generation_id ORDER BY g.created_at DESC, t.rank LIMIT 3")
        titles = [row[0] for row in rows]
        assert titles, r.json()
        assert check_output(titles, ci) == [], titles  # nothing delivered ever copies, names a competitor brand, or claims volume / ranking / sales
        informed += mode == "CEO_BROKERED_CI"
        if mode == "INDEPENDENT":
            assert "set aside" in structured["provenance"].get("ci_note", "") or "ci_note" not in structured["provenance"]
    print(f"CMO eval ({eval_model}): informed draft usable in {informed} of {RUNS} runs; themes offered: {THEMES}; reference title length {len(CASPIAN_TITLE)}; bullets {len(COMP_BULLETS)}")
