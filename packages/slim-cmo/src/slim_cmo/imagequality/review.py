"""M9: the transparent 0-100 image quality score, per-image findings and set-level coverage. Pure: no model, no I/O, no clock, no floats.

Six dimensions with fixed weights (clarity 20, lighting 15, product visibility 20, composition 15, background 15, set consistency and coverage 15). Each image gets a 0..100 percentage per dimension or `None`
(NOT_ASSESSED, with the reason) when the measurement does not apply or cannot be made; the primary image counts 60% and the secondary images 40% of a dimension. A single number is given ONLY when every
dimension was assessed; otherwise the points earned out of the points assessable are shown and the score is withheld. The score is IMAGE QUALITY. It is not marketplace compliance and not listing readiness.
Every recommendation is advice, never a marketplace requirement, unless a verified official rule is cited by `compliance`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

METHOD_VERSION = "m9-image-review-1"
SHOT_TYPES = ("FRONT", "BACK", "SIDE", "ANGLE", "DETAIL", "SIZE", "USAGE", "PACKAGING", "OTHER")
ROLES = ("PRIMARY", "SECONDARY")
DIMENSIONS: tuple[tuple[str, str, int], ...] = (
    ("clarity", "Image clarity", 20), ("lighting", "Lighting and exposure", 15), ("visibility", "Product visibility", 20),
    ("composition", "Composition and cropping", 15), ("background", "Background quality", 15), ("set", "Image-set consistency and coverage", 15),
)
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
SHOT_LABEL = {"FRONT": "front view", "BACK": "back view", "SIDE": "side view", "ANGLE": "angled view", "DETAIL": "close-up detail", "SIZE": "size or dimensions visual",
              "USAGE": "in-use or lifestyle view", "PACKAGING": "packaging view", "OTHER": "other view"}
_ANGLE_TYPES = frozenset({"BACK", "SIDE", "ANGLE"})

# code -> (problem, why it matters to the buyer, what to do)
TEXT: dict[str, tuple[str, str, str]] = {
    "LOW_RESOLUTION": ("The image is small", "Buyers cannot zoom in to check details, and a small picture looks unprofessional next to larger ones.", "Re-shoot or export it at 1000 pixels or more on the long side."),
    "BELOW_ZOOM_SIZE": ("The image is under 1000 pixels on its long side", "Larger images stay sharp when a buyer zooms in.", "If you have the original, upload it at 1000 pixels or more on the long side."),
    "BLURRY": ("The image looks blurry", "A blurry product picture hides detail and makes buyers doubt quality.", "Re-shoot with a steady camera or tripod, good focus and enough light."),
    "SLIGHTLY_SOFT": ("The image looks slightly soft", "Soft focus makes small details and text on the product hard to read.", "Focus on the product and avoid motion; a tripod and more light help."),
    "TOO_DARK": ("The product looks too dark", "Buyers cannot judge colour or finish in a dark picture.", "Shoot in even, brighter light or add a soft light source; avoid back-lighting."),
    "UNDEREXPOSED": ("The product is somewhat dark", "Dim pictures make colours look dull.", "Add soft light or raise the exposure when shooting."),
    "OVEREXPOSED": ("The product looks washed out", "Over-bright areas lose detail and colour.", "Reduce direct light or exposure; use soft, even light."),
    "CLIPPED_SHADOWS": ("Large parts of the product are almost pure black", "Detail in the dark areas is lost.", "Add fill light so shadows keep detail."),
    "CLIPPED_HIGHLIGHTS": ("Large parts of the product are almost pure white", "Detail in the bright areas is lost.", "Reduce glare and direct light on glossy surfaces."),
    "FLAT_CONTRAST": ("The product has very little contrast", "A flat picture makes shape and texture hard to see.", "Light the product from the side or use a backdrop that contrasts with it."),
    "PRODUCT_TOO_SMALL_OR_ABSENT": ("The product is hardly visible", "Buyers need to see the product clearly at a glance.", "Move closer or crop so the product fills most of the frame."),
    "PRODUCT_SMALL": ("The product fills only a small part of the frame", "A small product wastes space and shows less detail.", "Move closer or crop so the product fills about half to most of the frame."),
    "PRODUCT_OVERFILLED": ("The product fills almost the whole frame", "With no margin the product can look cramped or cut off.", "Leave a little space around the product."),
    "SUBJECT_OFF_CENTER": ("The product sits well off centre", "An unbalanced frame looks careless and may push the product partly out of view in search thumbnails.", "Centre the product in the frame."),
    "SUBJECT_NEAR_EDGE": ("The product touches or nearly touches one edge", "The product may look cut off.", "Leave a small margin on all sides."),
    "SUBJECT_CUT_OFF": ("The product reaches two or more edges", "It is probably cut off; buyers cannot see the whole product.", "Step back or crop wider so the whole product is inside the frame."),
    "UNUSUAL_ASPECT": ("The image is unusually wide or tall", "Odd shapes get cropped or shrunk in thumbnails.", "Use a shape close to square or 3:4."),
    "BUSY_BACKGROUND": ("The background is not plain", "A busy background pulls attention away from the product.", "Use a plain, even backdrop. Check your marketplace's rule for the main image."),
    "CLUTTERED_BACKGROUND": ("There are many distracting details around the product", "Clutter competes with the product for attention.", "Remove other objects and shoot against a clean backdrop."),
    "POSSIBLE_OVERLAY": ("There may be text, a logo or a graphic away from the product (low-confidence check)", "Overlays can distract and some marketplaces restrict them on the main image.", "Look at the image; if there is overlay text or a watermark, use a clean version for the main image."),
    "NO_PRIMARY": ("No main image has been chosen", "The main image is what buyers see first in search.", "Mark one image as the main image."),
    "ONLY_ONE_IMAGE": ("Only one image is uploaded", "Buyers use several pictures to judge a product; one image gives little to go on.", "Add more images showing other angles, details, size and use."),
    "MISSING_ANGLE": ("No back, side or angled view", "Buyers want to see the product from more than one side.", "Add a back, side or angled photo."),
    "MISSING_DETAIL": ("No close-up detail image", "Close-ups show material, finish and build quality.", "Add a close-up of an important detail."),
    "MISSING_SIZE": ("No size or dimensions visual", "Unclear size is a common reason for returns and questions.", "Add an image showing the size, for example with measurements or next to a familiar object."),
    "MISSING_USAGE": ("No in-use or lifestyle image", "It helps buyers picture the product in use.", "Add a photo of the product being used."),
    "INCONSISTENT_ASPECT": ("The images have different shapes", "Mixed shapes look uneven in the image gallery.", "Use the same aspect ratio for all images."),
    "INCONSISTENT_RESOLUTION": ("Some images are much smaller than others", "Mixed sizes look uneven and the small ones look worse when zoomed.", "Re-export the smaller images at a similar size."),
    "INCONSISTENT_LIGHTING": ("Brightness differs a lot between images", "The product can look like a different colour from picture to picture.", "Shoot all images in the same light."),
    "REPEATED_IMAGE": ("Two images look almost the same", "A repeated picture uses a gallery slot without telling the buyer anything new.", "Replace one of them with a different angle, a close-up detail, a size visual or an in-use photo."),
    "INCONSISTENT_BACKGROUND": ("The background colour differs between images", "A consistent set looks professional.", "Use the same backdrop for the product-on-plain images."),
}


def _tier(v: int, table: Sequence[tuple[int, int]], low: int) -> int:
    for floor, pct in table:
        if v >= floor:
            return pct
    return low


def _finding(code: str, severity: str, evidence: Mapping[str, Any], *, number: int | None = None, image_id: str | None = None, role: str | None = None, shot: str | None = None) -> dict[str, Any]:
    problem, why, fix = TEXT[code]
    if code == "REPEATED_IMAGE":
        a, b = evidence["images"]
        problem = f"Image {a} and image {b} look almost the same"
    return {"imageNumber": number, "imageId": image_id, "role": role, "shotType": shot, "code": code, "severity": severity, "problem": problem, "whyItMatters": why, "recommendation": fix,
            "evidence": dict(evidence), "isMarketplaceRequirement": False}


def score_image(m: Mapping[str, Any], role: str, shot: str) -> tuple[dict[str, int | None], dict[str, str], list[tuple[str, str, dict[str, Any]]]]:
    """Per-dimension percentages (None = NOT_ASSESSED), the reason for each None, and findings as (code, severity, evidence)."""
    primary = role == "PRIMARY"
    pct: dict[str, int | None] = {}
    why_not: dict[str, str] = {}
    found: list[tuple[str, str, dict[str, Any]]] = []
    # ---- clarity --------------------------------------------------------------------------------------------------------------------------------------
    long_side, sharp = int(m["long_side"]), int(m["sharpness"])
    res = _tier(long_side, ((1000, 100), (800, 80), (500, 55), (300, 25)), 5)
    sh = _tier(sharp, ((300, 100), (200, 80), (150, 55), (100, 30)), 10)
    pct["clarity"] = (res * 40 + sh * 60) // 100
    if long_side < 500:
        found.append(("LOW_RESOLUTION", "HIGH" if primary else "MEDIUM", {"longSidePx": long_side}))
    elif long_side < 1000:
        found.append(("BELOW_ZOOM_SIZE", "LOW", {"longSidePx": long_side}))
    if sh <= 30:
        found.append(("BLURRY", "HIGH" if primary else "MEDIUM", {"sharpnessIndex": sharp}))
    elif sh <= 55:
        found.append(("SLIGHTLY_SOFT", "MEDIUM" if primary else "LOW", {"sharpnessIndex": sharp}))
    # ---- lighting -------------------------------------------------------------------------------------------------------------------------------------
    isolated, plain = bool(m["subject_isolated"]), bool(m["plain_background"])
    if plain and not isolated:
        pct["lighting"] = None
        why_not["lighting"] = "The product is too small in the frame to judge its lighting."
    else:
        luma = int(m["subject_mean_luma"])
        base = 100 if 85 <= luma <= 200 else 70 if (60 <= luma < 85 or 200 < luma <= 225) else 40 if (40 <= luma < 60 or 225 < luma <= 240) else 10
        if int(m["dark_clip_permille"]) >= 300:
            base -= 20
            found.append(("CLIPPED_SHADOWS", "MEDIUM", {"darkClippedPermille": int(m["dark_clip_permille"])}))
        if int(m["bright_clip_permille"]) >= 300 and isolated:
            base -= 20
            found.append(("CLIPPED_HIGHLIGHTS", "MEDIUM", {"brightClippedPermille": int(m["bright_clip_permille"])}))
        if int(m["contrast_range"]) < 50:
            base -= 20
            found.append(("FLAT_CONTRAST", "MEDIUM" if primary else "LOW", {"contrastRange": int(m["contrast_range"])}))
        pct["lighting"] = max(0, base)
        if luma < 40:
            found.append(("TOO_DARK", "HIGH" if primary else "MEDIUM", {"meanBrightness": luma}))
        elif luma < 60:
            found.append(("UNDEREXPOSED", "MEDIUM" if primary else "LOW", {"meanBrightness": luma}))
        elif luma > 240:
            found.append(("OVEREXPOSED", "HIGH" if primary else "MEDIUM", {"meanBrightness": luma}))
        elif luma > 225:
            found.append(("OVEREXPOSED", "MEDIUM" if primary else "LOW", {"meanBrightness": luma}))
    # ---- aspect (advice; part of composition when the product can be located) ------------------------------------------------------------------------------
    asp = int(m["aspect_x100"])
    asp_pen = 0 if 75 <= asp <= 134 else 15 if 50 <= asp <= 200 else 35
    if asp_pen:
        found.append(("UNUSUAL_ASPECT", "LOW" if asp_pen == 15 else "MEDIUM", {"aspectRatioX100": asp}))
    overlay = str(m["overlay"])
    # ---- visibility, composition and background ----------------------------------------------------------------------------------------------------------
    if shot in ("USAGE", "DETAIL"):
        for k in ("visibility", "composition", "background"):
            pct[k] = None
            why_not[k] = "Not applicable to a " + SHOT_LABEL[shot] + ": the product is not expected to sit alone in the frame."
    else:
        if plain and not isolated:
            pct["visibility"], pct["composition"] = 10, None
            why_not["composition"] = "The product is too small to locate."
            found.append(("PRODUCT_TOO_SMALL_OR_ABSENT", "HIGH" if primary else "MEDIUM", {"subjectPixelsPermille": int(m["subject_pixels_permille"])}))
        elif not isolated:
            pct["visibility"] = pct["composition"] = None
            why_not["visibility"] = why_not["composition"] = "The background is too varied to separate the product from it."
        else:
            box = int(m["subject_box_permille"])
            vis = 100 if 350 <= box <= 850 else 70 if (200 <= box < 350 or 850 < box <= 950) else 40 if 100 <= box < 200 else 15 if box < 100 else 50
            if box < 100:
                found.append(("PRODUCT_TOO_SMALL_OR_ABSENT", "HIGH" if primary else "MEDIUM", {"productShareOfFramePermille": box}))
            elif box < 200:
                found.append(("PRODUCT_SMALL", "MEDIUM" if primary else "LOW", {"productShareOfFramePermille": box}))
            elif box > 950:
                found.append(("PRODUCT_OVERFILLED", "LOW", {"productShareOfFramePermille": box}))
            if overlay == "POSSIBLE_OVERLAY" and primary:
                vis = max(0, vis - 20)
            pct["visibility"] = vis
            off, touched = int(m["center_offset_permille"]), int(m["edges_touched"])
            comp = 100 if off <= 100 else 75 if off <= 200 else 45 if off <= 300 else 20
            if off > 200:
                found.append(("SUBJECT_OFF_CENTER", "MEDIUM" if primary else "LOW", {"centreOffsetPermille": off}))
            if touched >= 2:
                comp -= 50
                found.append(("SUBJECT_CUT_OFF", "HIGH" if primary else "MEDIUM", {"edgesTouched": touched}))
            elif touched == 1:
                comp -= 25
                found.append(("SUBJECT_NEAR_EDGE", "MEDIUM" if primary else "LOW", {"edgesTouched": touched}))
            pct["composition"] = max(0, comp - asp_pen)
        u = int(m["border_plain_permille"])
        bg = 100 if u >= 900 else 80 if u >= 750 else 55 if u >= 500 else 35 if u >= 300 else 15
        busy = m["background_busy_permille"]
        if busy is not None and int(busy) > 150:
            bg -= 15
            found.append(("CLUTTERED_BACKGROUND", "MEDIUM" if primary else "LOW", {"backgroundBusyPermille": int(busy)}))
        if overlay == "POSSIBLE_OVERLAY" and primary:
            bg -= 15
        if u < 750:
            found.append(("BUSY_BACKGROUND", "MEDIUM" if primary else "LOW", {"plainBorderPermille": u}))
        pct["background"] = max(0, bg)
    if overlay == "POSSIBLE_OVERLAY" and shot != "SIZE":
        found.append(("POSSIBLE_OVERLAY", "MEDIUM" if primary else "LOW", {"check": "low-confidence heuristic"}))
    return pct, why_not, found


# Near-duplicate detection. Conservative on purpose: a front and a back view of the same product on the same backdrop are legitimately alike, so a pair is called a repeat only when BOTH
# fingerprints agree very closely (and more closely still when the two images are labelled as different kinds of shot). A pair that is alike but not alike enough is reported as NOT_ASSESSED, never flagged.
SAME_SHOT = {"hash": 4, "colour": 12}
DIFFERENT_SHOT = {"hash": -1, "colour": -1}  # the seller labelled them as different views: a visual match is never enough to call a repeat; it is reported as NOT_ASSESSED
UNCERTAIN = {"hash": 10, "colour": 30}


def _compare(a: Mapping[str, Any], b: Mapping[str, Any], same_shot: bool) -> dict[str, Any]:
    hd = bin(int(a["dhash"]) ^ int(b["dhash"])).count("1")
    ta, tb = a["thumb"], b["thumb"]
    cd = sum(abs(x - y) for x, y in zip(ta, tb)) // len(ta)  # average difference per colour value, 0..255
    cut = SAME_SHOT if same_shot else DIFFERENT_SHOT
    if hd <= cut["hash"] and cd <= cut["colour"]:
        verdict = "REPEAT"
    elif hd <= UNCERTAIN["hash"] and cd <= UNCERTAIN["colour"]:
        verdict = "NOT_ASSESSED"
    else:
        verdict = "DIFFERENT"
    return {"verdict": verdict, "hashDistanceOf64": hd, "colourDifference": cd, "sameKindOfShot": same_shot}


def duplicate_check(images: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pairwise near-duplicate check over the set. Pairs judged different are not listed. Needs two or more images."""
    if len(images) < 2:
        return {"state": "NOT_ASSESSED", "reason": "Needs at least two images.", "pairs": []}
    pairs: list[dict[str, Any]] = []
    for i in range(len(images)):
        for j in range(i + 1, len(images)):
            c = _compare(images[i]["measures"]["fingerprint"], images[j]["measures"]["fingerprint"], images[i]["shotType"] == images[j]["shotType"])
            if c["verdict"] == "DIFFERENT":
                continue
            why = ("The two pictures have almost the same shapes and colours (difference hash distance %d of 64, average colour difference %d of 255)." % (c["hashDistanceOf64"], c["colourDifference"])
                   if c["verdict"] == "REPEAT" else "The two pictures are alike but not alike enough to call a repeat; they may be two views of the same product. Not assessed.")
            pairs.append({"images": [i + 1, j + 1], **c, "reason": why})
    return {"state": "CHECKED", "reason": None, "pairs": pairs}


