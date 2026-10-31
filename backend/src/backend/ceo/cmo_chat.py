"""CMO 3.0 M0 - the CEO chat steps that were missing around Slim CMO (docs/CMO-3.0/CMO_IMPLEMENTATION_MAP.md M0; docs/specs/ceo-cmo-delegation.md section 6.11).

What this module IS: CODE that (1) gives a product a stable identity (`product_sku`) so what the seller confirmed about it is saved against it and found again in the next
conversation, (2) reads the title sets the seller can choose from and parses their choice, (3) matches a title the seller types to one they already approved, (4) records a
photo hint the seller confirmed, and (5) answers "is my bottle dishwasher safe?" from the seller's own saved facts.

What it is NOT: it asks no model anything, computes no money, runs no marketplace write, and chooses nothing for the seller. A title is only ever recorded from the seller's own
answer (a click, a number, or their own words); a fact is only ever reported if the seller gave it. Missing = "not confirmed", never a guess.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from backend.repositories import cmo_chat_repo

logger = logging.getLogger(__name__)

SKU_MAX = 120
PRODUCT_NAME_ATTRIBUTE = "product_name"  # the attribute name `slim_cmo.service.generate` stores the product name under
COPY_NOTE = "Copying or marking a title as used only records an action in Metrion. It does not prove the title was published on any marketplace."


# ------------------------------------------------------------------------------------------------ product identity
def product_sku(name: str | None) -> str | None:
    """A stable identity for a product the seller named in chat: the name lower-cased and reduced to letters, digits and hyphens. The same name always gives the same value, so facts
    the seller confirmed are found again; two different names never collide by accident. None for a name too short to identify anything."""
    folded = unicodedata.normalize("NFKC", str(name or "")).casefold()
    slug = re.sub(r"[^\w]+", "-", folded, flags=re.UNICODE).replace("_", "-").strip("-")[:SKU_MAX].strip("-")
    return slug if len(slug) >= 2 else None


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.casefold()))


_FILLER = frozenset({"my", "our", "the", "a", "an", "of", "for", "water"})


def resolve_product(tenant_id: UUID, hint: str | None) -> tuple[str, str] | None:
    """(sku, name) of the ONE product the seller already saved that `hint` names: exactly the same name, else words that appear in exactly one saved name. Two candidates or none = None
    (the seller is asked); nothing is guessed."""
    if not hint or not product_sku(hint):
        return None
    try:
        names = cmo_chat_repo.product_names(tenant_id)
    except Exception:  # noqa: BLE001
        logger.exception("could not read product names")
        return None
    exact = [(s, n) for s, n in names if s == product_sku(hint)]
    if exact:
        return exact[0]
    want = _tokens(hint) - _FILLER
    loose = [(s, n) for s, n in names if want and want <= _tokens(n)]
    return loose[0] if len(loose) == 1 else None


def _slug(attribute: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", attribute.casefold()).strip("_")


def saved_answers(tenant_id: UUID, product: str | None) -> tuple[dict[str, str], str | None]:
    """What the seller told Metrion about this product before, as answers to the writing questions (`fact_*`, `category_hint`), newest statement winning, so they are not asked
    again. They are the seller's own statements; the plan card shows them and the seller approves the plan, which is where they are confirmed again."""
    found = resolve_product(tenant_id, product)
    sku = found[0] if found else product_sku(product)
    if not sku:
        return {}, None
    try:
        rows = cmo_chat_repo.saved_facts(tenant_id, sku)
    except Exception:  # noqa: BLE001 - remembering is a convenience; the question is still asked
        logger.exception("could not read saved CMO facts")
        return {}, None
    out: dict[str, str] = {}
    for r in rows:  # oldest -> newest: a later statement replaces an earlier one
        value = " ".join(str(r["value"]).split())[:200]
        if not value:
            continue
        if r["type"] == "BRAND":
            out["fact_brand"] = value
        elif r["type"] == "CATEGORY":
            out["category_hint"] = value
        elif r["type"] == "ATTRIBUTE" and r["name"] and str(r["name"]).casefold() != PRODUCT_NAME_ATTRIBUTE and _slug(str(r["name"])):
            out[f"fact_{_slug(str(r['name']))}"] = value
    return out, (found[1] if found else None)


