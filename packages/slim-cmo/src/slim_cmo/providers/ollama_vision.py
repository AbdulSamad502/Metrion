"""`OllamaVisionProvider` - the local `VisionProvider` (P6 decision 3: Ollama / local only, no hosted provider).

Calls a local Ollama `/api/generate` with ONE base64 image and the fixed schema prompt (`vision.prompts`, which takes
no facts). The image handed in is the already-NORMALISED PNG - never the original upload - and is the only tenant
data that leaves the process (to a caller-supplied local host). The reply is returned as raw UNTRUSTED text; a
`<think>` block is stripped, nothing else is interpreted here. Any transport or HTTP failure is `VisionUnavailable`:
never fabricated output.

`host` and `timeout_seconds` (whole seconds) are REQUIRED and come from the composition root; there is no default
host, model or timeout. `keep_alive` is optional (None leaves Ollama's own default).
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

import httpx

from slim_cmo.vision.prompts import vision_prompt
from slim_cmo.vision.provider import ImageInput, VisionUnavailable

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


@dataclass(frozen=True, slots=True)
class OllamaVisionProvider:
    host: str
    timeout_seconds: int
    keep_alive: str | None = None
    transport: httpx.BaseTransport | None = None  # tests inject a mock transport

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("host is required")
        if type(self.timeout_seconds) is not int or self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be a positive integer")

    def describe(self, *, model: str, schema_version: str, image: ImageInput) -> str:
        payload: dict[str, object] = {
            "model": model,
            "prompt": vision_prompt(schema_version),
            "images": [base64.b64encode(image.data).decode("ascii")],
            "stream": False,
        }
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.host.rstrip('/')}/api/generate", json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise VisionUnavailable(f"Ollama vision request failed: {type(exc).__name__}") from exc
        text = body.get("response") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise VisionUnavailable("Ollama vision response had no 'response' text field")
        return _THINK_BLOCK_RE.sub("", text).strip()
