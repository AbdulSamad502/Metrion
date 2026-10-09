"""CEO composition root (B3): wires the orchestrator to a model provider and the configured leg bounds.

Same shape as `cmo_runtime`: the CEO only ever sees the model interface in `backend.llm.model` (text in, text out, plus timings); Ollama is
the DEVELOPMENT backend and another provider is added to `_PROVIDERS`. No model, host, timeout or leg bound is hardcoded here, and none
is chosen by this module: a missing REQUIRED value raises `MissingConfig` (the route answers 503 `CEO_NOT_CONFIGURED`); a missing leg
bound is carried as None and makes an investigation with legs refuse with CONFIG_MISSING (spec §6.12 rule 5).
"""

from __future__ import annotations

from collections.abc import Callable

from backend import config
from backend.ceo.runtime import CeoRuntime
from backend.llm.model import LlmModel, OllamaEvalModel


def _ollama(model: str) -> LlmModel:
    return OllamaEvalModel(
        name=model, host=config.ceo_ollama_host(), think=config.ceo_llm_think(), timeout_seconds=float(config.ceo_llm_timeout_seconds()),
    )


_PROVIDERS: dict[str, Callable[[str], LlmModel]] = {"ollama": _ollama}


def build_runtime() -> CeoRuntime:
    name = config.ceo_llm_provider()
    factory = _PROVIDERS.get(name)
    if factory is None:
        raise config.MissingConfig(f"CEO_LLM_PROVIDER={name!r} is not a registered provider")
    return CeoRuntime(
        classifier=factory(config.ceo_classifier_model()), composer=factory(config.ceo_llm_model()),
        leg_timeout_seconds=config.ceo_leg_timeout_seconds(), max_legs=config.ceo_playbook_max_legs(),
        max_candidate_prices=config.ceo_max_candidate_prices(),
    )