def saved_answers_note(product: str | None, answers: Mapping[str, str]) -> str | None:
    names = sorted({k[len("fact_"):].replace("_", " ") for k in answers if k.startswith("fact_")} | ({"category"} if "category_hint" in answers else set()))
    if not names:
        return None
    return (f"I reused what you told me before about {product}: {', '.join(names)}. They are listed on the plan; tell me if anything has changed.")


# ------------------------------------------------------------------------------------------------ choosing a title
_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_NUM = r"(\d|one|two|three|four|five|first|second|third|fourth|fifth)"
_PICK = re.compile(rf"(?:\b(?:option|title|number|no\.?|choice)\s*#?\s*|#){_NUM}\b", re.IGNORECASE)
_BARE = re.compile(rf"^\W*(?:option |title |number |no\.? |#)?{_NUM}\W*$", re.IGNORECASE)
_NOT_A_TITLE = frozenset({"yes", "no", "ok", "okay", "sure", "fine", "approve", "approved", "go ahead", "correct", "right", "done"})
MIN_EDIT_WORDS = 4  # a typed title shorter than this is far more likely a reply than a title


def pick_index(text: str, count: int) -> int | None:
    """1-based position the seller named ("2", "option three", "use title 4"), or None. A number outside the list is not a pick."""
    t = " ".join(text.split())
    m = _BARE.match(t) or (_PICK.search(t) if len(t.split()) <= 8 else None)
    if not m:
        return None
    raw = m.group(1).casefold()
    n = int(raw) if raw.isdigit() else _WORDS[raw]
    return n if 1 <= n <= count else None


def parse_choice(text: str, options: Sequence[Mapping[str, Any]]) -> tuple[str, Any] | None:
    """("OPTION", option) when the seller named one of the options, ("EDIT", text) when they typed a title of their own, else None. Never picks for them."""
    idx = pick_index(text, len(options))
    if idx is not None:
        return "OPTION", options[idx - 1]
    t = " ".join(text.split())
    if t.casefold().strip(" .!") in _NOT_A_TITLE or t.endswith("?") or len(t.split()) < MIN_EDIT_WORDS:
        return None
    return "EDIT", t


def title_sets(tenant_id: UUID) -> list[dict[str, Any]]:
    try:
        return cmo_chat_repo.recent_title_sets(tenant_id)
    except Exception:  # noqa: BLE001
        logger.exception("could not read title sets")
        return []


def choose_set(sets: Sequence[Mapping[str, Any]], marketplace: str | None) -> Mapping[str, Any] | None:
    if marketplace:
        return next((s for s in sets if s["marketplace"] == marketplace.upper()), None)
    return sets[0] if len(sets) == 1 else None


def options_text(chosen: Mapping[str, Any]) -> str:
    return "\n".join(f"{o['rank']}. {o['text']}" for o in chosen["options"])


def matching_approval(tenant_id: UUID, product: str | None, marketplace: str | None, title: str | None) -> str | None:
    """The id of the approval whose text is exactly the title the seller gave for this product and marketplace (case and spacing aside), so the copy is grounded on the APPROVED
    title and not on a pasted copy of it. None when the seller typed some other title: that stays a seller-supplied title."""
    sku = product_sku(product)
    if not (sku and marketplace and title):
        return None
    want = " ".join(title.split()).casefold()
    try:
        for a in cmo_chat_repo.approved_titles(tenant_id, sku=sku, marketplace=marketplace.upper(), limit=10):
            if " ".join(a["text"].split()).casefold() == want:
                return a["approvalId"]
    except Exception:  # noqa: BLE001
        logger.exception("could not read approved titles")
    return None