def set_analysis(images: Sequence[Mapping[str, Any]]) -> tuple[int, int | None, list[dict[str, Any]], list[dict[str, Any]], list[tuple[str, str, dict[str, Any]]]]:
    """(coverage %, consistency % or None when fewer than two images, checks, missing-shot advice, set-level findings)."""
    shots = {str(i["shotType"]) for i in images}
    have = set()
    if shots & _ANGLE_TYPES:
        have.add("ANGLE")
    for k in ("DETAIL", "SIZE", "USAGE"):
        if k in shots:
            have.add(k)
    has_front = any(i["role"] == "PRIMARY" or i["shotType"] == "FRONT" for i in images)
    cov = min(100, 20 * (len(have) + (1 if has_front else 0)))
    found: list[tuple[str, str, dict[str, Any]]] = []
    missing: list[dict[str, Any]] = []
    for key, code in (("ANGLE", "MISSING_ANGLE"), ("DETAIL", "MISSING_DETAIL"), ("SIZE", "MISSING_SIZE"), ("USAGE", "MISSING_USAGE")):
        if key not in have:
            problem, why, fix = TEXT[code]
            missing.append({"code": code, "shotType": key, "problem": problem, "whyItMatters": why, "recommendation": fix, "isMarketplaceRequirement": False})
            found.append((code, "LOW", {"shotType": key}))
    if len(images) == 1:
        found.append(("ONLY_ONE_IMAGE", "MEDIUM", {"images": 1}))
    checks: list[dict[str, Any]] = []
    if len(images) >= 2:
        ms = [i["measures"] for i in images]
        asps = [int(m["aspect_x100"]) for m in ms]
        longs = [int(m["long_side"]) for m in ms]
        checks.append({"key": "aspect", "passed": max(asps) - min(asps) <= 20, "detail": {"minX100": min(asps), "maxX100": max(asps)}, "code": "INCONSISTENT_ASPECT"})
        checks.append({"key": "resolution", "passed": min(longs) * 100 >= 50 * max(longs), "detail": {"minLongSidePx": min(longs), "maxLongSidePx": max(longs)}, "code": "INCONSISTENT_RESOLUTION"})
        plain_ms = [m for m in ms if m["plain_background"]]
        if len(plain_ms) >= 2:
            lumas = [int(m["mean_luma"]) for m in plain_ms]
            checks.append({"key": "lighting", "passed": max(lumas) - min(lumas) <= 60, "detail": {"minBrightness": min(lumas), "maxBrightness": max(lumas)}, "code": "INCONSISTENT_LIGHTING"})
            cols = [m["border_color"] for m in plain_ms]
            spread = max(max(c[k] for c in cols) - min(c[k] for c in cols) for k in range(3))
            checks.append({"key": "background", "passed": spread <= 30, "detail": {"colourSpread": spread}, "code": "INCONSISTENT_BACKGROUND"})
        for c in checks:
            if not c["passed"]:
                found.append((c["code"], "MEDIUM" if c["key"] in ("aspect", "resolution") else "LOW", c["detail"]))
    cons = None if not checks else 100 * sum(1 for c in checks if c["passed"]) // len(checks)
    return cov, cons, checks, missing, found


