"""The complete, audited listing (CMO 3.0 M6; docs/specs/slim-cmo-agent.md section 6.18, ceo-cmo-delegation.md section 6.16).

What this module IS: the backend orchestration around pieces that already exist. It reuses, never re-implements: the copy-pack / backend-terms / hashtag generation and its per-artefact billing (`cmo_actions.run_billable`, one call per
artefact with a request key derived from the plan's key, so reservation, metering and idempotency are exactly the proven path), the M2 keyword research, the M3 hard-failure rules, the M5 buyer questions, the CEO-brokered competitor
inputs, and the pure M6 rules in `slim_cmo.listing` (audit, keyword map, revision, preconditions). The audit, the keyword map, the seller's own edit and "approved for use" are free (no unit, no model).

What it is NOT: it publishes nothing and has no marketplace write path. Generated, audited, approved for use, copied and marked used are separate recorded facts; "published" or "live" is never known and never stored.
The rules-unavailable basis is entered only by the SERVER: the full-listing workflow marker comes from `full_listing_workflow()` (set by the CEO for its own plan) or from `run_full_listing` itself, never from a request body.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

from slim_cmo import billing
from slim_cmo.buyer.questions import analyse as analyse_questions
from slim_cmo.ci_inputs import CiInputs, CiInsight
from slim_cmo.claims import Attribute
from slim_cmo.constraints import FormatConstraint
from slim_cmo.generation.facts import build_fact_context
from slim_cmo.listing import audit as audit_rules
from slim_cmo.listing import basis as rules_basis
from slim_cmo.listing import ci_evidence, edit as edit_rules, keyword_map, preconditions, revise, title_currency
from slim_cmo.listing.context import ListingContext
from slim_cmo.listing.text import words
from slim_cmo.service.errors import NotFound
from slim_cmo.service.generate import GroundingRequest, Intake
from slim_cmo.service.listing_audit import ListingAuditStore
from slim_cmo.service.models import Actor, DuplicateArtefact, GenerationRecord
from slim_cmo.service.rewrite import ListingRewriteService, RewriteRequest
from slim_cmo.service.readiness import keyword_analysis
from slim_cmo.titles_analysis.analyzer import AnalysisInputs, RuleContext, TitleOption, analyse_titles
from slim_cmo.types import GenerationStatus, GroundingBasis, Marketplace, OutputType

from backend.repositories import cmo_chat_repo
from backend.services import cmo_actions, cmo_runtime

logger = logging.getLogger(__name__)

WORKFLOW: contextvars.ContextVar[str | None] = contextvars.ContextVar("cmo_listing_workflow", default=None)
APPROVED_TEXT = "Approved for use in Metrion; not published."
NOTICE = ("Generated, audited, approved for use, copied and marked used are separate steps. None of them means the listing is published, live, accepted or verified by any marketplace; "
          "Metrion cannot see or change what is on a marketplace.")


class ListingRefused(Exception):
    """A full-listing request that cannot proceed, in the seller's words. `code` is machine-readable; nothing is charged and nothing is saved."""

    def __init__(self, code: str, detail: str, *, missing: Sequence[str] = (), status: int = 422) -> None:
        super().__init__(detail)
        self.code, self.detail, self.missing, self.status = code, detail, tuple(missing), status


# ------------------------------------------------------------------------------------------------ the server-side workflow marker
@contextmanager
def full_listing_workflow() -> Iterator[None]:
    """Set ONLY by the CEO for a step of its own full-listing plan (a title step run inside the request). Never read from a request body."""
    token = WORKFLOW.set(rules_basis.FULL_LISTING)
    try:
        yield
    finally:
        WORKFLOW.reset(token)


def workflow_context() -> ListingContext | None:
    return ListingContext(workflow=rules_basis.FULL_LISTING) if WORKFLOW.get() == rules_basis.FULL_LISTING else None


# ------------------------------------------------------------------------------------------------ gathering what the audit needs
def _stems(ci: CiInputs | None) -> list[str]:
    return sorted({w.casefold() for t in (ci.themes() if ci else ()) for w in t.split()} | ({f for c in ci.feature_categories() for f in c.split()} if ci else set()))


def _snapshot_ci(snapshot: Mapping[str, Any] | None) -> CiInputs | None:
    """The competitor inputs as they were stored with the pack (derived words and ids only; the competitors' own text was never stored)."""
    if not isinstance(snapshot, Mapping) or not snapshot.get("insights"):
        return None
    ins = tuple(CiInsight(str(i["id"]), tuple(i.get("keyword_themes") or ()), tuple(i.get("feature_categories") or ()), tuple(i.get("benefit_terms") or ()),
                          tuple(i.get("differentiation_opportunities") or ())) for i in snapshot["insights"])
    return CiInputs(insights=ins)


def _questions(tenant: UUID, sku: str, name: str | None, ci: CiInputs | None) -> dict[str, Any]:
    from backend.ceo import cmo_profile  # noqa: PLC0415 - the M1 read model; lazy so the CEO package is not imported at load time

    profile = cmo_profile.profile_from_rows(cmo_chat_repo.profile_rows(tenant, sku))
    return analyse_questions(profile, name, _stems(ci), len(ci.insights) if ci else 0)


