"""Buyer questions and listing readiness for the CEO chat (CMO 3.0 M5; docs/specs/slim-cmo-agent.md section 6.17, ceo-cmo-delegation.md section 6.15).

`build_card` assembles ONE `READINESS` card for one product from what already exists and reuses it: the seller's confirmed facts (M1 profile), keyword research (M2), the M3 title analyses
(shared with the M4 preview: the same saved analysis), the title the seller chose (M0), saved listing copy, and the seller's own photo. Both views (buyer questions, readiness per marketplace)
ride in the card, so switching marketplace or view in the browser makes no request.

* Free: no entitlement check, no reservation, no metered event, no model, no network. A run record is written only for a NEW saved result.
* Tenant-scoped everywhere. Nothing is sent to a marketplace; nothing is published; no product claim, buyer demand or marketplace compliance is ever invented: what cannot be assessed is NOT_ASSESSED.
* The seller can answer a question in the chat ("For my AquaNest bottle, dishwasher safe is: yes, I tested it"); `save_fact` records that statement as their own (append-only, zero units).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from slim_cmo.buyer.questions import MAX_VALUE_CHARS, METHOD as Q_METHOD, analyse as analyse_questions, is_unknown_value, topic_for_label
from slim_cmo.forbidden import scan_forbidden
from slim_cmo.readiness.checklist import METHOD as R_METHOD, MarketplaceInputs, ProductInputs, assess_all
from slim_cmo.service.models import Actor, NewFact
from slim_cmo.service.readiness import keyword_analysis, save_result
from slim_cmo.service.title_analysis import TitleAnalysisService
from slim_cmo.types import SellerFactType

from backend.repositories import cmo_chat_repo
from backend.services import cmo_actions, cmo_ci_inputs, cmo_runtime

logger = logging.getLogger(__name__)
MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
NOTICE = ("This is an internal assessment of what is done and what is missing for your own listing. It is not a marketplace approval, ranking, conversion or sales prediction, "
          "and a requirement that could not be assessed is never counted as passed.")


def _digest(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _ci(ctx: Any) -> Any:
    try:
        ids, _note = cmo_ci_inputs.broker(ctx.tenant_id, ctx.role, ctx.permissions, now=datetime.now(timezone.utc))
        return cmo_ci_inputs.load_inputs(ctx, [UUID(i) for i in ids]) if ids else None
    except Exception:  # noqa: BLE001 - competitor evidence is optional; the analysis then runs on the seller's facts alone
        logger.info("competitor evidence not used for buyer questions")
        return None


def build_card(ctx: Any, investigation_id: UUID, sku: str, name: str, view: str) -> dict[str, Any]:
    from backend.ceo import cmo_profile  # noqa: PLC0415 - the pure profile read model (M1); lazy so the CEO package is never imported at load time

    tenant, user = ctx.tenant_id, ctx.app_user_id
    rt = cmo_runtime.build_runtime()
    actor, principal = Actor(tenant, user), cmo_actions.Principal(tenant, user)
    kinds = getattr(rt.generation, "accepted_row_kinds", None)
    svc = TitleAnalysisService(rt.store, clock=rt.clock, **({"accepted_row_kinds": kinds} if kinds else {}))

    profile = cmo_profile.profile_from_rows(cmo_chat_repo.profile_rows(tenant, sku))
    ci = _ci(ctx)
    kw, fctx = keyword_analysis(rt.store, tenant, sku, None, ci)
    stems = sorted({w.casefold() for t in (ci.themes() if ci else ()) for w in t.split()} | ({f for c in ci.feature_categories() for f in c.split()} if ci else set()))
    questions = analyse_questions(profile, name, stems, len(ci.insights) if ci else 0)

    sets = {s["marketplace"]: s for s in cmo_chat_repo.title_sets_for_sku(tenant, sku)}
    copy_packs = cmo_chat_repo.copy_pack_marketplaces(tenant, sku)
    has_photo = False
    try:
        has_photo = cmo_chat_repo.photo_attachment(tenant, investigation_id) is not None or cmo_chat_repo.has_photo_fact(tenant, sku)
    except Exception:  # noqa: BLE001 - presence only; a failed lookup is "no photo shown", never "a photo exists"
        logger.exception("could not look up the product photo")
    fact_key = _digest(sorted(fctx.fact_ids))
    markets: list[MarketplaceInputs] = []
    approvals: list[str] = []
    for mp in MARKETPLACES:
        analysis = None
        if mp in sets:
            gid = UUID(sets[mp]["generationId"])
            started, run_id = rt.clock(), uuid4()
            analysis = svc.run(actor, gid, f"preview-{gid}-{fact_key}")  # the very key the M4 preview uses: one saved analysis per title set and set of facts
            if not analysis["reused"]:
                cmo_actions.record_free_run(principal, rt, "cmo.title_analysis", run_id, started)
        approved = cmo_chat_repo.approved_titles(tenant, sku=sku, marketplace=mp, limit=1)
        approvals.extend(a["approvalId"] for a in approved)
        rule_verified = bool(analysis and any(((o.get("dimensions") or {}).get("marketplaceRules") or {}).get("ruleKind") == "VERIFIED" for o in analysis.get("options", [])))
        markets.append(MarketplaceInputs(mp, analysis, approved[0]["text"] if approved else None, mp in copy_packs, rule_verified))
    readiness = assess_all(ProductInputs(profile, questions, kw, has_photo), markets)

    q_started, q_run = rt.clock(), uuid4()
    qid, q_reused = save_result(actor, "questions", sku, Q_METHOD, questions, f"questions-{sku}-{_digest(fact_key, stems)}"[:128], q_run)
    r_started, r_run = rt.clock(), uuid4()
    rid, r_reused = save_result(actor, "readiness", sku, R_METHOD, readiness, f"readiness-{sku}-{_digest(fact_key, sorted(s['generationId'] for s in sets.values()), sorted(approvals), sorted(copy_packs), has_photo, stems)}"[:128], r_run)
    if not q_reused:
        cmo_actions.record_free_run(principal, rt, "cmo.buyer_questions", q_run, q_started)
    if not r_reused:
        cmo_actions.record_free_run(principal, rt, "cmo.listing_readiness", r_run, r_started)
    first = next((mp for mp in MARKETPLACES if mp in sets), "AMAZON")
    return {"version": 1, "kind": "READINESS", "view": view, "notice": NOTICE, "investigationId": str(investigation_id), "product": {"name": name, "sku": sku},
            "questionsId": qid, "readinessId": rid, "questions": questions, "readiness": readiness, "defaultMarketplace": first,
            "answerHint": f"For my {name}, {{topic}} is: your answer"}


# ------------------------------------------------------------------------------------------------ what the seller asks
_Q = (r"\bwhat (?:questions|things) (?:will|would|might|may|do|are) (?:buyers|customers|shoppers|people)\b[^.?!]{0,20}\bask\b|\b(?:buyer|customer|shopper) questions\b|"
      r"\bquestions (?:that )?(?:buyers|customers|shoppers)\b[^.?!]{0,20}\bask\b|\bwhat (?:will|would|might) (?:buyers|customers) want to know\b")
_R = (r"\b(?:is|are) (?:my|our|the) [\w][\w \-']{0,60}? (?:ready|good) to (?:list|sell|publish|launch|go live)\b|\bready to (?:list|sell|publish|launch)\b|\blisting readiness\b|\breadiness (?:check|checklist|score|report)\b|"
      r"\bwhat(?:'s| is) missing (?:from|in|before)\b[^.?!]{0,30}\blist(?:ing|ed)?\b|\bcan i (?:list|sell) (?:my|this|the)\b")
_HINT = re.compile(r"\b(?:my|our|the)\s+(?P<p>[\w][\w \-']{1,60}?)(?=\s+(?:ready|good|before|from|on|for)\b|[?.!,]|$)", re.IGNORECASE)
_STATEMENT = re.compile(r"^\s*for (?:my|our|the)\s+(?P<p>.+?),\s*(?P<t>[A-Za-z][A-Za-z ]{1,38}?)\s+is:\s*(?P<v>.+?)\s*$", re.IGNORECASE | re.DOTALL)
_NOT_PRODUCT = frozenset({"questions", "listing", "listings", "business", "profit", "titles", "title", "catalog", "store", "shop", "account", "readiness", "checklist", "score", "report", "check", "buyer", "customer", "ready", "listing"})


def request_kind(text: str) -> str | None:
    """"questions" or "readiness" when the message asks for one of them, else None. A request to WRITE something is never one of them."""
    t = " ".join(text.split())
    if re.search(r"\b(?:write|generate|create|make|draft)\b", t, re.IGNORECASE):
        return None
    if re.search(_Q, t, re.IGNORECASE):
        return "questions"
    if re.search(_R, t, re.IGNORECASE):
        return "readiness"
    return None


def product_hint(text: str) -> str | None:
    m = _HINT.search(" ".join(text.split()))
    if not m:
        return None
    hint = m.group("p").strip()
    return None if set(re.findall(r"[a-z]+", hint.casefold())) <= _NOT_PRODUCT else hint


def parse_statement(text: str) -> tuple[str, str, str] | None:
    """(product words, the question topic's label, the seller's value) for "For my AquaNest bottle, dishwasher safe is: yes, tested", else None. The topic must be one of the known questions."""
    m = _STATEMENT.match(text)
    if not m:
        return None
    topic = topic_for_label(m.group("t"))
    return (m.group("p").strip(), topic.label, m.group("v").strip()) if topic else None


def save_fact(tenant: UUID, user: UUID, sku: str, label: str, value: str) -> None:
    """Records the seller's own statement as a new fact (append-only, zero units, one run record). Raises ValueError with a plain reason when the value cannot be used."""
    v = " ".join(value.split())
    if not v:
        raise ValueError("I need your answer after the colon.")
    if len(v) > MAX_VALUE_CHARS:
        raise ValueError(f"Please keep it to {MAX_VALUE_CHARS} characters.")
    if scan_forbidden(v):
        raise ValueError("That contains wording I cannot put in a listing (a price, tax, ranking or similar claim), so I did not save it. Please state only the product detail.")
    rt = cmo_runtime.build_runtime()
    started, run_id = rt.clock(), uuid4()
    rt.store.save_facts(tenant, user, [NewFact(SellerFactType.ATTRIBUTE, sku, label, v)])
    cmo_actions.record_free_run(cmo_actions.Principal(tenant, user), rt, "cmo.confirm_fact", run_id, started)


