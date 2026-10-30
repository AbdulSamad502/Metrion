"""CMO 3.0 M1 - Smart Product Intelligence: the saved product profile (docs/specs/ceo-cmo-delegation.md section 6.13).

The profile is a READ over what the seller already told Metrion about one product (`seller_fact`, append-only): the latest value of each detail, where it came from and when, and the
earlier values it replaced. No new table, nothing is written, nothing is added that the seller did not say, and a detail they never gave is shown as "not confirmed" - never filled in,
never zero. Photo-derived details appear only when the seller confirmed them (a photo suggestion on its own is never stored as a fact).

Answered by code, with no model and no unit, when the seller asks "remember my AquaNest bottle?" or "what do you know about my bottle?". Questions about the business itself
("what do you know about my business") are not product questions and are left to the business Q&A.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from backend.ceo import cmo_chat
from backend.repositories import cmo_chat_repo

logger = logging.getLogger(__name__)

STANDARD_DETAILS = ("Brand", "Size", "Color", "Material")  # what every listing needs; shown as "not confirmed" when the seller never gave them


def profile_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pure. `rows` are the seller's statements oldest -> newest."""
    latest: dict[str, dict[str, Any]] = {}
    notes: list[dict[str, Any]] = []
    name: str | None = None
    for r in rows:
        value = " ".join(str(r["value"]).split())
        if not value:
            continue
        kind, attr = r["type"], r.get("name")
        if kind == "ATTRIBUTE" and attr and str(attr).casefold() == cmo_chat.PRODUCT_NAME_ATTRIBUTE:
            name = value
            continue
        if kind == "FREE_TEXT":
            notes.append({"value": value, "at": r["at"]})
            continue
        label = {"BRAND": "Brand", "CATEGORY": "Category"}.get(kind) or (str(attr).replace("_", " ").title() if attr else None)
        if not label:
            continue
        source = "confirmed by you from a photo reading" if r.get("fromPhoto") else "you told me"
        entry = latest.get(label.casefold())
        if entry is None:
            latest[label.casefold()] = {"label": label, "value": value, "source": source, "at": r["at"], "history": []}
        elif entry["value"].casefold() != value.casefold():
            entry["history"].append({"value": entry["value"], "at": entry["at"]})
            entry.update(value=value, source=source, at=r["at"])
        else:
            entry.update(source=source, at=r["at"])
    return {"name": name, "attributes": list(latest.values()), "notes": notes, "notConfirmed": [d for d in STANDARD_DETAILS if d.casefold() not in latest]}


def profile_text(profile: Mapping[str, Any], fallback_name: str) -> str:
    name = profile.get("name") or fallback_name
    if not profile["attributes"] and not profile["notes"] and not profile.get("name"):
        return f"I have no saved details for {name} yet. Tell me about it, for example by asking for titles, and I will keep what you confirm."
    lines = [f"I found your saved profile for {name}. These are your own statements; Metrion has not checked them:"]
    for a in profile["attributes"]:
        line = f"• {a['label']}: {a['value']} ({a['source']}, {a['at'].date().isoformat()})"
        if a["history"]:
            line += "; earlier you said " + ", ".join(f"{h['value']} ({h['at'].date().isoformat()})" for h in a["history"])
        lines.append(line)
    for n in profile["notes"][-3:]:
        lines.append(f"• Note: {n['value']} ({n['at'].date().isoformat()})")
    if profile["notConfirmed"]:
        lines.append("Not confirmed yet: " + ", ".join(profile["notConfirmed"]) + ". I will not state any of these in a listing until you confirm them.")
    lines.append("Tell me if anything has changed; a new statement replaces the old one for new writing, and the old one stays in your history.")
    return "\n".join(lines)


_ASK = (
    r"(?:do you )?(?:remember|recall)|what do you (?:know|remember|have saved) about|show (?:me )?what you know about|"
    r"(?:show (?:me )?)?(?:the |my )?(?:saved )?(?:product )?profile (?:of|for)|show (?:me )?the saved (?:profile|details) (?:of|for)"
)
_PROFILE_Q = re.compile(rf"^\W*(?:hi (?:ceo)?\W*|hello\W*)?(?:{_ASK})\s+(?:my|our|the)\s+(?P<p>[\w][\w \-']{{1,60}}?)\s*\??\W*$", re.IGNORECASE)
_NOT_A_PRODUCT = frozenset({"business", "store", "shop", "company", "brand", "goal", "goals", "niche", "account", "competitors", "competitor", "expenses", "sales", "profit", "data", "reports"})


def profile_question(text: str) -> str | None:
    """The product words in "remember my AquaNest bottle?", else None. A question about the business itself is not a product question."""
    m = _PROFILE_Q.match(" ".join(text.split()))
    if not m:
        return None
    hint = m.group("p").strip()
    words = set(re.findall(r"[a-z0-9]+", hint.casefold()))
    return None if words <= _NOT_A_PRODUCT else hint


def profile_reply(tenant_id: UUID, hint: str) -> str:
    try:
        found = cmo_chat.resolve_product(tenant_id, hint)
        if found is None:
            names = cmo_chat_repo.product_names(tenant_id)
            if not names:
                return f"I have no saved product details yet, so there is no profile for “{hint}”. Tell me about it and I will keep what you confirm."
            return "Which product do you mean? I have saved details for: " + "; ".join(f"“{n}”" for _, n in names[:5]) + "."
        sku, name = found
        return profile_text(profile_from_rows(cmo_chat_repo.profile_rows(tenant_id, sku)), name)
    except Exception:  # noqa: BLE001
        logger.exception("could not read the product profile")
        return "I could not read that profile just now, so I have not answered. Nothing was changed."


def direct_reply(ctx: Any, text: str) -> str | None:
    hint = profile_question(text)
    return profile_reply(ctx.tenant_id, hint) if hint is not None else None
