"""Local-disk storage safety and the Ollama vision provider boundary (mock transport only - no live model)."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid

import httpx
import pytest

from slim_cmo.providers.ollama_vision import OllamaVisionProvider
from slim_cmo.storage.local_disk import ImageStoreError, LocalDiskImageStore
from slim_cmo.vision import prompts
from slim_cmo.vision.provider import ImageInput, VisionUnavailable
from slim_cmo.vision.schema import SCHEMA_VERSION

TENANT_A, TENANT_B = uuid.uuid4(), uuid.uuid4()
DATA = b"\x89PNG\r\n\x1a\n" + b"pixels" * 50
SHA = hashlib.sha256(DATA).hexdigest()


class TestLocalDiskStore:
    def test_round_trip_and_uri_shape(self, tmp_path):
        store = LocalDiskImageStore(str(tmp_path))
        uri = store.put(TENANT_A, SHA, DATA)
        assert uri == f"local://{TENANT_A}/{SHA}.png" and store.get(uri) == DATA
        assert (tmp_path / str(TENANT_A) / SHA[:2] / f"{SHA}.png").exists()
        assert str(tmp_path) not in uri  # no filesystem path leaks into the database

    def test_put_is_idempotent_and_atomic(self, tmp_path):
        store = LocalDiskImageStore(str(tmp_path))
        assert store.put(TENANT_A, SHA, DATA) == store.put(TENANT_A, SHA, DATA)
        assert not [p for p in tmp_path.rglob(".part-*")]

    def test_tenants_are_partitioned_on_disk(self, tmp_path):
        store = LocalDiskImageStore(str(tmp_path))
        store.put(TENANT_A, SHA, DATA)
        store.put(TENANT_B, SHA, DATA)
        assert (tmp_path / str(TENANT_A)).is_dir() and (tmp_path / str(TENANT_B)).is_dir()
        with pytest.raises(ImageStoreError):
            store.get(f"local://{uuid.uuid4()}/{SHA}.png")  # a tenant that never stored it

    def test_content_must_match_its_hash(self, tmp_path):
        with pytest.raises(ImageStoreError):
            LocalDiskImageStore(str(tmp_path)).put(TENANT_A, SHA, DATA + b"x")

    @pytest.mark.parametrize("bad", ["../../etc/passwd", "a" * 63, "A" * 64, "g" * 64, "", SHA + "00", f"../{SHA}", f"{SHA[:-1]}/"])
    def test_a_hash_that_could_form_a_path_is_refused(self, tmp_path, bad):
        with pytest.raises(ImageStoreError):
            LocalDiskImageStore(str(tmp_path)).put(TENANT_A, bad, DATA)

    @pytest.mark.parametrize("uri", [
        "", "file:///etc/passwd", f"local://../{SHA}.png", f"local://{TENANT_A}/../{SHA}.png", f"local://{TENANT_A}/{SHA}.jpg",
        f"local://{TENANT_A}/{SHA}.png/../..", f"local://not-a-uuid/{SHA}.png", f"LOCAL://{TENANT_A}/{SHA}.png", "local://" + "x" * 500,
    ])
    def test_an_arbitrary_stored_string_is_never_turned_into_a_path(self, tmp_path, uri):
        with pytest.raises(ImageStoreError):
            LocalDiskImageStore(str(tmp_path)).get(uri)

    def test_a_tampered_file_fails_its_integrity_check(self, tmp_path):
        store = LocalDiskImageStore(str(tmp_path))
        uri = store.put(TENANT_A, SHA, DATA)
        (tmp_path / str(TENANT_A) / SHA[:2] / f"{SHA}.png").write_bytes(b"tampered")
        with pytest.raises(ImageStoreError):
            store.get(uri)

    def test_a_missing_file_is_an_error_not_a_crash(self, tmp_path):
        with pytest.raises(ImageStoreError):
            LocalDiskImageStore(str(tmp_path)).get(f"local://{TENANT_A}/{SHA}.png")

    @pytest.mark.parametrize("base", ["", "   ", None, 5])
    def test_the_base_directory_is_required_with_no_default(self, base):
        with pytest.raises(ValueError):
            LocalDiskImageStore(base)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            LocalDiskImageStore()  # type: ignore[call-arg]


IMG = ImageInput("image/png", DATA)


def provider(handler, **kw):
    return OllamaVisionProvider(host="http://ollama.test", timeout_seconds=5, transport=httpx.MockTransport(handler), **kw)


class TestOllamaVisionProvider:
    def test_sends_exactly_the_given_image_and_the_fixed_prompt_and_nothing_else(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"], seen["body"] = str(request.url), json.loads(request.content)
            return httpx.Response(200, json={"response": ' {"color": "blue"} '})

        out = provider(handler).describe(model="m", schema_version=SCHEMA_VERSION, image=IMG)
        assert out == '{"color": "blue"}'
        body = seen["body"]
        assert seen["url"] == "http://ollama.test/api/generate" and set(body) == {"model", "prompt", "images", "stream"}
        assert body["model"] == "m" and body["stream"] is False and body["prompt"] == prompts.vision_prompt(SCHEMA_VERSION)
        assert body["images"] == [base64.b64encode(DATA).decode()] and len(body["images"]) == 1  # one image per request

    def test_keep_alive_is_sent_only_when_configured(self):
        seen = []
        handler = lambda r: (seen.append(json.loads(r.content)), httpx.Response(200, json={"response": "{}"}))[1]  # noqa: E731
        provider(handler, keep_alive="30m").describe(model="m", schema_version=SCHEMA_VERSION, image=IMG)
        provider(handler).describe(model="m", schema_version=SCHEMA_VERSION, image=IMG)
        assert seen[0]["keep_alive"] == "30m" and "keep_alive" not in seen[1]

    def test_think_blocks_are_stripped_and_the_reply_is_otherwise_untouched(self):
        out = provider(lambda r: httpx.Response(200, json={"response": "<think>hmm {weight}</think>\n{\"color\": \"red\"}"})).describe(model="m", schema_version=SCHEMA_VERSION, image=IMG)
        assert out == '{"color": "red"}'

    @pytest.mark.parametrize("handler", [
        lambda r: httpx.Response(500, json={}), lambda r: httpx.Response(404, json={}), lambda r: httpx.Response(200, json={"nope": 1}),
        lambda r: httpx.Response(200, json=["x"]), lambda r: httpx.Response(200, content=b"not json"),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")),
    ])
    def test_every_failure_is_vision_unavailable_never_fabricated_text(self, handler):
        with pytest.raises(VisionUnavailable) as caught:
            provider(handler).describe(model="m", schema_version=SCHEMA_VERSION, image=IMG)
        assert "ollama.test" not in str(caught.value) and "://" not in str(caught.value)  # no host or URL in the error

    def test_an_unsupported_schema_version_is_refused_before_any_request(self):
        called = []
        with pytest.raises(ValueError):
            provider(lambda r: called.append(r) or httpx.Response(200, json={"response": "{}"})).describe(model="m", schema_version="v0", image=IMG)
        assert called == []

    @pytest.mark.parametrize("kw", [{"host": " ", "timeout_seconds": 5}, {"host": "h", "timeout_seconds": 0}, {"host": "h", "timeout_seconds": True}, {"host": "h", "timeout_seconds": 2.5}])
    def test_host_and_timeout_are_required_and_validated_never_defaulted(self, kw):
        with pytest.raises(ValueError):
            OllamaVisionProvider(**kw)
        with pytest.raises(TypeError):
            OllamaVisionProvider()  # type: ignore[call-arg]
