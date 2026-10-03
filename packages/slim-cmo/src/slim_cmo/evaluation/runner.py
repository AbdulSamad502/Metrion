"""Run a vision evaluation and record it (spec §6.2.1; P6 decision 13).

REFUSES (raises `EvalRefused`, writes nothing) unless it is given: a named human operator (`run_by`), a labelled
dataset in which EVERY item labels EVERY schema field, and an explicit bar/threshold file that states every
threshold. There is no default bar and no built-in dataset: the pass bar is a human decision identified by
`bar_ref` (`<bar name>@<sha256 prefix of the bar file>`), never invented in code.

Every dataset image goes through the SAME `normalize_image` the upload path uses, and every reply through the SAME
`parse_analysis` production uses, so the evaluation measures what production would trust.

A provider failure ABORTS the run without writing: an outage must not be recorded as a failing evaluation (which
would revoke trust). Only a completed run is persisted, passing or not. The result is a new immutable
`vision_eval_run` row; the latest one for the exact provider/model/schema_version is what the gate reads.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from slim_cmo.imaging.normalize import ImageLimits, ImageRejected, normalize_image
from slim_cmo.vision.eval import Bar, BarInvalid, DatasetInvalid, LabelledItem, Metrics, Verdict, judge, parse_bar, score, validate_item
from slim_cmo.vision.parse import ParsedAnalysis, parse_analysis
from slim_cmo.vision.provider import ImageInput, VisionProvider
from slim_cmo.vision.schema import SUPPORTED_SCHEMA_VERSIONS

_EXT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class EvalRefused(Exception):
    """The evaluation was not run (missing/invalid operator input, bar or dataset, or a provider outage)."""


class EvalWriter(Protocol):
    def write(
        self, *, provider: str, model: str, schema_version: str, dataset_ref: str, metrics: dict[str, Any],
        bar_ref: str, passed: bool, run_by: str,
    ) -> UUID: ...


@dataclass(frozen=True, slots=True)
class EvalReport:
    run_id: UUID
    passed: bool
    failures: tuple[str, ...]
    metrics: dict[str, Any]
    bar_ref: str
    dataset_ref: str


def load_bar(path: Path | None) -> tuple[Bar, str]:
    if path is None:
        raise EvalRefused("no bar/threshold file was given: refusing to run (there is no default bar)")
    try:
        raw = path.read_bytes()
    except OSError:
        raise EvalRefused("the bar/threshold file could not be read") from None
    try:
        bar = parse_bar(json.loads(raw))
    except (ValueError, BarInvalid) as exc:
        problems = exc.problems if isinstance(exc, BarInvalid) else ("the bar file is not valid JSON",)
        raise EvalRefused("the bar is invalid: " + "; ".join(problems)) from None
    return bar, f"{bar.name}@{hashlib.sha256(raw).hexdigest()[:16]}"


def load_dataset(directory: Path | None) -> tuple[str, list[tuple[LabelledItem, Path]]]:
    if directory is None:
        raise EvalRefused("no labelled dataset was given: refusing to run")
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (OSError, ValueError):
        raise EvalRefused("the dataset needs a readable manifest.json") from None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("items"), list) or not manifest["items"]:
        raise EvalRefused("the dataset manifest must list at least one item")
    name, version = manifest.get("name"), manifest.get("version")
    if not isinstance(name, str) or not name.strip() or not isinstance(version, str) or not version.strip():
        raise EvalRefused("the dataset manifest needs a `name` and a `version` (they identify the labelled set in `dataset_ref`)")
    base = directory.resolve()
    items: list[tuple[LabelledItem, Path]] = []
    seen: set[str] = set()
    for entry in manifest["items"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("image"), str):
            raise EvalRefused("every dataset item needs an `id`, an `image` and `labels`")
        if entry["id"] in seen:
            raise EvalRefused(f"duplicate dataset item id {entry['id']!r}")
        seen.add(entry["id"])
        path = (base / entry["image"]).resolve()
        if base not in path.parents:
            raise EvalRefused(f"item {entry['id']!r}: the image path escapes the dataset directory")
        try:
            items.append((validate_item(entry["id"], entry.get("labels")), path))
        except DatasetInvalid as exc:
            raise EvalRefused(str(exc)) from None
    return f"{name.strip()}@{version.strip()}", items


def run_evaluation(
    *,
    provider: VisionProvider,
    provider_name: str,
    model: str,
    schema_version: str,
    run_by: str,
    dataset_dir: Path | None,
    bar_path: Path | None,
    limits: ImageLimits,
    writer: EvalWriter,
    on_item: Callable[[str], None] = lambda _id: None,
) -> EvalReport:
    if not isinstance(run_by, str) or len(run_by.strip()) < 2:
        raise EvalRefused("a named human operator (--run-by) is required")
    if not provider_name.strip() or not model.strip():
        raise EvalRefused("provider and model are required")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise EvalRefused(f"unsupported schema version {schema_version!r}")
    bar, bar_ref = load_bar(bar_path)
    dataset_ref, items = load_dataset(dataset_dir)

    pairs: list[tuple[LabelledItem, ParsedAnalysis]] = []
    for item, path in items:
        on_item(item.item_id)
        declared = _EXT_TYPES.get(path.suffix.lower())
        if declared is None:
            raise EvalRefused(f"item {item.item_id!r}: unsupported image extension")
        try:
            image = normalize_image(path.read_bytes(), declared, limits)
        except OSError:
            raise EvalRefused(f"item {item.item_id!r}: the image could not be read") from None
        except ImageRejected as exc:
            raise EvalRefused(f"item {item.item_id!r}: the image was rejected ({exc.code})") from None
        try:
            raw = provider.describe(model=model, schema_version=schema_version, image=ImageInput(image.content_type, image.data))
        except Exception:  # noqa: BLE001
            raise EvalRefused("the vision provider failed during the run; nothing was recorded (an outage is not a failing evaluation)") from None
        pairs.append((item, parse_analysis(raw, schema_version)))

    metrics: Metrics = score(pairs)
    verdict: Verdict = judge(metrics, bar)
    payload = metrics.to_json()
    payload.update({"bar_name": bar.name, "failures": list(verdict.failures), "dataset_items": len(items)})
    run_id = writer.write(
        provider=provider_name, model=model, schema_version=schema_version, dataset_ref=dataset_ref,
        metrics=payload, bar_ref=bar_ref, passed=verdict.passed, run_by=run_by.strip(),
    )
    return EvalReport(run_id, verdict.passed, verdict.failures, payload, bar_ref, dataset_ref)
