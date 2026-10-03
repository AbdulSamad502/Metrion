"""`VisionProvider` - a SEPARATE slot from `LlmProvider` (spec §6.2): image in, raw text out.

`describe` returns the model's raw reply as UNTRUSTED text; the pure `parse.parse_analysis` turns it into a
structured analysis. The provider is handed only the NORMALISED image (metadata stripped); it never sees the
original upload, a seller fact, a product name or a price. Model name is supplied by the composition root.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ImageInput:
    content_type: str
    data: bytes


class VisionProvider(Protocol):
    def describe(self, *, model: str, schema_version: str, image: ImageInput) -> str: ...


class VisionUnavailable(Exception):
    """The vision model could not be reached / timed out / errored. Never a reason to fabricate an observation."""


class ScriptedVisionProvider:
    """Deterministic provider for tests and offline evaluation: replays a script and records every call."""

    def __init__(self, replies: Iterable[str | Exception]) -> None:
        self._replies: list[str | Exception] = list(replies)
        self.images: list[ImageInput] = []
        self.models: list[str] = []
        self.schema_versions: list[str] = []

    def describe(self, *, model: str, schema_version: str, image: ImageInput) -> str:
        self.images.append(image)
        self.models.append(model)
        self.schema_versions.append(schema_version)
        if not self._replies:
            raise VisionUnavailable("scripted vision provider has no more replies")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    @property
    def calls(self) -> int:
        return len(self.images)
