"""CMO 3.0 M7 in the CEO chat: "show my listing history", "compare version 1 and version 3", "what changed in my latest listing?", "what should I improve next?" (docs/specs/ceo-cmo-delegation.md
section 6.17). Free, no model, nothing generated and nothing changed. The CEO works out WHICH product, marketplace and versions the seller means; when the words leave that open it asks one short
question and keeps the question in the conversation so the seller's next message answers it. The CMO side (`services.cmo_history`) does the exact comparison; this module only chooses what to
fetch and says it in plain words. Typed text never approves anything here.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from slim_cmo.history import ask as asks

from backend.repositories import investigation_repo as inv_repo

logger = logging.getLogger(__name__)
MP_NAME = {"AMAZON": "Amazon", "FLIPKART": "Flipkart", "MEESHO": "Meesho"}
NO_HISTORY = "You do not have a saved listing yet. Ask me to “write my complete listing” and I will plan it for your approval first. Nothing is saved until you approve."
FAILED = "I could not read your listing history just now. Nothing was changed or used up. Please try again."
FOLLOWUP = re.compile(r"^\s*(?:the\s+)?(?:(?:for\s+)?(?:my\s+)?[\w -]{1,60}|\d{1,3}(?:\s*(?:and|&|,|to)\s*\d{1,3})?|version\s*\d{1,3}(?:\s*(?:and|&|,|to|vs)\s*(?:version\s*)?\d{1,3})?)\s*[.!?]?\s*$", re.IGNORECASE)


# ------------------------------------------------------------------------------------------------ conversation context
def _last_card(tenant: UUID, investigation_id: UUID) -> dict[str, Any] | None:
    """The newest CEO answer's card when it is a listing-history card (else None): the follow-up context, and an open question to answer."""
    try:
        for m in reversed(inv_repo.list_messages(tenant, investigation_id)):
            if m["role"] != "CEO":
                continue
            c = m.get("choices")
            return c if isinstance(c, dict) and c.get("kind") == "LISTING_HISTORY" else None
    except Exception:  # noqa: BLE001
        logger.exception("could not read the conversation for listing-history context")
    return None