def _title_analysis(text: str, ctx: Any, kw: Mapping[str, Any], name: str | None, brand: str | None, mp: Marketplace) -> dict[str, Any]:
    """The M3 analyzer run on ONE title: the same hard failures and the same descriptive strategy as for a title set, without inventing a marketplace rule."""
    res = analyse_titles(AnalysisInputs(options=[TitleOption("approved", 1, text)], facts=ctx, product_name=name, brand=brand, keyword_result=kw,
                                        rule=RuleContext(reason="no verified marketplace rule is used for this check"), marketplace=mp))
    return (res.get("options") or [{}])[0]


def _constraint_row(rt: Any, tenant: UUID, mp: Marketplace, ref: str | None) -> FormatConstraint | None:
    if not ref:
        return None
    kinds = getattr(rt.generation, "accepted_row_kinds", None)
    rows = rt.store.load_constraints(tenant, mp, kinds) if kinds else rt.store.load_constraints(tenant, mp, frozenset())
    return next((r for r in rows if str(r.id) == str(ref)), None)


def _approved_text(tenant: UUID, approval_id: UUID | None, structured: Mapping[str, Any]) -> str | None:
    if approval_id is not None:
        return cmo_chat_repo.approval_text(tenant, approval_id)
    prov = structured.get("provenance")
    t = prov.get("grounding_title") if isinstance(prov, Mapping) else None
    return str(t) if t else None


def title_status(tenant: UUID, pack: Mapping[str, Any]) -> dict[str, Any]:
    """N-15d: was this saved version written from the title the seller has approved NOW for this product and marketplace? Read-only and computed on demand, so nothing is stored, edited,
    relabelled or regenerated and every historical version is judged by the same rule. A title change that was never approved changes nothing."""
    sku, mp = pack["sku"], pack["marketplace"]
    built_from = _approved_text(tenant, pack["approvalId"], pack["structured"])
    built = cmo_chat_repo.approval_ref(tenant, pack["approvalId"]) if pack["approvalId"] is not None else None
    cur = cmo_chat_repo.current_approval(tenant, sku, mp) if sku else None
    ref = lambda r: title_currency.ApprovalRef(r["id"], r["text"], r["approvedAt"]) if r else None  # noqa: E731
    return title_currency.assess(built_from=built_from, built_approval=ref(built), current=ref(cur), marketplace=mp, product=cmo_chat_repo.product_label(tenant, sku) if sku else None)


def earlier_title_notice(tenant: UUID, title_set_id: UUID) -> list[dict[str, Any]]:
    """After the seller approves a title: the seller's newest complete listing for that product and marketplace, when it was built from a previous title (else nothing). Best-effort: a
    failed lookup adds nothing and never blocks the approval."""
    try:
        found = cmo_chat_repo.title_set_product(tenant, title_set_id)
        if found is None:
            return []
        gid = cmo_chat_repo.latest_listing_pack(tenant, sku=found[0], marketplace=found[1])
        pack = cmo_chat_repo.listing_pack(tenant, gid) if gid else None
        status = title_status(tenant, pack) if pack else None
    except Exception:  # noqa: BLE001
        logger.exception("could not check the saved listing against the newly approved title")
        return []
    if not status or status["state"] != title_currency.OUTDATED:
        return []
    return [{"generationId": str(gid), "marketplace": status["marketplace"], "product": status["product"], "explanation": status["explanation"], "nextStep": status["nextStep"]}]


def _gaps(attrs: Sequence[Attribute]) -> list[str]:
    out = preconditions.missing_facts(attrs)
    if not any(a.name.casefold() == "category" and a.value for a in attrs):
        out.append("Category")
    return out