def review(images: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """`images`: ordered dicts {id, role, shotType, measures}. Deterministic: the same input gives the same report."""
    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for n, img in enumerate(images, start=1):
        pct, why_not, found = score_image(img["measures"], img["role"], img["shotType"])
        m = img["measures"]
        rows.append({"imageNumber": n, "imageId": img["id"], "role": img["role"], "shotType": img["shotType"], "widthPx": int(m["width"]), "heightPx": int(m["height"]),
                     "dimensions": pct, "notAssessed": why_not, "overlayCheck": m["overlay"], "overlayCheckConfidence": "LOW"})
        findings += [_finding(c, s, e, number=n, image_id=img["id"], role=img["role"], shot=img["shotType"]) for c, s, e in found]
    prim = [r for r in rows if r["role"] == "PRIMARY"]
    sec = [r for r in rows if r["role"] == "SECONDARY"]
    cov, cons, checks, missing, set_found = set_analysis(images) if images else (0, None, [], [], [])
    dup = duplicate_check(images)
    for p in dup["pairs"]:
        if p["verdict"] == "REPEAT":
            set_found.append(("REPEATED_IMAGE", "LOW", {"images": p["images"], "hashDistanceOf64": p["hashDistanceOf64"], "colourDifference": p["colourDifference"]}))
    findings += [_finding(c, s, e) for c, s, e in set_found]
    if not prim:
        findings.append(_finding("NO_PRIMARY", "HIGH", {}))
    dims: list[dict[str, Any]] = []
    earned_total = assessable_total = 0
    for key, label, mx in DIMENSIONS:
        if key == "set":
            if not images:
                dims.append({"key": key, "label": label, "max": mx, "state": "NOT_ASSESSED", "earned": None, "assessableMax": 0, "percent": None, "reason": "No images."})
                continue
            earned = 8 * cov // 100 + (7 * cons // 100 if cons is not None else 0)
            assess = 15 if cons is not None else 8
            dims.append({"key": key, "label": label, "max": mx, "state": "ASSESSED" if cons is not None else "PARTIAL", "earned": earned, "assessableMax": assess, "percent": earned * 100 // assess,
                         "reason": None if cons is not None else "Consistency needs at least two images; only coverage (8 of 15 points) was assessed.", "checks": checks})
            earned_total, assessable_total = earned_total + earned, assessable_total + assess
            continue
        p = prim[0]["dimensions"].get(key) if prim else None
        secs = [r["dimensions"][key] for r in sec if r["dimensions"].get(key) is not None]
        if p is None:
            reason = (prim[0]["notAssessed"].get(key) if prim else "There is no main image.") or "Could not be measured."
            dims.append({"key": key, "label": label, "max": mx, "state": "NOT_ASSESSED", "earned": None, "assessableMax": 0, "percent": None, "reason": reason})
            continue
        sp = (p * 60 + (sum(secs) // len(secs)) * 40) // 100 if secs else p
        e = mx * sp // 100
        dims.append({"key": key, "label": label, "max": mx, "state": "ASSESSED", "earned": e, "assessableMax": mx, "percent": sp, "reason": None})
        earned_total, assessable_total = earned_total + e, assessable_total + mx
    complete = bool(prim) and all(d["state"] == "ASSESSED" for d in dims)
    state = "COMPLETE" if complete else "PARTIAL" if prim else "NOT_CALCULABLE"
    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], 0 if f["role"] == "PRIMARY" else 1 if f["imageNumber"] else 2, f["imageNumber"] or 99, f["code"]))
    return {
        "method": METHOD_VERSION, "scoreState": state, "score": earned_total if complete else None, "maxScore": 100,
        "pointsEarned": earned_total if images else None, "pointsAssessable": assessable_total if images else None,
        "dimensions": dims, "images": rows, "findings": findings, "missingShots": missing, "duplicateCheck": dup,
        "notes": ["This is image quality, not marketplace compliance and not listing readiness.",
                  "Measurements are made by fixed image-processing rules; no AI model looked at the pictures and nothing was guessed about the product.",
                  "The text, logo and watermark check is a rough low-confidence heuristic; it cannot read text.",
                  "Recommendations are advice, not marketplace requirements."],
    }


