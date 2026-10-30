"""The vision client's timeout and Ollama `keep_alive` are operator-configurable. Measured on a
CPU-only host: a real llava extraction takes 13-160 s and the first call after the model unloads
~140 s, but both production construction sites used the hard-coded 60 s default, so those calls
timed out and silently degraded to manual entry. Defaults are UNCHANGED (60 s / no keep_alive)."""

from __future__ import annotations

import httpx
import pytest

from backend import config
from backend.api.v1 import ceo_hub as ceo_routes
from backend.api.v1 import ci as ci_routes
from competitor_intelligence.evidence.ollama_client import HttpOllamaClient


class _Resp:
    status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, str]:
        return {"response": "ok"}


@pytest.fixture(autouse=True)
def _clear_config_cache():
    for fn in (config.ollama_vision_timeout_seconds, config.ollama_keep_alive, config.ollama_vision_think):
        fn.cache_clear()
    yield
    for fn in (config.ollama_vision_timeout_seconds, config.ollama_keep_alive, config.ollama_vision_think):
        fn.cache_clear()


def _capture(monkeypatch) -> dict[str, object]:
    seen: dict[str, object] = {}

    def fake_post(url, *, json, timeout):  # type: ignore[no-untyped-def]
        seen.update(url=url, json=json, timeout=timeout)
        return _Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    return seen


def test_default_request_is_unchanged_no_keep_alive_key(monkeypatch) -> None:
    seen = _capture(monkeypatch)
    HttpOllamaClient(host="http://h").generate(model="llava", prompt="p", image_bytes=b"x")
    assert "keep_alive" not in seen["json"]  # type: ignore[operator]
    assert seen["timeout"] == 60.0


def test_keep_alive_and_timeout_are_sent_when_configured(monkeypatch) -> None:
    seen = _capture(monkeypatch)
    HttpOllamaClient(host="http://h", timeout_seconds=300, keep_alive="30m").generate(
        model="llava", prompt="p", image_bytes=b"x"
    )
    assert seen["json"]["keep_alive"] == "30m"  # type: ignore[index]
    assert seen["timeout"] == 300


def test_env_configuration_and_defaults(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_VISION_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("OLLAMA_KEEP_ALIVE", raising=False)
    assert config.ollama_vision_timeout_seconds() == 60.0
    assert config.ollama_keep_alive() is None

    config.ollama_vision_timeout_seconds.cache_clear()
    config.ollama_keep_alive.cache_clear()
    monkeypatch.setenv("OLLAMA_VISION_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", " 30m ")
    assert config.ollama_vision_timeout_seconds() == 240.0
    assert config.ollama_keep_alive() == "30m"


@pytest.mark.parametrize("bad", ["0", "-5"])
def test_nonsense_timeout_is_rejected(monkeypatch, bad) -> None:
    monkeypatch.setenv("OLLAMA_VISION_TIMEOUT_SECONDS", bad)
    with pytest.raises(ValueError):
        config.ollama_vision_timeout_seconds()


def test_both_production_composition_roots_use_the_configured_values(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OLLAMA_VISION_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "30m")
    monkeypatch.setattr(ceo_routes, "ci_evidence_storage_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ci_routes, "ci_evidence_storage_dir", lambda: str(tmp_path))

    ceo_client = ceo_routes._vision_extractor().ollama
    assert (ceo_client.timeout_seconds, ceo_client.keep_alive) == (240.0, "30m")

    # ci.py builds its (review) extractor inline in the route; assert via the same config helpers it imports
    assert ci_routes.ollama_vision_timeout_seconds() == 240.0
    assert ci_routes.ollama_keep_alive() == "30m"


def test_think_is_sent_as_false_by_default(monkeypatch) -> None:
    seen = _capture(monkeypatch)
    HttpOllamaClient(host="http://h").generate(model="llava", prompt="p", image_bytes=b"x")
    assert seen["json"]["think"] is False


def test_think_can_be_configured_or_omitted(monkeypatch) -> None:
    seen = _capture(monkeypatch)
    HttpOllamaClient(host="http://h", think=True).generate(model="llava", prompt="p", image_bytes=b"x")
    assert seen["json"]["think"] is True

    seen.clear()
    HttpOllamaClient(host="http://h", think=None).generate(model="llava", prompt="p", image_bytes=b"x")
    assert "think" not in seen["json"]


def test_think_tags_are_stripped(monkeypatch) -> None:
    class _ThinkingResp(_Resp):
        def json(self) -> dict[str, str]:
            return {"response": "<think>some internal reasoning</think>  {\"listed_price\": 99}  "}

    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _ThinkingResp())
    client = HttpOllamaClient(host="http://h")
    assert client.generate(model="llava", prompt="p", image_bytes=b"x") == '{"listed_price": 99}'


def test_env_configuration_think(monkeypatch) -> None:
    monkeypatch.delenv("CI_VISION_THINK", raising=False)
    monkeypatch.delenv("OLLAMA_VISION_THINK", raising=False)
    assert config.ollama_vision_think() is False

    config.ollama_vision_think.cache_clear()
    monkeypatch.setenv("CI_VISION_THINK", "true")
    assert config.ollama_vision_think() is True

    config.ollama_vision_think.cache_clear()
    monkeypatch.setenv("CI_VISION_THINK", "invalid")
    with pytest.raises(ValueError):
        config.ollama_vision_think()