def audit_pack(tenant: UUID, user: UUID, rt: Any, copy_id: UUID, *, ci: CiInputs | None = None, agent_run_id: UUID | None = None, backend_terms: Sequence[str] | None = None,
               sections: revise.Sections | None = None) -> dict[str, Any]:
    """Audit one saved pack (and its backend terms), save the audit once per version, and return it with the keyword map and the competitor evidence rows. Free: no model, no unit.
    `sections` lets a revision be audited as the text it WILL be before it is saved."""
    pack = cmo_chat_repo.listing_pack(tenant, copy_id)
    if pack is None:
        raise NotFound("listing not found")
    s: Mapping[str, Any] = pack["structured"]
    mp = Marketplace(pack["marketplace"])
    sku = pack["sku"]
    if not sku:
        raise ListingRefused("NO_PRODUCT", "This listing has no saved product, so it cannot be audited.")
    approved = _approved_text(tenant, pack["approvalId"], s)
    if not approved:
        raise ListingRefused("NO_TITLE", "I cannot find the title this listing was written for.")
    terms: Sequence[str] | None = None
    if mp is Marketplace.AMAZON:  # backend terms exist only for Amazon; an Amazon listing whose terms step has not (yet) produced any is audited with none, never as "not applicable"
        saved = s.get("backend_terms_saved")  # a revised version carries its own terms; an original pack's terms are the sibling artefact written under the derived request key
        terms = backend_terms if backend_terms is not None else (list(saved) if isinstance(saved, list) else cmo_chat_repo.backend_terms_for(tenant, pack["requestKey"]) or [])
    secs = sections or revise.sections_from(s, title=approved, backend_terms=terms)
    kw, ctx = keyword_analysis(rt.store, tenant, sku, mp, ci)
    by = {a.name.casefold(): a.value for a in ctx.eligible if a.value}
    name, brand = by.get("product_name"), by.get("brand")
    attrs = tuple(a for a in [*ctx.eligible, *(x for x, _ in ctx.ineligible)] if a.name.casefold() != "product_name")
    questions = _questions(tenant, sku, name, ci)
    snap_ci = _snapshot_ci(pack["ciSnapshot"])
    rows = ci_evidence.evidence_rows(ci or snap_ci, attrs)
    basis = str(s.get("rules_basis") or rules_basis.VERIFIED)
    row = _constraint_row(rt, tenant, mp, pack["constraintRef"]) if basis == rules_basis.VERIFIED else None
    hard = list((_title_analysis(approved, ctx, kw, name, brand, mp).get("hardFailures")) or [])
    inputs = audit_rules.AuditInputs(
        marketplace=mp.value, rules_basis=basis, constraint=row, approved_title=approved, title=secs.title, bullets=secs.bullets, description=secs.description, keywords=secs.keywords,
        backend_terms=secs.backend_terms, attributes=attrs, candidates=tuple(kw.get("candidates") or ()), excluded=tuple(kw.get("excluded") or ()), questions=questions,
        ci_rows=tuple(rows), ci=ci, title_hard_failures=tuple(str(h) for h in hard), gaps=tuple(_gaps(attrs)),
    )
    result = audit_rules.run(inputs)
    kmap = keyword_map.build(inputs.candidates, title=secs.title, bullets=secs.bullets, description=secs.description, keywords=secs.keywords, backend_terms=secs.backend_terms, excluded=inputs.excluded)
    return {"result": result, "keywordMap": kmap, "ciRows": rows, "sections": secs, "basis": basis, "mp": mp, "strategy": (_title_analysis(approved, ctx, kw, name, brand, mp).get("strategy")),
            "base": inputs, "pack": pack}


def save_audit(tenant: UUID, user: UUID, copy_id: UUID, built: Mapping[str, Any], agent_run_id: UUID | None = None) -> dict[str, Any]:
    secs: revise.Sections = built["sections"]
    saved = ListingAuditStore().save(
        Actor(tenant, user), generation_id=copy_id, marketplace=built["mp"].value, content_hash=secs.hash(built["mp"].value), rules_basis=built["basis"], result=built["result"],
        keyword_map=built["keywordMap"], agent_run_id=agent_run_id,
    )
    return saved


# ------------------------------------------------------------------------------------------------ the card
def build_card(tenant: UUID, user: UUID, rt: Any, copy_id: UUID, *, investigation_id: UUID | None = None, ci: CiInputs | None = None) -> dict[str, Any]:
    """Audit (saved once per version) and assemble ONE `LISTING` card for a saved pack. The card is data only: text, statuses, findings; no image, no demand, ranking or sales figure."""
    built = audit_pack(tenant, user, rt, copy_id, ci=ci)
    started, run_id = rt.clock(), uuid4()
    saved = save_audit(tenant, user, copy_id, built, run_id)
    if not saved["reused"]:
        cmo_actions.record_free_run(cmo_actions.Principal(tenant, user), rt, "cmo.listing_audit", run_id, started)
    secs: revise.Sections = built["sections"]
    states = cmo_chat_repo.listing_states(tenant, copy_id)
    res = built["result"]
    basis = built["basis"]
    mp: Marketplace = built["mp"]
    banner = rules_basis.BANNER.format(marketplace=mp.value.title()) if basis == rules_basis.UNVERIFIED else None
    return {
        "version": 1, "kind": "LISTING", "notice": NOTICE, "investigationId": str(investigation_id) if investigation_id else None, "generationId": str(copy_id),
        "marketplace": mp.value, "rulesBasis": basis, "banner": banner,
        "strategy": (built["strategy"] if built["pack"]["approvalId"] is not None else None) or "NOT_ASSESSED",  # N-05t: a title the seller typed has no M3 strategy; none is invented for it
        "sections": secs.as_dict(), "revisionOf": built["pack"]["revisionOf"], "keywordMap": built["keywordMap"],
        "audit": {"auditId": saved["auditId"], "contentHash": saved["contentHash"], "verdict": res["verdict"], "counts": res["counts"], "checks": res["checks"], "findings": res["findings"],
                  "measured": res["measured"], "limits": res["limits"], "method": res["method"], "createdAt": saved["createdAt"]},
        "ci": {"rows": built["ciRows"], "considerIfTrue": ci_evidence.consider_if_true(built["ciRows"]), "used": bool(built["pack"]["ciSnapshot"])},
        "titleStatus": title_status(tenant, built["pack"]), "states": states, "editHint": "Change bullet 3 to: your own text", "approveHint": APPROVED_TEXT,
    }


