"""Listing readiness checklist and 0-100 readiness score (CMO 3.0 M5; docs/specs/slim-cmo-agent.md section 6.17).

What this module IS: pure, deterministic code. For one product and ONE marketplace it lists every requirement before the seller lists it, with a status that never hides a gap:

* DONE - the requirement is met, by something the seller confirmed or something Metrion already produced and checked;
* MISSING - the seller (or a CEO request) can still do it: it earns nothing and is listed with the action to take;
* BLOCKED - something that must be fixed first (every title option fails a hard check; the chosen title has a hard failure; the verified marketplace rule is broken);
* NOT_ASSESSED - it cannot be judged from the evidence Metrion has (above all: no VERIFIED marketplace rule exists, so no marketplace requirement can be called met). It earns nothing and is
  taken out of BOTH the points earned and the points assessable; it is never counted as passed and never as zero.

The score is 100 fixed points (product facts 25, title 20, keywords 10, buyer questions 15, listing content 15, product photo 10, marketplace requirements 5), integer arithmetic only, with every
item's points shown. It is `100 x earned / assessable`, shown with how many of the 100 points could be assessed; below MIN_ASSESSED_POINTS there is no score. The verdict is NOT the score:

* BLOCKED - at least one item is blocked;
* NOT_READY - nothing blocked, but something is missing;
* DRAFT_READY_NOT_VERIFIED - nothing blocked or missing, but at least one requirement could not be assessed (today always the marketplace's own requirements);
* READY - every requirement is done and assessed. Without verified marketplace rules this verdict cannot appear.

It calls no model and reads no database. The score is an internal readiness assessment, not a marketplace approval, ranking, conversion or sales prediction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

METHOD = "listing-readiness-v1"
DONE, MISSING, BLOCKED, NOT_ASSESSED = "DONE", "MISSING", "BLOCKED", "NOT_ASSESSED"
MIN_ASSESSED_POINTS = 50  # below this many assessable points there is no score (an internal rule of thumb, stated to the seller)
CATEGORIES = (("facts", "Confirmed product facts", 25), ("title", "Title", 20), ("keywords", "Keywords", 10), ("buyer", "Buyer questions", 15), ("content", "Listing content", 15),
              ("photo", "Product photo", 10), ("marketplace", "Marketplace requirements", 5))
FACT_ITEMS = (("brand", "Brand", ("brand",)), ("size", "Size or capacity", ("size", "capacity", "volume")), ("material", "Material", ("material",)), ("color", "Colour", ("color", "colour")),
              ("category", "Category", ("category",)))
TITLE_BAND_POINTS = {"STRONG": 12, "GOOD": 9, "FAIR": 5, "WEAK": 2}  # of the 12 title-quality points, by the M3 band of the best eligible option
VERDICT_TEXT = {
    BLOCKED: "Blocked: something must be fixed before you list.",
    "NOT_READY": "Not ready: some requirements are still missing.",
    "DRAFT_READY_NOT_VERIFIED": "Draft ready, but not verified: everything Metrion can check is done, yet the marketplace's own requirements could not be assessed.",
    "READY": "Ready: every requirement is done and assessed.",
}


@dataclass(frozen=True, slots=True)
class MarketplaceInputs:
    marketplace: str
    title_analysis: Mapping[str, Any] | None  # the stored M3 analysis of the newest title set for this product and marketplace, or None
    approved_title: str | None  # the title the seller chose (M0) for this marketplace, or None
    copy_pack: bool  # a complete listing copy pack exists for this marketplace
    rule_verified: bool  # a VERIFIED, current marketplace title rule exists (from the M3 analysis)


@dataclass(frozen=True, slots=True)
class ProductInputs:
    profile: Mapping[str, Any]  # M1 product profile
    questions: Mapping[str, Any]  # M5 buyer questions analysis
    keyword_result: Mapping[str, Any] | None  # M2 keyword analysis
    has_photo: bool  # the seller's own photo was attached for Slim CMO to read (presence only; quality is not assessed)


def _share(max_points: int, num: int, den: int) -> int:
    return (max_points * num * 2 + den) // (2 * den) if den else 0


def _item(item_id: str, label: str, status: str, max_points: int, earned: int, detail: str, action: str | None = None) -> dict[str, Any]:
    return {"id": item_id, "label": label, "status": status, "max": max_points, "earned": earned if status != NOT_ASSESSED else None, "detail": detail, "action": action}


def _best_option(analysis: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    opts = [o for o in (analysis or {}).get("options", []) if o.get("eligible")]
    scored = [o for o in opts if (o.get("scores") or {}).get("overall", {}).get("status") == "ASSESSED"]
    if not scored:
        return opts[0] if opts else None
    return max(scored, key=lambda o: (o["scores"]["overall"]["score"], -o["rank"]))


def _facts_items(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    have = {str(a["label"]).casefold(): a for a in profile.get("attributes", [])}
    out = []
    for fid, label, names in FACT_ITEMS:
        hit = next((have[n] for n in names if n in have), None)
        out.append(_item(f"fact_{fid}", label, DONE if hit else MISSING, 5, 5 if hit else 0, f"You told me: {hit['value']}." if hit else f"Not confirmed yet.", None if hit else f"Tell me the {label.lower()}."))
    return out


def _title_items(m: MarketplaceInputs) -> list[dict[str, Any]]:
    name = m.marketplace.title()
    a = m.title_analysis
    if not a:
        return [_item("title_written", f"Title options written for {name}", MISSING, 4, 0, "No title options are saved for this marketplace.", f"Ask me to write titles for {name}."),
                _item("title_clean", "At least one title passes the hard checks", MISSING, 4, 0, "There are no titles to check yet.", None),
                _item("title_quality", "Title quality", MISSING, 12, 0, "There are no titles to score yet.", None)]
    items = [_item("title_written", f"Title options written for {name}", DONE, 4, 4, f"{len(a.get('options', []))} saved options.")]
    ok = [o for o in a.get("options", []) if o.get("eligible")]
    items.append(_item("title_clean", "At least one title passes the hard checks", DONE if ok else BLOCKED, 4, 4 if ok else 0,
                       f"{len(ok)} of {len(a.get('options', []))} options pass." if ok else "Every option has a hard failure (an unconfirmed claim or a broken verified rule).",
                       None if ok else "Confirm the missing facts or ask me for new titles."))
    best = _best_option(a)
    ov = ((best or {}).get("scores") or {}).get("overall") or {}
    if ov.get("status") == "ASSESSED":
        band = str(ov.get("band"))
        pts = TITLE_BAND_POINTS.get(band, 0)
        items.append(_item("title_quality", "Title quality", DONE if band in ("STRONG", "GOOD") else MISSING, 12, pts,
                           f"Best option scores {ov['score']}/100 ({band.lower()}) on {ov['assessablePoints']} of 100 assessable points.", None if band in ("STRONG", "GOOD") else "Improve the title: see the title comparison."))
    else:
        items.append(_item("title_quality", "Title quality", NOT_ASSESSED, 12, 0, "Not assessed: not enough confirmed evidence to score the titles."))
    return items


def _keyword_items(p: ProductInputs, m: MarketplaceInputs) -> list[dict[str, Any]]:
    kw = p.keyword_result or {}
    cands = [c for c in kw.get("candidates", []) if c.get("recommended") and "TITLE" in c.get("placement", [])]
    if kw.get("status") != "COMPLETE" or not cands:
        why = "Not assessed: keyword research needs confirmed product facts first."
        return [_item("kw_found", "Title-worthy keywords identified", NOT_ASSESSED, 4, 0, why), _item("kw_in_title", "The title carries the keywords", NOT_ASSESSED, 6, 0, why)]
    items = [_item("kw_found", "Title-worthy keywords identified", DONE, 4, 4, f"{len(cands)} keywords fit your product (volume and demand are not assessed).")]
    best = _best_option(m.title_analysis)
    d = ((best or {}).get("dimensions") or {}).get("keywordRelevance") or {}
    if not best or d.get("status") in (None, NOT_ASSESSED):
        items.append(_item("kw_in_title", "The title carries the keywords", MISSING if not best else NOT_ASSESSED, 6, 0,
                           "There is no title to check yet." if not best else "Not assessed.", "Ask me to write titles." if not best else None))
    else:
        c, miss = len(d.get("covered", [])), len(d.get("missing", []))
        earned = _share(6, c, c + miss)
        items.append(_item("kw_in_title", "The title carries the keywords", DONE if not miss else MISSING, 6, earned, f"The best title carries {c} of {c + miss}." + ("" if not miss else " Missing: " + ", ".join(f"“{k}”" for k in d["missing"][:3]) + "."),
                           None if not miss else "Add the missing keywords to the title."))
    return items


def _buyer_items(p: ProductInputs) -> list[dict[str, Any]]:
    qs = p.questions.get("questions") or []
    if not qs:
        return [_item("buyer_handled", "Buyer questions answered", NOT_ASSESSED, 15, 0, "Not assessed: there are no questions yet (they need a product name).")]
    handled = [q for q in qs if q["status"] in ("CONFIRMED", "SELLER_UNKNOWN")]
    open_ = [q for q in qs if q["status"] == "NOT_CONFIRMED"]
    earned = _share(15, len(handled), len(qs))
    detail = f"{len(handled)} of {len(qs)} buyer questions are answered or settled."
    if open_:
        detail += " Unanswered: " + "; ".join(q["topic"].lower() for q in open_[:5]) + ("; …" if len(open_) > 5 else "") + "."
    return [_item("buyer_handled", "Buyer questions answered", DONE if not open_ else MISSING, 15, earned, detail, None if not open_ else "Answer the open questions (each is NOT CONFIRMED until you tell me).")]


def _content_items(m: MarketplaceInputs) -> list[dict[str, Any]]:
    name = m.marketplace.title()
    items = [_item("content_title", f"You chose a title for {name}", DONE if m.approved_title else MISSING, 5, 5 if m.approved_title else 0,
                   f"Chosen: {m.approved_title}" if m.approved_title else "No title has been chosen.", None if m.approved_title else "Say “use option 1” (or pick one) after comparing titles.")]
    if m.approved_title and m.title_analysis:
        hit = next((o for o in m.title_analysis.get("options", []) if " ".join(o["text"].split()).casefold() == " ".join(m.approved_title.split()).casefold()), None)
        if hit and hit.get("hardFailures"):
            items[0] = _item("content_title", f"You chose a title for {name}", BLOCKED, 5, 0, "The title you chose has a hard failure: " + " ".join(hit["hardFailures"]), "Choose another title or confirm the missing fact.")
    items.append(_item("content_copy", f"Listing copy written for {name}", DONE if m.copy_pack else MISSING, 10, 10 if m.copy_pack else 0,
                       "Description, bullet points and keywords are saved." if m.copy_pack else "No complete listing copy is saved.", None if m.copy_pack else f"Ask me to write the listing copy for {name}."))
    return items


def _photo_items(p: ProductInputs) -> list[dict[str, Any]]:
    return [_item("photo_present", "Product photo", DONE if p.has_photo else MISSING, 10, 10 if p.has_photo else 0,
                  "You attached a photo for Slim CMO to read. Photo quality is not assessed." if p.has_photo else "No product photo was attached for this product.",
                  None if p.has_photo else "Attach a clear product photo in this conversation and ask me to read it.")]


def _market_items(m: MarketplaceInputs) -> list[dict[str, Any]]:
    name = m.marketplace.title()
    label = f"Title meets {name}'s verified length rule"
    rules = [(o, (o.get("dimensions") or {}).get("marketplaceRules") or {}) for o in (m.title_analysis or {}).get("options", [])]
    known = [r for _, r in rules if r.get("status") in ("PASS", "FAIL")]
    if not m.rule_verified or not known:
        items = [_item("market_title_rule", label, NOT_ASSESSED, 5, 0, f"Not assessed: no verified, current {name} rule exists, so this cannot be called met.")]
    elif any(r["status"] == "PASS" for r in known):
        ok = next(r for r in known if r["status"] == "PASS")
        items = [_item("market_title_rule", label, DONE, 5, 5, ok.get("detail") or "At least one title passes the verified rule.")]
    else:
        items = [_item("market_title_rule", label, BLOCKED, 5, 0, known[0].get("detail") or "Every title breaks the verified rule.", "Shorten the title.")]
    items.append(_item("market_attrs", f"{name} category-specific required fields", NOT_ASSESSED, 0, 0,
                       "Not assessed: no verified category taxonomy exists, so required fields cannot be listed. Check them in your seller account. Until one exists the verdict cannot be READY."))
    return items


def assess(p: ProductInputs, m: MarketplaceInputs) -> dict[str, Any]:
    builders = {"facts": lambda: _facts_items(p.profile), "title": lambda: _title_items(m), "keywords": lambda: _keyword_items(p, m), "buyer": lambda: _buyer_items(p),
                "content": lambda: _content_items(m), "photo": lambda: _photo_items(p), "marketplace": lambda: _market_items(m)}
    cats: list[dict[str, Any]] = []
    for cid, label, mx in CATEGORIES:
        items = builders[cid]()
        assessed = [i for i in items if i["status"] != NOT_ASSESSED and i["max"] > 0]
        earned, assessable = sum(i["earned"] for i in assessed), sum(i["max"] for i in assessed)
        cats.append({"id": cid, "label": label, "max": mx, "status": "ASSESSED" if assessed else NOT_ASSESSED, "earned": earned if assessed else None, "assessable": assessable,
                     "score": _share(100, earned, assessable) if assessable else None, "items": items})
    all_items = [i for c in cats for i in c["items"]]
    earned = sum(i["earned"] for i in all_items if i["status"] != NOT_ASSESSED and i["max"] > 0)
    assessable = sum(i["max"] for i in all_items if i["status"] != NOT_ASSESSED and i["max"] > 0)
    if assessable < MIN_ASSESSED_POINTS:
        score: dict[str, Any] = {"status": NOT_ASSESSED, "assessablePoints": assessable, "note": f"Not enough evidence for a readiness score: only {assessable} of 100 points could be assessed (at least {MIN_ASSESSED_POINTS} are needed)."}
    else:
        score = {"status": "ASSESSED", "score": _share(100, earned, assessable), "earnedPoints": earned, "assessablePoints": assessable,
                 "note": "Based on all 100 points." if assessable == 100 else f"Based on {assessable} of 100 assessable points; requirements that could not be assessed are left out, not counted as passed or as zero."}
    blocked = [i for i in all_items if i["status"] == BLOCKED]
    missing = [i for i in all_items if i["status"] == MISSING]
    unassessed = [i for i in all_items if i["status"] == NOT_ASSESSED]
    verdict = "BLOCKED" if blocked else "NOT_READY" if missing else "DRAFT_READY_NOT_VERIFIED" if unassessed else "READY"
    actions = [{"id": i["id"], "label": i["label"], "action": i["action"], "status": i["status"], "points": i["max"]} for i in sorted(blocked + missing, key=lambda x: (x["status"] != BLOCKED, -x["max"], x["id"])) if i["action"]][:6]
    return {"method": METHOD, "marketplace": m.marketplace, "verdict": verdict, "verdictText": VERDICT_TEXT[verdict], "score": score, "categories": cats, "nextActions": actions,
            "counts": {"done": sum(i["status"] == DONE for i in all_items), "missing": len(missing), "blocked": len(blocked), "notAssessed": len(unassessed)}}


def assess_all(p: ProductInputs, markets: Sequence[MarketplaceInputs]) -> dict[str, Any]:
    return {"method": METHOD, "marketplaces": [assess(p, m) for m in markets],
            "limits": ["The readiness score is an internal assessment of what is done and what is missing for your own listing. It is not a marketplace approval, ranking, conversion or sales prediction.",
                       "A requirement that could not be assessed (above all the marketplace's own requirements, because no verified rule exists) is shown as NOT ASSESSED. It is never counted as passed.",
                       "Photo quality, category-specific required fields and search demand are not assessed."]}
