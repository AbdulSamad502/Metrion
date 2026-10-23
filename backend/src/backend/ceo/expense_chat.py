"""The CEO's side of the Expense Tracker conversation (docs/specs/ceo-expense-tracker-chat.md).

Pure helpers: what the seller said is turned into values BY CODE (an amount, a day, a category from a closed list, one of their own entries), never by a model. Nothing here
saves anything: a write is only ever prepared as an input session -> plan card, and runs when the seller presses Approve. The session fields that use these helpers live in
`input_session.py`; the registry handlers that perform an approved write are in `services/ceo_expense_ops.py`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from calc_engine.repositories import expense_tracker_repo as ledger

from backend.ceo import periods, slot_resolvers
from backend.ceo.figure_format import format_paise
from backend.services import expense_ledger_rules as rules

READ_KEY = "cfo.expense_summary"
ADD_KEY, CORRECT_KEY, VOID_KEY, PAID_KEY = "cfo.expense_add", "cfo.expense_correct", "cfo.expense_void", "cfo.expense_paid"
WRITE_KEYS = (ADD_KEY, CORRECT_KEY, VOID_KEY, PAID_KEY)
MENTION_FLAG = "EXPENSE_MENTION"
MAX_PICK = 3


@dataclass(frozen=True, slots=True)
class Bad:
    """A reading that failed: the reason is shown with the question again."""

    why: str


# ------------------------------------------------------------------------------------------------ category (a closed list, matched by words, never guessed)
_CATEGORY_WORDS: Mapping[str, tuple[str, ...]] = {
    "operating_overhead": ("rent", "electricity", "utility", "utilities", "power bill", "water bill", "internet", "wifi", "broadband", "office", "maintenance", "cleaning", "stationery", "telephone", "phone bill"),
    "software": ("software", "subscription", "saas", "app", "tool", "tools", "hosting", "domain", "license", "licence", "erp", "tally"),
    "personnel": ("salary", "salaries", "wages", "wage", "staff", "payroll", "labour", "labor", "bonus", "freelancer", "freelance", "contractor"),
    "advertising": ("ads", "ad ", "advertising", "advertisement", "campaign", "promotion", "promotions", "sponsored", "marketing", "boost", "facebook ads", "google ads"),
    "packaging": ("packaging", "packing", "boxes", "box", "bubble wrap", "tape", "poly bags", "cartons", "carton"),
    "inward_freight": ("inward freight", "freight", "transport", "transportation", "courier inward", "shipping to warehouse", "cartage"),
    "storage": ("storage", "warehouse", "warehousing", "godown", "fulfilment", "fulfillment", "fba"),
    "financial_charges": ("bank charges", "bank charge", "interest", "loan", "emi", "payment gateway", "razorpay", "processing fee", "finance charges", "forex"),
    "taxes": ("gst payment", "income tax", "advance tax", "tds", "tax", "taxes", "professional tax"),
}
_ID_BY_LABEL = {c.label.casefold(): k for k, c in rules.CATEGORIES.items()}


def infer_category(text: str) -> str | None:
    """The one category the words point at, or None when they point at none or at more than one (then the seller chooses)."""
    t = f" {' '.join((text or '').casefold().split())} "
    hits = {cid for cid, words in _CATEGORY_WORDS.items() if any((f" {w.strip()} " in t) or (w.endswith(" ") and w in t) for w in words)}
    return next(iter(hits)) if len(hits) == 1 else None


def parse_category(raw: str) -> str | Bad:
    t = " ".join((raw or "").casefold().split())
    if t in rules.CATEGORIES:
        return t
    if t in _ID_BY_LABEL:
        return _ID_BY_LABEL[t]
    for label, cid in _ID_BY_LABEL.items():  # "overhead", "storage", "freight": a word of the label
        if t and len(t) >= 4 and (t == label.split(" (")[0] or t in label):
            return cid
    found = infer_category(t)
    return found if found is not None else Bad("I could not tell which category that is. Pick one of the options, or type one of: " + ", ".join(c.label.split(" (")[0].lower() for c in rules.CATEGORIES.values()) + ".")


def category_label(cid: str) -> str:
    c = rules.CATEGORIES.get(cid)
    return c.label if c else cid


def category_choices(tenant: UUID, hint: str = "") -> list[tuple[str, str]]:
    """Up to three categories to offer: the one the words suggest, then the seller's most used ones, then common defaults. (id, label)."""
    out: list[str] = []
    guess = infer_category(hint)
    if guess:
        out.append(guess)
    try:
        rows, _ = ledger.list_records(tenant, date_from=None, date_to=None, category=None, cost_class=None, review_state=None, payment_status=None, channel_scope=None,
                                      include_voided=False, limit=rules.PAGE_SIZE_MAX, offset=0)
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["category"]] = counts.get(r["category"], 0) + 1
        out += [c for c, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    except Exception:  # noqa: BLE001 - offering is a convenience; the question is still asked
        pass
    out += ["operating_overhead", "advertising", "packaging"]
    seen: list[str] = []
    for c in out:
        if c in rules.CATEGORIES and c not in seen:
            seen.append(c)
    return [(c, category_label(c)) for c in seen[:MAX_PICK]]


# ------------------------------------------------------------------------------------------------ amount and day
def parse_amount(raw: str) -> int | Bad:
    paise = slot_resolvers.parse_amount_paise(raw)
    if paise is None:
        return Bad("I could not read that as an amount in rupees above zero. For example 5,000 or 1,299.50.")
    if paise > rules.AMOUNT_MAX_PAISE:
        return Bad("That amount is above the limit the Expense Tracker accepts.")
    return paise


def parse_day(raw: str, today: date) -> str | Bad:
    d = periods.single_day(raw, today=today)
    if d is None:
        return Bad("I could not read that as a day. For example today, yesterday, 5 October or 2026-10-05.")
    if d > today:
        return Bad("That day has not come yet. Expenses are recorded for today or an earlier day.")
    return d.isoformat()


# ------------------------------------------------------------------------------------------------ the seller's own entries
def _entry_label(r: Mapping[str, Any]) -> str:
    who = f" · {r['vendor']}" if r.get("vendor") else ""
    return f"{r['effective_date'].strftime('%d %b %Y')} · {category_label(r['category']).split(' (')[0]} · {format_paise(int(r['amount_paise']))}{who}"


def _match_score(r: Mapping[str, Any], hint: str) -> int:
    h = f" {' '.join(hint.casefold().split())} "
    if not h.strip():
        return 0
    score = 0
    for text in (category_label(r["category"]), str(r.get("vendor") or ""), str(r.get("description") or "")):
        for w in re.findall(r"[a-z0-9]{3,}", text.casefold()):
            if f" {w} " in h:
                score += 2
    if r["effective_date"].isoformat() in h or r["effective_date"].strftime("%d %b").casefold().lstrip("0") in h.replace("th ", " "):
        score += 3
    digits = re.findall(r"\d[\d,]*", hint)
    if any(d.replace(",", "") == str(int(r["amount_paise"]) // 100) for d in digits):
        score += 3
    return score


def recent_entries(tenant: UUID, hint: str = "", limit: int = MAX_PICK) -> list[dict[str, Any]]:
    """The seller's live (not voided) entries ranked by how well they match what was said, newest first among equals."""
    rows, _ = ledger.list_records(tenant, date_from=None, date_to=None, category=None, cost_class=None, review_state=None, payment_status=None, channel_scope=None,
                                  include_voided=False, limit=rules.PAGE_SIZE_MAX, offset=0)
    rows = [r for r in rows if r["review_state"] != "voided"]
    ranked = sorted(rows, key=lambda r: (-_match_score(r, hint), -r["effective_date"].toordinal(), str(r["id"])))
    if hint.strip():
        best = _match_score(ranked[0], hint) if ranked else 0
        if best > 0:
            ranked = [r for r in ranked if _match_score(r, hint) > 0]
    return ranked[:limit]


def snapshot(r: Mapping[str, Any]) -> dict[str, Any]:
    """What a correction needs to know about the original, kept in the session (the seller's own stored values, JSON-safe)."""
    return {"id": str(r["id"]), "label": _entry_label(r), "effective_date": r["effective_date"].isoformat(), "category": r["category"], "amount_paise": int(r["amount_paise"]),
            "vendor": r.get("vendor"), "description": r.get("description")}


def pick_options(tenant: UUID, hint: str) -> list[tuple[str, str, str]]:
    """(label, text, reason) for the entries to offer: the text is the entry's id, exactly what would be parsed if it were typed."""
    return [(_entry_label(r), str(r["id"]), "One of your entries") for r in recent_entries(tenant, hint)]


def parse_pick(raw: str, tenant: UUID, hint: str = "") -> dict[str, Any] | Bad:
    t = " ".join(raw.split())
    try:
        row = ledger.get_record(tenant, UUID(t))
    except (ValueError, AttributeError):
        row = None
    if row is not None:
        if row["review_state"] == "voided":
            return Bad("That entry has already been removed.")
        return snapshot(row)
    found = recent_entries(tenant, f"{t} {hint}".strip(), limit=10)
    best = [r for r in found if _match_score(r, f"{t} {hint}") > 0]
    if len(best) == 1:
        return snapshot(best[0])
    if not best:
        return Bad("I could not find an entry that matches that. Pick one of your recent entries, or describe it (for example the category, the day or the amount).")
    top = _match_score(best[0], f"{t} {hint}")
    tied = [r for r in best if _match_score(r, f"{t} {hint}") == top]
    if len(tied) == 1:
        return snapshot(tied[0])
    return Bad("That matches more than one entry. Pick one of the options, or add the day or the amount.")


# ------------------------------------------------------------------------------------------------ what the plan card says
def plan_extras(key: str, slots: Mapping[str, Any], tenant: UUID) -> tuple[list[str], list[str], str]:
    """(details, compact lines, title) for the approval card, written by code from the frozen slots. The seller reads exactly what will be saved."""
    def money(v: Any) -> str:
        return format_paise(int(v))

    if key == ADD_KEY:
        parts = [f"Amount: {money(slots['amount_paise'])}", f"Category: {category_label(str(slots['category']))}", f"Date: {slots['effective_date']}"]
        if slots.get("vendor"):
            parts.append(f"Paid to: {slots['vendor']}")
        if slots.get("description"):
            parts.append(f"Note: {slots['description']}")
        return (["It adds this expense to your Expense Tracker as confirmed."], ["Add an expense to your Expense Tracker:", *parts, "Saved only when you press Approve."], "Add an expense to your Expense Tracker")
    if key == CORRECT_KEY:
        row = _row(tenant, slots.get("expense_id"))
        was = _entry_label(row) if row is not None else "the entry you picked"
        parts = [f"Now: {money(slots['amount_paise'])} · {category_label(str(slots['category']))} · {slots['effective_date']}"]
        if slots.get("vendor"):
            parts.append(f"Paid to: {slots['vendor']}")
        return (["The original stays in the history as removed and is replaced by the corrected entry."], [f"Change an expense: {was}", *parts, "Saved only when you press Approve."], "Change an expense in your Expense Tracker")
    if key == VOID_KEY:
        row = _row(tenant, slots.get("expense_id"))
        was = _entry_label(row) if row is not None else "the entry you picked"
        return (["The entry is voided, not deleted: it stays in the history with your reason."], [f"Remove this expense: {was}", f"Reason: {slots.get('reason')}", "Saved only when you press Approve."],
                "Remove an expense from your Expense Tracker")
    row = _row(tenant, slots.get("expense_id"))
    was = _entry_label(row) if row is not None else "the entry you picked"
    status = str(slots.get("status", "")).replace("_", " ")
    extra = f" ({money(slots['paid_amount_paise'])} paid)" if slots.get("paid_amount_paise") is not None else ""
    return (["Payment status is display only; it does not change any profit figure."], [f"Mark as {status}{extra}: {was}", "Saved only when you press Approve."], "Update an expense's payment status")


def _row(tenant: UUID, expense_id: Any) -> dict[str, Any] | None:
    try:
        return ledger.get_record(tenant, UUID(str(expense_id)))
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------------------------------------ evidence for the answer
def heading_for(key: str) -> str:
    return {ADD_KEY: "Done. Here is what was saved to your Expense Tracker.", CORRECT_KEY: "Done. Here is the corrected entry in your Expense Tracker.",
            VOID_KEY: "Done. This expense was removed from your totals; it stays in the history.", PAID_KEY: "Done. The payment status was updated."}[key]


# ------------------------------------------------------------------------------------------------ recognising what the seller said (all by rule; every value still passes the parsers above)
_AMOUNT_TOKEN = r"(?:(?:₹|rs\.?|inr)\s*\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s*(?:rupees?|rs\.?|inr)\b)"
_AMOUNT_RX = re.compile(_AMOUNT_TOKEN, re.IGNORECASE)
_BARE_AMOUNT_AFTER = re.compile(r"\b(?:of|for|worth|amount(?: of)?|total(?: of)?|rs\.?|₹)\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_PAID_STATEMENT = re.compile(r"\b(?:i|we)(?:'ve| have)?\s+(?:just\s+|already\s+|recently\s+)?(?:paid|spent|bought|purchased|booked|recharged|renewed|ordered)\b", re.IGNORECASE)
_NOT_A_MENTION = re.compile(r"\?|\b(?:should i|if i|what if|would i|could i|can i|do i|did i|how much (?:should|would|can)|is it worth|planning to|going to|want to|thinking of|will pay|will spend)\b|\b(?:sold|received|refund(?:ed)?|got paid|customer paid)\b",
                            re.IGNORECASE)
_DAY_PHRASE = re.compile(r"\b(today|yesterday|(?:on\s+)?\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:\s+\d{4})?|(?:on\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)
_FOR_PHRASE = re.compile(r"\bfor\s+(?:the\s+|my\s+|our\s+|a\s+|an\s+)?([a-z][a-z0-9 &/'\-]{2,60}?)(?=\s+(?:on|today|yesterday|at|from|of|in)\b|\s*[.,;!]|$)", re.IGNORECASE)


def amount_text(text: str) -> str | None:
    m = _AMOUNT_RX.search(text)
    if m:
        return m.group(0).strip()
    m = _BARE_AMOUNT_AFTER.search(text)
    return m.group(1) if m else None


def day_text(text: str) -> str | None:
    m = _DAY_PHRASE.search(text)
    return m.group(1).strip() if m else None


def note_text(text: str) -> str | None:
    m = _FOR_PHRASE.search(text)
    return " ".join(m.group(1).split()) if m else None


def slots_for_add(text: str) -> dict[str, str]:
    """Only what the seller said, as text for the session's own parsers (which may still refuse it). Nothing is inferred beyond a keyword category."""
    out: dict[str, str] = {}
    if (a := amount_text(text)):
        out["amount"] = a
    if (d := day_text(text)):
        out["period"] = d
    note = note_text(text)
    if note:
        out["note"] = note
    cat = infer_category(text)
    if cat:
        out["category"] = cat
    return out


def is_mention(text: str) -> bool:
    """A first-person statement that money was paid, with an amount: worth ASKING about. Never a question, a plan or a hypothetical; never an action."""
    t = " ".join(text.split())
    return bool(_PAID_STATEMENT.search(t)) and not _NOT_A_MENTION.search(t) and amount_text(t) is not None


def mention_summary(collected: Mapping[str, Any]) -> str:
    bits = []
    if collected.get("expense_amount"):
        bits.append(format_paise(int(collected["expense_amount"])))
    if collected.get("expense_category"):
        bits.append(category_label(str(collected["expense_category"])).split(" (")[0].lower())
    if collected.get("expense_date"):
        bits.append(str(collected["expense_date"]))
    return ", ".join(bits)


_PERIOD_CANDIDATES = (
    re.compile(r"\b(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+(?:\s+\d{4})?\s+(?:to|till|until|-)\s+\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+(?:\s+\d{4})?)\b", re.IGNORECASE),
    re.compile(r"\b(\d{4}-\d{2}-\d{2}\s*(?:to|-|–)\s*\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b((?:the\s+)?(?:last|past|previous)\s+\d{1,3}\s+days)\b", re.IGNORECASE),
    re.compile(r"\b(last month|previous month|this month|today|yesterday)\b", re.IGNORECASE),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b((?:on\s+)?\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:\s+\d{4})?)\b", re.IGNORECASE),
    re.compile(r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)\b", re.IGNORECASE),
    re.compile(r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*(?:\s+\d{4})?)\b", re.IGNORECASE),
    re.compile(r"\b(\d{4}-\d{2})\b"),
)


def period_text(text: str) -> str | None:
    """The period words in a question, for `resolve_period` to read exactly (or to ask about); the first form that appears, longest forms first."""
    for rx in _PERIOD_CANDIDATES:
        m = rx.search(text)
        if m:
            return " ".join(m.group(1).split())
    return None


def read_slots(text: str) -> dict[str, str]:
    out = {"question": " ".join(text.split())[:300]}
    if (p := period_text(text)):
        out["period"] = p
    return out


def entry_hint(text: str) -> dict[str, str]:
    """What the seller said about WHICH entry (for ranking the options); the entry itself is always picked, never typed."""
    return {"note": " ".join(text.split())[:200]}


def hidden_for(key: str | None, slots: Mapping[str, str], flags: Any) -> dict[str, Any] | None:
    """Session state the seller did not type: that this started from a MENTION (the first question asks whether it is an expense at all), and what they said about which entry."""
    if key not in (ADD_KEY, CORRECT_KEY, VOID_KEY, PAID_KEY):
        return None
    out: dict[str, Any] = {}
    if MENTION_FLAG in (flags or ()):
        out["_mention"] = True
    if slots.get("note"):
        out["_hint"] = str(slots["note"])[:200]
    return out or None


# ------------------------------------------------------------------------------------------------ evidence
def summary_refs(payload: Mapping[str, Any]) -> list[Any]:
    """The engine results of a tracker summary the answer needs: per bucket the total, each category and - only when something waits - the review-queue amount.
    Everything else in the summary stays on the Expense Tracker page. (A custom extractor: the default would carry every cost-class figure of every month.)"""
    from backend.ceo.contract import Ref, RefKind  # noqa: PLC0415
    from backend.ceo.provenance import _as_uuid  # noqa: PLC0415

    out: list[Ref] = []
    seen: set[UUID] = set()

    def add(raw: Any) -> None:
        ident = _as_uuid(raw)
        if ident is not None and ident not in seen:
            seen.add(ident)
            out.append(Ref(kind=RefKind.ENGINE_RESULT, id=ident))

    for b in payload.get("buckets") or []:
        s = b.get("summary") or {}
        add((s.get("expenseTotal") or {}).get("engineResultRef"))
        for c in s.get("byCategory") or []:
            add(c.get("engineResultRef"))
        rq = s.get("reviewQueue") or {}
        if rq.get("items"):
            add(rq.get("engineResultRef"))
    return out


def entry_figure(e: Mapping[str, Any], prefix: str = "") -> Any:
    """One tracker entry as a figure: the amount is shown only through a reference to the very record (Register MANUAL: entered by the seller)."""
    from backend.ceo.contract import Figure, Ref, RefKind, Register  # noqa: PLC0415

    who = f" ({e['vendor']})" if e.get("vendor") else ""
    label = f"{prefix}{str(e.get('categoryLabel') or e.get('category')).split(' (')[0]} on {e['effectiveDate']}{who}"
    return Figure(label, format_paise(int(e["amountPaise"])), Register.MANUAL, Ref(RefKind.AGENT_REPORT_FIELD, UUID(str(e["id"])), source="expense_event"))