def saved_text(label: str, value: str) -> str:
    if is_unknown_value(value):
        return (f"Noted: you told me “{label}: {value}”. That counts as not confirmed, so I will not claim it in your listing. "
                "It is saved as your own statement and is not checked by Metrion.")
    return (f"Saved: {label}: {value}. It is your own statement (Metrion has not checked it) and I will use it in your listing exactly as you said it. "
            "Ask “What questions will buyers ask?” to see the updated answers.")


def chat_text(card: dict[str, Any]) -> str:
    q = card["questions"]
    c = q["counts"]
    r = {m["marketplace"]: m for m in card["readiness"]["marketplaces"]}[card["defaultMarketplace"]]
    sc = r["score"]
    score = f"readiness {sc['score']}/100 on {sc['assessablePoints']} of 100 assessable points" if sc["status"] == "ASSESSED" else "no readiness score yet (not enough evidence)"
    lead = ("Here are the questions buyers commonly ask about this kind of product, and what I can answer from what you confirmed. " if card["view"] == "questions"
            else "Here is your listing readiness checklist. ")
    return (f"{lead}{c['CONFIRMED']} of {len(q['questions'])} questions are answered from your own facts, {c['NOT_CONFIRMED']} are NOT CONFIRMED and {c['SELLER_UNKNOWN']} you told me you do not know. "
            f"For {card['defaultMarketplace'].title()}: {score}. {r['verdictText']} Use the card to see each question, each requirement and what to do next. Nothing is used up and nothing is published.")
