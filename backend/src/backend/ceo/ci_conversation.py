"""The CEO's Competitor Intelligence conversations (docs/specs/competitor-intelligence-agent.md §6.21–§6.25, C32, C37–C40, C46).

The seller talks to the CEO and nobody else. This module is the CEO's own, deterministic handling of the CI
turns that are not a plain question to a classifier:

* a competitor screenshot (listing or reviews) attached to the chat,
* the seller's answer to a confirmation question CI asked through the CEO,
* "track this link" / "approve the first two" / "reject 3" / "show me what you found",
* "Ask CEO" about one stored finding from the dashboard (the finding id is re-read server-side).

It has two halves and no model in either:

`plan_turn` — reads only what this tenant already holds (attachments, open confirmation questions, the latest
discovery candidates) and the seller's words, and decides which FIXED registered actions to run, with ids it has
validated itself. It never guesses: an unnamed competitor, an unclear product or an ambiguous number is a question
back to the seller, and nothing is stored.

`compose` — writes the reply from the stored results, in code. Every figure is one CI stored or the seller typed;
none is computed here (CLAUDE.md hard rule). A competitor's price is always labelled with whether it is confirmed,
and the text is checked against the no-live-monitoring-claim rule before it is sent.

The orchestrator runs the returned steps through the normal choke point (permission, attachment, entitlement,
agent_run audit), exactly like any other leg.
"""

from __future__ import annotations

import contextvars
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from backend.ceo import slot_resolvers
from backend.ceo.figure_format import format_paise
from backend.services import ceo_reads
from backend.services import ci_conv_data as data

IMAGE_TYPES = frozenset({"PNG", "JPEG", "WEBP"})
# Written into the CEO's own question (see `_c_intake`); a short "yes" is read as an answer to it only when the CEO's last message carries it, so an unrelated
# "ok" or "yes" in another conversation thread is never mistaken for a confirmation.
CONFIRM_MARKER = "until you confirm them"
MAX_URLS = 5
BULK_MARKER = "Before I add them"  # in the CEO's own bulk-add question; a short "yes" is read as its answer only when the last CEO message carries it