# ------------------------------------------------------------------------------------------------ approved for use (free, a click, never typed)
def approve_for_use(tenant: UUID, user: UUID, rt: Any, copy_id: UUID) -> dict[str, Any]:
    """Records that the seller approved THIS saved version for use in Metrion. 0 units, no metered event, no reservation. Refused when the audit of this exact version is BLOCKED.
    It does not publish anything and does not mean a marketplace accepted it."""
    built = audit_pack(tenant, user, rt, copy_id)
    saved = save_audit(tenant, user, copy_id, built)
    if saved["verdict"] == audit_rules.BLOCKED:
        raise ListingRefused("AUDIT_BLOCKED", "This version has problems that must be fixed first, so it cannot be approved for use. See the findings on the card.", status=409)
    started, run_id = rt.clock(), uuid4()
    new = cmo_chat_repo.record_approved(tenant, user, copy_id)
    if new:
        cmo_actions.record_free_run(cmo_actions.Principal(tenant, user), rt, "cmo.approve_for_use", run_id, started)
    states = cmo_chat_repo.listing_states(tenant, copy_id)
    return {"approved": True, "newlyRecorded": new, "message": APPROVED_TEXT, "rulesBasis": built["basis"], "states": states,
            "banner": rules_basis.BANNER.format(marketplace=built["mp"].value.title()) if built["basis"] == rules_basis.UNVERIFIED else None}


# ------------------------------------------------------------------------------------------------ the seller's own edit (free; deterministic)
def apply_edit(tenant: UUID, user: UUID, rt: Any, copy_id: UUID, message: str, *, ci: CiInputs | None = None) -> dict[str, Any]:
    req = edit_rules.parse(message)
    if req.kind == edit_rules.NOT_AN_EDIT:
        raise ListingRefused("NOT_AN_EDIT", "That is not one of my edit sentences. Try “Change bullet 3 to: your text”.")
    if req.kind == edit_rules.REFUSED:
        raise ListingRefused(req.code or "EDIT_REFUSED", req.reason or "I could not use that edit.")
    built = audit_pack(tenant, user, rt, copy_id, ci=ci)
    applied = revise.apply_edit(built["sections"], req)
    if isinstance(applied, revise.Refused):
        raise ListingRefused(applied.code, applied.reason)
    result, refused = revise.check_edit(applied, built["base"])
    if refused is not None:
        raise ListingRefused(refused.code, refused.reason)
    pack = built["pack"]
    new_hash = applied.sections.hash(built["mp"].value)
    structured = revise.revision_structured(pack["structured"], built["sections"], applied, source_id=str(copy_id), by="SELLER_TEXT")
    rec = GenerationRecord(
        output_type=OutputType.LISTING_COPY, marketplace=built["mp"], sku=pack["sku"], status=GenerationStatus.COMPLETE, request_key=f"rev-{str(copy_id)[:8]}-{new_hash[:24]}",
        generated_by=user, agent_run_id=None, output_text=None, output_structured=structured, failure_reason=None, format_constraint_ref=pack["constraintRef"],
        image_analysis_id=None, grounding_basis=GroundingBasis(pack["groundingBasis"]) if pack["groundingBasis"] else None, grounding_approval_id=pack["approvalId"],
        input_mode=pack["inputMode"], ci_inputs_snapshot=pack["ciSnapshot"],
    )
    started, run_id = rt.clock(), uuid4()
    try:
        new_id = rt.store.save_generation(tenant, rec)
        newly = True
    except DuplicateArtefact:  # an identical edit already saved under the same key: serve that one (idempotent), no second row
        existing = [e for e in rt.store.find_artefacts(tenant, rec.request_key) if e.output_type is OutputType.LISTING_COPY and e.status is GenerationStatus.COMPLETE]
        if not existing:
            raise
        new_id, newly = existing[0].id, False
    if newly:
        cmo_actions.record_free_run(cmo_actions.Principal(tenant, user), rt, "cmo.edit_listing_section", run_id, started)
    return {"generationId": str(new_id), "changed": applied.changed, "revisionOf": str(copy_id), "reused": not newly}


