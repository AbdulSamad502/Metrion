"""Re-export: the model layer now lives in `backend.llm.model` (shared with production). Behaviour unchanged."""

from backend.llm.model import (  # noqa: F401
    STATIC_END, Completion, EvalModel, LlmModel, OllamaEvalModel, OllamaUnavailable, ProviderAdapter, ScriptedModel, _THINK_BLOCK_RE,
)
