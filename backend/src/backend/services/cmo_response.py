"""Allow-list serialisation of Slim CMO artefacts for the API (P5).

Responses are built from the PERSISTED artefact row, field by field - never by passing a stored
dict through. Deliberately NOT returned: prompts, raw model output (none is stored), provenance and
fact ids, excluded-facts lists, internal constraint-row ids, failure `detail` internals, SQL or
exception text, provider URLs. Everything shown is something the domain contract says the seller
may see: the artefact itself, its status, a plain failure reason with screened missing-fact names,
and the cited marketplace rule (source URL, `verified_at`, version).

Keys are camelCase like the other `/api/v1` routes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from slim_cmo.service.models import StoredGeneration
from slim_cmo.types import GenerationStatus, OutputType


def _strs(value: object) -> list[str]:
    return [str(x) for x in value] if isinstance(value, (list, tuple)) else []


def _cite(structured: Mapping[str, Any]) -> dict[str, Any] | None:
    c = structured.get("constraint")
    if not isinstance(c, dict):
        return None
    return {"sourceUrl": c.get("source_url"), "verifiedAt": c.get("verified_at"), "version": c.get("version"), "ruleKind": c.get("row_kind")}


def _rule_fields(structured: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "thinInput": bool(structured.get("thin_input")),
        "rulesBasis": structured.get("rules_basis") if structured.get("rules_basis") in ("VERIFIED", "UNVERIFIED") else None,
        "constraint": _cite(structured),
        "unverifiedLimits": _strs(structured.get("unverified_limits")),
        "countRule": structured.get("count_rule"),
    }


def _attribute(a: Mapping[str, Any]) -> dict[str, Any]:
    s = a.get("suggestion")
    e = a.get("estimate")
    return {
        "attribute": a.get("attribute"),
        "value": a.get("value"),
        "basis": a.get("basis"),
        "claimEligible": bool(a.get("claim_eligible")),
        "requiresSellerInput": bool(a.get("requires_seller_input")),
        "note": a.get("note"),
        "suggestion": {"value": s.get("value"), "text": s.get("text")} if isinstance(s, dict) else None,
        "estimate": dict(e) if isinstance(e, dict) else None,
        "supersededValues": _strs(a.get("superseded_values")),
        "conflictingObservation": a.get("conflicting_observation"),
    }


def _content(row: StoredGeneration, s: Mapping[str, Any]) -> dict[str, Any]:
    t = row.output_type
    if t is OutputType.TITLE_SET:
        return {
            "options": [{"id": str(o.id), "rank": o.rank, "text": o.title_text, "charCount": o.char_count} for o in row.options],
            "expectedOptionCount": s.get("expected_option_count"),
            "deliveredOptionCount": s.get("delivered_option_count"),
            "short": bool(s.get("short")),
            "shortLabel": s.get("short_label"),
            **_rule_fields(s),
        }
    if t is OutputType.LISTING_COPY:
        out: dict[str, Any] = {
            "description": s.get("description"), "bullets": _strs(s.get("bullets")), "keywords": _strs(s.get("keywords")),
            "descriptionType": s.get("description_type"), **_rule_fields(s),
        }
        if isinstance(s.get("structured_fields"), dict):
            sf = s["structured_fields"]
            out["structuredFields"] = {"state": sf.get("state"), "reason": sf.get("reason"), "fields": _strs(sf.get("fields"))}
        shared = (s.get("diagnostics") or {}).get("shared_text") if isinstance(s.get("diagnostics"), dict) else None
        out["sharedTextFindings"] = [dict(x) for x in shared if isinstance(x, dict)] if isinstance(shared, list) else []
        return out
    if t is OutputType.DESCRIPTION:
        return {"description": s.get("description"), "descriptionType": s.get("description_type"), **_rule_fields(s)}
    if t is OutputType.BULLETS:
        return {"bullets": _strs(s.get("bullets")), **_rule_fields(s)}
    if t is OutputType.KEYWORDS:
        return {"keywords": _strs(s.get("keywords")), **_rule_fields(s)}
    if t is OutputType.BACKEND_TERMS:
        return {"terms": _strs(s.get("backend_terms")), "joined": s.get("joined"), "byteCount": s.get("byte_count"),
                "maxBytes": s.get("max_bytes"), **_rule_fields(s)}
    if t is OutputType.HASHTAGS:
        return {"hashtags": _strs(s.get("hashtags")), "label": s.get("label"), "listingField": False, "maxSetSize": s.get("max_set_size")}
    if t is OutputType.CATALOG_ANSWER:
        attrs = s.get("attributes")
        return {
            "attributes": [_attribute(a) for a in attrs if isinstance(a, dict)] if isinstance(attrs, list) else [],
            "basisCounts": dict(s["basis_counts"]) if isinstance(s.get("basis_counts"), dict) else {},
            "disclaimer": s.get("disclaimer"),
        }
    return {}


def artefact_json(row: StoredGeneration, *, reused: bool) -> dict[str, Any]:
    structured: Mapping[str, Any] = row.output_structured or {}
    out: dict[str, Any] = {
        "id": str(row.id),
        "outputType": row.output_type.value,
        "marketplace": row.marketplace.value if row.marketplace else None,
        "status": row.status.value,
        "reused": reused,
        "agentRunId": str(row.agent_run_id) if row.agent_run_id else None,
    }
    if row.status is GenerationStatus.FAILED:
        out["failure"] = {
            "code": structured.get("failure_code") if isinstance(structured.get("failure_code"), str) else "UNKNOWN",
            "reason": row.failure_reason,
            "missingFacts": _strs(structured.get("missing_facts")),
        }
        return out
    out.update(_content(row, structured))
    return out


def run_json(
    artefacts: Sequence[Mapping[str, Any]], *, run_status: str, units_billed: int, agent_run_id: UUID | None
) -> dict[str, Any]:
    return {
        "runStatus": run_status,
        "unitsBilled": units_billed,
        "agentRunId": str(agent_run_id) if agent_run_id else None,
        "artefacts": list(artefacts),
    }