# ---- marketplace requirements: only verified official rules, never invented -------------------------------------------------------------------------------
IMAGE_RULE_FIELDS = ("image.min_long_side_px", "image.main.min_long_side_px", "image.min_count", "image.max_count")
NOT_ASSESSED_NOTE = "Background colour, aspect ratio, file size, overlay and text rules, and category-specific image rules are NOT_ASSESSED: no verified official rule for them is recorded."


def _verified_image_rules(register: Mapping[str, Any], marketplace: str, today: date, max_age_days: int | None) -> dict[str, Mapping[str, Any]]:
    hosts = {str(h) for h in register.get("official_hosts", [])}
    verified: dict[str, Mapping[str, Any]] = {}
    for r in register.get("rules", []):
        field = str(r.get("field", ""))
        if r.get("marketplace") != marketplace or field not in IMAGE_RULE_FIELDS or r.get("status") != "OFFICIAL_VERIFIED" or "ALL_CATEGORIES" not in str(r.get("scope", "")):
            continue
        url = str((r.get("source") or {}).get("url", ""))
        parts = url.split("/")
        host = parts[2] if url.startswith("https://") and len(parts) > 2 else ""
        try:
            age = (today - date.fromisoformat(str(r.get("checked_on")))).days
        except ValueError:
            continue
        if host in hosts and isinstance(r.get("value"), int) and not isinstance(r.get("value"), bool) and (max_age_days is None or age <= max_age_days):
            verified[field] = r
    return verified


