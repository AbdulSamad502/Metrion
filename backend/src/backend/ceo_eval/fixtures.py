"""Loads the labelled fixture files (`fixtures/*.jsonl`, one JSON case per line; `#` lines are comments)."""

from __future__ import annotations

import json
from pathlib import Path

from backend.ceo_eval import business_qa, classifier, composer

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _read(name: str) -> list[dict]:
    out: list[dict] = []
    for n, line in enumerate((FIXTURE_DIR / name).read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            out.append(json.loads(s))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name}:{n}: {exc}") from exc
    return out


def _read_optional(name: str) -> list[dict]:
    return _read(name) if (FIXTURE_DIR / name).exists() else []


def load_classifier_cases() -> list[classifier.ClassifierCase]:
    """The hand-written cases plus the template-expanded ones (`classifier_gen.jsonl`, produced by `generate.py`; each carries its family)."""
    return [classifier.case_from_json(r) for r in (*_read("classifier.jsonl"), *_read_optional("classifier_gen.jsonl"))]


def load_business_qa_cases() -> list[business_qa.QaCase]:
    """The CEO business Q&A answer cases (spec agent-needs-and-shared-knowledge.md 8.3 a, b, c): a deterministic suite, no model needed."""
    return [business_qa.case_from_json(r) for r in _read("business_qa.jsonl")]


def load_composer_cases() -> list[composer.ComposerCase]:
    return [composer.case_from_json(r) for r in (*_read("composer.jsonl"), *_read_optional("composer_gen.jsonl"))]