# ------------------------------------------------------------------------------------------------ a model rewrite of ONE section (billed: 1 unit per delivered section)
def rewrite_preflight(tenant: UUID, user: UUID, rt: Any, copy_id: UUID, *, target: str, bullet_number: int | None, topic: str, sku: str | None = None,
                      marketplace: Marketplace | None = None) -> dict[str, Any]:
    """Everything that must be true before a rewrite is planned or run (spec 6.18.7, N-15c): the saved version is the seller's own (a foreign or unknown id is NotFound), it is the product and
    marketplace the seller named, the section exists, and the topic is carried by a confirmed fact and is not one the seller has left unconfirmed. Raises ListingRefused with the plain reason;
    nothing is charged and nothing is saved. Free: no model."""
    built = audit_pack(tenant, user, rt, copy_id)
    pack, mp = built["pack"], built["mp"]
    if sku is not None and sku != pack["sku"]:
        raise ListingRefused("WRONG_PRODUCT", "That listing belongs to a different product, so I did not rewrite it.", status=409)
    if marketplace is not None and marketplace is not mp:
        raise ListingRefused("WRONG_MARKETPLACE", f"That listing is for {mp.value.title()}, not {marketplace.value.title()}, so I did not rewrite it.", status=409)
    secs: revise.Sections = built["sections"]
    if target == "bullet":
        if bullet_number is None or not 1 <= bullet_number <= len(secs.bullets):
            raise ListingRefused("BULLET_OUT_OF_RANGE", f"This listing has bullets 1-{len(secs.bullets)}; there is no bullet {bullet_number}.")
    elif target != "description" or bullet_number is not None:
        raise ListingRefused("NOT_A_SECTION", "I can rewrite one bullet (for example bullet 3) or the description. The title, keywords and backend terms are not rewritten by the model.")
    clean = " ".join(str(topic).split())
    if len(clean) < 2 or len(clean) > 80:
        raise ListingRefused("TOPIC_INVALID", "Tell me, in a few words, what the rewrite should mention (for example “wide opening”).")
    base: audit_rules.AuditInputs = built["base"]
    if not preconditions.topic_supported(clean, base.attributes):
        raise ListingRefused("TOPIC_NOT_CONFIRMED", f"Your confirmed details do not say anything about “{clean}”, so I will not write about it. Tell me that detail first, then ask again.")
    wanted = set(words(clean))
    dnc = [str(q["topic"]) for q in (base.questions or {}).get("questions", []) if q.get("claim") and q.get("status") != "CONFIRMED"]
    if any(wanted <= set(words(d)) or set(words(d)) <= wanted for d in dnc):
        raise ListingRefused("TOPIC_NOT_CONFIRMED", f"“{clean}” is something you have not confirmed yet, so I will not write about it. Confirm it first, then ask again.")
    return {"built": built, "topic": clean, "doNotClaim": dnc, "vocab": [str(c["keyword"]) for c in keyword_map.placeable(base.candidates)]}


def rewrite_section(ctx: Any, body: Any) -> dict[str, Any]:
    """The model rewrites ONE bullet or the description of a saved version to mention a confirmed topic. Billed as exactly one GENERATE_LISTING_COPY artefact on the proven path (reservation,
    entitlement, metered event, idempotency); the result is a NEW immutable version that has passed the same gates as a seller's own edit and is audited; the earlier version and every other
    section are untouched. A rewrite that cannot pass is a FAILED row and uses nothing."""
    tenant, user = ctx.tenant_id, ctx.app_user_id
    rt = cmo_runtime.build_runtime()
    pre = rewrite_preflight(tenant, user, rt, body.generation_id, target=body.target, bullet_number=body.bullet_number, topic=body.topic, sku=body.sku, marketplace=body.marketplace)
    built = pre["built"]
    pack, mp = built["pack"], built["mp"]
    key = billing.normalise_request_key(body.request_key)
    req = RewriteRequest(
        request_key=key, marketplace=mp, sku=pack["sku"], source_generation_id=body.generation_id, target=body.target, bullet_number=body.bullet_number, topic=pre["topic"],
        sections=built["sections"], base=built["base"], structured=pack["structured"], approval_id=pack["approvalId"], grounding_basis=pack["groundingBasis"],
        constraint_ref=pack["constraintRef"], input_mode=pack["inputMode"], ci_snapshot=pack["ciSnapshot"], do_not_claim=pre["doNotClaim"], keywords_allowed=pre["vocab"],
    )
    service = ListingRewriteService(rt.store, rt.generation.provider, model=rt.generation.model, clock=rt.clock)
    actor = Actor(tenant, user)
    out = cmo_actions.run_billable(
        cmo_actions.Principal(tenant, user), rt, action=billing.Action.GENERATE_LISTING_COPY, items=[billing.RequestedArtefact(OutputType.LISTING_COPY, mp)], request_key=key,
        execute=lambda run: service.rewrite(actor, req),
    )
    art = _artefact(out, OutputType.LISTING_COPY)
    out.update({"marketplace": mp.value, "sourceGenerationId": str(body.generation_id), "card": None, "status": "FAILED"})
    if art is not None and art.get("status") == "COMPLETE":
        out["status"] = "COMPLETE"
        out["card"] = build_card(tenant, user, rt, UUID(str(art["id"])))  # audited as the version it is; an approval of an earlier version never carries over (it is bound to that row)
    return out


def rewrite_prefill(text: str) -> dict[str, str]:
    """The section and topic the seller already named in their sentence ("rewrite bullet 3 to mention wide opening"); offered to the same field parsers, so nothing already said is asked again."""
    found = edit_rules.parse_rewrite_ask(text)
    return {"rewrite_target": found[0], "rewrite_topic": found[1]} if found else {}


