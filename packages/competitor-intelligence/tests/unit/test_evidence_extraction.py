"""evidence/extraction.py — the honest stub, same pattern as capture/parser.py's UnimplementedParser."""

from __future__ import annotations

import pytest

from competitor_intelligence.evidence.extraction import UnimplementedVisionExtractor


def test_unimplemented_vision_extractor_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="No vision extraction model wired yet"):
        UnimplementedVisionExtractor().extract("some/image/ref.jpg")
