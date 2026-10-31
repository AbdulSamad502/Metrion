"""The marketplace rules register (B1/B6): where each listing rule came from, when it was read, and whether it may ever become a `format_constraint` row.

`rules/marketplace_rules.json` is the single place a person records what they read on an official marketplace page. Nothing here is a rule the system enforces by itself: a row reaches
`format_constraint` (the only thing generation and the audit trust) through a deliberate, reviewed step, and `promotable_row` refuses unless EVERY field a constraint row needs is
OFFICIAL_VERIFIED, from an official host, with a date. Pure; no I/O beyond reading the JSON next to the package; no model.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

OFFICIAL_VERIFIED, OFFICIAL_PARTIAL, THIRD_PARTY_ONLY, NOT_FOUND = "OFFICIAL_VERIFIED", "OFFICIAL_PARTIAL", "THIRD_PARTY_ONLY", "NOT_FOUND"
STATUSES = frozenset({OFFICIAL_VERIFIED, OFFICIAL_PARTIAL, THIRD_PARTY_ONLY, NOT_FOUND})
_PATH = Path(__file__).resolve().parents[3] / "rules" / "marketplace_rules.json"


def load(path: Path | None = None) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((path or _PATH).read_text(encoding="utf-8"))
    return data


def problems(data: dict[str, Any]) -> list[str]:
    """Every way the register breaks its own policy; empty means it is consistent. A source, a date and an official host are required for anything that states a value."""
    out: list[str] = []
    hosts = set(data.get("official_hosts", []))
    for i, r in enumerate(data.get("rules", [])):
        tag = f"{r.get('marketplace')}:{r.get('field')}"
        st = r.get("status")
        if st not in STATUSES:
            out.append(f"{tag}: unknown status {st!r}")
            continue
        src = r.get("source")
        if st in (OFFICIAL_VERIFIED, OFFICIAL_PARTIAL):
            url = (src or {}).get("url", "")
            p = urlparse(url)
            if p.scheme != "https" or p.hostname not in hosts:
                out.append(f"{tag}: an official rule needs an https URL on an official host")
            if r.get("value") is None:
                out.append(f"{tag}: an official rule needs a value")
        else:
            if r.get("value") is not None:
                out.append(f"{tag}: {st} must carry value null (a hint belongs in `hint`)")
        try:
            date.fromisoformat(str(r.get("checked_on")))
        except ValueError:
            out.append(f"{tag}: checked_on must be an ISO date")
    for a in data.get("access_attempts", []):
        if not (str(a.get("url", "")).startswith("https://") and a.get("result") and a.get("marketplace")):
            out.append(f"access attempt without an https URL, marketplace and result: {a}")
    for m in ("AMAZON", "FLIPKART", "MEESHO"):
        if not data.get("evidence_needed_from_a_seller_account", {}).get(m):
            out.append(f"{m}: the exact evidence needed from a seller account is not listed")
    return out


def official_hosts(data: dict[str, Any]) -> frozenset[str]:
    return frozenset(str(h) for h in data.get("official_hosts", []))


def display_rules_config(data: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """The `title_display_rules` shape the preview reads ({marketplace: {screen: {visible_chars, source_url, verified_at}}}), built ONLY from OFFICIAL_VERIFIED entries whose scope is
    ALL_CATEGORIES (a preview has no category, so a category-limited number cannot apply). Today it is empty: no marketplace publishes one."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in data.get("rules", []):
        field = str(r.get("field", ""))
        if r.get("status") != OFFICIAL_VERIFIED or not field.startswith("title.display_chars.") or "ALL_CATEGORIES" not in str(r.get("scope", "")):
            continue
        out.setdefault(str(r["marketplace"]), {})[field.rsplit(".", 1)[1]] = {"visible_chars": r["value"], "source_url": (r.get("source") or {}).get("url"), "verified_at": r["checked_on"]}
    return out


def promotable_row(data: dict[str, Any], marketplace: str, scope_contains: str = "") -> dict[str, Any] | None:
    """The values for a `format_constraint` row when EVERY required field is OFFICIAL_VERIFIED for this marketplace (and scope), else None. Today none is: that is the honest state."""
    need = list(data.get("required_for_constraint_row", []))
    got: dict[str, Any] = {}
    for r in data.get("rules", []):
        if r.get("marketplace") == marketplace and r.get("status") == OFFICIAL_VERIFIED and scope_contains in str(r.get("scope", "")):
            got[str(r["field"])] = r["value"]
    return got if all(f in got for f in need) else None