def chat_rewrite_prepare(tenant: UUID, user: UUID, direct: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """For the CEO chat, before a plan card exists: (the closed slots of the rewrite plan, None) or (None, the plain reason it cannot be planned). The version to rewrite is the seller's latest
    complete listing for that product and marketplace, found by code. Fails closed: an unexpected error plans nothing."""
    try:
        mp = Marketplace(str(direct.get("marketplace")))
        sku = str(direct.get("sku") or "")
        pack = cmo_chat_repo.latest_listing_pack(tenant, sku=sku or None, marketplace=mp.value)
        if pack is None:
            return None, f"You do not have a complete {mp.value.title()} listing for that product yet. Ask me to “write my complete listing” first."
        target, _, number = str(direct.get("rewrite_target") or "").partition(":")
        bullet = int(number) if number.isdigit() else None
        pre = rewrite_preflight(tenant, user, cmo_runtime.build_runtime(), pack, target=target, bullet_number=bullet, topic=str(direct.get("rewrite_topic") or ""), sku=sku or None, marketplace=mp)
    except ListingRefused as exc:
        return None, exc.detail
    except Exception:  # noqa: BLE001
        logger.exception("could not pre-check the rewrite")
        return None, "I could not check that rewrite just now, so I did not plan it. Nothing was charged."
    slots: dict[str, Any] = {"request_key": direct["request_key"], "generation_id": str(pack), "target": target, "topic": pre["topic"], "sku": sku, "marketplace": mp.value}
    if bullet is not None:
        slots["bullet_number"] = bullet
    if direct.get("product_name"):
        slots["product_name"] = direct["product_name"]
    return slots, None


# ------------------------------------------------------------------------------------------------ the full-listing run (billed, per artefact, on the proven path)
def _derived(key: str, suffix: str) -> str:
    k = billing.normalise_request_key(key)
    return f"{k[: 128 - len(suffix) - 1]}:{suffix}"


def _artefact(run: Mapping[str, Any], output_type: OutputType) -> Mapping[str, Any] | None:
    return next((a for a in run.get("artefacts", []) if a.get("outputType") == output_type.value), None)


def preflight(tenant: UUID, rt: Any, *, sku: str, mp: Marketplace, grounding: GroundingRequest, ci: CiInputs | None) -> dict[str, Any]:
    """Everything that must be true before the plan card (spec 6.18.2): a title, enough non-contradictory confirmed facts, at least one researched keyword. Raises ListingRefused with the
    plain reason otherwise; nothing is charged and nothing is saved. Returns the researched keywords, the topics not to claim and the facts' context."""
    if (grounding.approval_id is None) == (grounding.seller_title is None):
        raise ListingRefused("NO_TITLE", "A listing is written for an approved title. Approve a title first, or give me the title to use.")
    if grounding.approval_id is not None:
        a = rt.store.load_approval(tenant, grounding.approval_id)
        if a is None or a.marketplace is not mp or (a.sku is not None and a.sku != sku):
            raise ListingRefused("NO_TITLE", "I cannot find that approved title for this product and marketplace.", status=404)
    kw, ctx = keyword_analysis(rt.store, tenant, sku, mp, ci)
    attrs = tuple(a for a in [*ctx.eligible, *(x for x, _ in ctx.ineligible)] if a.name.casefold() != "product_name")
    clash = preconditions.contradictions(attrs)
    if clash:
        d = clash[0]
        raise ListingRefused("CONTRADICTORY_FACTS", f"Your confirmed details disagree about the {d['detail']}: {' vs '.join(map(str, d['values']))}. Tell me which is right before I write the listing.", status=409)
    missing = preconditions.missing_facts(attrs)
    vocab = [str(c["keyword"]) for c in keyword_map.placeable(kw.get("candidates") or [])]
    if kw.get("status") == "NO_FACTS" or not vocab or missing:  # spec 6.18.2 items 2 and 4: the details a listing needs, named, before any plan card (N-05f, N-05h)
        raise ListingRefused("NEEDS_FACTS", "I do not have enough confirmed details to research keywords yet. Tell me: " + (", ".join(missing) or "a few more details about the product") + ".", missing=missing)
    name = next((a.value for a in ctx.eligible if a.name.casefold() == "product_name" and a.value), None)
    qs = _questions(tenant, sku, name, ci)
    dnc = [str(q["topic"]) for q in qs.get("questions", []) if q.get("claim") and q.get("status") != "CONFIRMED"]
    return {"vocab": vocab, "doNotClaim": dnc, "missing": missing}


def rules_state(tenant: UUID, rt: Any, mp: Marketplace) -> tuple[str, str]:
    """("VERIFIED" | "UNVERIFIED" | "BLOCKED", the plain sentence for the plan card) for the full-listing workflow. VERIFIED: a usable verified row exists. UNVERIFIED: none does, the operator flag is
    on and the draft target is set. BLOCKED: none does and unverified drafts are not enabled (or the target is missing). Mirrors exactly what generation will do."""
    from slim_cmo.config import FORMAT_CONSTRAINT_MAX_AGE_DAYS  # noqa: PLC0415
    from slim_cmo.constraints import ConstraintUnavailable, resolve_constraint  # noqa: PLC0415
    from slim_cmo.types import ConstraintRowKind  # noqa: PLC0415

    values = rt.store.load_config(tenant, (FORMAT_CONSTRAINT_MAX_AGE_DAYS, rules_basis.FLAG_KEY, rules_basis.BULLET_TARGET_KEY), rt.clock().date())
    kinds = getattr(rt.generation, "accepted_row_kinds", None) or frozenset({ConstraintRowKind.VERIFIED})
    age = values.get(FORMAT_CONSTRAINT_MAX_AGE_DAYS)
    res = resolve_constraint(rt.store.load_constraints(tenant, mp, kinds), marketplace=mp, category=None, output_type=OutputType.LISTING_COPY, now=rt.clock(),
                             max_age_days=age if isinstance(age, int) else None, accepted_row_kinds=kinds)
    if not isinstance(res, ConstraintUnavailable):
        return "VERIFIED", f"Marketplace rules: the verified {mp.value.title()} rule (checked {res.row.verified_at.date().isoformat()}) is used, and lengths are checked against it."
    settings = rules_basis.BasisSettings(rules_basis.parse_flag(values.get(rules_basis.FLAG_KEY)), rules_basis.parse_target(values.get(rules_basis.BULLET_TARGET_KEY)), rules_basis.FULL_LISTING)
    if rules_basis.applies(res, settings) and settings.bullet_target is not None:
        return "UNVERIFIED", (f"Marketplace rules are not verified for {mp.value.title()}. The listing is written from your confirmed facts: lengths will be measured, not checked, and every marketplace "
                              f"check will say NOT ASSESSED. Draft target: {settings.bullet_target} bullets (not a marketplace requirement).")
    if rules_basis.applies(res, settings):
        return "BLOCKED", "Marketplace rules are not verified and the draft settings are incomplete (the draft bullet target is not configured), so I cannot write this listing yet."
    return "BLOCKED", f"Marketplace rules are not verified for {mp.value.title()} and unverified drafts are not enabled, so I cannot write this listing yet."


def plan_lines(tenant: UUID, slots: Mapping[str, Any]) -> tuple[list[str], str | None]:
    """(detail lines for the plan card, one short line for the compact card). Best-effort: a failed lookup adds nothing and never invents a rule statement."""
    try:
        state, sentence = rules_state(tenant, cmo_runtime.build_runtime(), Marketplace(str(slots.get("marketplace"))))
    except Exception:  # noqa: BLE001
        logger.exception("could not describe the marketplace rules for the plan card")
        return [], None
    short = {"VERIFIED": "Rules: the verified rule is used.", "UNVERIFIED": "Rules: not verified; the draft is labelled and not checked against them.", "BLOCKED": None}[state]
    return [sentence], short


def chat_refusal(tenant: UUID, direct: Mapping[str, Any]) -> str | None:
    """For the CEO chat, before a plan card exists: the plain reason a complete listing cannot be planned yet, else None. A failed check never invents a refusal or hides a plan: the handler
    re-checks and refuses safely."""
    try:
        approval = UUID(str(direct["approval_id"])) if direct.get("approval_id") else None
        title = None if approval else (str(direct.get("seller_title") or "").strip() or None)
        rt = cmo_runtime.build_runtime()
        state, sentence = rules_state(tenant, rt, Marketplace(str(direct.get("marketplace"))))
        if state == "BLOCKED":
            return sentence
        preflight(tenant, rt, sku=str(direct.get("sku") or ""), mp=Marketplace(str(direct.get("marketplace"))), grounding=GroundingRequest(approval, title), ci=None)
    except ListingRefused as exc:
        return exc.detail
    except Exception:  # noqa: BLE001
        logger.exception("could not pre-check the complete listing")
    return None


_SHOW = re.compile(r"^\s*show\s+(?:me\s+)?(?:my|the|our)\s+(?:latest\s+|current\s+)?(?:complete\s+|full\s+)?listing\s*[.?!]*\s*$", re.IGNORECASE)


def chat_reply(ctx: Any, text: str) -> tuple[str, dict[str, Any] | None] | None:
    """CMO 3.0 M6 in the CEO chat (free: no unit, no model): the seller's own edit sentence, or "show my listing". None when the message is neither, so it is routed as usual.
    A refused edit says why in plain words and saves nothing. Typed text never approves a listing: approval is a click on the card."""
    tenant, user = ctx.tenant_id, ctx.app_user_id
    req = edit_rules.parse(text)
    if req.kind == edit_rules.NOT_AN_EDIT and not _SHOW.match(text):
        return None
    if req.kind == edit_rules.REFUSED:
        return (req.reason or "I could not use that edit."), None
    rt = cmo_runtime.build_runtime()
    sku: str | None = None
    if req.product:
        from backend.ceo import cmo_chat  # noqa: PLC0415 - the product-name matcher lives with the other chat helpers

        found = cmo_chat.resolve_product(tenant, req.product)
        if found is None:
            return f"I do not have a saved product called “{req.product}”. Tell me which product you mean.", None
        sku = found[0]
    mp = req.marketplace
    pack = cmo_chat_repo.latest_listing_pack(tenant, sku=sku, marketplace=mp)
    if pack is None:
        return "You do not have a complete listing saved yet. Ask me to “write my complete listing” and I will plan it for your approval first.", None
    try:
        if req.kind == edit_rules.EDIT:
            done = apply_edit(tenant, user, rt, pack, text)
            card = build_card(tenant, user, rt, UUID(done["generationId"]))
            lead = f"Changed {done['changed'].lower()}. This is a new version; the earlier one is still saved. "
        else:
            card = build_card(tenant, user, rt, pack)
            lead = "Here is your latest complete listing. "
    except ListingRefused as exc:
        return exc.detail, None
    return (lead + "Nothing was charged and nothing was published. Approving it for use only records your decision in Metrion."), card


def _flatten(out: dict[str, Any]) -> dict[str, Any]:
    """One artefact list and one status for the CEO's existing result presentation (footer, failure wording). The per-step runs stay in the response."""
    arts: list[Any] = []
    for step in ("copy", "backendTerms", "hashtags"):
        run = out.get(step)
        if isinstance(run, Mapping):
            arts.extend(run.get("artefacts", []))
    out["artefacts"] = arts
    out["runStatus"] = out["status"]
    out["agentRunId"] = (out.get("copy") or {}).get("agentRunId")
    return out


def run_full_listing(ctx: Any, body: Any, *, make_intake: Any) -> dict[str, Any]:
    """Copy pack -> Amazon backend terms -> optional hashtags -> audit. Each artefact is its OWN billable call (reservation, entitlement, metered event, idempotency exactly as the single
    actions) under a key derived from the request key; a failed later step never undoes or recharges an earlier delivered one. The pack failing stops the run with 0 units."""
    tenant, user = ctx.tenant_id, ctx.app_user_id
    rt = cmo_runtime.build_runtime()
    principal = cmo_actions.Principal(tenant, user)
    mp: Marketplace = body.marketplace
    if not body.sku:
        raise ListingRefused("NO_PRODUCT", "A listing is written for a saved product. Name the product first.")
    grounding = GroundingRequest(body.approval_id, body.seller_title)
    ci = body._ci
    info = preflight(tenant, rt, sku=body.sku, mp=mp, grounding=grounding, ci=ci)
    listing = ListingContext(workflow=rules_basis.FULL_LISTING, keyword_vocab=tuple(info["vocab"]), do_not_claim=tuple(info["doNotClaim"]))
    key = billing.normalise_request_key(body.request_key)

    def intake_for(k: str, run: UUID | None) -> Intake:
        return replace(make_intake(body, run), request_key=k, listing=listing)

    copy_key = _derived(key, "copy")
    copy_run = cmo_actions.run_billable(
        principal, rt, action=billing.Action.GENERATE_LISTING_COPY, items=[billing.RequestedArtefact(OutputType.LISTING_COPY, mp)], request_key=copy_key,
        execute=lambda run: rt.generation.generate_listing_copy(Actor(tenant, user), intake_for(copy_key, run), mp, grounding),
    )
    copy = _artefact(copy_run, OutputType.LISTING_COPY)
    out: dict[str, Any] = {"status": "FAILED", "marketplace": mp.value, "copy": copy_run, "backendTerms": None, "hashtags": None, "card": None, "unitsBilled": int(copy_run.get("unitsBilled", 0))}
    if copy is None or copy.get("status") != "COMPLETE":
        return _flatten(out)
    copy_id = UUID(str(copy["id"]))
    steps_ok = True
    if mp is Marketplace.AMAZON:
        terms_key = _derived(key, "terms")
        terms_run = cmo_actions.run_billable(
            principal, rt, action=billing.Action.GENERATE_BACKEND_TERMS, items=[billing.RequestedArtefact(OutputType.BACKEND_TERMS, mp)], request_key=terms_key,
            execute=lambda run: rt.generation.generate_standalone(Actor(tenant, user), intake_for(terms_key, run), OutputType.BACKEND_TERMS, mp, grounding),
        )
        out["backendTerms"] = terms_run
        out["unitsBilled"] += int(terms_run.get("unitsBilled", 0))
        t = _artefact(terms_run, OutputType.BACKEND_TERMS)
        steps_ok = t is not None and t.get("status") == "COMPLETE"
    if getattr(body, "include_hashtags", False):
        tags_key = _derived(key, "tags")
        tags_run = cmo_actions.run_billable(
            principal, rt, action=billing.Action.GENERATE_HASHTAGS, items=[billing.RequestedArtefact(OutputType.HASHTAGS, mp)], request_key=tags_key,
            execute=lambda run: rt.generation.generate_hashtags(Actor(tenant, user), intake_for(tags_key, run), mp),
        )
        out["hashtags"] = tags_run
        out["unitsBilled"] += int(tags_run.get("unitsBilled", 0))
        h = _artefact(tags_run, OutputType.HASHTAGS)
        steps_ok = steps_ok and h is not None and h.get("status") == "COMPLETE"
    out["card"] = build_card(tenant, user, rt, copy_id, ci=ci)
    out["status"] = "COMPLETE" if steps_ok else "PARTIAL"
    return _flatten(out)


__all__ = ["rewrite_preflight", "rewrite_section", "chat_rewrite_prepare", "rewrite_prefill", "rules_state", "plan_lines", "chat_reply", "chat_refusal", "ListingRefused", "full_listing_workflow", "workflow_context", "audit_pack", "build_card", "approve_for_use", "apply_edit", "preflight", "run_full_listing"]
