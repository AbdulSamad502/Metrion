"""CMO 3.0 M9 in the CEO chat: "analyze my product images", "check my main product image", "which image has the lowest quality?", "what is wrong with image 2?", "what additional product photos should I
upload?", "are my images suitable for Amazon?", "show my image quality report". Free: no model (not even the vision model), no AI credit, nothing generated, edited or published.

Every figure and sentence comes from `services.cmo_image_review` (deterministic measurements over the seller's own stored images). The CEO only works out WHICH product and marketplace the seller means, asks ONE
short question when the words leave that open, and shows the stored review as a card. A photo attached in the chat is NEVER added to a product's images by itself: when the seller asks to add it, the card offers
a button, and only that button (the same route as the images page) adds it. Typing "yes" adds nothing."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)
KIND = "IMAGE_QUALITY"
MP_NAME = {"AMAZON": "Amazon", "FLIPKART": "Flipkart", "MEESHO": "Meesho"}
MARKETPLACES = {"amazon": "AMAZON", "flipkart": "FLIPKART", "meesho": "MEESHO"}
IMAGE_TYPES = ("PNG", "JPEG", "WEBP")
PAGE = "/dashboard/cmo/images"
FAILED = "I could not read your product images just now. Nothing was changed. Please try again."
NO_PRODUCT = "I do not know any of your products yet. Tell me about a product in the chat first, then upload its images on the images page."
_FOLD = lambda t: " ".join(re.sub(r"[?!.,;\"“”']", " ", t.casefold()).split())  # noqa: E731

REPORT, PRIMARY, LOWEST, IMAGE_N, MISSING, SUITABLE = "REPORT", "PRIMARY", "LOWEST", "IMAGE_N", "MISSING", "SUITABLE"
_IMG = r"(?:images?|photos?|pictures?|photographs?|pics?)"
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (IMAGE_N, re.compile(rf"\b(?:what(?:'s| is)? wrong|what is the problem|any (?:problem|issue)s?|problems?|issues?|fix|improve|check|review|look at|tell me about)\b.{{0,25}}\b(?:{_IMG}|image|photo)\s*#?\s*(\d{{1,2}})\b|\b{_IMG}\s*#?\s*(\d{{1,2}})\b.{{0,25}}\b(?:wrong|problem|issue|bad|ok|fine|good)\b")),
    (LOWEST, re.compile(rf"\bwhich\b.{{0,15}}\b{_IMG}\b.{{0,25}}\b(?:lowest|worst|weakest|poorest|least)\b|\b(?:lowest|worst|weakest|poorest)\b.{{0,15}}\b(?:quality|scoring|rated)?\s*{_IMG}\b|\b(?:lowest|worst|weakest|poorest)\b.{{0,15}}\bquality\b.{{0,15}}\b{_IMG}\b")),
    (MISSING, re.compile(rf"\b(?:what|which)\b.{{0,25}}\b(?:additional|more|extra|other|missing|else|further)\b.{{0,25}}\b{_IMG}\b|\b(?:what|which)\b.{{0,20}}\b{_IMG}\b.{{0,25}}\b(?:should|do|must|need)\b.{{0,15}}\b(?:i )?(?:upload|add|take|need|have)\b|\bwhat\b.{{0,15}}\b(?:angles?|shots?)\b.{{0,25}}\b(?:missing|should|need|add)\b|\bmissing\b.{{0,15}}\b{_IMG}\b")),
    (SUITABLE, re.compile(rf"\b(?:are|is|do|does|will|would)\b.{{0,20}}\b(?:my|the)?\s*(?:product )?{_IMG}\b.{{0,40}}\b(?:suitable|good enough|ok|okay|fine|acceptable|meet|compliant|compliance|allowed|right|ready|accepted)\b|\b(?:suitable|good enough|compliant|compliance|requirements?|rules?)\b.{{0,30}}\b(?:{_IMG})\b.{{0,30}}\b(?:amazon|flipkart|meesho|marketplace)\b|\b{_IMG}\b.{{0,40}}\b(?:suitable|compliant|meet)\b.{{0,25}}\b(?:amazon|flipkart|meesho|marketplace)\b")),
    (PRIMARY, re.compile(rf"\b(?:check|review|analy[sz]e|look at|assess|evaluate|rate|how is|how(?:'s| is) good)\b.{{0,25}}\b(?:main|primary|first|hero|cover|lead)\b.{{0,15}}\b(?:product )?{_IMG}\b|\b(?:main|primary|hero)\b.{{0,15}}\b(?:product )?{_IMG}\b.{{0,20}}\b(?:quality|check|ok|good)\b")),
    (REPORT, re.compile(rf"\b(?:analy[sz]e|review|check|assess|evaluate|score|rate|audit|inspect|show|open|give)\b.{{0,30}}\b(?:my |the |our )?(?:product )?{_IMG}\b.{{0,25}}\b(?:quality|report|analysis|review|score|clarity|lighting|background)?\b|\b{_IMG} quality\b|\bimage (?:quality )?(?:report|analysis|review|score)\b")),
)
_ATTACH = re.compile(rf"\b(?:add|use|put|attach|save|include|set)\b.{{0,30}}\b(?:this|it|that|the|these|my)\b.{{0,25}}\b(?:{_IMG})\b.{{0,40}}\b(?:product|listing|images?|set|gallery|main|primary|secondary)\b|\b(?:use|set|make)\b.{{0,15}}\b(?:this|it)\b.{{0,15}}\b(?:as )?(?:my |the )?(?:main|primary)\b.{{0,15}}\b{_IMG}\b|\badd (?:this|it) to (?:my |the )?(?:product )?{_IMG}\b")


def classify(text: str) -> str | None:
    t = _FOLD(text or "")
    if not t or len(t) > 300:
        return None
    if re.search(r"\b(?:competitor|their|rival|screenshot|price)\b", t):
        return None  # competitor images and price screenshots are never the seller's product images
    return next((k for k, rx in _RULES if rx.search(t)), None)


def is_attach_request(text: str) -> bool:
    t = _FOLD(text or "")
    return bool(t) and len(t) <= 300 and bool(_ATTACH.search(t)) and not re.search(r"\b(?:competitor|their|rival|screenshot)\b", t)


# ------------------------------------------------------------------------------------------------ small readers
def _prior(tenant: UUID, investigation_id: UUID) -> dict[str, Any] | None:
    from backend.repositories import investigation_repo as inv_repo  # noqa: PLC0415

    try:
        for m in reversed(inv_repo.list_messages(tenant, investigation_id)):
            c = m.get("choices") if isinstance(m, dict) else None
            if m.get("role") == "CEO" and isinstance(c, dict):
                return c if c.get("kind") == KIND else None
    except Exception:  # noqa: BLE001 - no history means no remembered question
        logger.exception("could not read the previous card")
    return None


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.casefold()) if len(w) > 2}


def _mp_in(text: str) -> str | None:
    t = _FOLD(text)
    found = [v for k, v in MARKETPLACES.items() if re.search(rf"\b{k}\b", t)]
    return found[0] if len(found) == 1 else None


_GENERIC = frozenset("the my our images image photos photo pictures picture product products quality report main primary check analyze analyse review show which what are for amazon flipkart meesho wrong with lowest worst additional upload should suitable please".split())


def _find_product(text: str, names: Mapping[str, str]) -> list[str]:
    """The products whose name or SKU shares the most words with the message (generic words ignored); empty when none shares a word."""
    t = _words(text) - _GENERIC
    scored = [(len(t & _words(f"{n} {s}")), s) for s, n in names.items()]
    best = max((sc for sc, _ in scored), default=0)
    return [s for sc, s in scored if sc == best] if best >= 1 else []


def _card(view: str, **kw: Any) -> dict[str, Any]:
    return {"version": 1, "kind": KIND, "view": view, "page": PAGE, "aiCredits": 0, **kw}


def _clarify(question: str, ask: Mapping[str, Any], options: Sequence[Mapping[str, Any]]) -> tuple[str, dict[str, Any]]:
    return question, _card("CLARIFY", question=question, options=list(options), ask=dict(ask))


def _score_text(rep: Mapping[str, Any]) -> str:
    if rep["scoreState"] == "COMPLETE":
        return f"{rep['score']} / 100"
    if rep["scoreState"] == "PARTIAL":
        return f"Score withheld: {rep['pointsEarned']} of {rep['pointsAssessable']} assessable points earned"
    return "Not calculated"


def _shot(rep: Mapping[str, Any], n: int) -> str:
    from slim_cmo.imagequality.review import SHOT_LABEL  # noqa: PLC0415

    row = next(i for i in rep["images"] if i["imageNumber"] == n)
    return ("Main image" if row["role"] == "PRIMARY" else "Additional image") + f" {n} ({SHOT_LABEL.get(row['shotType'], 'image')})"


def _dims(rep: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"key": d["key"], "label": d["label"], "state": d["state"], "pointsText": (f"{d['earned']} of {d['max']}" if d["state"] == "ASSESSED" else f"{d['earned']} of {d['assessableMax']} assessable" if d["state"] == "PARTIAL" else "Not assessed"),
             "reason": d.get("reason")} for d in rep["dimensions"]]


def _finding_view(rep: Mapping[str, Any], f: Mapping[str, Any]) -> dict[str, Any]:
    n = f["imageNumber"]
    return {"imageLabel": _shot(rep, n) if n else "Whole image set", "imageNumber": n, "severity": f["severity"], "problem": f["problem"], "whyItMatters": f["whyItMatters"], "recommendation": f["recommendation"],
            "isMarketplaceRequirement": False}


def _compliance(c: Mapping[str, Any]) -> dict[str, Any]:
    return {"status": c["status"], "marketplace": c["marketplace"], "message": c["message"], "notAssessed": c["notAssessed"],
            "checks": [{"rule": x["rule"], "imageNumber": x.get("imageNumber"), "result": x["result"], "sourceUrl": x["source"]["url"], "checkedOn": x["source"]["checkedOn"], "scope": x["source"]["scope"]} for x in c["checks"]]}


def _report_card(view: str, sku: str, name: str, mp: str, out: Mapping[str, Any], focus: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    rep = out["report"]
    return _card(view, product={"sku": sku, "name": name}, marketplace=mp, marketplaceName=MP_NAME[mp], link=f"{PAGE}?sku={sku}&marketplace={mp}", scoreState=rep["scoreState"], scoreText=_score_text(rep),
                 dimensions=_dims(rep), images=[{"imageNumber": i["imageNumber"], "label": _shot(rep, i["imageNumber"]), "sizeText": f"{i['widthPx']} × {i['heightPx']} px"} for i in rep["images"]],
                 findings=[_finding_view(rep, f) for f in rep["findings"][:8]], moreFindings=max(0, len(rep["findings"]) - 8), missingShots=rep["missingShots"], compliance=_compliance(out["compliance"]),
                 notes=rep["notes"], reviewSaved=bool(out["saved"]), focus=focus, **extra)


# ------------------------------------------------------------------------------------------------ the entry point
def reply(ctx: Any, text: str, investigation_id: UUID) -> tuple[str, dict[str, Any]] | None:
    """A code-written answer for an image request, or None when the message is not one (it then goes on to the rest of the CEO unchanged)."""
    from backend.services import cmo_image_review  # noqa: PLC0415

    tenant = ctx.tenant_id
    prior = _prior(tenant, investigation_id)
    pending = prior.get("ask") if isinstance(prior, dict) and prior.get("view") == "CLARIFY" and isinstance(prior.get("ask"), dict) else None
    kind = classify(text)
    if kind is None and pending is not None and len(_FOLD(text).split()) <= 8:
        kind = pending.get("kind")  # a short answer to the question I just asked
    if kind is None:
        return None
    try:
        return _answer(ctx, tenant, kind, text, pending, cmo_image_review)
    except cmo_image_review.ImageReviewRefused as exc:
        return exc.detail, _card("REFUSED", message=exc.detail, code=exc.code)
    except Exception:  # noqa: BLE001
        logger.exception("image request failed")
        return FAILED, _card("REFUSED", message=FAILED, code="FAILED")


def _answer(ctx: Any, tenant: UUID, kind: str, text: str, pending: Mapping[str, Any] | None, svc: Any) -> tuple[str, dict[str, Any]]:
    from backend.services.cmo_actions import Principal  # noqa: PLC0415

    view = svc.products_view(tenant)
    names = {p["sku"]: p["name"] for p in view["products"]}
    sets = {(p["sku"], s["marketplace"]) for p in view["products"] for s in p["sets"]}
    if not names:
        return NO_PRODUCT, _card("EMPTY", message=NO_PRODUCT)
    sku = (pending or {}).get("sku")
    mp = (pending or {}).get("marketplace") or _mp_in(text)
    n_img = (pending or {}).get("imageNumber")
    if (m := re.search(r"\b(?:image|photo|picture|pic)\s*#?\s*(\d{1,2})\b", _FOLD(text))) and kind == IMAGE_N:
        n_img = int(m[1])
    if sku is None:
        with_images = sorted({s for s, _ in sets})
        mentioned = _find_product(text, names)
        if len(mentioned) == 1:
            sku = mentioned[0]
        elif len(mentioned) > 1 or len(with_images) > 1:
            pool = mentioned or with_images
            q = "Which product do you mean?"
            return _clarify(q, {"kind": kind, "marketplace": mp, "imageNumber": n_img}, [{"label": names[s], "sku": s} for s in pool][:6])
        elif len(with_images) == 1:
            sku = with_images[0]
        elif len(names) == 1:
            sku = next(iter(names))
    if sku is None:
        msg = "You have not uploaded images for any product yet. Choose a product and upload its images on the images page: " + PAGE
        return msg, _card("EMPTY", message=msg)
    if mp is None:
        mps = sorted(m for s, m in sets if s == sku)
        if len(mps) == 1:
            mp = mps[0]
        elif len(mps) > 1:
            return _clarify(f"Which marketplace for {names[sku]}?", {"kind": kind, "sku": sku, "imageNumber": n_img}, [{"label": MP_NAME[m], "sku": sku, "marketplace": m} for m in mps])
        else:
            mp = "AMAZON"
    if (sku, mp) not in sets:
        msg = (f"You have no images uploaded for {names[sku]} on {MP_NAME[mp]} yet, so I have nothing to review. Upload them on the images page "
               f"({PAGE}?sku={sku}&marketplace={mp}); I will not look at anyone else's pictures or guess.")
        return msg, _card("EMPTY", message=msg, product={"sku": sku, "name": names[sku]}, marketplace=mp, marketplaceName=MP_NAME[mp], link=f"{PAGE}?sku={sku}&marketplace={mp}")
    out = svc.review(Principal(tenant, ctx.app_user_id), sku, mp)
    rep = out["report"]
    name = names[sku]
    head = f"Image quality for {name} on {MP_NAME[mp]}: " + _score_text(rep) + ". "
    comp = out["compliance"]
    suffix = " Marketplace image requirements are NOT_ASSESSED: no verified official rule is recorded." if comp["status"] == "NOT_ASSESSED" else " " + comp["message"]
    if kind == PRIMARY:
        prim = next((i for i in rep["images"] if i["role"] == "PRIMARY"), None)
        if prim is None:
            return head + "No main image has been chosen. Mark one image as the main image on the images page.", _report_card("REPORT", sku, name, mp, out)
        mine = [f for f in rep["findings"] if f["imageNumber"] == prim["imageNumber"]]
        body = f"{len(mine)} issue(s) found on your main image." if mine else "No issues were found on your main image by these checks."
        return head + body + suffix, _report_card("IMAGE", sku, name, mp, out, focus={"imageNumber": prim["imageNumber"], "label": _shot(rep, prim["imageNumber"])})
    if kind == IMAGE_N:
        row = next((i for i in rep["images"] if i["imageNumber"] == n_img), None)
        if row is None:
            q = f"{name} has {len(rep['images'])} image(s). Which image number do you mean?"
            return _clarify(q, {"kind": IMAGE_N, "sku": sku, "marketplace": mp}, [{"label": f"Image {i['imageNumber']}", "sku": sku, "marketplace": mp, "imageNumber": i["imageNumber"]} for i in rep["images"]][:8])
        mine = [f for f in rep["findings"] if f["imageNumber"] == n_img]
        body = f"{_shot(rep, n_img)}: " + (f"{len(mine)} issue(s), most important first." if mine else "no issues were found by these checks.")
        return head + body, _report_card("IMAGE", sku, name, mp, out, focus={"imageNumber": n_img, "label": _shot(rep, n_img)})
    if kind == LOWEST:
        scored = [(sum(v for v in i["dimensions"].values() if v is not None) * 100 // max(1, 100 * sum(1 for v in i["dimensions"].values() if v is not None)), i["imageNumber"]) for i in rep["images"]
                  if any(v is not None for v in i["dimensions"].values())]
        if not scored:
            return head + "There is nothing measurable to compare yet.", _report_card("REPORT", sku, name, mp, out)
        low = min(scored)
        return head + f"The lowest-quality image is {_shot(rep, low[1])}, at {low[0]} out of 100 on the dimensions that could be measured for it.", _report_card("IMAGE", sku, name, mp, out, focus={"imageNumber": low[1], "label": _shot(rep, low[1]), "isLowest": True})
    if kind == MISSING:
        miss = rep["missingShots"]
        body = ("Photos that would help: " + "; ".join(m["problem"].replace("No ", "a ", 1).rstrip(".") for m in miss) + ". These are suggestions, not marketplace requirements.") if miss else "You already have a main, an angle, a detail, a size and a usage image. More is optional."
        return head + body, _report_card("MISSING", sku, name, mp, out)
    if kind == SUITABLE:
        body = (f"I cannot say whether your images meet {MP_NAME[mp]}'s requirements: no verified official image rule is recorded, so those checks are NOT_ASSESSED. "
                "What I can tell you is the general image quality below, which is not compliance.") if comp["status"] == "NOT_ASSESSED" else comp["message"]
        return head + body, _report_card("REPORT", sku, name, mp, out)
    return head + f"{len(rep['findings'])} finding(s) listed, most important first." + suffix, _report_card("REPORT", sku, name, mp, out)


def attach_proposal(ctx: Any, text: str, investigation_id: UUID, photo: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """The seller attached a photo and asked to add it to a product's images. Nothing is added: the card lets them choose product, marketplace and kind of shot and press the button."""
    from backend.services import cmo_image_review  # noqa: PLC0415

    view = cmo_image_review.products_view(ctx.tenant_id)
    names = {p["sku"]: p["name"] for p in view["products"]}
    if not names:
        return NO_PRODUCT, _card("EMPTY", message=NO_PRODUCT)
    mentioned = _find_product(text, names)
    pre_sku = mentioned[0] if len(mentioned) == 1 else (next(iter(names)) if len(names) == 1 else None)
    role = "PRIMARY" if re.search(r"\b(?:main|primary)\b", _FOLD(text)) else "SECONDARY"
    msg = (f"I have not added “{photo.get('filename') or 'your photo'}” to any product. Choose the product, marketplace and kind of shot, then press “Add to my product images”. "
           "Typing yes does not add it. Nothing is published.")
    return msg, _card("ATTACH", message=msg, attachment={"id": str(photo["id"]), "filename": str(photo.get("filename") or "photo")}, products=[{"sku": s, "name": n} for s, n in names.items()],
                      marketplaces=[{"key": k, "label": MP_NAME[k]} for k in MP_NAME], shotTypes=view["shotTypes"], preselect={"sku": pre_sku, "marketplace": _mp_in(text) or "AMAZON", "role": role, "shotType": "FRONT" if role == "PRIMARY" else "OTHER"})