def record_typed_title_approval(tenant_id: UUID, user_id: UUID, direct: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """N-05t: the seller confirmed the exact title they typed for a complete listing; this records their approval of it as its OWN row (`title_source = SELLER_TYPED`, no title-set generation, no
    unit, no model). Returns (approval id, None), or (None, the plain refusal). An identical title already approved for this product and marketplace is reused, never duplicated."""
    from backend.services import cmo_runtime  # noqa: PLC0415
    from slim_cmo.service.approve import ApprovalRefused  # noqa: PLC0415
    from slim_cmo.service.models import Actor  # noqa: PLC0415
    from slim_cmo.types import Marketplace  # noqa: PLC0415

    title, sku, name = str(direct.get("seller_title") or "").strip(), str(direct.get("sku") or product_sku(direct.get("product_name")) or ""), direct.get("product_name")
    if not (title and sku and direct.get("marketplace")):
        return None, None
    existing = matching_approval(tenant_id, name, str(direct["marketplace"]), title)
    if existing:
        return existing, None
    res = cmo_runtime.build_runtime().approvals.approve_typed_title(Actor(tenant_id, user_id), sku=sku, marketplace=Marketplace(str(direct["marketplace"]).upper()), text=title)
    if isinstance(res, ApprovalRefused):
        return None, f"I could not use that title: {res.detail}. Give me a different title, or ask me for title options first."
    return str(res.approval_id), None


def approved_title_text(tenant_id: UUID, product: str | None, marketplace: str | None) -> str | None:
    sku = product_sku(product)
    if not (sku and marketplace):
        return None
    try:
        rows = cmo_chat_repo.approved_titles(tenant_id, sku=sku, marketplace=marketplace.upper(), limit=1)
    except Exception:  # noqa: BLE001
        return None
    return rows[0]["text"] if rows else None


def approval_text(tenant_id: UUID, approval_id: str) -> str | None:
    try:
        return cmo_chat_repo.approval_text(tenant_id, UUID(approval_id))
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------------------------------ history
def approved_history_artefact(tenant_id: UUID, limit: int = 5) -> tuple[str, tuple[str, ...], str] | None:
    """The titles the seller chose, quoted, with what was recorded for each: the day, whether it was edited, and how many times it was copied or marked used. Copied, approved and
    live on a marketplace are three different things; the last one is never known to Metrion."""
    rows = cmo_chat_repo.approved_titles(tenant_id, limit=limit)
    if not rows:
        return None
    items: list[str] = []
    for r in rows:
        bits = [f"approved by you on {r['approvedAt'].date().isoformat()}"]
        if r["editedBySeller"]:
            bits.append("worded by you")
        if r["copied"] or r["markedUsed"]:
            bits.append(f"copied {r['copied']} time{'s' if r['copied'] != 1 else ''}, marked used {r['markedUsed']} time{'s' if r['markedUsed'] != 1 else ''}")
        where = f"{str(r['marketplace']).title()} - {r['label']}" if r.get("label") else str(r["marketplace"]).title()
        items.append(f"{where}: {r['text']} ({'; '.join(bits)})")
    return "Titles you chose", tuple(items), COPY_NOTE


# ------------------------------------------------------------------------------------------------ a photo hint the seller confirmed
def record_image_hints(ctx: Any, inputs: Mapping[str, Any]) -> list[str]:
    """Records each photo hint the seller confirmed by their own answer, as a new SELLER_PROVIDED fact attached to the product and linked to the reading (zero units, its own audit
    row). `inputs["image_hints"]` is written by the question loop only for answers the seller gave. Best-effort: a failure here never blocks the plan. Returns what was recorded."""
    hints, analysis_id = inputs.get("image_hints"), inputs.get("hint_analysis_id")
    sku = product_sku(inputs.get("product_name"))
    if not (isinstance(hints, list) and hints and analysis_id and sku):
        return []
    from backend.services import cmo_hints  # noqa: PLC0415

    return cmo_hints.record_confirmed_hints(ctx.tenant_id, ctx.app_user_id, analysis_id=str(analysis_id), sku=sku, hints=hints)


# ------------------------------------------------------------------------------------------------ "is my bottle dishwasher safe?"
_PROPERTY_WORDS = (
    r"dishwasher[- ]safe|microwave[- ]safe|freezer[- ]safe|leak[- ]?proof|spill[- ]?proof|insulated|waterproof|water[- ]resistant|bpa[- ]free|rust[- ]?proof|food[- ]grade|heat[- ]resistant|"
    r"unbreakable|shatter[- ]?proof|vacuum[- ]sealed|non[- ]toxic"
)
_PROPERTY_Q = re.compile(
    rf"^\W*(?:is|are|does|do|can)\s+(?:(?:my|our|the)\s+)?(?P<p>[\w][\w \-']{{0,60}}?)\s+(?:it\s+)?(?P<prop>{_PROPERTY_WORDS})\s*\??\W*$", re.IGNORECASE)
_PROPERTY_IT = re.compile(rf"^\W*(?:is|are|does|do|can)\s+(?:it|this|that)\s+(?P<prop>{_PROPERTY_WORDS})\s*\??\W*$", re.IGNORECASE)
_STEM = {"dishwasher": ("dishwasher",), "microwave": ("microwave",), "freezer": ("freezer",), "leak": ("leak", "spill"), "spill": ("leak", "spill"), "insulated": ("insulat", "vacuum", "thermal"),
         "waterproof": ("waterproof", "water resist"), "water": ("waterproof", "water resist"), "bpa": ("bpa",), "rust": ("rust",), "food": ("food grade", "food-grade"), "heat": ("heat",),
         "unbreakable": ("unbreakable", "shatter"), "shatter": ("unbreakable", "shatter"), "vacuum": ("vacuum", "insulat"), "non": ("toxic",)}


def property_question(text: str) -> tuple[str | None, str] | None:
    """(product words or None, the property asked about) for a yes/no question about a product property, else None."""
    t = " ".join(text.split())
    m = _PROPERTY_Q.match(t)
    if m:
        return m.group("p").strip(), m.group("prop").casefold().replace("-", " ")
    m = _PROPERTY_IT.match(t)
    return (None, m.group("prop").casefold().replace("-", " ")) if m else None


def property_reply(tenant_id: UUID, hint: str | None, prop: str, last_product: str | None = None) -> str:
    """The seller's own answer if they gave one, else an honest "not confirmed". Nothing is looked up elsewhere and nothing is assumed."""
    try:
        names = cmo_chat_repo.product_names(tenant_id)
    except Exception:  # noqa: BLE001
        logger.exception("could not read product names")
        return "I could not read your saved product details just now, so I have not answered. Nothing was changed."
    found = resolve_product(tenant_id, hint)
    matches = [found] if found else []
    if not matches and hint is None and last_product:
        matches = [(s, n) for s, n in names if s == product_sku(last_product)]
    if not matches and len(names) == 1:
        matches = names[:1]
    if len(matches) != 1:
        if not names:
            return (f"I have no saved product details yet, so I cannot say whether it is {prop}. Nothing is confirmed. Tell me about the product, for example by asking for titles, "
                    "and I will keep what you confirm.")
        listed = "; ".join(f"“{n}”" for _, n in names[:5])
        return f"Which product do you mean? I have saved details for: {listed}. I cannot say whether it is {prop} until I know which one."
    sku, name = matches[0]
    stems = _STEM.get(prop.split()[0], (prop.split()[0],))
    facts = cmo_chat_repo.saved_facts(tenant_id, sku)
    found = [f for f in facts if any(s in f"{f['name'] or ''} {f['value']}".casefold() for s in stems)]
    if found:
        f = found[-1]
        label = f"{f['name']}: " if f["name"] else ""
        return (f"For {name}, you told me: {label}{f['value']} (on {f['at'].date().isoformat()}). That is your own statement; Metrion has not checked it. "
                "I will only use it in a listing as you gave it.")
    return (f"That has not been confirmed for {name}. You have not told me it is {prop}, and I will not state it in any title, bullet point or description without your confirmation. "
            f"If you have tested it, tell me (for example, “it is {prop}, I tested it”) and I will use it exactly as you say.")


_COPIED_PUBLISHED = re.compile(r"\b(?:copy|copied|copying|mark(?:ed|ing)?(?: it)?(?: as)? used)\b.*\b(?:publish\w*|live|posted|uploaded|on (?:amazon|flipkart|meesho))\b", re.IGNORECASE)


def direct_reply(ctx: Any, text: str, last_product: str | None = None) -> str | None:
    """A code-written answer for a question this module owns, else None (the message is routed as usual)."""
    if _COPIED_PUBLISHED.search(text) and text.rstrip().endswith("?"):
        return "No. " + COPY_NOTE + " Metrion never publishes for you and cannot see whether you did, so a title is only live on a marketplace once you put it there yourself."
    q = property_question(text)
    if q is None:
        return None
    return property_reply(ctx.tenant_id, q[0], q[1], last_product)


# ------------------------------------------------------------------------------------------------ the visual listing preview (CMO 3.0 M4)
def is_preview_request(text: str) -> bool:
    from backend.services import cmo_preview  # noqa: PLC0415

    return cmo_preview.is_preview_request(text)


def preview_reply(ctx: Any, investigation_id: UUID) -> tuple[str, dict[str, Any] | None]:
    """(the chat sentence, the PREVIEW card or None). Free; built from the seller's saved titles, facts and their own photo; the card carries everything the browser needs to switch
    marketplace, title and screen without another request."""
    from backend.services import cmo_preview  # noqa: PLC0415

    try:
        card = cmo_preview.build_card(ctx.tenant_id, ctx.app_user_id, investigation_id)
    except Exception:  # noqa: BLE001
        logger.exception("could not build the listing preview")
        return "I could not build the preview just now. Nothing was changed or used up. Please try again.", None
    return cmo_preview.chat_text(card), card


# ------------------------------------------------------------------------------------------------ buyer questions and listing readiness (CMO 3.0 M5)
def readiness_reply(ctx: Any, text: str, investigation_id: UUID) -> tuple[str, dict[str, Any] | None] | None:
    """A code-written answer for "What questions will buyers ask?", "Is my AquaNest bottle ready to list?" and for the seller's own answer to a question ("For my AquaNest bottle, dishwasher
    safe is: yes, I tested it"). Free; no model; None when the message is neither. The card carries both views for every marketplace so switching makes no request."""
    from backend.services import cmo_readiness  # noqa: PLC0415

    tenant = ctx.tenant_id
    st = cmo_readiness.parse_statement(text)
    if st is not None:
        hint, label, value = st
        found = resolve_product(tenant, hint)
        if found is None:
            return f"I could not tell which saved product “{hint}” is, so I saved nothing. Name it as you did when you gave me its details.", None
        try:
            cmo_readiness.save_fact(tenant, ctx.app_user_id, found[0], label, value)
        except ValueError as exc:
            return str(exc), None
        except Exception:  # noqa: BLE001
            logger.exception("could not save the seller's answer")
            return "I could not save that just now. Nothing was changed. Please try again.", None
        return cmo_readiness.saved_text(label, value), None
    kind = cmo_readiness.request_kind(text)
    if kind is None:
        return None
    hint = cmo_readiness.product_hint(text)
    found = resolve_product(tenant, hint) if hint else None
    if found is None:
        try:
            names = cmo_chat_repo.product_names(tenant)
        except Exception:  # noqa: BLE001
            logger.exception("could not read product names")
            return "I could not read your saved products just now, so I have not answered. Nothing was changed.", None
        if not names:
            return "I have no saved product details yet, so there is nothing to assess. Ask me to write titles for a product and tell me about it first.", None
        if len(names) > 1 or hint:
            return "Which product do you mean? I have saved details for: " + "; ".join(f"“{n}”" for _, n in names[:5]) + ".", None
        found = names[0]
    try:
        card = cmo_readiness.build_card(ctx, investigation_id, found[0], found[1], kind)
    except Exception:  # noqa: BLE001
        logger.exception("could not build the readiness card")
        return "I could not build that just now. Nothing was changed or used up. Please try again.", None
    return cmo_readiness.chat_text(card), card


# ------------------------------------------------------------------------------------------------ CMO 3.0 M6: the complete listing
def full_listing_refusal(tenant_id: UUID, direct: Mapping[str, Any]) -> str | None:
    """The plain reason a complete listing cannot be planned yet, else None (the same preflight the handler runs, before any plan card exists: nothing is charged or saved on a refusal)."""
    from backend.services import cmo_listing  # noqa: PLC0415

    return cmo_listing.chat_refusal(tenant_id, direct)


def listing_reply(ctx: Any, text: str) -> tuple[str, dict[str, Any] | None] | None:
    """CMO 3.0 M6: the seller's own section edit, or "show my listing" (free). None when the message is neither."""
    from backend.services import cmo_listing  # noqa: PLC0415

    return cmo_listing.chat_reply(ctx, text)


def full_listing_plan_lines(tenant_id: UUID, slots: Mapping[str, Any]) -> tuple[list[str], str | None]:
    """CMO 3.0 M6: the marketplace-rules sentence for the plan card (and one short compact line). Empty when it cannot be worked out; never an invented rule statement."""
    from backend.services import cmo_listing  # noqa: PLC0415

    return cmo_listing.plan_lines(tenant_id, slots)


def rewrite_prepare(tenant_id: UUID, user_id: UUID, direct: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """CMO 3.0 M6 (Q26): (the closed slots of the rewrite plan, None) or (None, the plain reason it cannot be planned), checked BEFORE the plan card: the seller's latest saved listing for the
    product and marketplace, the section, and a topic their confirmed facts carry. Nothing is charged or saved."""
    from backend.services import cmo_listing  # noqa: PLC0415

    return cmo_listing.chat_rewrite_prepare(tenant_id, user_id, direct)


def rewrite_prefill(text: str) -> dict[str, str]:
    """The section and topic already named in "rewrite bullet 3 to mention wide opening" (offered to the same parsers as a typed answer)."""
    from backend.services import cmo_listing  # noqa: PLC0415

    return cmo_listing.rewrite_prefill(text)


def title_step_inputs(done_inputs: Mapping[str, Any], anchor: str) -> dict[str, Any] | None:
    """N-05b: the seller chose "write title options for me first" at the title question of a complete-listing request. The title set is planned for THIS product and marketplace, and carries the
    server-side listing marker (`listing_workflow`, CEO-only: never a slot of the CMO action and never read from text). None when the product or marketplace is not known."""
    name, mp = done_inputs.get("product_name"), done_inputs.get("marketplace")
    sku = product_sku(name)
    if not (name and mp and sku):
        return None
    return {"product_name": str(name), "sku": sku, "marketplaces": [str(mp)], "request_key": f"ceo-{anchor}-titles", "listing_workflow": True}


def listing_continuation(tenant_id: UUID, generation_id: UUID) -> dict[str, str] | None:
    """After the seller approved a title from a set that was written inside a complete-listing request, the facts that request already has (product, marketplace, the approved title), so the
    request continues with its remaining questions. None for any other title set."""
    if cmo_chat_repo.title_set_workflow(tenant_id, generation_id) != "FULL_LISTING":
        return None
    pm = cmo_chat_repo.title_set_product(tenant_id, generation_id)
    if pm is None:
        return None
    sku, mp = pm
    label = cmo_chat_repo.product_label(tenant_id, sku)
    approved = approved_title_text(tenant_id, label, mp) if label else None
    return {"product_name": label, "marketplace": mp, "seller_title": approved} if label and approved else None


def title_step_rules_sentence(tenant_id: UUID, marketplace: str) -> str:
    """The plain sentence about marketplace rules for the title step's plan card (best-effort: a failed lookup adds nothing and never invents a rule statement)."""
    try:
        from backend.services import cmo_listing, cmo_runtime  # noqa: PLC0415
        from slim_cmo.types import Marketplace  # noqa: PLC0415

        return cmo_listing.rules_state(tenant_id, cmo_runtime.build_runtime(), Marketplace(marketplace))[1]
    except Exception:  # noqa: BLE001
        logger.exception("could not describe the marketplace rules for the title step")
        return ""


@contextmanager
def title_step_scope(plan: Mapping[str, Any]) -> Iterator[None]:
    """N-16a: runs the frozen title-set leg of a complete-listing request with the server-side workflow marker. The marker comes from the stored plan (frozen, hash-bound), never from a request."""
    follow = plan.get("followup") or {}
    if plan.get("route_key") == "cmo.generate_title_sets" and follow.get("workflow") == "FULL_LISTING":
        from backend.services import cmo_listing  # noqa: PLC0415

        with cmo_listing.full_listing_workflow():
            yield
    else:
        yield


def title_step_blocked(tenant_id: UUID, marketplace: str) -> str | None:
    """The plain reason the title step of a complete-listing request cannot run (no verified marketplace rule and unverified drafts are off), told BEFORE any plan card exists so the seller is
    never asked to approve a plan that can only be refused. None when it can run, or when the lookup failed (the run then refuses safely on its own)."""
    try:
        from backend.services import cmo_listing, cmo_runtime  # noqa: PLC0415
        from slim_cmo.types import Marketplace  # noqa: PLC0415

        state, sentence = cmo_listing.rules_state(tenant_id, cmo_runtime.build_runtime(), Marketplace(marketplace))
        return sentence if state == "BLOCKED" else None
    except Exception:  # noqa: BLE001
        logger.exception("could not check the marketplace rules for the title step")
        return None
