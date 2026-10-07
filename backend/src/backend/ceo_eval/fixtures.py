"""Loads the labelled fixture files (`fixtures/*.jsonl`, one JSON case per line; `#` lines are comments)."""

from __future__ import annotations

import json
from pathlib import Path

from backend.ceo_eval import classifier, composer

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


def load_classifier_cases() -> list[classifier.ClassifierCase]:
    return [classifier.case_from_json(r) for r in _read("classifier.jsonl")]


def load_composer_cases() -> list[composer.ComposerCase]:
    return [composer.case_from_json(r) for r in _read("composer.jsonl")]