def compliance(register: Mapping[str, Any], marketplace: str, images: Sequence[Mapping[str, Any]], *, today: date, max_age_days: int | None) -> dict[str, Any]:
    """Compares the images with the OFFICIAL_VERIFIED image rules for this marketplace in the rules register (scope ALL_CATEGORIES, https source on an official host, not older than the configured age).
    With no such rule the answer is NOT_ASSESSED. It never says 'compliant': passing a listed check only means that check passed."""
    verified = _verified_image_rules(register, marketplace, today, max_age_days)
    if not verified:
        return {"status": "NOT_ASSESSED", "marketplace": marketplace, "checks": [], "notAssessed": NOT_ASSESSED_NOTE,
                "message": "No verified official image rule is recorded for this marketplace, so nothing is checked against marketplace requirements."}
    checks: list[dict[str, Any]] = []
    for field, r in sorted(verified.items()):
        src = {"url": r["source"]["url"], "checkedOn": r["checked_on"], "scope": r["scope"], "value": r["value"]}
        if field in ("image.min_long_side_px", "image.main.min_long_side_px"):
            for n, img in enumerate(images, start=1):
                if field == "image.main.min_long_side_px" and img["role"] != "PRIMARY":
                    continue
                ok = int(img["measures"]["long_side"]) >= int(r["value"])
                checks.append({"rule": field, "imageNumber": n, "result": "PASS" if ok else "FAIL", "measuredLongSidePx": int(img["measures"]["long_side"]), "source": src})
        elif field == "image.min_count":
            checks.append({"rule": field, "result": "PASS" if len(images) >= int(r["value"]) else "FAIL", "measuredCount": len(images), "source": src})
        else:
            checks.append({"rule": field, "result": "PASS" if len(images) <= int(r["value"]) else "FAIL", "measuredCount": len(images), "source": src})
    failed = any(c["result"] == "FAIL" for c in checks)
    return {"status": "CHECKED_FAILED" if failed else "CHECKED_PASSED", "marketplace": marketplace, "checks": checks, "notAssessed": NOT_ASSESSED_NOTE,
            "message": "Only the verified rules listed here were checked. This is not a statement that the images meet every marketplace requirement."}
