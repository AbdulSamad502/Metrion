"""The CEO's side of importing attached reports into the CFO financial records (docs/specs/cfo-3-growth-advisor.md, Phase 0).

Reading an attachment writes nothing. Importing it is a financial write, so it only ever happens as: a PREVIEW written by code -> an exact plan card -> the seller presses Approve -> the existing
validated upload pipeline runs (`services/ceo_import_ops.py`). This module holds only the wording and the small amount of state the guided conversation needs; it parses no value and writes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from backend.services import ceo_import_ops as ops

IMPORT_KEY = "cfo.import_attachments"
MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")


def hidden_for(prep: Mapping[str, Any]) -> dict[str, Any]:
    """The session's underscore state (never an answer): the previews, the conversation, and whether any file still needs its marketplace named."""
    previews = list(prep.get("previews") or [])
    return {"_files": previews, "_investigation": str(prep.get("investigation") or ""), "_needs_marketplace": any(p["status"] != "UNREADABLE" and not p.get("marketplace") for p in previews)}


def importable(previews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The files the plan will hand to the importer: every readable spreadsheet (a file that needs mapping is handed over too, and the importer says so honestly)."""
    return [p for p in previews if p["status"] != "UNREADABLE"]


def inputs_from(collected: Mapping[str, Any]) -> dict[str, Any]:
    """The frozen slots of the registry action, from the previews and the one thing the seller may have answered (the marketplace of files that did not say)."""
    answered = collected.get("import_marketplace")
    files = []
    for p in importable(list(collected.get("_files") or [])):
        files.append({"attachment_id": p["attachment_id"], "filename": p["filename"], "marketplace": p.get("marketplace") or answered, "report_kind": p.get("report_kind") or "SALES",
                      "adapter_id": p.get("adapter_id")})
    return {"investigation_id": collected["_investigation"], "files": files, "request_key": "pending"}


def parse_marketplace(raw: str) -> str | None:
    t = " ".join((raw or "").casefold().split())
    for mk in MARKETPLACES:
        if t == mk.casefold() or t.startswith(mk.casefold()):
            return mk
    return ops.marketplace_in(t)


def nothing_to_import_text(previews: list[dict[str, Any]]) -> str:
    if not previews:
        return ("I do not see a spreadsheet attached to this conversation, so there is nothing to add to your financial records. Attach your marketplace reports (CSV or Excel) "
                "and tell me to add them. Nothing was imported or changed.")
    return ("None of the attached files can be imported:\n" + "\n".join(f"- {line}" for line in ops.card_lines(previews)) + "\nNothing was imported or changed.")


def plan_extras(slots: Mapping[str, Any], tenant: UUID) -> tuple[list[str], list[str], str]:
    """(details, compact lines, title) for the approval card, written by code from the frozen slots. Each file is described again from the stored attachment, so the card shows what will
    be handed to the importer, not what an earlier message said."""
    previews = ops.previews_for_slots(tenant, UUID(str(slots["investigation_id"])), list(slots.get("files") or []))
    lines = ops.card_lines(previews)
    details = ["It hands the files to the same importer as the CFO Data & imports page: report recognition, duplicate and overlap protection, held rows and the audit trail all apply.",
               "A file you already imported is recognised and not added twice."]
    compact = ["Add these reports to your financial records:", *lines, "Nothing is added until you press Approve."]
    return details, compact, "Add your attached reports to your financial records"


def heading() -> str:
    return "Done. This is what the importer reported for your files."
