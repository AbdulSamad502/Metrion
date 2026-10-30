"""Applying the seller's section-edit sentence to a saved listing (docs/specs/slim-cmo-agent.md section 6.18.7a). Pure: no model, no I/O.

`apply_edit` builds the new version of ONE section and nothing else; the title is never touched. `check_edit` re-runs the listing audit on the new version and refuses the edit when the changed
section has a BLOCKER finding (an unsupported claim, an unconfirmed topic, an unsupported number, a contradiction, a non-researched keyword, ...). Problems that already existed in a section the
seller did not touch are not a reason to refuse this edit. A refused edit saves nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from slim_cmo.listing import audit
from slim_cmo.listing.edit import EditRequest
from slim_cmo.listing.text import content_hash


@dataclass(frozen=True, slots=True)
class Sections:
    title: str
    bullets: tuple[str, ...]
    description: str
    keywords: tuple[str, ...]
    backend_terms: tuple[str, ...] | None  # None = no backend-terms step (every marketplace but Amazon)

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "bullets": list(self.bullets), "description": self.description, "keywords": list(self.keywords),
                "backend_terms": None if self.backend_terms is None else list(self.backend_terms)}

    def hash(self, marketplace: str) -> str:
        return content_hash(marketplace, self.as_dict())


@dataclass(frozen=True, slots=True)
class Applied:
    sections: Sections
    changed: str  # the audit section label that changed: BULLET n | DESCRIPTION | KEYWORDS | BACKEND_TERMS


@dataclass(frozen=True, slots=True)
class Refused:
    code: str
    reason: str


def apply_edit(sections: Sections, req: EditRequest) -> Applied | Refused:
    if req.target == "bullet":
        n = req.bullet_number or 0
        if n < 1 or n > len(sections.bullets):
            return Refused("BULLET_OUT_OF_RANGE", f"This pack has bullets 1-{len(sections.bullets)}; there is no bullet {n}.")
        new = list(sections.bullets)
        new[n - 1] = req.text or ""
        return Applied(replace(sections, bullets=tuple(new)), f"BULLET {n}")
    if req.target == "description":
        return Applied(replace(sections, description=req.text or ""), "DESCRIPTION")
    if req.target == "keywords":
        return Applied(replace(sections, keywords=tuple(req.terms)), "KEYWORDS")
    if req.target == "backend_terms":
        if sections.backend_terms is None:
            return Refused("BACKEND_TERMS_AMAZON_ONLY", "Backend search terms exist only for Amazon, and this listing has none.")
        return Applied(replace(sections, backend_terms=tuple(req.terms)), "BACKEND_TERMS")
    return Refused("NOT_AN_EDIT", "That is not a section I can edit this way.")


def check_edit(applied: Applied, base: audit.AuditInputs) -> tuple[dict[str, Any], Refused | None]:
    """(the audit of the new version, a refusal when the changed section has a blocker). The audit is returned either way so the caller can show it."""
    s = applied.sections
    inputs = replace(base, title=s.title, bullets=s.bullets, description=s.description, keywords=s.keywords, backend_terms=s.backend_terms)
    result = audit.run(inputs)
    mine = [f for f in result["findings"] if f["severity"] == audit.BLOCKER and (f["section"] == applied.changed or (applied.changed == "KEYWORDS" and f["section"] == "KEYWORDS"))]
    if mine:
        first = mine[0]
        return result, Refused(first["code"], f"{first['explanation']} {first['correction'] or ''}".strip())
    return result, None


def sections_from(structured: Mapping[str, Any], *, title: str, backend_terms: Sequence[str] | None) -> Sections:
    """The sections of a saved LISTING_COPY pack (its `output_structured`), with the approved title and the saved backend terms (or None)."""
    return Sections(
        title=title, bullets=tuple(str(b) for b in structured.get("bullets") or ()), description=str(structured.get("description") or ""),
        keywords=tuple(str(k) for k in structured.get("keywords") or ()), backend_terms=None if backend_terms is None else tuple(str(t) for t in backend_terms),
    )


def revision_structured(base: Mapping[str, Any], old: Sections, applied: Applied, *, source_id: str, by: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The `output_structured` of a revised version: the saved pack with ONE section changed, the lineage (`revision_of`) and the previous text kept (for M7's version history). The title,
    the rules basis, the constraint citation and the provenance are carried over unchanged; the earlier row is never touched."""
    s = dict(base)
    new = applied.sections
    s.update({
        "bullets": list(new.bullets), "description": new.description, "keywords": list(new.keywords), "revision_of": source_id,
        "revision": {"section": applied.changed, "by": by, "of": source_id, **(dict(extra) if extra else {})},
        "previous": {"bullets": list(old.bullets), "description": old.description, "keywords": list(old.keywords)},
        "backend_terms_saved": None if new.backend_terms is None else list(new.backend_terms),
    })
    s.pop("diagnostics", None)
    return s

