"""Answering a question about the spreadsheets attached to a CEO conversation, by code (spec 6.34 addendum).

The bytes are read from the tenant-scoped attachment rows, parsed into tables and analysed by `attachment_tables`. No model is called and nothing is written: the
answer is the CEO's message and nothing else (no ledger row, no finding, no import). A file that cannot be read is named with a plain reason; it is never skipped
silently and never described as analysed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any
from uuid import UUID

from backend.repositories import investigation_repo as repo
from backend.services import attachment_tables as tables

logger = logging.getLogger(__name__)
READ_TIMEOUT_SECONDS = 30  # a guard against a pathological file, not a business setting
SPREADSHEET_TYPES = ("CSV", "XLSX")


def is_analysis_request(text: str) -> bool:
    """Is this message a question about the attached file (rather than a request for something else)?"""
    return tables.is_analysis_request(text)


_PRIOR_FILE = re.compile(
    r"\b(?:file|attachment|spreadsheet|csv|xlsx|report|sheet)\b.*\b(?:attached|uploaded|sent|shared)\b.*\b(?:previous|earlier|before|last|prior)\b|"
    r"\b(?:attached|uploaded|sent|shared)\b.*\b(?:in|with) (?:my |the )?(?:previous|earlier|last|prior)\b|\b(?:previous|earlier|last|prior) (?:file|attachment|upload|spreadsheet)\b|"
    r"\b(?:the|that|this) (?:file|spreadsheet|csv)\b.*\b(?:i|we) (?:attached|uploaded|sent|shared)\b", re.IGNORECASE)


def refers_to_earlier_file(text: str) -> bool:
    """Does this message (which has no attachment of its own) point back at a file attached earlier in the conversation?"""
    return bool(_PRIOR_FILE.search(" ".join(text.split())))


def answer_from_earlier(tenant: UUID, investigation_id: UUID, question: str) -> str:
    """A follow-up about "the file I attached before": uses the newest spreadsheet stored in this conversation and says which file that is, or says plainly that there is none."""
    found = [a for a in repo.latest_attachments(tenant, investigation_id, limit=5) if a.get("detected_type") in SPREADSHEET_TYPES]
    if not found:
        return ("I cannot find a spreadsheet attached earlier in this conversation, so I have nothing to continue from. Attach the file again and I will read it. "
                "Nothing was imported or changed.")
    chosen = found[0]
    body = answer(tenant, investigation_id, [chosen], question)
    return f"Using the most recent spreadsheet attached in this conversation: {tables._q(chosen['filename'])}. If you meant a different file, attach it again.\n\n{body}"


def spreadsheets(attachments: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [a for a in attachments if a.get("detected_type") in SPREADSHEET_TYPES]


def answer(tenant: UUID, investigation_id: UUID, attachments: Sequence[Mapping[str, Any]], question: str) -> str:
    rows = repo.get_attachment_contents(tenant, investigation_id, [a["id"] for a in spreadsheets(attachments)])
    books: list[tables.Workbook] = []
    problems: list[str] = []
    for r in rows:
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ceo-table")
        try:
            books.append(pool.submit(tables.read_table, r["content"], r["detected_type"], r["filename"]).result(timeout=READ_TIMEOUT_SECONDS))
        except tables.UnreadableTable as exc:
            problems.append(f"I could not read {tables._q(r['filename'])} as a table: {exc}")
        except FutureTimeout:
            problems.append(f"Reading {tables._q(r['filename'])} took too long, so I stopped. Nothing from it is in this answer.")
        except Exception:  # noqa: BLE001 - never a stack trace, never the file's content
            logger.exception("could not analyse an attachment (tenant=%s investigation=%s)", tenant, investigation_id)
            problems.append(f"I could not read {tables._q(r['filename'])}. Nothing from it is in this answer.")
        finally:
            pool.shutdown(wait=False)
    if not books:
        return "\n".join(problems or ["I could not find a spreadsheet to read in this conversation."]) + "\n\nNothing was imported or changed."
    text = tables.analyse(books, question)
    if problems:
        text = "\n".join(problems) + "\n\n" + text
    return text


def upload_summary(data: bytes, kind: str, filename: str) -> dict[str, Any] | None:
    """What the upload response says about a spreadsheet: whether it can be read as a table, and its sheets and sizes (no cell values). None for other file types."""
    if kind not in SPREADSHEET_TYPES:
        return None
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ceo-table")
    try:
        wb = pool.submit(tables.read_table, data, kind, filename).result(timeout=READ_TIMEOUT_SECONDS)
        return {"status": "READ", **tables.summary(wb)}
    except tables.UnreadableTable as exc:
        return {"status": "UNREADABLE", "note": str(exc)}
    except FutureTimeout:
        return {"status": "UNREADABLE", "note": "Reading this file took too long."}
    except Exception:  # noqa: BLE001
        logger.exception("could not summarise an attachment")
        return {"status": "UNREADABLE", "note": "This file could not be read as a table."}
    finally:
        pool.shutdown(wait=False)