_CI_WORDS = re.compile(r"\b(competitors?|rivals?|listing|screenshots?|their price|reviews?|ratings?)\b", re.IGNORECASE)
_REVIEW_WORDS = re.compile(r"\b(reviews?|ratings page|customer reviews|complaints?)\b", re.IGNORECASE)
_FRESH_CAPTURE = re.compile(r"\b(fresh capture|new capture|it'?s new|it is new|new screenshot|use it anyway|yes,? use it)\b", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_TRACK_VERBS = re.compile(r"\b(track|add|monitor|watch|follow|keep an eye on)\b", re.IGNORECASE)
_APPROVE = re.compile(r"\b(track|approve|accept)\b", re.IGNORECASE)
_REJECT = re.compile(r"\b(reject|skip|ignore)\b", re.IGNORECASE)
_LIST_CANDIDATES = re.compile(r"\b(show|list|what)\b.*\b(candidates?|competitors? (?:you|i) (?:found|have)|did you find|you found)\b|\bwhat did you find\b", re.IGNORECASE)
_AFFIRM = re.compile(r"^\W*(?:yes|yep|yeah|yup|correct|right|confirmed?|that'?s (?:right|correct)|looks (?:right|good|correct)|all correct|ok(?:ay)?)\b", re.IGNORECASE)
_DECLINE = re.compile(r"\b(skip|not sure|don'?t know|no idea|can'?t confirm|cannot confirm|leave it|never mind)\b", re.IGNORECASE)
_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d{1,2})?", re.IGNORECASE)
_DISCOUNT = re.compile(r"\bdiscount\b\D{0,12}((?:₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)
_DELIVERY = re.compile(r"\bdelivery(?: charges?| fee| cost)?\b\D{0,15}?((?:₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)
_NO_DISCOUNT = re.compile(
    r"\bno (?:visible |extra |additional )?discount\b|\bdiscount\b\D{0,12}\b(?:0|0\.0+|nil|none|zero)\b(?!\d|[.,]\d)|\bnot an? (?:additional |extra )?discount\b|\breference[- ]price discount\b|\bnot (?:to )?(?:be )?subtract", re.IGNORECASE)
_QUESTION = re.compile(r"\?\s*$|^\W*(?:what|how|show|explain|is|are|does|do|can|could|tell|which|when|who|why|compare|analy[sz]e|check|stop|start|find|set|alert)\b", re.IGNORECASE)
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")
_UNIT_NUMBER = re.compile(r"\b\d+(?:\.\d+)?[A-Za-z]+\b")  # 1L, 6mm, 2kg: a size, never a price
_FREE_DELIVERY = re.compile(r"\bfree (?:delivery|shipping)\b|\b(?:delivery|shipping) (?:is |was )?free\b", re.IGNORECASE)
_OUT = re.compile(r"\b(out[- ]of[- ]stock|sold out|unavailable|not available)\b", re.IGNORECASE)
_IN = re.compile(r"\b(in[- ]stock|available)\b", re.IGNORECASE)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "last": -1}
_WORD_COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_NUMBER = re.compile(r"(?:#|no\.?\s*|number\s*)?\b(\d{1,2})\b")


@dataclass(frozen=True, slots=True)
class Step:
    key: str
    slots: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Plan:
    kind: str
    steps: tuple[Step, ...] = ()
    text: str | None = None  # a reply with no action (a question back, a list)
    context: Mapping[str, Any] = field(default_factory=dict)
    card: Mapping[str, Any] | None = None  # an interactive card shown with the reply (the candidate pick card)


# ------------------------------------------------------------------------------------------------ helpers
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def candidate_queue(tenant_id: UUID) -> list[dict[str, Any]]:
    """The candidates a seller can still decide on, in the order the dashboard and every reply number them: the newest discovery run, recommended
    tier first, then analysed, each in creation order. Decided and already-tracked candidates are not in it."""
    rows = data.latest_run_candidates(tenant_id)
    order = {"RECOMMENDED": 0, "ANALYZED": 1, "RAW": 2}
    rows = [r for r in rows if r["seller_decision"] == "NONE" and r.get("competitor_url_id") is None and r["tier"] != "RAW"]
    rows.sort(key=lambda c: (order.get(c["tier"], 3), -(c.get("relevance_score") or 0), c["created_at"]))  # best match first, in the order the dashboard shows
    return rows


def business_categories(tenant_id: UUID) -> list[str]:
    return ceo_reads.business_categories(tenant_id)


def has_categories(tenant_id: UUID) -> bool:
    """True when the seller's business profile lists at least one category."""
    return bool(ceo_reads.business_categories(tenant_id))


def only_product(tenant_id: UUID) -> tuple[str, str | None] | None:
    """The seller's product when they have exactly one, else None."""
    products = ceo_reads.list_seller_products(tenant_id)
    return products[0] if len(products) == 1 else None


def discovery_followup(tenant_id: UUID) -> str:
    """What the seller sees right after an approved competitor search: the numbered leads (or the plain fact that none looked like their product), written by code from what the
    search stored, so "show me what you found" is not a second step."""
    queue = candidate_queue(tenant_id)
    if not queue:
        return ("The search did not return any lead that looks like your product, so there is nothing to decide on. A more specific product name or a few key attributes "
                "(material, size) in your product profile usually helps.")
    shown = queue[:TOP_MATCHES]
    more = f"\n(Showing the top {len(shown)} of {len(queue)}; say “show me what you found” for the rest.)" if len(queue) > len(shown) else ""
    return _candidate_list(shown, data.watchlist_status(tenant_id)) + more


def candidate_card(tenant_id: UUID) -> dict[str, Any] | None:
    """The same top matches as a pick card the chat shows with check boxes: the seller ticks up to their free slots and saves. The card carries no new facts: its items are the numbered
    list above, in the same order, so a ticked number is exactly what \"track 1 and 3\" would say."""
    queue = candidate_queue(tenant_id)[:TOP_MATCHES]
    if not queue:
        return None
    st = data.watchlist_status(tenant_id)
    items = []
    for i, c in enumerate(queue, start=1):
        rel = c.get("relationship_class") or "UNKNOWN"
        note = data.identity_note(c) if c.get("category") else (RELATIONSHIP_WORDS.get(rel) if rel != "UNKNOWN" else data.identity_note(c))
        items.append({"n": i, "title": " ".join(str(c.get("title") or "").split())[:110] or "A listing", "marketplace": str(c["marketplace"]).title() if c.get("marketplace") else None,
                      "url": c.get("candidate_url"), "note": note})
    free, who = st["free"], [ceo_reads.competitor_label(r) for r in st["active"]]
    sub = (f"Your list is full ({st['limit']} of {st['limit']}). Stop tracking one first, then pick." if free == 0 else
           f"Tick up to {free} (you track {st['limit'] - free} of {st['limit']} now). They are added to your list and tracked until you remove them.")
    if who:
        sub += " Tracked now: " + ", ".join(who) + "."
    return pick_card("Choose the competitors to track", sub, "multi", free, [{**i, "key": str(i["n"])} for i in items],
                     [{"id": "track", "label": "Save and track", "template": "track {numbers}"}])


def numbers_in(text: str, limit: int) -> list[int]:
    """Candidate positions the seller named ("1 and 3", "#2", "the first two", "all"). Out-of-range numbers are dropped by the caller, never rounded."""
    t = text.lower()
    picked: list[int] = []
    if re.search(r"\ball (?:of them|candidates|three|four|five)\b|\beveryone\b|\ball\b", t) and not re.search(r"\bat all\b", t):
        return list(range(1, limit + 1))
    m = re.search(r"\b(?:the )?first (one|two|three|four|five)\b", t)
    if m:
        return list(range(1, _WORD_COUNTS[m.group(1)] + 1))
    for word, n in _ORDINALS.items():
        if re.search(rf"\b{word}\b", t):
            picked.append(limit if n == -1 else n)
    picked += [int(x) for x in _NUMBER.findall(text)]
    seen: set[int] = set()
    return [n for n in picked if not (n in seen or seen.add(n))]


def parse_confirmation(text: str, fields: Sequence[str]) -> tuple[dict[str, Any], bool, bool]:
    """-> (explicit corrections by field, affirmed, declined). Only the three consequential fields can be corrected. A bare amount is a price correction
    only when a price is actually being asked about; an ambiguous message corrects nothing and affirms nothing."""
    corrections: dict[str, Any] = {}
    t = text
    if "delivery_charge_paise" in fields:  # read first and removed from the text, so its amount is never mistaken for the price
        if _FREE_DELIVERY.search(t):
            corrections["delivery_charge_paise"] = 0
            t = _FREE_DELIVERY.sub(" ", t)
        else:
            m = _DELIVERY.search(t)
            if m:
                paise = slot_resolvers.parse_amount_paise(m.group(1))
                if paise is not None:
                    corrections["delivery_charge_paise"] = paise
                t = t.replace(m.group(0), " ")
    if "visible_discount_paise" in fields:
        if _NO_DISCOUNT.search(t):  # "no discount" / "discount 0": an explicit zero, which is a correction of what was read, never a missing value
            corrections["visible_discount_paise"] = 0
            t = _NO_DISCOUNT.sub(" ", t)
        m = _DISCOUNT.search(t)
        if m and "visible_discount_paise" not in corrections:
            paise = slot_resolvers.parse_amount_paise(m.group(1))
            if paise is not None:
                corrections["visible_discount_paise"] = paise
                t = t.replace(m.group(0), " ")
    if "listed_price_paise" in fields:
        t = _UNIT_NUMBER.sub(" ", _PERCENT.sub(" ", t))  # "39% off" and "1L" are not the price
        amounts = [a.strip() for a in _AMOUNT.findall(t) if re.search(r"\d", a)]
        parsed = [p for p in (slot_resolvers.parse_amount_paise(a) for a in amounts) if p is not None]
        if len(set(parsed)) == 1:
            corrections["listed_price_paise"] = parsed[0]
    if "availability" in fields:
        if _OUT.search(t):
            corrections["availability"] = "OUT_OF_STOCK"
        elif _IN.search(t):
            corrections["availability"] = "IN_STOCK"
    return corrections, bool(_AFFIRM.search(text)), bool(_DECLINE.search(text))


# ------------------------------------------------------------------------------------------------ planning
def plan_turn(
    tenant_id: UUID,
    inv_id: UUID,
    text: str,
    attachments: Sequence[Mapping[str, Any]],
    *,
    recent: Sequence[str] = (),
    latest_attachments: Sequence[Mapping[str, Any]] = (),
    finding_id: UUID | None = None,
    other_agent_intent: bool = False,
    last_ceo_text: str = "",
    router_matched: bool = True,
) -> Plan | None:
    """Returns the CI plan for this turn, or `None` when the turn is not a CI conversation (the normal route then handles it, unchanged).
    `other_agent_intent` is True when an explicit rule already recognised a request for another agent (e.g. a product photo for CMO titles)."""
    text = _norm(text)
    _RECENT.set(tuple(_norm(m) for m in recent)[-14:])  # what the conversation has been about, oldest first

    if finding_id is not None:
        return Plan("EXPLAIN_FINDING", steps=(Step("ci.explain_finding", {"finding_id": str(finding_id)}),))

    plan = _confirmation(tenant_id, text, awaiting=CONFIRM_MARKER in (last_ceo_text or ""))
    if plan is not None:
        return plan

    plan = _none_match(tenant_id, text)  # before the screenshot step: "none of these" must not ask the same question again
    if plan is not None:
        return plan

    if not other_agent_intent:
        plan = _screenshot(tenant_id, inv_id, text, attachments, latest_attachments)
        if plan is not None:
            return plan

    plan = _alert_settings(tenant_id, text)
    if plan is not None:
        return plan

    plan = _bulk_confirmed(tenant_id, text, last_ceo_text or "")
    if plan is not None:
        return plan

    plan = _track_links(tenant_id, text)
    if plan is not None:
        return plan

    plan = _candidates(tenant_id, text)
    if plan is not None:
        return plan

    for builder in (_track_this, _listing_patterns, _competitor_facts, _review_explain, _verify, _details_for, _pick_reply, _pick_prompt, _track_by_names, _compare_all, _review_sources, _tracked_list, _price_question, _relationship_question, _provenance_question, _restore, _explain_latest):
        plan = (builder(tenant_id, text, finding_id=finding_id) if builder is _explain_latest
                else builder(tenant_id, text, last_ceo_text or "") if builder is _pick_reply else builder(tenant_id, text))
        if plan is not None:
            return plan
    if not other_agent_intent and not any(a.get("detected_type") in IMAGE_TYPES for a in attachments):
        plan = _screenshot_missing(tenant_id, text)
        if plan is not None:
            return plan
    return None if router_matched or other_agent_intent else _competitor_help(tenant_id, text)


_FIELD_WORDS_RX = {
    "listed_price_paise": r"price",
    "visible_discount_paise": r"discount",
    "delivery_charge_paise": r"delivery|shipping",
    "availability": r"stock|availability",
    "offers": r"offers?|coupons?|cashback",
}
_NOT_COUNT = re.compile(r"\b(?:do not|don'?t|not|never)\s+(?:count|include|subtract|apply|use)\b", re.IGNORECASE)
_HOLD = re.compile(r"\b(?:keep|leave|set|mark|treat)\b[^.;\n]*\b(?:unknown|unconfirmed|blank|empty)\b|\b(?:skip|ignore|exclude|omit|do not use|don'?t use|leave out|not sure about)\b", re.IGNORECASE)


def _held_fields(text: str, fields: Sequence[str]) -> set[str]:
    """The consequential fields the seller said to leave out ("keep delivery, offers and stock as unknown", "skip the discount"): found clause by clause, so
    "yes, the price is 279. Keep delivery as unknown" holds delivery only. A bare "skip" with no field named is the existing decline-everything, not this."""
    held: set[str] = set()
    for clause in re.split(r"[.;\n]", text):
        if _NOT_COUNT.search(clause) and "offers" in fields and re.search(r"\b(?:offers?|coupons?|cashback)\b", clause, re.IGNORECASE):
            held.add("offers")  # "do not count cashback or conditional bank offers": the offers are left out, nothing else in that sentence is
            continue
        if not _HOLD.search(clause):
            continue
        for name in fields:
            rx = _FIELD_WORDS_RX.get(name)
            if rx and re.search(rf"\b(?:{rx})\b", clause, re.IGNORECASE):
                held.add(name)
    return held


def _confirmation(tenant_id: UUID, text: str, *, awaiting: bool) -> Plan | None:
    open_requests = [r for r in data.open_requests(tenant_id) if r["consequential"] and r["snapshot_id"] is not None]
    if not open_requests:
        return None
    snapshot_id = open_requests[-1]["snapshot_id"]  # the newest screenshot's questions; an older unanswered snapshot is left to expire
    mine = [r for r in open_requests if r["snapshot_id"] == snapshot_id]
    fields = [r["field_name"] for r in mine]
    corrections, affirmed, declined = parse_confirmation(text, fields)
    held = _held_fields(text, fields)
    if "visible_discount_paise" in fields and _NO_DISCOUNT.search(text) and "visible_discount_paise" not in corrections:
        corrections["visible_discount_paise"] = 0
    if not awaiting and _QUESTION.search(text):
        corrections, held = {}, set()  # a question or a request is never a correction: a number in it ("1L", "₹399") is not what the competitor charges
    if held or corrections:
        affirmed = False  # a message that gives its own instructions per field is not a blanket "yes": what it does not mention stays open and is asked about
    mentions = bool(re.search(r"\b(price|discount|stock|available|unavailable|sold out|delivery|shipping|offers?|coupon)\b", text, re.IGNORECASE))
    if not awaiting:
        # Not a reply to CI's question: only an explicit statement about the price / stock / discount counts, never a bare "yes" or a bare number.
        affirmed = declined = False
        if not mentions:
            corrections = {}
    if not (corrections or affirmed or declined or held):
        return None
    answers: list[dict[str, Any]] = []
    declined_ids: list[str] = []
    for r in mine:
        name = r["field_name"]
        if name in held and name not in corrections:
            declined_ids.append(str(r["id"]))
        elif declined and name not in corrections:
            declined_ids.append(str(r["id"]))
        elif name in corrections:
            answers.append({"info_request_id": str(r["id"]), "value": corrections[name]})
        elif affirmed and r.get("proposed_value") is not None:
            answers.append({"info_request_id": str(r["id"]), "value": r["proposed_value"]})
    if not answers and not declined_ids:
        return None
    return Plan(
        "CONFIRM",
        steps=(Step("ci.confirm_field", {"answers": answers, "declined": declined_ids}),),
        context={"asked": fields, "answered": [a["info_request_id"] for a in answers], "declined": declined_ids, "corrected": sorted(corrections), "held": sorted(held)},
    )


def _pending_image(tenant_id: UUID, attachments: Sequence[Mapping[str, Any]], latest: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The image this turn is about: one attached now, else the newest image in this conversation that has not been read yet."""
    for pool in (attachments, latest):
        for a in pool:
            if a.get("detected_type") in IMAGE_TYPES:
                sha = a.get("sha256")
                if pool is latest and sha and data.evidence_exists(tenant_id, str(sha)):
                    continue
                return a
    return None


_NAMES_IT = re.compile(r"\b(?:this is|it is|it's|that is|called|named|for)\s+\S", re.IGNORECASE)  # the seller is naming a competitor (which may be a different one)


def _screenshot(tenant_id: UUID, inv_id: UUID, text: str, attachments: Sequence[Mapping[str, Any]], latest: Sequence[Mapping[str, Any]]) -> Plan | None:
    named = slot_resolvers.resolve_competitor(tenant_id, text)
    if not isinstance(named, slot_resolvers.CompetitorMatch) and _PRONOUN.search(text):
        fid, flabel = focus_competitor(tenant_id)
        if fid:
            named = slot_resolvers.CompetitorMatch(UUID(fid), flabel or "that competitor")
    names_a_competitor = isinstance(named, slot_resolvers.CompetitorMatch)
    signals_ci = bool(_CI_WORDS.search(text)) or names_a_competitor or bool(_FRESH_CAPTURE.search(text))
    image_now = any(a.get("detected_type") in IMAGE_TYPES for a in attachments)
    if not signals_ci:
        return None
    if not image_now and not names_a_competitor and not _FRESH_CAPTURE.search(text):
        return None  # an earlier image is picked up again only when the seller names the competitor (or says it is a fresh capture): a question about reviews or prices is just a question
    image = _pending_image(tenant_id, attachments, latest if not image_now else ())
    if image is None:
        return None

    only_one = (not isinstance(named, slot_resolvers.CompetitorMatch) and named.reason == "NOT_FOUND" and len(named.candidates) == 1
                and not _NAMES_IT.search(text))  # one tracked competitor and the seller named none: the screenshot is of that one
    if isinstance(named, slot_resolvers.CompetitorMatch):
        competitor_id, label = named.url_id, named.label
    elif only_one:
        competitor_id, label = named.candidates[0]
    elif named.reason == "NONE_TRACKED":
        return Plan("NEEDS_COMPETITOR", text=(
            "I can read that screenshot, but you are not tracking any competitor yet, and I do not add one on my own. "
            "Say “find my competitors”, tick the ones to track, then send the screenshot again and tell me which one it shows."))
    else:
        lead = "That matches more than one of your tracked competitors" if named.reason == "AMBIGUOUS" else "I could not tell which tracked competitor that screenshot shows"
        rows = ([{"id": cid, "label": lab, "marketplace": None} for cid, lab in named.candidates] or [{"id": lab, "label": lab, "marketplace": None} for lab in named.choices]
                or data.watchlist_status(tenant_id)["active"])
        return Plan("NEEDS_COMPETITOR", text=f"{lead}. Pick the one it shows below, or say none of them match. Nothing has been stored yet.", card=screenshot_card(rows),
                    context={"pending_image": str(image["id"])})
    review = bool(_REVIEW_WORDS.search(text))
    slots: dict[str, Any] = {"attachment_id": str(image["id"]), "competitor_url_id": str(competitor_id)}
    if image.get("sha256"):
        slots["sha256"] = str(image["sha256"])
    if review:
        slots.pop("sha256", None)
        return Plan("REVIEW_INTAKE", steps=(Step("ci.review_intake", slots),), context={"label": label})
    slots["allow_near_duplicate"] = bool(_FRESH_CAPTURE.search(text))
    return Plan("INTAKE", steps=(Step("ci.evidence_intake", slots),), context={"label": label})


DEFAULT_TZ = "Asia/Kolkata"  # the product serves Indian sellers; the reply says plainly which timezone was used so a wrong assumption is visible
_QUIET_OFF = re.compile(r"\b(?:turn off|switch off|remove|clear|stop|no more|disable)\b.*\bquiet hours?\b", re.IGNORECASE)
_QUIET_ON = re.compile(
    r"\bquiet hours?\b\D{0,20}?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to|until|till|-|–|and)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*(ist|utc))?", re.IGNORECASE)
_THRESHOLD = re.compile(r"\b(?:alert|notify|tell|warn)\b[^%]{0,80}?\bprice\b[^%]{0,60}?(\d{1,2}(?:\.\d{1,2})?)\s*%|\bprice\b[^%]{0,40}?\b(?:change|drop|move)\w*\b[^%]{0,40}?(\d{1,2}(?:\.\d{1,2})?)\s*%", re.IGNORECASE)


def _seller_tz(tenant_id: UUID) -> str:
    """The seller's configured timezone when it is a real zone, else India time. The reply always says which was used."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    try:
        tz = data.tenant_timezone(tenant_id)
        if tz:
            ZoneInfo(tz)
            return tz
    except Exception:  # noqa: BLE001 - an unreadable or invalid setting falls back, it never blocks the seller
        pass
    return DEFAULT_TZ


_THRESHOLD_BEFORE = re.compile(r"\b(\d{1,2}(?:\.\d{1,2})?)\s*%[^.?!%]{0,40}\b(?:price[- ]?change|price)\b[^.?!%]{0,30}\b(?:alert|threshold)\b|\bthreshold\b[^%.?!]{0,30}\b(\d{1,2}(?:\.\d{1,2})?)\s*%", re.IGNORECASE)


def _clock(hour: str, minute: str | None, meridiem: str | None) -> str | None:
    h, m = int(hour), int(minute or 0)
    if meridiem:
        if not 1 <= h <= 12:
            return None
        h = (h % 12) + (12 if meridiem.lower() == "pm" else 0)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"


def _alert_settings(tenant_id: UUID, text: str) -> Plan | None:
    slots: dict[str, Any] = {}
    if _QUIET_OFF.search(text):
        slots["clear_quiet"] = True
    else:
        q = _QUIET_ON.search(text)
        if q:
            start, end = _clock(q.group(1), q.group(2), q.group(3)), _clock(q.group(4), q.group(5), q.group(6))
            if start is None or end is None or start == end:
                return Plan("ALERT_SETTINGS_ASK", text="I could not read those quiet hours. Say them like “quiet hours 10pm to 7am”. Nothing was changed.")
            slots.update(quiet_start=start, quiet_end=end, quiet_tz="UTC" if (q.group(7) or "").lower() == "utc" else _seller_tz(tenant_id))
    t = _THRESHOLD.search(text) or _THRESHOLD_BEFORE.search(text)
    if t:
        pct = t.group(1) or t.group(2)
        slots["price_threshold_pct"] = pct
    if not slots:
        return None
    return Plan("ALERT_SETTINGS", steps=(Step("ci.alert_settings_set", slots),), context={"asked": sorted(slots)})


def _track_links(tenant_id: UUID, text: str) -> Plan | None:
    urls = [u.rstrip(".,;") for u in _URL.findall(text)]
    if not urls or not _TRACK_VERBS.search(text):
        return None
    urls = list(dict.fromkeys(urls))[:MAX_URLS]
    rest = _URL.sub(" ", text)
    product_id: str | None = None
    phrase = _product_phrase(rest)
    found = slot_resolvers.resolve_seller_product(tenant_id, phrase)
    products = ceo_reads.list_seller_products(tenant_id)
    if isinstance(found, slot_resolvers.ProductMatch):
        product_id = found.product_id
    elif not phrase:  # no product was named: only when there is exactly one candidate is it unambiguous; a product the seller DID name but that is not theirs is never swapped for another
        linked = data.linked_skus(tenant_id)
        if len(products) == 1:
            product_id = products[0][0]
        elif not products and len(linked) == 1:
            product_id = linked[0]
    if product_id is None:
        if not products:
            return Plan("NEEDS_PRODUCT", text=(
                "I do not have any of your products yet, so I cannot link this competitor to one. Upload a sales report so your products appear, or add a product profile, "
                "then ask me again. Nothing has been added yet."))
        names = "; ".join(f"“{t or p}”" for p, t in products[:6])
        named = f" I could not find “{phrase}” among them." if phrase else ""
        return Plan("NEEDS_PRODUCT", text=(
            f"Which of your products is this competitor for? Your products: {names}.{named} "
            "Tell me which one. Nothing has been added yet."))
    label = _label_from(rest)
    if len(urls) > 1:
        st = data.watchlist_status(tenant_id)
        if st["free"] == 0:
            return Plan("CAP_FULL", text=_full_text(st["limit"], [ceo_reads.competitor_label(r) for r in st["active"]]) + " Nothing has been added yet.")
        if st["free"] < len(urls):
            who = "; ".join(f"“{ceo_reads.competitor_label(r)}”" for r in st["active"])
            return Plan("CAP_BULK", text=(
                f"You sent {len(urls)} links but have {st['free']} free competitor slot{'s' if st['free'] != 1 else ''} of {st['limit']}" + (f" (tracked now: {who})" if who else "") +
                ". Send only the ones you want, or stop tracking one first, for example “stop tracking <name>”. Nothing has been added yet."))
    if len(urls) > 1:  # several links at once are echoed back first (C39); nothing is added until the seller says yes
        title = next((t or p for p, t in ceo_reads.list_seller_products(tenant_id) if p == product_id), product_id)  # a product known only through its competitors is named by its SKU
        if title:
            lines = "\n".join(f"{i}. {u}" for i, u in enumerate(urls, start=1))
            return Plan("BULK_CONFIRM", text=(
                f"You gave me {len(urls)} links. {BULK_MARKER}, please check them:\n{lines}\n"
                f"I would track all of them for your product “{title}”. Reply “yes” to add all {len(urls)}, or send only the ones you want. Nothing has been added yet."))
    steps = tuple(Step("ci.competitor_add", {"url": u, "product_id": product_id, **({"label": label} if label and len(urls) == 1 else {})}) for u in urls)
    return Plan("ADD_COMPETITORS", steps=steps, context={"urls": urls})


def _bulk_confirmed(tenant_id: UUID, text: str, last_ceo_text: str) -> Plan | None:
    """A “yes” to the CEO's own bulk-add question: the links and the product are read back from that question, and the product is re-resolved by its exact name."""
    if BULK_MARKER not in last_ceo_text or not _AFFIRM.search(text) or _URL.search(text):
        return None
    urls = list(dict.fromkeys(u.rstrip(".,;") for u in _URL.findall(last_ceo_text)))[:MAX_URLS]
    m = re.search(r"your product “([^”]+)”", last_ceo_text)
    if not urls or m is None:
        return None
    wanted = m.group(1).strip().casefold()
    ids = [p for p, t in ceo_reads.list_seller_products(tenant_id) if (t or p).strip().casefold() == wanted] or [k for k in data.linked_skus(tenant_id) if k.strip().casefold() == wanted]
    if len(ids) != 1:
        return Plan("NEEDS_PRODUCT", text="I could not tell which product those links were for, so nothing was added. Say it again with the product, for example “track <link> for my <product>”.")
    steps = tuple(Step("ci.competitor_add", {"url": u, "product_id": ids[0]}) for u in urls)
    return Plan("ADD_COMPETITORS", steps=steps, context={"urls": urls})


def _product_phrase(text: str) -> str | None:
    m = re.search(r"\bfor (?:my|our|the)?\s*([\w][\w \-'()&/+#]{1,80}?)(?=[.,?!]|$)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _label_from(text: str) -> str | None:
    m = re.search(r"\b(?:competitor|product|listing)?\s*name\s*(?:is|:)\s*([\w][\w \-'&()./+#,]{1,78}?)(?=\s*(?:\.\s|\.$|\blisting url\b|\burl\b|\blink\b|;|\n|$))", text, re.IGNORECASE)
    if m:
        return m.group(1).strip(" ,")
    m = re.search(r"\b(?:called|named)\s+([\w][\w \-'&()./+#]{0,58}?)(?=\s+for\s+(?:my|our|the)\b|[,;?!]|\.\s|\.$|$)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\bas\s+([A-Z][\w\-']*(?:\s+[A-Z][\w\-']*){0,3})", text)
    return m.group(1) if m else None


_CAND_CMD = re.compile(r"^\W*(?:ok(?:ay)?\W+|please\W+)?(?:track|approve|accept|reject|skip|ignore|drop)\b(?P<rest>.*)$", re.IGNORECASE | re.DOTALL)
_CAND_REST = re.compile(
    r"^[\s,.&#\d]*(?:(?:and|the|first|second|third|fourth|fifth|sixth|last|one|two|three|four|five|all|of|them|candidates?|competitors?|leads?|no\.?|number|numbers?|ones?|it|that|these|those)\b[\s,.&#\d]*)*$",
    re.IGNORECASE)


def _candidates(tenant_id: UUID, text: str) -> Plan | None:
    cmd = _CAND_CMD.match(text)
    decision_phrase = bool(cmd and _CAND_REST.match(cmd.group("rest").strip()) and re.search(r"\d|first|second|third|fourth|fifth|sixth|last|\ball\b|\bone\b|\btwo\b|\bthree\b", cmd.group("rest"), re.IGNORECASE))
    wants_list = bool(_LIST_CANDIDATES.search(text)) and not re.search(r"\b(?:product )?ideas?\b|\btrending\b|\bniche\b|\bresearch(?:ed)?\b|\breport\b", text, re.IGNORECASE)  # "what product ideas did you find" is the product-research answer, not this
    approve, reject = bool(_APPROVE.search(text)), bool(_REJECT.search(text))
    if not (wants_list or decision_phrase):
        return None
    queue = candidate_queue(tenant_id)
    if wants_list and not (approve or reject):
        if not queue:
            return Plan("CANDIDATES", text="There are no competitor candidates waiting for your decision. Ask me to find competitors for one of your products and I will list what I find here.")
        return Plan("CANDIDATES", text=_candidate_list(queue[:TOP_MATCHES], data.watchlist_status(tenant_id)), context={"count": len(queue)}, card=candidate_card(tenant_id))
    if not queue:
        return None  # nothing to decide on: let the normal route answer
    picked = [n for n in numbers_in(text, len(queue)) if 1 <= n <= len(queue)]
    if not picked:
        return Plan("CANDIDATES", text="Which ones? Say the numbers from my list, for example “track 1 and 3” or “reject 2”.\n\n" + _candidate_list(queue[:TOP_MATCHES], data.watchlist_status(tenant_id)))
    key = "ci.competitor_reject" if (reject and not approve) or re.search(r"\b(reject|skip|ignore|drop)\b", text, re.IGNORECASE) else "ci.competitor_approve"
    if key == "ci.competitor_approve":
        st = data.watchlist_status(tenant_id)
        if st["free"] == 0:
            return Plan("CAP_FULL", text=_full_text(st["limit"], [ceo_reads.competitor_label(r) for r in st["active"]]) + " Nothing has been added yet.")
        if len(picked) > st["free"]:
            who = "; ".join(f"“{ceo_reads.competitor_label(r)}”" for r in st["active"])
            return Plan("CAP_PICK", text=(
                f"You picked {len(picked)} but have {st['free']} free competitor slot{'s' if st['free'] != 1 else ''} of {st['limit']}" + (f" (tracked now: {who})" if who else "") +
                (f". Pick up to {st['free']}, for example “track 1” (I will not add part of a request)." if st["free"] else ". Stop tracking one first, for example “stop tracking <name>”.") + " Nothing has been added yet."))
    steps = tuple(Step(key, {"candidate_id": str(queue[n - 1]["id"])}) for n in picked)
    return Plan("DECIDE_CANDIDATES", steps=steps, context={"positions": picked, "decision": "REJECT" if key.endswith("reject") else "APPROVE"})


_TRACKED_LIST = re.compile(
    r"^(?!.*\b(?:monitor|re-?check|how are|changes?|complain\w*|stale|compare|cheaper|price of|reviews?|source|history|who confirmed|exact match|variant|alternative|cancel)\b)"
    r".*\b(?:show|list|which|what|see|display|give me)\b.*(?:\b(?:competitors?|rivals?)\b.*\b(?:track(?:ed|ing)?|watch(?:ing|list)?|have i|do i have)\b|\b(?:track(?:ed|ing)?|watch(?:ing|list)?)\b.*\b(?:competitors?|rivals?)\b)"
    r"|\bmy (?:competitor )?watch ?list\b", re.IGNORECASE)
_RELATION_Q = re.compile(r"\b(?:exact match|same product|a variant|variant|cross-brand|functional alternative|direct competitor)\b", re.IGNORECASE)
_PROVENANCE_Q = re.compile(r"\b(?:source|provenance|confirmation history|who confirmed|when (?:was|did) it (?:observed|confirmed)|where did\b.*\bcome from)\b", re.IGNORECASE)
_NEEDS_LINK = re.compile(r"\b(?:track|add|follow)\b[^.?!]*\b(?:this|a|new|another|the)\s+(?:amazon |flipkart |meesho )?(?:competitor|rival|listing)\b|\bcompetitor name\b|\blisting url\b|\[paste", re.IGNORECASE)
_PRICE_Q = re.compile(
    r"\b(?:total|all[- ]in|in total)\b.*\b(?:pay|cost|price|amount)\b|\bincluding delivery\b|\beffective price\b|\bbuyer total\b|\bwhat (?:does|is|do|will)\b.*\b(?:charge|charging|sell(?:ing)? (?:for|at)|cost|price)\b|\bhow much (?:does|is|do)\b",
    re.IGNORECASE)
_RESTORE = re.compile(r"\b(?:start|resume|begin|restart|re-?start)\b[^.?!]*\btracking\b[^.?!]*\bagain\b|\btrack\b[^.?!]*\bagain\b|\bre-?add\b|\brestore\b[^.?!]*\bcompetitor", re.IGNORECASE)
_EXPLAIN = re.compile(r"\b(?:explain|describe|walk me through|tell me about|what is|what does)\b[^.?!]*\b(?:competitor )?finding\b", re.IGNORECASE)
_SCREENSHOT_TALK = re.compile(r"\b(?:newer|new|latest|fresh|updated|another|second)\s+screenshot\b|\bscreenshot\b[^.?!]*\b(?:i have|i attached|attached|i sent|here)\b", re.IGNORECASE)
_AVAIL_WORDS = {"IN_STOCK": "in stock", "OUT_OF_STOCK": "out of stock"}


_REVIEW_ASK = re.compile(r"\b(?:reviews?|complaints?|complain\w*|what do (?:customers|buyers) (?:say|think|complain))\b", re.IGNORECASE)
_THEIR = re.compile(r"\b(?:competitors?|rivals?|their|them|competition)\b", re.IGNORECASE)


def _review_sources(tenant_id: UUID, text: str) -> Plan | None:
    """A question about what customers say about the seller's competitors, when no review evidence is saved yet. Reviews are only ever read from a screenshot (or review text) the seller
    sends, with its real sample size: Metrion does not scrape a reviews page, and a web-search snippet is not a review. So this points to where each competitor's reviews are and asks for
    a screenshot. When any evidence is saved, the normal route shows it (themes with their sample sizes)."""
    if len(text) > 400 or _URL.search(text) or not _REVIEW_ASK.search(text) or not _THEIR.search(text):
        return None
    info = data.review_sources(tenant_id)
    comps = info["competitors"]
    if not comps or any(c["hasEvidence"] for c in comps):
        return None
    lines = ["I have no review evidence for your tracked competitors yet, so I cannot say what their customers say. I do not read review pages myself, and a web search result is not a review, "
             "so I only use reviews you show me."]
    lines.append("Where each competitor's reviews are (open the link, scroll to several reviews, and send me a screenshot here):")
    for i, c in enumerate(comps[:5], start=1):
        lines.append(f"{i}. {c['label'] or 'Competitor'} ({str(c['marketplace']).title()}): {c['reviewsUrl']}")
    lines.append(f"I will tell you how many reviews I could read and what customers repeat. I only call something a recurring theme when at least {info['minSample']} reviews were read, "
                 "and anything smaller is shown as a small sample. You can also paste the review text.")
    return Plan("REVIEW_SOURCES", text="\n".join(lines), context={"count": len(comps)})


def _tracked_list(tenant_id: UUID, text: str) -> Plan | None:
    if not _TRACKED_LIST.search(text):
        return None
    products = ceo_reads.list_seller_products(tenant_id)
    phrase = _product_phrase(text)
    found = slot_resolvers.resolve_seller_product(tenant_id, phrase) if phrase else None
    product_id = found.product_id if isinstance(found, slot_resolvers.ProductMatch) else None
    if phrase and product_id is None and products:
        names = "; ".join(f"“{t or p}”" for p, t in products[:6])
        return Plan("TRACKED_LIST", text=f"I could not find “{phrase}” among your products. Your products: {names}. Tell me which one.")
    comps = [c for c in data.all_competitors(tenant_id) if product_id is None or c.get("groupId") == product_id]
    url_id_named, label_named = _named_competitor(tenant_id, text)
    if url_id_named is not None:  # "show my tracked CASPIAN Astra competitor and its verified price": that one, in full
        only = [c for c in comps if c["id"] == url_id_named]
        if only:
            comps = only
    if not comps:
        return Plan("TRACKED_LIST", text="You have no competitors on your list yet. Say “find my competitors”, choose a category, and tick the ones to track.")
    lines = [f"You have {len(comps)} competitor{'s' if len(comps) != 1 else ''} on your list:"]
    for i, c in enumerate(comps, start=1):
        market = str(c["marketplace"]).title()
        if c["priceStatus"] == "VERIFIED":
            price = f"verified price {format_paise(c['listedPricePaise'])}, evidence of {(c.get('evidenceDate') or '')[:10]}"
        elif c["priceStatus"] == "UNVERIFIED":
            price = "a screenshot is waiting for your confirmation, so there is no verified price yet"
        else:
            price = "no verified price yet: send me a screenshot of its listing"
        fresh = {"FRESH": "fresh", "AGING": "ageing", "STALE": "stale", "UNAVAILABLE": "no current evidence"}.get(str(c.get("freshness")), str(c.get("freshness") or "").lower())
        group = f" [{c['group']}]" if c.get("group") else ""
        lines.append(f"{i}. {c['label']} ({market}){group}: {price}; evidence is {fresh}.")
    lines.append("This is exactly what your Competitors page shows. I only know what your screenshots showed; I do not watch listings between them.")
    return Plan("TRACKED_LIST", text="\n".join(lines), context={"count": len(comps)})


_RECENT: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("ci_recent_messages", default=())
_PRONOUN = re.compile(
    r"\b(?:this|that|the same|same)\s+(?:competitor|rival|one|listing|product|screenshot|seller|brand)\b|\bi am talking about\b|\bi meant\b|\bi'?m talking about\b|\bthese reviews\b", re.IGNORECASE)


def focus_competitor(tenant_id: UUID) -> tuple[str | None, str | None]:
    """The tracked competitor this conversation is about: the most recent one named in the last messages (the seller's or the CEO's). The CEO reads the conversation, so "this competitor",
    "it" or "that screenshot" means the one just discussed instead of a question about which product or competitor."""
    for msg in reversed(_RECENT.get()):
        found = slot_resolvers.resolve_competitor(tenant_id, msg)
        if isinstance(found, slot_resolvers.CompetitorMatch):
            return str(found.url_id), found.label
    return None, None


def _named_competitor(tenant_id: UUID, text: str) -> tuple[str | None, str | None]:
    named = slot_resolvers.resolve_competitor(tenant_id, text)
    if isinstance(named, slot_resolvers.CompetitorMatch):
        return str(named.url_id), named.label
    if _PRONOUN.search(text):
        return focus_competitor(tenant_id)
    return None, None


def _price_question(tenant_id: UUID, text: str) -> Plan | None:
    """"What would a buyer pay for <a tracked competitor>, delivery included?": answered from the engine's stored effective price (the same figures as the Competitors page), only
    when the seller named one of their tracked competitors, so a general money question is never taken for this."""
    if not _PRICE_Q.search(text):
        return None
    url_id, label = _named_competitor(tenant_id, text)
    if url_id is None:
        return None
    row = next((c for c in data.all_competitors(tenant_id) if c["id"] == url_id), None)
    if row is None:
        return None
    if row["priceStatus"] != "VERIFIED":
        why = "a screenshot of it is waiting for your confirmation" if row["priceStatus"] == "UNVERIFIED" else "I have no confirmed screenshot of it"
        return Plan("PRICE_Q", text=f"I cannot say what a buyer pays for {row['label']}: {why}. Send me a screenshot of its listing, tell me it is {row['label']}, and confirm what I read.")
    ep = row.get("effectivePrice") or {}
    eff, tot = ep.get("effective") or {}, ep.get("buyerTotal") or {}
    date = (row.get("evidenceDate") or "")[:10]
    lines = [f"{row['label']} ({str(row['marketplace']).title()}), from your screenshot of {date}:", f"- Listed price: {format_paise(row['listedPricePaise'])}"]
    if eff.get("isAvailable"):
        lines.append(f"- After the confirmed discounts: {format_paise(eff['valuePaise'])} (worked out by Metrion's price engine)")
    else:
        lines.append(f"- After discounts: not available ({str(eff.get('unavailableReason') or 'not enough confirmed').lower().replace('_', ' ')})")
    if tot.get("isAvailable"):
        d = ep.get("deliveryChargePaise")
        lines.append(f"- With delivery: {format_paise(tot['valuePaise'])}" + (" (free delivery was shown)" if d == 0 else ""))
    else:
        lines.append(f"- With delivery: not available, because the delivery charge is not confirmed ({str(tot.get('unavailableReason') or '').lower().replace('_', ' ')})")
    offers = ep.get("offers") or []
    if offers:
        n_not = sum(1 for o in offers if o.get("conditional") or o.get("amountPaise") is None)
        lines.append(f"- Offers shown: {len(offers)}; {n_not} not counted because they need a card or a condition, so the price above does not include them")
    else:
        lines.append("- Offers: no offer is counted in this price (an offer that needs a card or a condition is never subtracted, and offers you asked me to leave out are not used)")
    lines.append("I do not know what it costs today unless you have sent a newer screenshot.")
    return Plan("PRICE_Q", text="\n".join(lines), context={"competitor": label})


PICK_MARKER = "Reply with a number, a name, or ALL."
_GENERIC_COMPETITORS = re.compile(
    r"^\W*(?:please\s+)?(?:track|check|monitor|watch|follow|show|update|refresh|review)\s+(?:my\s+|the\s+|all\s+)?(?:tracked\s+|current\s+)?(?:competitors?|rivals?)\W*$", re.IGNORECASE)


def _pick_prompt(tenant_id: UUID, text: str) -> Plan | None:
    """"Track / check my competitors" with no name: the tracked competitors to choose from, with ALL. Nothing is guessed and nothing is added by this question."""
    if _URL.search(text) or not _GENERIC_COMPETITORS.match(text):
        return None
    st = data.watchlist_status(tenant_id)
    names = [ceo_reads.competitor_label(r) for r in st["active"]]
    if not names:
        return Plan("PICK", text="You are not tracking any competitor yet. Say “find my competitors”, choose a category, and tick the ones to track.")
    lines = [f"Your list has {len(names)} of {st['limit']} competitors. Tick the ones you want, then choose what to do:"]
    lines += [f"{i}. {n}" for i, n in enumerate(names, start=1)]
    lines.append(f"ALL: every one of them. {PICK_MARKER}")  # typing works too
    return Plan("PICK", text="\n".join(lines), context={"ids": [str(r["id"]) for r in st["active"]]}, card=tracked_card(st["active"]))


def _pick_reply(tenant_id: UUID, text: str, last_ceo_text: str) -> Plan | None:
    """The answer to the picker: a number, a name or ALL."""
    if PICK_MARKER not in last_ceo_text or len(text.split()) > 6:
        return None
    st = data.watchlist_status(tenant_id)
    rows = st["active"]
    if re.search(r"^\W*all\b", text, re.IGNORECASE):
        return _competitor_detail(tenant_id, [r["id"] for r in rows])
    picked: list[Any] = [rows[n - 1]["id"] for n in numbers_in(text, len(rows)) if 1 <= n <= len(rows)]
    if not picked:
        named = slot_resolvers.resolve_competitor(tenant_id, text)
        if isinstance(named, slot_resolvers.CompetitorMatch):
            picked = [named.url_id]
    if not picked:
        return None
    return _competitor_detail(tenant_id, picked)


def _competitor_detail(tenant_id: UUID, ids: Sequence[Any]) -> Plan:
    want = {str(i) for i in ids}
    every = data.all_competitors(tenant_id)
    comps = [c for c in every if c["id"] in want] or every
    lines = []
    for i, c in enumerate(comps, start=1):
        market = str(c["marketplace"]).title()
        if c["priceStatus"] == "VERIFIED":
            price = f"verified price {format_paise(c['listedPricePaise'])}, evidence of {(c.get('evidenceDate') or '')[:10]}"
        elif c["priceStatus"] == "UNVERIFIED":
            price = "a screenshot is waiting for your confirmation, so there is no verified price yet"
        else:
            price = "no verified price yet: send me a screenshot of its listing and say it is " + str(c["label"])
        lines.append(f"{i}. {c['label']} ({market}): {price}.")
    return Plan("PICK", text="\n".join(lines) if lines else "I do not see those competitors in your list.")


_TRACK_NAMES = re.compile(r"^\W*(?:please\s+)?(?:track|add|follow|approve|start tracking)\s+(?P<names>.+?)\W*$", re.IGNORECASE | re.DOTALL)


def _split_names(raw: str) -> list[str]:
    parts = re.split(r"\s*(?:,|;|&|\band\b)\s*", raw)
    cleaned = [re.sub(r"\s+again$", "", re.sub(r"^(?:the\s+)?(?:competitors?\s+)?", "", p.strip(), flags=re.IGNORECASE).strip(" ."), flags=re.IGNORECASE) for p in parts if p.strip(" .")]
    return [c for c in cleaned if c]


def _track_by_names(tenant_id: UUID, text: str) -> Plan | None:
    """"Track CASPIAN Astra 1L and The Better Home 1L": each name is looked up among the discovered leads (by the title the search returned) and the competitors stopped earlier,
    and resolved to that listing's own id, never to a name. A name that matches nothing is said so; a name that matches two leads is asked about."""
    m = _TRACK_NAMES.match(text)
    if m is None or _URL.search(text) or _CAND_CMD.match(text) and _CAND_REST.match(_CAND_CMD.match(text).group("rest").strip()):
        return None
    if re.search(r"\b(?:called|named|name:|for my|for our|listing url|this|a new|another)\b", text, re.IGNORECASE) or len(text.split()) > 14:
        return None
    names = _split_names(m.group("names"))
    if not names or any(len(n.split()) < 2 for n in names):
        return None  # a single word is too thin to resolve to a listing
    leads = candidate_queue(tenant_id)
    archived = data.archived_competitors(tenant_id)
    active = data.watchlist_status(tenant_id)["active"]
    steps: list[Step] = []
    labels: list[str] = []
    notes: list[str] = []
    for name in names:
        if any(slot_resolvers.label_matches(name, ceo_reads.competitor_label(r)) for r in active):
            notes.append(f"{name} is already on your list.")
            continue
        hits = [c for c in leads if c.get("title") and slot_resolvers.label_matches(name, str(c["title"]))]
        old = [r for r in archived if r.get("label") and slot_resolvers.label_matches(name, str(r["label"]))]
        if len(hits) + len(old) > 1:
            options = "; ".join([f"“{c['title']}”" for c in hits[:4]] + [f"“{r['label']}”" for r in old[:2]])
            notes.append(f"“{name}” matches more than one: {options}. Say a longer part of the name.")
        elif hits:
            steps.append(Step("ci.competitor_approve", {"candidate_id": str(hits[0]["id"])}))
            labels.append(str(hits[0]["title"]))
        elif old:
            steps.append(Step("ci.competitor_add", {"url": old[0]["url"], "product_id": old[0]["linked_sku"] or "", "label": old[0]["label"]}))
            labels.append(str(old[0]["label"]))
        else:
            notes.append(f"I could not find “{name}” among the competitors I found or that you tracked before. Say “find my competitors” to search again.")
    if not steps:
        return Plan("TRACK_NAMES", text=" ".join(notes) if notes else None, context={}) if notes else None
    st = data.watchlist_status(tenant_id)
    if steps and st["free"] == 0:
        return Plan("CAP_FULL", text=_full_text(st["limit"], [ceo_reads.competitor_label(r) for r in st["active"]]) + " Nothing has been added yet.")
    if len(steps) > st["free"]:
        who = "; ".join(f"“{ceo_reads.competitor_label(r)}”" for r in st["active"])
        return Plan("TRACK_NAMES", text=(
            f"You named {len(steps)} but have {st['free']} free competitor slot{'s' if st['free'] != 1 else ''} of {st['limit']}" + (f" (tracked now: {who})" if who else "") +
            ". Name fewer, or stop tracking one first. Nothing has been added yet."))
    return Plan("TRACK_NAMES_RUN", steps=tuple(steps), context={"labels": labels, "notes": notes})


def _c_track_names(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    lines: list[str] = []
    full: Mapping[str, Any] | None = None
    for label, (step, leg) in zip(plan.context.get("labels", []), results):
        failed = _failed(leg)
        status = (getattr(leg, "payload", None) or {}).get("status")
        if failed:
            lines.append(f"{label}: {failed}")
        elif status in ("OK", "RESTORED"):
            lines.append(f"Tracking {label}." if status == "OK" else f"{label} was tracked before; I have started tracking it again with its history.")
        elif status == "CAP_REACHED":
            lines.append(f"{label}: not added.")
            full = getattr(leg, "payload", None) or {}
        else:
            lines.append(f"{label}: I could not add it.")
    lines += list(plan.context.get("notes", []))
    if full is not None:
        lines.append(_full_text(full.get("limit"), full.get("activeNames") or []))
    if any(ln.startswith("Tracking") or "tracked before" in ln for ln in lines):
        lines.append("I have no price for them until you send a screenshot of each listing and say which competitor it is.")
    return "\n".join(lines)


_COMPARE_VERB = re.compile(r"\b(?:compare|comparison|versus|vs\.?|stack up|where do i stand|how does|how do)\b", re.IGNORECASE)
_COMPETITORS_PLURAL = re.compile(r"\b(?:all|every|each)\b[^.?!]*\b(?:competitors?|rivals?)\b|\bmy competitors\b|\bcompetitors'? prices?\b|\bcompetitors\b", re.IGNORECASE)
_PRICE_IN_TEXT = re.compile(r"(?:₹|\brs\.?\s*|\binr\s*)(\d[\d,]*(?:\.\d{1,2})?)|\b(?:is|at|sells? (?:at|for)|priced at|selling (?:at|for))\s+(\d{2,6})\b", re.IGNORECASE)
_FINANCE_WORDS = re.compile(r"\b(?:profit|profitable|margin|loss|fees?|gst|cost|costs|roi|break[- ]?even)\b", re.IGNORECASE)


def _compare_all(tenant_id: UUID, text: str) -> Plan | None:
    """"Compare my price with all my competitors": one engine comparison per competitor that has a verified price, in the seller's own words about THEIR price; no profit is computed
    (that goes to finance). Without a seller price the seller is asked for it (or told to put it in the product profile)."""
    if not _COMPARE_VERB.search(text) or not _COMPETITORS_PLURAL.search(text) or _FINANCE_WORDS.search(text.replace("Do not calculate profit", "")):
        return None
    if isinstance(slot_resolvers.resolve_competitor(tenant_id, text), slot_resolvers.CompetitorMatch):
        return None  # one named competitor: that is the single comparison
    m = _PRICE_IN_TEXT.search(_PERCENT.sub(" ", text))
    price = slot_resolvers.parse_amount_paise(m.group(1) or m.group(2)) if m else None
    products = ceo_reads.list_seller_products(tenant_id)
    phrase = _product_phrase(text)
    found = slot_resolvers.resolve_seller_product(tenant_id, phrase) if phrase else None
    product_id: str | None = None
    if isinstance(found, slot_resolvers.ProductMatch):
        product_id, title = found.product_id, found.title or found.product_id
    elif price is not None:
        title = (products[0][1] or products[0][0]) if len(products) == 1 and not phrase else "your price"  # a stated price is compared with every tracked competitor: no product has to be chosen
    elif len(products) == 1 and not phrase:
        product_id, title = products[0][0], products[0][1] or products[0][0]
    elif not products:
        return Plan("COMPARE_ALL_ASK", text=NO_PRODUCTS_FOR_COMPARE)
    else:
        names = "; ".join(f"“{t or p}”" for p, t in products[:6])
        return Plan("COMPARE_ALL_ASK", text=f"Which of your products should I compare? Your products: {names}. Say it, or give me a price, for example “compare my price of ₹399 with all my competitors”.")
    if price is None and product_id is not None:
        price = data.seller_price_paise(tenant_id, product_id)
    if price is None:
        return Plan("COMPARE_ALL_ASK", text=f"I need your selling price for {title} to compare it. Tell me, for example “my price is ₹399”, or save it in your product profile. I never guess it.")
    comps = [c for c in data.all_competitors(tenant_id) if product_id is None or c.get("groupId") == product_id]
    verified = [c for c in comps if c["priceStatus"] == "VERIFIED" and c.get("listedPricePaise")][:5]
    skipped = [str(c["label"]) for c in comps if c not in verified]
    if not comps:
        return Plan("COMPARE_ALL_ASK", text=f"You have no competitors on your list for {title} yet, so there is nothing to compare with. Say “find my competitors”, choose a category, and tick the ones to track.")
    if not verified:
        return Plan("COMPARE_ALL_ASK", text=("None of your competitors has a verified price yet, so I cannot compare: " + "; ".join(skipped) + ". Send me a screenshot of each listing, say which competitor it is, and confirm the price."))
    steps = tuple(Step("ci.request_price_scenario", {"competitor_url_id": c["id"], "seller_price_paise": price}) for c in verified)
    return Plan("COMPARE_ALL", steps=steps, context={"labels": [str(c["label"]) for c in verified], "prices": [int(c["listedPricePaise"]) for c in verified], "price": price, "skipped": skipped, "title": title})


NO_PRODUCTS_FOR_COMPARE = "I do not have any of your products yet, so I cannot compare a price. Upload a sales report or add a product profile, then ask me again."


def _c_compare(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    price = int(plan.context["price"])
    rows: list[tuple[int, str, str]] = []
    for label, comp_price, (_, leg) in zip(plan.context["labels"], plan.context["prices"], results):
        failed = _failed(leg)
        pp = ((getattr(leg, "payload", None) or {}).get("pricePositioning") or [None])[0]
        if failed or not pp or pp.get("valuePaise") is None:
            rows.append((comp_price, label, f"{label}: {failed or 'the engine could not compare it'}"))
            continue
        gap = int(pp["valuePaise"])
        basis = str(pp.get("calculationBasis") or "")
        mine = re.search(r"gap_pct_of_seller_price=(-?[\d.]+)%", basis)
        theirs = re.search(r"gap_pct=(-?[\d.]+)%", basis)
        pct = (f" ({mine.group(1).lstrip('-')}% of your price" + (f", {theirs.group(1).lstrip('-')}% of theirs" if theirs else "") + ")") if mine else ""
        if gap == 0:
            line = f"{label}: {format_paise(comp_price)}, the same as your price."
        elif gap > 0:
            line = f"{label}: {format_paise(comp_price)}, which is {format_paise(gap)} below your price{pct}."
        else:
            line = f"{label}: {format_paise(comp_price)}, which is {format_paise(-gap)} above your price{pct}."
        rows.append((comp_price, label, line))
    rows.sort(key=lambda r: r[0])
    lines = [f"Your price for {plan.context['title']} is {format_paise(price)}. Compared with {len(rows)} competitor{'s' if len(rows) != 1 else ''} that have a verified price:"]
    lines += [f"- {r[2]}" for r in rows]
    below = sum(1 for p in plan.context["prices"] if p < price)
    if rows:
        lines.append(f"Cheapest: {rows[0][1]} at {format_paise(rows[0][0])}. Highest: {rows[-1][1]} at {format_paise(rows[-1][0])}. {below} of {len(rows)} are cheaper than you.")
    if plan.context.get("skipped"):
        lines.append("No verified price yet, so not compared: " + "; ".join(plan.context["skipped"]) + ". Send a screenshot of each and confirm the price.")
    lines.append("The differences are worked out by Metrion's price engine from your confirmed screenshots. They say nothing about profit; for what a price change would do to your margin, ask me and I will bring in finance.")
    return "\n".join(lines)


_COMPETITOR_SIGNAL = re.compile(r"\b(?:competitors?|rivals?|competition)\b", re.IGNORECASE)
_OTHER_AGENT = re.compile(r"\b(?:profit|profitable|margin|loss|fees?|gst|cost|costs|title|titles|bullets?|description|hashtags?|keywords?|listing copy|seo)\b", re.IGNORECASE)


def _competitor_help(tenant_id: UUID, text: str) -> Plan | None:
    """A competitor request nothing above recognised, and no explicit rule claims: instead of letting a small model guess (it once sent such questions to the finance form), say what CI
    can do, in words the seller can copy."""
    named = _named_competitor(tenant_id, text)[0] is not None
    # only a question or request about the seller's OWN competitors: a statement ("a competitor cut their price") is left to the normal route, which starts the right finance session
    if (not _QUESTION.search(text) or not (named or re.search(r"\bmy (?:competitors?|competition|rivals?)\b", text, re.IGNORECASE)) or _OTHER_AGENT.search(text)
            or re.search(r"\b(?:price|prices|pricing|rupees?|rs\.?|margin|cost|charges?)\b|₹", text, re.IGNORECASE)):  # a price question is the model's to route (price scenario / finance), not a help menu
        return None
    st = data.watchlist_status(tenant_id)
    example = ceo_reads.competitor_label(st["active"][0]) if st["active"] else "<name>"
    return Plan("CI_HELP", text=(
        "I can help with your competitors, but I am not sure which of these you want. You can say, for example:\n"
        "- “Show my tracked competitors”\n"
        "- “Compare my price with all my competitors”\n"
        f"- “What would a buyer pay for {example}, delivery included?”\n"
        f"- “Is {example} a variant or a direct competitor?”\n"
        "- “Check my tracked competitors” (freshness and verified changes)\n"
        f"- “Track a competitor” (I find matches for you to tick) or “Stop tracking {example}”\n"
        "- “Find competitors for my <product>” (I ask your approval first)\n"
        "For profit or margin questions I bring in finance, and for listing text I bring in the marketing writer."))


def _needs_link(tenant_id: UUID, text: str) -> Plan | None:
    """"Track this competitor ..." with no link in it (or a placeholder where it should be): CI asks for the link and adds nothing."""
    if _URL.search(text) or not _NEEDS_LINK.search(text):
        return None
    return Plan("NEEDS_LINK", text=(
        "I need the competitor's listing link to track it: an amazon.in, flipkart.com or meesho.com address. Send it with the name, for example “track <link> called <name> for my <product>”. "
        "Nothing has been added yet."))


def _none_match(tenant_id: UUID, text: str) -> Plan | None:
    """The seller said none of their tracked competitors is in the screenshot (the pick card's "None of these"): nothing is stored."""
    if NONE_MATCH_TEXT not in text.casefold() and not re.search(r"\bnone of (?:these|them|my tracked competitors)\b", text, re.IGNORECASE):
        return None
    return Plan("NONE_MATCH", text="Understood: that screenshot does not show any of your tracked competitors, so I stored nothing and read nothing from it. "
                "If it is a new competitor, say “find my competitors”, tick it in the list to track it, then send the screenshot again.")


_VERIFY = re.compile(r"^\W*(?:please\s+)?verify\s+(?P<name>.+?)\W*$", re.IGNORECASE)
_DETAILS = re.compile(r"^\W*details for\s+(?P<names>.+?)\W*$", re.IGNORECASE)


def _verify(tenant_id: UUID, text: str) -> Plan | None:
    """"Verify <competitor>": a price is verified only from a listing screenshot the seller sends and confirms, so this says exactly what to attach."""
    m = _VERIFY.match(text)
    if not m:
        return None
    named = slot_resolvers.resolve_competitor(tenant_id, m.group("name"))
    if not isinstance(named, slot_resolvers.CompetitorMatch):
        return None
    return Plan("VERIFY", text=(f"To verify {named.label}, attach a screenshot of its listing here (the page with the price, delivery and stock visible) and send it with “this is {named.label}”. "
                                "I read it, ask you to confirm the price, stock, discount and offers, and only then do they count as verified."), context={"focus": str(named.url_id)})


def _details_for(tenant_id: UUID, text: str) -> Plan | None:
    m = _DETAILS.match(text)
    if not m:
        return None
    ids = []
    for name in _split_names(m.group("names")):
        found = slot_resolvers.resolve_competitor(tenant_id, name)
        if isinstance(found, slot_resolvers.CompetitorMatch):
            ids.append(found.url_id)
    return _competitor_detail(tenant_id, ids) if ids else None


_FACTS_Q = re.compile(
    r"\b(?:what do you know|tell me|show|give me|summari[sz]e|details?|status|info)\b[^.?!]*\b(?:this|that|the same|it|its)\b|\b(?:verified price|delivery charge|stock status|evidence date)\b[^.?!]*\b(?:this|that)\b", re.IGNORECASE)
_REVIEW_EXPLAIN = re.compile(
    r"\b(?:enough|reliable|sample size|how many (?:individual )?reviews|recurring|how sure|can i trust)\b[^.?!]*\b(?:reviews?|complaints?|themes?|sample)\b|\b(?:reviews?|complaints?)\b[^.?!]*\b(?:enough|reliable|sample size|recurring)\b", re.IGNORECASE)


_PATTERNS_Q = re.compile(
    r"\b(?:analy[sz]e|patterns?|what do|compare|look at|summari[sz]e)\b[^.?!]*\b(?:titles?|bullets?|descriptions?|keywords?|selling points?|listings?)\b[^.?!]*\b(?:competitors?|rivals?)\b"
    r"|\b(?:competitors?|rivals?)\b[^.?!]*\b(?:titles?|keywords?|bullets?|selling points?)\b", re.IGNORECASE)


def _listing_patterns(tenant_id: UUID, text: str) -> Plan | None:
    """"What patterns do my competitors' titles, keywords and selling points show?": answered from the listing captures the seller already sent (derived words only), saying how many
    competitors it rests on and what it cannot tell (search volume, rank, sales). Writing the seller's own listing from it is a separate, approved step."""
    if not _PATTERNS_Q.search(text) or re.search(r"\b(?:write|improve|rewrite|create|generate|optimi[sz]e)\b", text, re.IGNORECASE):
        return None
    info = data.listing_patterns(tenant_id)
    n = info["competitors"]
    if n == 0:
        return Plan("LISTING_PATTERNS", text=("I have no saved listing capture of your competitors yet, so there is no pattern to report. Attach a screenshot of a competitor's listing (title, bullets and "
                                              "description visible) and say which competitor it is; I read it, you confirm it, and I keep the title words and feature areas."))
    lines = [f"From the listing screenshots you sent for {n} competitor{'s' if n != 1 else ''}:"]
    if info["words"]:
        lines.append("- Words their titles share: " + ", ".join(info["words"]))
    if info["features"]:
        lines.append("- Feature areas they mention: " + ", ".join(info["features"]))
    if info["avgTitleWords"]:
        lines.append(f"- Their titles are about {info['avgTitleWords']} words long on average")
    lines.append("This comes only from the screenshots you sent, so it is a small sample, not the whole market. It says nothing about search volume, ranking or sales.")
    lines.append("To use it, say “Improve my listing”: I write original text from your own product facts and check it is not a copy of any competitor's wording.")
    return Plan("LISTING_PATTERNS", text="\n".join(lines))


_TRACK_THIS = re.compile(r"^\W*(?:please\s+)?(?:track|add|follow)\s+(?:this|that|the)\s+(?:new\s+)?(?:competitor|rival)\W*(?:\d+\.?\s*)?[^:/]{0,60}$", re.IGNORECASE)


def _track_this(tenant_id: UUID, text: str) -> Plan | None:
    """"Track this competitor" with no link: nothing is searched and no link is asked for. If it names a competitor already on the list, it says so; otherwise it points to the find-and-tick flow."""
    if _URL.search(text) or not (_TRACK_THIS.match(text) or _NEEDS_LINK.search(text)):
        return None
    url_id, label = _named_competitor(tenant_id, text)
    if url_id is not None:
        return Plan("TRACK_THIS", text=f"{label} is already on your list, so there is nothing to add. Press “Verify price” on its row, or attach its listing screenshot here.")
    return Plan("TRACK_THIS", text="To track a competitor, say “find my competitors”, choose a category, and tick the ones to track. I do not add one from a name alone.")


def _competitor_facts(tenant_id: UUID, text: str) -> Plan | None:
    """"Show the verified price, delivery, stock and evidence date for THIS competitor": what is saved for the competitor the conversation is about."""
    if not _FACTS_Q.search(text) or _URL.search(text) or isinstance(slot_resolvers.resolve_competitor(tenant_id, text), slot_resolvers.CompetitorMatch):
        return None
    url_id, label = _named_competitor(tenant_id, text)
    if url_id is None:
        return None
    row = next((c for c in data.all_competitors(tenant_id) if c["id"] == url_id), None)
    if row is None:
        return None
    if row["priceStatus"] != "VERIFIED":
        why = "a screenshot of it is waiting for your confirmation" if row["priceStatus"] == "UNVERIFIED" else "I have no confirmed screenshot of it yet"
        return Plan("COMPETITOR_FACTS", text=f"{row['label']}: no verified price, because {why}. Press “Verify price” on its row, or attach its listing screenshot here and say it is {row['label']}.")
    ep = row.get("effectivePrice") or {}
    tot = ep.get("buyerTotal") or {}
    d = ep.get("deliveryChargePaise")
    delivery = "free delivery" if d == 0 else (format_paise(d) if isinstance(d, int) else "not confirmed")
    stock = {"IN_STOCK": "in stock", "OUT_OF_STOCK": "out of stock"}.get(str(row.get("availability")), "not confirmed")
    lines = [f"{row['label']} ({str(row['marketplace']).title()}), from your confirmed screenshot of {(row.get('evidenceDate') or '')[:10]}:",
             f"- Verified price: {format_paise(row['listedPricePaise'])}", f"- Delivery: {delivery}", f"- Stock: {stock}"]
    if tot.get("isAvailable"):
        lines.append(f"- A buyer pays: {format_paise(tot['valuePaise'])} with delivery (worked out by Metrion's price engine)")
    return Plan("COMPETITOR_FACTS", text="\n".join(lines), context={"focus": url_id})


def _review_explain(tenant_id: UUID, text: str) -> Plan | None:
    """"Are these reviews enough to call a complaint reliable? Explain the sample size": answered from what was read, never from a model's opinion."""
    if not _REVIEW_EXPLAIN.search(text):
        return None
    url_id, label = _named_competitor(tenant_id, text)
    if url_id is None:
        return None
    summary = data.review_summary(tenant_id, url_id)
    if summary is None:
        return Plan("REVIEW_EXPLAIN", text=f"I have no review screenshot of {label} yet, so there is no sample to judge. Attach a screenshot of its reviews and say it is {label}.")
    n, need = summary.get("reviewsConsidered"), int(summary.get("minSample") or 0)
    if not isinstance(n, int):
        return Plan("REVIEW_EXPLAIN", text=f"I saved review themes for {label}, but the screenshot did not show how many reviews it covered, so I cannot judge the sample.")
    enough = "enough to call a theme recurring" if n >= need else "not enough to call anything recurring"
    return Plan("REVIEW_EXPLAIN", text=(
        f"For {label} I read {n} review{'s' if n != 1 else ''} in your screenshot. I only call a theme recurring when at least {need} reviews were read; {n} is {enough}. "
        + ("" if n >= need else "So what is listed are single mentions, not a pattern, and no finding was raised. Send more review screenshots of the same competitor to build a reliable sample. ")
        + "The reading is done by a small local model that can make mistakes, so please check it against your screenshot."), context={"focus": url_id})


def _relationship_question(tenant_id: UUID, text: str) -> Plan | None:
    """"Is X an exact match, a variant, a direct competitor or a functional alternative?": what CI stored, or the plain fact that it has not classified it."""
    if not _RELATION_Q.search(text):
        return None
    url_id, label = _named_competitor(tenant_id, text)
    if url_id is None:
        return None
    ws = data.workspace(tenant_id, None)
    row = next((c for c in ws.get("competitors", []) if c["id"] == url_id), None)
    if row is None:
        return None
    rel = row.get("relationshipClass") or "UNKNOWN"
    seen = []
    if row.get("ratingValue"):
        seen.append(f"its rating on the listing was {row['ratingValue']}" + (f" from {row['ratingCount']} ratings" if row.get("ratingCount") else ""))
    if row.get("evidenceDate"):
        seen.append(f"my newest screenshot of it is from {row['evidenceDate'][:10]}")
    known = ("What I hold: " + "; ".join(seen) + ".") if seen else "I hold no screenshot details of it yet."
    if rel == "UNKNOWN":
        return Plan("RELATION_Q", text=(
            f"I have not classified {row['label']}. It was added by link, so I have no search-time comparison of its product against yours, and a classification needs its title and attributes next to yours. "
            f"{known} I do not guess between an exact match, a variant, a direct competitor and a functional alternative; ask me to find competitors for your product and I will classify the leads I find, "
            "or tell me what differs (size, material, pack size) and I will note it."))
    words = RELATIONSHIP_WORDS.get(rel, "is not classified yet")
    basis = []
    if row.get("identityMatch"):
        basis.append(f"identity check: {str(row['identityMatch']).lower().replace('_', ' ')}")
    if row.get("relevanceBand"):
        basis.append(f"relevance: {str(row['relevanceBand']).lower()}" + (" (provisional)" if row.get("relevanceProvisional") else ""))
    return Plan("RELATION_Q", text=f"{row['label']} {words}. " + (("Evidence: " + "; ".join(basis) + ". ") if basis else "") + known +
                " Attributes I could not compare stay unknown; I never fill them in.")


def _provenance_question(tenant_id: UUID, text: str) -> Plan | None:
    """"Where did X's price come from and who confirmed it?": from the stored state of that competitor's evidence."""
    if not _PROVENANCE_Q.search(text):
        return None
    url_id, label = _named_competitor(tenant_id, text)
    if url_id is None:
        return None
    ws = data.workspace(tenant_id, None)
    row = next((c for c in ws.get("competitors", []) if c["id"] == url_id), None)
    if row is None:
        return None
    waiting = [p for p in ws.get("pending", []) if p.get("competitorId") == url_id]
    if row["priceStatus"] == "VERIFIED":
        return Plan("PROVENANCE", text=(
            f"{row['label']}'s price of {format_paise(row['listedPricePaise'])} comes from a screenshot you sent, dated {(row.get('evidenceDate') or '')[:10]}. A vision model read it, and you confirmed or corrected "
            "the price in this chat before it was used; a price is never used before that. Your Competitors page keeps the evidence and the confirmation in its history."))
    if row["priceStatus"] == "UNVERIFIED":
        fields = ", ".join(str(p["field"]).replace("_paise", "").replace("_", " ") for p in waiting) or "some details"
        return Plan("PROVENANCE", text=(
            f"{row['label']} has no verified price yet. A screenshot was read, but nobody has confirmed it, so no price is used. Still waiting on you: {fields}. "
            "Reply with the right values, or “yes” if they are right."))
    return Plan("PROVENANCE", text=f"I have no screenshot of {row['label']} yet, so there is no price and nothing to trace. Send one and say which competitor it is.")


def _restore(tenant_id: UUID, text: str) -> Plan | None:
    if not _RESTORE.search(text) or _URL.search(text):
        return None
    norm = _norm(text).casefold()
    rows = [r for r in data.archived_competitors(tenant_id) if r.get("label") and slot_resolvers.label_matches(norm, str(r["label"]))]
    if len(rows) == 1:
        r = rows[0]
        return Plan("ADD_COMPETITORS", steps=(Step("ci.competitor_add", {"url": r["url"], "product_id": r["linked_sku"] or "", "label": r["label"]}),), context={"urls": [r["url"]]})
    if len(rows) > 1:
        return Plan("RESTORE", text="That matches more than one competitor you stopped tracking: " + "; ".join(str(r["label"]) for r in rows[:6]) + ". Which one?")
    return Plan("RESTORE", text="I do not have a competitor of that name that you tracked before. Say “find my competitors” to search again.")


def _explain_latest(tenant_id: UUID, text: str, *, finding_id: UUID | None = None) -> Plan | None:
    if finding_id is not None or not _EXPLAIN.search(text):
        return None
    ws = data.workspace(tenant_id, None)
    findings = sorted(ws.get("findings") or [], key=lambda f: f.get("createdAt") or "", reverse=True)
    if not findings:
        return Plan("EXPLAIN_NONE", text="I have no competitor findings to explain yet. A finding appears when you confirm a screenshot that shows a price or stock change, or when I read a reviews screenshot with enough reviews.")
    return Plan("EXPLAIN_FINDING", steps=(Step("ci.explain_finding", {"finding_id": findings[0]["id"]}),))


def _screenshot_missing(tenant_id: UUID, text: str) -> Plan | None:
    """The seller talks about a screenshot they have, but none is attached: say so and how to send it, plus the newest verified change CI already holds."""
    if not _SCREENSHOT_TALK.search(text):
        return None
    ws = data.workspace(tenant_id, None)
    change = (ws.get("changes") or [None])[0]
    held = ""
    if change and change.get("deltaPct"):
        move = "down" if change.get("direction") == "DECREASE" else "up"
        held = f" Meanwhile, the newest verified change I hold is for {change['label']}: price {move} {str(change['deltaPct']).lstrip('-')}%, from your screenshots of {(change.get('evidenceDate') or '')[:10]}."
    return Plan("SCREENSHOT_MISSING", text=(
        "I do not see a screenshot attached to your message. Attach it in this chat with the paperclip and tell me which competitor it shows, for example “this is The Better Home 1L”. "
        "I will read it, ask you to confirm the price, and compare it with the previous one." + held))


RELATIONSHIP_WORDS = {
    "SAME_PRODUCT": "looks like the same product", "VARIANT": "may be a different variant", "DIRECT_COMPETITOR": "looks like a direct competitor",
    "FUNCTIONAL_ALTERNATIVE": "looks like a functional alternative", "UNRELATED": "looks unrelated", "UNKNOWN": "is not classified yet",
}


TOP_MATCHES = 15  # a competitor search shows the seller this many best matches (owner decision 2026-10-20)


def pick_card(title: str, subtitle: str, mode: str, max_pick: int, items: Sequence[Mapping[str, Any]], actions: Sequence[Mapping[str, Any]], *, select_all: bool = False) -> dict[str, Any]:
    """A card the chat shows with check boxes (mode "multi") or radio buttons (mode "single"). It carries no facts of its own: its items are what the CEO listed in the same message, and
    pressing an action sends the text its template makes ("{numbers}" -> "1, 3", "{labels}" -> "A and B") as if the seller had typed it, so exactly the same checks run. An action may need
    an exact number of picks (`exactly`)."""
    return {"version": 2, "kind": "PICK", "title": title, "subtitle": subtitle, "mode": mode, "maxPick": max_pick, "selectAll": select_all, "items": [dict(i) for i in items], "actions": [dict(a) for a in actions]}


def category_card(categories: Sequence[str]) -> dict[str, Any]:
    """The competitor-search question as a card: the business-profile categories to tick."""
    return pick_card("Which categories should I find competitors for?", "Tick one or more. I search each one and show the top matches to choose from.", "multi", len(categories),
                     [{"key": str(i), "n": i, "label": c} for i, c in enumerate(categories, start=1)], [{"id": "go", "label": "Find competitors", "template": "{numbers}"}], select_all=True)


def tracked_card(rows: Sequence[Mapping[str, Any]], *, with_actions: bool = True) -> dict[str, Any]:
    """The seller's tracked competitors as a card: tick one or more and choose what to do (see the details, send a screenshot to verify the price, stop tracking)."""
    items = [{"key": str(i), "n": i, "label": ceo_reads.competitor_label(r), "marketplace": str(r["marketplace"]).title() if r.get("marketplace") else None} for i, r in enumerate(rows, start=1)]
    acts = [{"id": "details", "label": "Show details", "template": "details for {labels}"},
            {"id": "verify", "label": "Verify price", "template": "verify {labels}", "exactly": 1},
            {"id": "stop", "label": "Stop tracking", "template": "stop tracking {labels}", "exactly": 1}] if with_actions else []
    return pick_card("Your tracked competitors", "Tick one or more, then choose what to do.", "multi", len(items), items, acts, select_all=True)


def screenshot_card(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Which tracked competitor a screenshot shows: pick one (or say none of them)."""
    items = [{"key": str(i), "n": i, "label": str(r["label"]) if r.get("label") and "url" not in r else ceo_reads.competitor_label(r), "marketplace": str(r["marketplace"]).title() if r.get("marketplace") else None}
             for i, r in enumerate(rows, start=1)]
    return pick_card("Which competitor is in this screenshot?", "Pick the one it shows. If it is none of them, nothing is stored.", "single", 1, items,
                     [{"id": "this", "label": "Confirm", "template": "this is {labels}"}, {"id": "none", "label": "None of these", "template": NONE_MATCH_TEXT, "noPick": True}])


NONE_MATCH_TEXT = "none of my tracked competitors match this screenshot"


def _pick_guidance(st: Mapping[str, Any] | None) -> str:
    """What the seller can do with the slots they have: pick up to the free ones, or make room first. Written from the stored watchlist, never guessed."""
    if not st:
        return "Tell me which to track, for example “track 1 and 3”, or which to reject."
    names = [ceo_reads.competitor_label(r) for r in st["active"]]
    who = f" (tracked now: {'; '.join(f'“{n}”' for n in names)})" if names else ""
    if st["free"] == 0:
        return (f"Your list is full: {len(names)} of {st['limit']} competitors are tracked{who}. To add any of these, first stop tracking one, for example “stop tracking {names[0]}”, then tell me "
                "which to track.")
    room = "" if not names else " To make more room, stop tracking one first."
    return (f"You can track {st['free']} more (of {st['limit']}){who}. Pick up to {st['free']} by number, for example “track 1 and 3”, or say which to reject.{room}")


def _candidate_list(queue: Sequence[Mapping[str, Any]], st: Mapping[str, Any] | None = None) -> str:
    what = "your categories" if any(c.get("category") for c in queue) else "your product"
    lines = [f"Here are the top {len(queue)} matches I found for {what}, best match first. These are search leads, not verified prices. {_pick_guidance(st)}"]
    for i, c in enumerate(queue, start=1):
        market = str(c["marketplace"]).title() if c.get("marketplace") else "a marketplace"
        rel = c.get("relationship_class") or "UNKNOWN"
        why = data.identity_note(c) if c.get("category") else (RELATIONSHIP_WORDS.get(rel) if rel != "UNKNOWN" else data.identity_note(c))
        title = " ".join(str(c.get("title") or "").split())[:110]
        if title:  # what the search called it, where it is, why it is listed, and the link to open it (nothing here is a price)
            lines.append(f"{i}. {title} ({market}): {why or 'not classified yet'}. {c.get('candidate_url') or ''}".rstrip())
        else:
            lines.append(f"{i}. A listing on {market} that {RELATIONSHIP_WORDS.get(rel, 'is not classified yet')}.")
    lines.append("To compare any of them with your product I need a screenshot of its listing: send it here and say which competitor it is.")
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ composing
def _fmt_field(name: str, value: Any) -> str:
    if name in ("listed_price_paise", "visible_discount_paise") and isinstance(value, int):
        return format_paise(value)
    if name == "availability":
        return "in stock" if value == "IN_STOCK" else "out of stock" if value == "OUT_OF_STOCK" else str(value).lower()
    if name == "delivery_charge_paise" and isinstance(value, int):
        return "free delivery" if value == 0 else format_paise(value)
    if name == "offers" and isinstance(value, list):
        return "; ".join(_fmt_offer(o) for o in value) or "no usable offer"
    return str(value)


def _fmt_offer(o: Mapping[str, Any]) -> str:
    kind = {"COUPON": "coupon", "BANK_OFFER": "bank offer"}.get(str(o.get("kind")), "offer")
    amount = f" {format_paise(o['amount_paise'])} off" if isinstance(o.get("amount_paise"), int) else ""
    cond = f" ({o['condition_text']}, which I will not count in the price)" if o.get("condition_text") else ""
    return f"{kind}{amount}{cond}"


_FIELD_WORDS = {"listed_price_paise": "price", "visible_discount_paise": "discount", "availability": "stock status", "delivery_charge_paise": "delivery charge", "offers": "offers"}
_QUALITY_WORDS = {
    "EMPTY": "the file is empty", "TOO_LARGE": "the file is larger than the allowed size", "NOT_AN_IMAGE": "it is not an image I can read",
    "UNSUPPORTED_TYPE": "only PNG, JPEG or WebP screenshots are supported", "TOO_SMALL": "the image is too small to read the details",
    "TOO_BLURRY": "the image is too blurry to read the price and details",
}
_ERROR_WORDS = {
    "ATTACHMENT_NOT_FOUND": "I could not find that attachment in this conversation.", "ATTACHMENT_CHANGED": "That attachment changed after I saw it, so I did not use it.",
    "VISION_ENDPOINT_NOT_VERIFIED": "The screenshot reader is not switched on for this account yet, so I could not read it. Nothing was stored.",
    "FINDING_NOT_FOUND": "I could not find that finding. It may belong to another account or no longer exist.", "NO_INVESTIGATION": "This needs an open conversation.",
    "INVALID_THRESHOLD": "I can alert you on price changes between 1% and 50%. Tell me a number in that range and I will save it. Nothing was changed.",
    "INVALID_QUIET_HOURS": "I could not save those quiet hours. Say them like “quiet hours 10pm to 7am”. Nothing was changed.",
}


def compose(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    """The reply, written by code from the stored results. `results` pairs each step with its LegResult."""
    if plan.text is not None and not plan.steps:
        return _guard(plan.text)
    handler = {
        "EXPLAIN_FINDING": _c_explain, "INTAKE": _c_intake, "REVIEW_INTAKE": _c_review, "CONFIRM": _c_confirm,
        "ADD_COMPETITORS": _c_add, "DECIDE_CANDIDATES": _c_decide, "ALERT_SETTINGS": _c_settings, "TRACK_NAMES_RUN": _c_track_names, "COMPARE_ALL": _c_compare,
    }.get(plan.kind)
    if handler is None:
        return "I could not work out what to do with that."
    return _guard(handler(plan, results))


def _guard(text: str) -> str:
    """The no-currency-claim rule (C40, AC47) applied to every CI reply: a reply that would claim live or current knowledge is replaced, never sent."""
    if data.currency_claims(text):
        return "I have recorded this from the evidence you sent. I do not watch competitors between your screenshots, so tell me when you have a newer one."
    return text


def _failed(leg: Any) -> str | None:
    status = getattr(getattr(leg, "status", None), "value", None)
    payload = getattr(leg, "payload", None) or {}
    if status in ("COMPLETE", "PARTIAL") and payload.get("status") == "REFUSED":
        return _ERROR_WORDS.get(str(payload.get("code")), "I could not do that, and nothing was changed.")
    if status in ("COMPLETE", "PARTIAL"):
        return None
    reason = getattr(leg, "reason", None) or ""
    if status == "DENIED":
        return "Your role or this conversation does not include Competitor Intelligence, so I did not do that."
    if status == "NOT_ENTITLED":
        return "Your plan does not include that yet, so I did not do it."
    return _ERROR_WORDS.get(str(reason).upper(), "I could not do that just now, and nothing was changed. Please try again.")


def _c_explain(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    leg = results[0][1]
    failed = _failed(leg)
    if failed or not getattr(leg, "payload", None):
        return failed or "I could not find that finding."
    p = leg.payload
    pay = p.get("payload") or {}
    label = pay.get("label") or "a competitor"
    ftype = p["findingType"]
    ev = p.get("evidence") or []
    date = (pay.get("evidenceDate") or "")[:10] or "a date I do not have"
    basis = f"It rests on {len(ev)} screenshot{'s' if len(ev) != 1 else ''} you sent" if ev else "It has no screenshot behind it, so I will not rely on it"
    if ftype in ("PRICE_CHANGE", "AVAILABILITY_CHANGE"):
        if pay.get("deltaPaise"):
            move = "dropped" if pay.get("direction") == "DECREASE" else "rose"
            body = (f"{label}'s price {move} from {format_paise(pay.get('fromPricePaise'))} to {format_paise(pay.get('toPricePaise'))} "
                    f"({str(pay.get('deltaPct', '')).lstrip('-')}%), according to the screenshots of {date}.")
        else:
            body = f"{label}'s stock status changed ({str(pay.get('availabilityChange') or 'changed').lower().replace('_', ' ')}), according to the screenshot of {date}."
        tail = "I have not worked out what this means for your margin. If you want to know whether to change your price, ask me and I will get the profit figures from the finance side."
    elif ftype == "REVIEW_THEME":
        themes = [t["theme"] if isinstance(t, dict) else str(t) for t in (pay.get("complaintThemes") or [])] if isinstance(pay.get("complaintThemes"), list) else list((pay.get("complaintThemes") or {}).keys())
        sample = f"{p['sampleSize']} reviews were read" if p.get("sampleSize") else "the number of reviews read is not stated"
        body = f"Customers of {label} mention: {', '.join(themes) if themes else 'no recurring complaint I could find'} ({sample}; that is only what the screenshot showed, not all their reviews)."
        tail = "If you want to turn this into listing ideas for your own product, ask me."
    elif ftype == "FRESHNESS":
        body = f"My newest screenshot of {label} is from {date}, so I cannot say what it costs now."
        tail = "Send me a fresh screenshot of its listing and I will compare it again."
    else:
        body = f"This is a {ftype.lower().replace('_', ' ')} finding about {label}."
        tail = ""
    conf = f"Confidence: {str(p['confidence']).lower()}; confirmation: {str(p['sellerConfirmation']).lower().replace('_', ' ')}."
    return "\n\n".join(x for x in (body, f"{basis}. {conf}", tail) if x)


def _c_intake(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    leg = results[0][1]
    failed = _failed(leg)
    if failed:
        return failed
    p = leg.payload or {}
    label = plan.context.get("label") or "that competitor"
    status = p.get("status")
    if status == "REJECTED_QUALITY":
        return f"I could not use that screenshot: {_QUALITY_WORDS.get(str(p.get('qualityReason')), 'it was not clear enough to read')}. Please send a clearer one. Nothing was stored."
    if status == "REJECTED_NOT_A_LISTING":
        return "That does not look like a marketplace listing, so I did not use it. Send a screenshot of the competitor's product page showing the price. Nothing was stored."
    if status == "DUPLICATE":
        return "I already have exactly this screenshot, so I did not add it again."
    if status == "NEAR_DUPLICATE":
        return ("This looks almost the same as a screenshot you already sent. If it is a new capture of the page, say “it's a fresh capture” and I will use it. Otherwise I have left it out.")
    if status == "EXTRACTION_FAILED":
        return "I could not read details from that screenshot, so nothing was stored. A clearer, full-page screenshot usually works."
    if status in ("NEEDS_COMPETITOR", "COMPETITOR_NOT_FOUND"):
        return "I could not tell which tracked competitor that is, so I stored nothing."
    qs = p.get("questions") or []
    read = []
    summary = p.get("summary") or {}
    if summary.get("rating"):
        read.append(f"rating {summary['rating']}" + (f" from {summary['ratingCount']} ratings" if summary.get("ratingCount") else ""))
    head = f"I read your screenshot of {label}" + (f" ({', '.join(read)})" if read else "") + "."
    if not qs:
        return head + " Nothing in it needed your confirmation, and it is saved with the evidence. I do not know anything newer than this screenshot."
    shown = "; ".join(f"{_FIELD_WORDS.get(q['field'], q['field'])} {_fmt_field(q['field'], q.get('proposedValue'))}" for q in qs if q.get("proposedValue") is not None)
    missing = [q for q in qs if q.get("proposedValue") is None]
    ask = f"I am not using these until you confirm them, because a misread price would mislead you: {shown}." if shown else ""
    if any(q["field"] == "visible_discount_paise" and q.get("proposedValue") is not None for q in qs):
        ask += " A percentage shown next to the price (for example “-39%”) is already inside the listed price and is not an extra discount; reply “no discount” if that is what this is."
    how = "Reply “yes” if they are right, or tell me the right value (for example “price is 2899”, “delivery is 49”, “free delivery” or “out of stock”), or say “skip” and I will leave them out."
    extra = (" I could not read " + ", ".join(_FIELD_WORDS.get(q["field"], q["field"]) for q in missing) + ".") if missing else ""
    if any(q["field"] == "listed_price_paise" for q in missing):  # the one field nothing can be done without
        return (head + " I could not read the price in this screenshot, so I cannot use it yet. Please send a clearer, full-page screenshot where the price is visible, "
                "or tell me the price (for example “price is 329”)." + (" " + ask if ask else ""))
    return "\n\n".join(x for x in (head, ask + extra, how) if x)


def _c_review(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    leg = results[0][1]
    failed = _failed(leg)
    if failed:
        return failed
    p = leg.payload or {}
    label = plan.context.get("label") or "that competitor"
    if p.get("status") == "REJECTED_QUALITY":
        return f"I could not use that screenshot: {_QUALITY_WORDS.get(str(p.get('qualityReason')), 'it was not clear enough')}. Please send a clearer one."
    state = p.get("insightState")
    if state in ("UNAVAILABLE", None):
        return f"I could not get review themes from that screenshot of {label}. A screenshot of the reviews section with several reviews visible works best."
    n = p.get("reviewsConsidered")
    if not isinstance(n, int):
        return (f"I read the reviews screenshot of {label}. The themes are saved with how many reviews were read, and they show on your Competitors page. "
                f"This is only what that screenshot showed, not all their reviews.")
    def top(themes: Mapping[str, Any]) -> str:
        return ", ".join(f"{t} ({c})" for t, c in sorted(themes.items(), key=lambda kv: (-int(kv[1]), kv[0]))[:6])
    low = int(p.get("minSample") or 0)
    lines = [f"I read {n} review{'s' if n != 1 else ''} in that screenshot of {label}, using the local reading model, which can get things wrong. Please check this against your screenshot."]
    lines.append("Complaints: " + (top(p.get("complaintThemes") or {}) or "none found") + ".")
    lines.append("Praise: " + (top(p.get("positiveThemes") or {}) or "none found") + ".")
    if low and n < low:
        lines.append(f"That is fewer than the {low} reviews I need before calling anything a recurring theme, so it is saved on your Competitors page as a small sample and no finding was raised.")
    else:
        lines.append("This is only what that screenshot showed, not all their reviews.")
    return "\n".join(lines)


def _c_confirm(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    leg = results[0][1]
    failed = _failed(leg)
    if failed:
        return failed
    p = leg.payload or {}
    state = p.get("priceConfirmation")
    open_left = p.get("stillOpen") or []
    if plan.context.get("declined") and state == "DECLINED" and not plan.context.get("held"):
        return "Understood. I have left those details out, so that screenshot will not be used for prices, comparisons or alerts."
    if open_left:
        names = ", ".join(_FIELD_WORDS.get(o["field"], o["field"]) for o in open_left)
        return f"Thanks. I am still not using the {names} {CONFIRM_MARKER}. Reply “yes” if it is right, or tell me the right value."
    change = p.get("verifiedChange")
    tail = ""
    if change:
        move = "down" if change.get("direction") == "DECREASE" else "up"
        tail = f" Compared with the previous screenshot, the price is {move} {str(change.get('deltaPct', '')).lstrip('-')}%."
    held_names = [_FIELD_WORDS.get(h, h) for h in sorted(set(plan.context.get("held") or []) | set(p.get("leftOut") or []))]
    held_note = (" I am not using " + ", ".join(held_names) + ", as you asked: they stay unknown, so nothing that needs them is worked out.") if held_names else ""
    corrected = plan.context.get("corrected") or []
    note = (" I used your corrected " + ", ".join(_FIELD_WORDS.get(c, c) for c in corrected) + " instead of what I read.") if corrected else ""
    return f"Thanks, confirmed.{note}{held_note} It is now part of your verified competitor data.{tail}"


def _full_text(limit: Any, names: Sequence[str]) -> str:
    n = len(names)
    who = "; ".join(f"“{x}”" for x in names)
    return (f"Your competitor list is full: {n} of {limit} are being tracked ({who}). Stop tracking one to make room, for example “stop tracking {names[0] if names else '<name>'}”, then ask me again.")


def _c_add(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    full: Mapping[str, Any] | None = None
    lines: list[str] = []
    for step, leg in results:
        failed = _failed(leg)
        host = re.sub(r"^https?://(www\.)?", "", str(step.slots["url"]))[:40]
        if failed:
            lines.append(f"{host}: {failed}")
            continue
        p = leg.payload or {}
        status = p.get("status")
        if status == "OK":
            lines.append(f"Tracking {host}.")
        elif status == "RESTORED":
            lines.append(f"{host} was tracked before; I have started tracking it again with its history.")
        elif status == "ALREADY_TRACKED":
            named = str(p.get("detail") or "")
            lines.append(f"{host} is already tracked; I have named it “{named[6:]}”." if named.startswith("named:") else f"{host} is already tracked.")
        elif status == "NOT_ALLOWLISTED":
            lines.append(f"{host}: I can only track amazon.in, flipkart.com and meesho.com links.")
        elif status == "CAP_REACHED":
            lines.append(f"{host}: not added.")
            full = p
        else:
            lines.append(f"{host}: I could not add it.")
    if full is not None:
        lines.append(_full_text(full.get("limit"), full.get("activeNames") or []))
    if any("Tracking" in ln or "tracked before" in ln for ln in lines):
        lines.append("I have no price for a competitor until you send me a screenshot of its listing. Send one here and say which competitor it is. You can ask me to stop tracking any of them.")
    return "\n".join(lines)


def _c_settings(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    leg = results[0][1]
    failed = _failed(leg)
    if failed:
        return failed
    p = leg.payload or {}
    parts: list[str] = []
    q = p.get("quietHours")
    if p.get("cleared"):
        parts.append("Quiet hours are off: I will show alerts as soon as I raise them.")
    elif "quiet_start" in plan.context.get("asked", []) or "quiet_end" in plan.context.get("asked", []) or "quiet_tz" in plan.context.get("asked", []):
        tz = "India time (IST)" if q and q["timezone"] == "Asia/Kolkata" else (q["timezone"] if q else "")
        parts.append(f"Quiet hours are now {q['start']} to {q['end']} {tz}. Alerts raised in that window are held and shown when it ends, if the evidence is still recent then. Nothing is dropped.")
    if "price_threshold_pct" in plan.context.get("asked", []):
        parts.append(f"I will alert you when a competitor's price moves by {p['priceThresholdPct']}% or more between two of your confirmed screenshots.")
    return " ".join(parts) or "Saved."


def _c_decide(plan: Plan, results: Sequence[tuple[Step, Any]]) -> str:
    ok = sum(1 for _, leg in results if _failed(leg) is None and (getattr(leg, "payload", None) or {}).get("status") == "OK")
    reject = plan.context.get("decision") == "REJECT"
    all_positions = list(plan.context.get("positions", []))
    done = [n for n, (_, leg) in zip(all_positions, results) if _failed(leg) is None and (getattr(leg, "payload", None) or {}).get("status") == "OK"]
    positions = ", ".join(str(n) for n in done or all_positions)
    full = next(((getattr(leg, "payload", None) or {}) for _, leg in results if (getattr(leg, "payload", None) or {}).get("status") == "CAP_REACHED"), None)
    if not reject and full is not None:
        head = (f"Now tracking {positions}. " if done else "") + f"{len(all_positions) - len(done)} could not be added. "
        return head + _full_text(full.get("limit"), full.get("activeNames") or []) + " The leads you did not add stay in your list."
    if ok == 0:
        return "I could not record that decision, and nothing was changed."
    if reject:
        return f"Rejected {positions}. I will not show those again for this product unless you ask me to."
    return (f"Now tracking {positions}. Each has no price yet: a search lead is not a verified price. Send me a screenshot of each listing and say which competitor it is, "
            "and I will compare it with your product.")