def _scope(card: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    """The product and marketplace the previous history card was about (a comparison and a suggestion carry them at the top; a version carries them inside; a history carries its filters)."""
    if not card:
        return None, None
    v = card.get("version") if isinstance(card.get("version"), dict) else {}  # (a CLARIFY card carries the envelope version number here)
    f = card.get("filters") if isinstance(card.get("filters"), dict) else {}
    return card.get("sku") or v.get("sku") or f.get("sku"), card.get("marketplace") or v.get("marketplace") or f.get("marketplace")


def _is_answer(text: str, card: Mapping[str, Any]) -> bool:
    """Is this short message the answer to the question in `card`? Only if it names one of the offered choices, a marketplace, or (when the question was about versions) gives version numbers; a new
    topic typed after the question is never swallowed as an answer."""
    t = text.casefold()
    if len(t.split()) > 6:  # a real answer is a few words; a sentence is a new request
        return False
    opts = [str(o.get("label", "")).casefold() for o in card.get("options") or []]
    if any(o and (o in t or (len(t.strip(" .!?")) >= 3 and t.strip(" .!?") in o)) for o in opts):
        return True
    n = len(t.split())
    if n <= 3 and any(re.search(rf"\b{k}\b", t) for k in asks.MARKETPLACES):
        return True
    return n <= 6 and bool(re.search(r"\d", t)) and any(o.startswith("version") for o in opts)


def _mp_word(mp: str) -> str:
    return MP_NAME.get(mp, mp.title())


def _on(card: Mapping[str, Any]) -> tuple[str | None, str | None]:
    return card.get("sku"), card.get("marketplace")


def _clarify(question: str, ask: asks.Ask, options: Sequence[Mapping[str, Any]], investigation_id: UUID) -> tuple[str, dict[str, Any]]:
    return question, {"version": 1, "kind": "LISTING_HISTORY", "view": "CLARIFY", "investigationId": str(investigation_id), "question": question, "options": list(options),
                      "ask": {"kind": ask.kind, "productHint": ask.product_hint, "marketplace": ask.marketplace, "versions": list(ask.versions), "relative": ask.relative}}


# ------------------------------------------------------------------------------------------------ choosing the versions
def _pick(versions: Sequence[Mapping[str, Any]], number: int | None, relative: str | None) -> Mapping[str, Any] | None:
    by = {v["number"]: v for v in versions}
    if number is not None:
        return by.get(number)
    if relative == "PREVIOUS":
        return by.get(max(by) - 1) if len(by) > 1 else None
    if relative == "ORIGINAL":
        return by[min(by)]
    return by[max(by)]


def _vlabel(v: Mapping[str, Any]) -> str:
    return f"version {v['number']} ({str(v['createdAt'])[:10]}, {v['sourceText'].lower() if v['source'] != 'ORIGINAL' else 'the original'})"


# ------------------------------------------------------------------------------------------------ the answer in words
def _history_text(card: Mapping[str, Any]) -> str:
    if card["empty"]:
        return NO_HISTORY
    lines = []
    for g in card["groups"]:
        lines.append(f"{g['product'] or 'Your product'} on {_mp_word(g['marketplace'])}: {g['versionCount']} version{'s' if g['versionCount'] != 1 else ''}, latest is version {g['latestNumber']}.")
    shown = card["versions"][:6]
    lines += [f"• Version {v['number']} — {v['createdAt'][:10]} — {v['sourceText']}" + (" — approved for use" if v["states"]["approvedForUse"]["done"] else "") for v in shown]
    if card["total"] > len(shown):
        lines.append(f"…and {card['total'] - len(shown)} more in the history below.")
    return "\n".join(lines) + "\nApproved for use only records your decision in Metrion; Metrion cannot see which version is live on a marketplace."


def _version_text(card: Mapping[str, Any]) -> str:
    v = card["version"]
    a = card["audit"]
    sec = card["sections"]
    lead = f"{v['product'] or 'Your product'} on {_mp_word(v['marketplace'])}, version {v['number']} of {card['versionCount']} ({v['sourceText']}, {str(v['createdAt'])[:10]})."
    approved = "approved for use in Metrion" if v["states"]["approvedForUse"]["done"] else "not approved for use"
    audit = f"Its own saved audit: {a['verdict'].replace('_', ' ').lower()}." if a else "It has no saved audit yet."
    return f"{lead}\nTitle: {sec['title']}\nIt is {approved}. {audit} Nothing is published by Metrion."


def _kw_line(rows: Sequence[Mapping[str, Any]]) -> str:
    return "; ".join(f"“{r['keyword']}” ({', '.join(r['before']) or 'not used'} → {', '.join(r['after']) or 'not used'})" for r in rows)


def _compare_text(card: Mapping[str, Any], focus: str) -> str:
    o, n = card["older"], card["newer"]
    head = f"Version {o['number']} → version {n['number']} ({card['product'] or 'your product'}, {_mp_word(card['marketplace'])})."
    if card["identical"]:
        return head + " The two versions have identical text."
    rows = card["keywordMovement"]["rows"]
    by = lambda r: [x for x in rows if x["result"] == r]  # noqa: E731
    if focus == asks.KEYWORDS_REMOVED:
        rem = by("REMOVED")
        moved = by("MOVED")
        return head + (f" Removed: {_kw_line(rem)}." if rem else " No keyword was removed.") + (f" Moved, not removed: {_kw_line(moved)}." if moved else "")
    if focus == asks.KEYWORDS_ADDED:
        add = by("ADDED")
        return head + (f" Added: {_kw_line(add)}." if add else " No keyword was added.")
    if focus == asks.AUDIT_CHANGES:
        a = card["audit"]
        if not a["available"]:
            return head + " One of the versions has no saved audit, so I cannot compare them."
        return head + f" Audit: {len(a['new'])} new issue(s), {len(a['resolved'])} resolved, {len(a['unresolved'])} still unresolved. Verdict {str(a['olderVerdict']).replace('_', ' ').lower()} → {str(a['newerVerdict']).replace('_', ' ').lower()}."
    if focus == asks.CLAIMS:
        c = card["claims"]
        if not c["available"]:
            return head + " The newer version has no saved audit, so I cannot say."
        if not c["new"]:
            return head + " The revision introduced no claim that your confirmed facts do not support."
        return head + " New claims your confirmed facts do not support: " + "; ".join(f"{x['section'].lower()}: “{x['claim'] or x['why']}”" for x in c["new"]) + ". Remove them or confirm them first."
    sc = card["sectionsChanged"]
    changed = [k for k, v in {"title": sc["title"], "bullets": sc["bullets"], "description": sc["description"], "keywords": sc["keywords"], "backend terms": sc["backendTerms"], "hashtags": sc["hashtags"]}.items() if v]
    kc = card["keywordMovement"]["counts"]
    bits = [f"Changed: {', '.join(changed)}."]
    if sc["title"]:
        bits.append(f"Title length {card['title']['oldLength']['characters']} → {card['title']['newLength']['characters']} characters.")
    bits.append(f"Keywords: {kc['ADDED']} added, {kc['REMOVED']} removed, {kc['MOVED']} moved, {kc['RETAINED']} kept.")
    if card["audit"]["available"]:
        bits.append(f"Audit: {len(card['audit']['new'])} new, {len(card['audit']['resolved'])} resolved, {len(card['audit']['unresolved'])} unresolved.")
    if card["claims"].get("new"):
        bits.append(f"{len(card['claims']['new'])} new claim(s) your confirmed facts do not support.")
    return head + " " + " ".join(bits) + " These are differences in the saved text; they do not show a version performs better."


def _recommend_text(card: Mapping[str, Any]) -> str:
    if card["state"] == "NO_EVIDENCE":
        return card["message"]
    if not card["recommendations"]:
        return f"For version {card['versionNumber']}: {card['message']}"
    lines = [f"• {r['recommendation']} ({r['section'].lower().replace('_', ' ')}): {r['reason']} {r['nextAction']}" for r in card["recommendations"][:5]]
    return (f"What I would look at next for version {card['versionNumber']}, from your saved audit, confirmed facts and researched keywords:\n" + "\n".join(lines)
            + "\nThese are suggestions for you to decide. They say nothing about search volume, ranking, demand or sales.")


# ------------------------------------------------------------------------------------------------ the entry point
def reply(ctx: Any, text: str, investigation_id: UUID) -> tuple[str, dict[str, Any] | None] | None:
    """A code-written answer for a listing-history request, or None when the message is not one (it then goes on to the rest of the CEO unchanged)."""
    from backend.ceo import cmo_chat  # noqa: PLC0415 - the product matcher lives with the other CMO chat helpers
    from backend.services import cmo_history, cmo_runtime  # noqa: PLC0415

    tenant, user = ctx.tenant_id, ctx.app_user_id
    prior = _last_card(tenant, investigation_id)
    pending = prior.get("ask") if isinstance(prior, dict) and prior.get("view") == "CLARIFY" and isinstance(prior.get("ask"), dict) else None
    ask = asks.parse(text, in_context=prior is not None)
    if (ask is None or ask.kind == asks.VERSION and not ask.relative) and pending is not None and FOLLOWUP.match(text) and _is_answer(text, prior):  # the seller's answer to the question I asked ("version 1 and 3" alone is an answer, not a new request)
        p = pending
        nums = tuple(int(x) for x in re.findall(r"\d{1,3}", text))[:2]
        mp = next((v for k, v in asks.MARKETPLACES.items() if re.search(rf"\b{k}\b", text.casefold())), None) or p.get("marketplace")
        ask = asks.Ask(p["kind"], asks.hint(re.sub(r"\d+", " ", text.casefold())) or p.get("productHint"), mp, nums or tuple(p.get("versions") or ()), None if nums else p.get("relative"))
    if ask is None:
        return None
    try:
        return _answer(ctx, tenant, user, ask, prior, investigation_id, cmo_chat, cmo_history, cmo_runtime)
    except cmo_history.HistoryRefused as exc:
        return exc.detail, None
    except Exception:  # noqa: BLE001
        logger.exception("listing history request failed")
        return FAILED, None


def _answer(ctx: Any, tenant: UUID, user: UUID, ask: asks.Ask, prior: Mapping[str, Any] | None, inv: UUID, cmo_chat: Any, cmo_history: Any, cmo_runtime: Any) -> tuple[str, dict[str, Any] | None]:
    everything = cmo_history.history(tenant, limit=cmo_history.MAX_PAGE)
    if everything["empty"]:
        return NO_HISTORY, None
    groups = everything["groups"]
    sku: str | None = None
    if ask.product_hint:
        found = cmo_chat.resolve_product(tenant, ask.product_hint)
        sku = found[0] if found else None
        if sku is None or not any(g["sku"] == sku for g in groups):
            names = sorted({g["product"] or g["sku"] for g in groups})
            return _clarify(f"I do not have a saved listing for “{ask.product_hint}”. Which product do you mean? You have listings for: " + "; ".join(f"“{n}”" for n in names[:6]) + ".", ask,
                            [{"label": n, "sku": next(g["sku"] for g in groups if (g["product"] or g["sku"]) == n)} for n in names[:6]], inv)
    elif _scope(prior)[0]:
        sku = _scope(prior)[0]
    skus = sorted({g["sku"] for g in groups})
    if sku is None and len(skus) == 1:
        sku = skus[0]
    if sku is None:
        if ask.kind == asks.HISTORY or ask.kind == asks.APPROVED:
            pass  # the whole account is a fine answer for these
        else:
            names = sorted({(g["product"] or g["sku"], g["sku"]) for g in groups})
            return _clarify("Which product do you mean? You have listings for: " + "; ".join(f"“{n}”" for n, _ in names[:6]) + ".", ask, [{"label": n, "sku": s} for n, s in names[:6]], inv)
    mine = [g for g in groups if sku is None or g["sku"] == sku]
    mp = ask.marketplace or (_scope(prior)[1] if _scope(prior)[0] == sku and not ask.product_hint else None)
    if mp and not any(g["marketplace"] == mp for g in mine):
        return f"You have no saved {_mp_word(mp)} listing for that product.", None
    if mp is None and ask.kind not in (asks.HISTORY, asks.APPROVED):
        mps = sorted({g["marketplace"] for g in mine})
        if len(mps) > 1:
            return _clarify("Which marketplace do you mean — " + " or ".join(_mp_word(m) for m in mps) + "?", ask, [{"label": _mp_word(m), "marketplace": m} for m in mps], inv)
        mp = mps[0] if mps else None
    rt = cmo_runtime.build_runtime()

    if ask.kind in (asks.HISTORY, asks.APPROVED):
        card = cmo_history.history(tenant, sku=sku, marketplace=mp, limit=20)
        card["investigationId"] = str(inv)
        if ask.kind == asks.APPROVED:
            ok = [v for v in card["versions"] if v["states"]["approvedForUse"]["done"]]
            card["focus"] = "APPROVED"
            if not ok:
                return "None of your saved versions is approved for use yet. The latest version is not assumed to be approved, and approval only records your decision in Metrion.", card
            return "Approved for use in Metrion: " + "; ".join(f"{(v['product'] or 'your product')} on {_mp_word(v['marketplace'])}, version {v['number']}" for v in ok[:6]) + ". Metrion cannot see which version, if any, is live.", card
        return _history_text(card), card

    ver = cmo_history.history(tenant, sku=sku, marketplace=mp, limit=cmo_history.MAX_PAGE)  # newest first
    versions = sorted(ver["versions"], key=lambda v: v["number"])
    if not versions:
        return NO_HISTORY, None

    if ask.kind == asks.VERSION:
        num = ask.versions[0] if ask.versions else None
        v = _pick(versions, num, ask.relative)
        if v is None:
            if ask.relative == "PREVIOUS" and len(versions) == 1:
                return "You have only one saved version of this listing, so there is no earlier one.", None
            return _clarify(f"I could not find version {num}. You have versions 1 to {versions[-1]['number']}. Which one do you want?", ask, [{"label": f"Version {x['number']}", "number": x["number"]} for x in versions[-6:]], inv)
        card = cmo_history.version_detail(tenant, user, rt, UUID(v["id"]))
        card["investigationId"] = str(inv)
        return _version_text(card), card

    latest = versions[-1]
    if ask.kind == asks.IMPROVE:
        target = _pick(versions, ask.versions[0] if ask.versions else None, None) or latest
        card = cmo_history.recommendations(tenant, user, rt, UUID(target["id"]))
        card["investigationId"] = str(inv)
        return _recommend_text(card), card

    if len(versions) == 1:
        if ask.kind == asks.WHY_REVISED:
            card = cmo_history.version_detail(tenant, user, rt, UUID(latest["id"]))
            card["investigationId"] = str(inv)
            return "This listing has only one version, the one Metrion first wrote, so there is no revision to explain.", card
        return "You have only one saved version of this listing, so there is nothing to compare yet. Once you edit or rewrite a section, the new version is saved next to it.", None

    older_v: Mapping[str, Any] | None
    newer_v: Mapping[str, Any] | None
    if ask.kind == asks.COMPARE:
        if len(ask.versions) == 2:
            older_v, newer_v = _pick(versions, ask.versions[0], None), _pick(versions, ask.versions[1], None)
        elif len(ask.versions) == 1:
            return _clarify(f"Which version do you want to compare with version {ask.versions[0]}?", ask, [{"label": f"Version {x['number']}", "number": x["number"]} for x in versions[-6:]], inv)
        elif len(versions) == 2 or ask.relative != "OLD_NEW":
            older_v, newer_v = versions[-2], versions[-1]
        else:  # "my old and new listings" with several versions: old could be the original or the one before
            return _clarify(f"You have {len(versions)} versions. Which two do you want to compare? For example “compare version 1 and version {versions[-1]['number']}”.", ask,
                            [{"label": f"Version {x['number']}", "number": x["number"]} for x in versions[-6:]], inv)
        if older_v is None or newer_v is None:
            return _clarify(f"One of those versions is not saved. You have versions 1 to {versions[-1]['number']}. Which two do you want?", ask, [{"label": f"Version {x['number']}", "number": x["number"]} for x in versions[-6:]], inv)
    else:  # what changed / why / claims / keywords / audit: the newest version against the one it came from
        newer_v = _pick(versions, ask.versions[0] if ask.versions else None, ask.relative if ask.relative in ("LATEST",) else None) or latest
        parent = next((x for x in versions if x["id"] == newer_v.get("parentId")), None) or next((x for x in reversed(versions) if x["number"] < newer_v["number"]), None)
        if parent is None:
            return "That is the first version, so there is nothing before it to compare with.", None
        older_v = parent
    card = cmo_history.compare(tenant, user, rt, UUID(older_v["id"]), UUID(newer_v["id"]))
    card["investigationId"] = str(inv)
    card["focus"] = ask.kind
    if ask.kind == asks.WHY_REVISED:
        n = newer_v
        why = card["newer"]["sourceText"] + (f" (changed {n['changedSection'].lower().replace('_', ' ')})" if n.get("changedSection") else "")
        return (f"Version {n['number']} was made as: {why}. Metrion records how and where a version changed, not your reason for changing it. " + _compare_text(card, asks.CHANGES)), card
    return _compare_text(card, ask.kind), card
