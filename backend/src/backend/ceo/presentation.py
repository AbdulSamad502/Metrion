"""The display snapshot of a finding — what the seller is shown in the Hub's "agent responses" panel (spec §6.27, R7 as amended).

A snapshot is built from the SAME verified evidence the composer sees (`EvidenceCollector`): every figure is resolved through its ref for
THIS tenant (`provenance`), formatted from the stored value by `figure_format`, and dropped with a named gap if it cannot be verified or is
unavailable; facts are closed enums or seller-authored text; gaps are plain-language reasons. Nothing here computes, ranks or estimates anything,
and no specialist free text is copied (R9) — exactly the rules the CEO's own answer follows.

It is written ONCE with the finding (the table is append-only for the app role), so a reload shows precisely what was shown. It is a DISPLAY copy:
the refs it carries remain the provenance, and a later turn re-resolves refs rather than trusting a snapshot.

The headline is the first thing a canvas node shows. It is built by a fixed rule from the snapshot's own content: the first figure's label and
value, else the first fact, else the first gap. It never aggregates or counts anything.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from backend.ceo import conflicts as conflict_rules
from backend.ceo import provenance
from backend.ceo.contract import BusinessStateEntry, LegResult
from backend.ceo.evidence import MAX_FIGURES, EvidenceCollector

logger = logging.getLogger(__name__)

PRESENTATION_VERSION = 1


def _snapshot(collector: EvidenceCollector) -> dict[str, Any]:
    gated = provenance.gate_figures(collector.tenant_id, tuple(collector.shown_figures()))  # the last defence, as in the composer's table
    verified = collector.verified_conflicts()  # before the gaps are read: an unverifiable conflict is named there
    gaps = list(collector.gaps)
    for g in gated.gaps:
        if g.message not in gaps:
            gaps.append(g.message)
    figures = [
        {
            "label": f.label,
            "value": f.formatted_value,
            "register": f.register.value,
            "as_of": f.as_of.isoformat() if f.as_of is not None else None,
            "note": f.note,
            "ref": f.ref.to_json(),
        }
        for f in gated.kept[:MAX_FIGURES]
    ]
    if len(gated.kept) > MAX_FIGURES:
        gaps.append("More verified results exist than are listed here; they are all cited in this finding's references.")
    facts = [{"label": label, "text": text, "basis": basis} for label, text, basis in collector.facts]
    offers = [{"key": key, "label": label} for key, label in collector.offers]
    conflicts = [
        {"what": c.what, "text": conflict_rules.render(c), "refIds": [str(c.a.ref.id), str(c.b.ref.id)], "kind": c.kind} for c in verified
    ]
    artefacts = [{"title": t, "items": list(items), "note": note} for t, items, note in collector.artefacts]
    return {
        "version": PRESENTATION_VERSION,
        "headline": _headline(figures, facts, gaps, conflicts, artefacts),
        "conflicts": conflicts,
        "figures": figures,
        "facts": facts,
        "gaps": gaps,
        "offers": offers,
        "artefacts": artefacts,
    }


def _headline(figures: list[dict[str, Any]], facts: list[dict[str, Any]], gaps: list[str], conflicts: list[dict[str, Any]] | None = None, artefacts: list[dict[str, Any]] | None = None) -> str:
    if figures:
        return f"{figures[0]['label']}: {figures[0]['value']}"
    if artefacts:
        return f"{artefacts[0]['title']} ready"
    if conflicts:
        return f"{conflicts[0]['what']} has two different stored values"
    if facts:
        return f"{facts[0]['label']}: {facts[0]['text']}"
    if gaps:
        return gaps[0]
    return "No result"


def present_leg(tenant_id: UUID, leg: LegResult) -> dict[str, Any]:
    """The snapshot for one specialist leg (completed, partial, refused or failed)."""
    collector = EvidenceCollector(tenant_id)
    collector.add_leg(leg)
    return _snapshot(collector)


def present_entry(tenant_id: UUID, entry: BusinessStateEntry) -> dict[str, Any]:
    """The snapshot for one Business State read."""
    collector = EvidenceCollector(tenant_id)
    collector.add_entry(entry)
    return _snapshot(collector)


def safe(builder: Any, *args: Any) -> Mapping[str, Any] | None:
    """A snapshot must never break a finding: any failure here is logged and the finding is written without one (the API then shows refs only)."""
    try:
        return builder(*args)  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        logger.exception("could not build a finding presentation")
        return None
