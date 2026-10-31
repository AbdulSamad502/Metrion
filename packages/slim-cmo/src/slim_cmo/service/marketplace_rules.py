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


DEVICES = frozenset({"mobile", "desktop"})
SURFACES = frozenset({"search_results", "product_page"})
MIN_MEASUREMENTS, MIN_DISTINCT_LISTINGS = 5, 3  # a summary needs this many observations of this many different live listings
_MEASURE_FIELDS = ("marketplace", "category", "device", "surface", "listing_ref", "observed_on", "method", "title_chars", "visible_chars", "truncated", "authorized_by")


def measurement_problems(data: dict[str, Any], today: date | None = None) -> list[str]:
    """Every way a recorded display measurement is incomplete or inconsistent. A measurement without its marketplace, category, device, listing, date, method and authorisation is not evidence."""
    out: list[str] = []
    for i, m in enumerate(data.get("display_measurements", [])):
        tag = f"measurement[{i}]"
        for f in _MEASURE_FIELDS:
            if m.get(f) in (None, ""):
                out.append(f"{tag}: {f} is required")
        if m.get("marketplace") not in ("AMAZON", "FLIPKART", "MEESHO"):
            out.append(f"{tag}: unknown marketplace")
        if m.get("device") not in DEVICES:
            out.append(f"{tag}: device must be mobile or desktop")
        if m.get("surface") not in SURFACES:
            out.append(f"{tag}: surface must be search_results or product_page")
        try:
            seen = date.fromisoformat(str(m.get("observed_on")))
            if seen > (today or date.today()):
                out.append(f"{tag}: observed_on is in the future")
        except ValueError:
            out.append(f"{tag}: observed_on must be an ISO date")
        ref = str(m.get("listing_ref", ""))
        if ref.startswith("http") and urlparse(ref).scheme != "https":
            out.append(f"{tag}: a listing URL must be https")
        tc, vc = m.get("title_chars"), m.get("visible_chars")
        if not (isinstance(tc, int) and isinstance(vc, int) and not isinstance(tc, bool) and not isinstance(vc, bool) and 0 < vc <= tc):
            out.append(f"{tag}: visible_chars must be a whole number from 1 up to title_chars")
        elif isinstance(m.get("truncated"), bool) and m["truncated"] != (vc < tc):
            out.append(f"{tag}: truncated must be true exactly when visible_chars is below title_chars")
        if not isinstance(m.get("truncated"), bool):
            out.append(f"{tag}: truncated must be true or false")
    return out


def measured_display_summary(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One summary per marketplace/category/device/surface: the range of visible characters over the TRUNCATED observations, or INSUFFICIENT when fewer than MIN_MEASUREMENTS observations
    over MIN_DISTINCT_LISTINGS different listings exist. A summary is a lead for a person to review; it is never a limit, never enforced and never changes a preview by itself."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for m in data.get("display_measurements", []):
        if measurement_problems({"display_measurements": [m], "official_hosts": data.get("official_hosts", [])}):
            continue
        groups.setdefault((m["marketplace"], m["category"], m["device"], m["surface"]), []).append(m)
    out: list[dict[str, Any]] = []
    for (mk, cat, dev, surf), ms in sorted(groups.items()):
        cut = sorted(int(m["visible_chars"]) for m in ms if m["truncated"])
        enough = len(ms) >= MIN_MEASUREMENTS and len({m["listing_ref"] for m in ms}) >= MIN_DISTINCT_LISTINGS and bool(cut)
        out.append({"marketplace": mk, "category": cat, "device": dev, "surface": surf, "observations": len(ms), "listings": len({m["listing_ref"] for m in ms}),
                    "status": "CANDIDATE_FOR_REVIEW" if enough else "INSUFFICIENT", "visible_chars_min": cut[0] if enough else None, "visible_chars_max": cut[-1] if enough else None,
                    "latest_observed_on": max(str(m["observed_on"]) for m in ms)})
    return out
