"""The visual listing preview for the CEO chat (CMO 3.0 M4; docs/specs/slim-cmo-agent.md section 6.16, ceo-cmo-delegation.md section 6.14).

`build_card` assembles ONE card holding every saved title set (the newest per marketplace) with, for every option, both screens (mobile and desktop), its M3 score with the points it rests
on, its marketplace-compliance status, and the truncation analysis, so the seller switches marketplace, title and screen in the browser with no further request and no model call.

* Free: no entitlement check, no reservation, no metered event, no model, no network. Each title set is analysed by the M3 service (zero units, saved once per set and set of facts; a run
  record is written only for a NEW analysis).
* Tenant-scoped everywhere; the investigation is the caller's own. Nothing is sent to a marketplace and nothing is published.
* The product picture is the seller's own photo only: the image attached in THIS conversation that Slim CMO was asked to read. The card carries its id, never its bytes; the browser fetches
  it through the authenticated image route. With no such photo the card says so and shows a neutral placeholder. No picture is ever generated.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from slim_cmo.preview.simulator import METHOD, SIMULATION_NOTICE, TITLE_DISPLAY_RULES_KEY, SourcePolicy, display_rules, set_preview
from slim_cmo.service import marketplace_rules
from slim_cmo.service.marketplace_rules import official_hosts
from slim_cmo.service.models import Actor
from slim_cmo.service.title_analysis import TitleAnalysisService

from backend.repositories import cmo_chat_repo
from backend.services import cmo_actions, cmo_runtime

logger = logging.getLogger(__name__)
MAX_SETS = 3  # one per marketplace
_DETAIL_LABELS = (("brand", "Brand"), ("size", "Size"), ("capacity", "Size"), ("material", "Material"), ("color", "Color"), ("colour", "Color"))
_CONFIG_KEYS = (TITLE_DISPLAY_RULES_KEY, "format_constraint_max_age_days")


def _register_policy() -> SourcePolicy:
    """A display rule is VERIFIED only from an official marketplace host (the hosts named in the rules register) and only for all categories."""
    return SourcePolicy(official_hosts(marketplace_rules.load()))


def configured_display_rules(platform_config: Any) -> Any:
    """The platform configuration row if there is one, else what the reviewed rules register holds (today nothing: no marketplace publishes a title display rule). Either way the simulator re-checks
    source host, scope, date and age; nothing here makes a preview verified by itself."""
    return platform_config if platform_config else (marketplace_rules.display_rules_config(marketplace_rules.load()) or None)


def details_of(ctx: Any) -> dict[str, str]:
    """The important confirmed details the seller would want visible in a title (brand, size, material, colour), from their own claim-eligible facts only."""
    by = {a.name.casefold(): str(a.value) for a in ctx.eligible if a.value}
    out: dict[str, str] = {}
    for key, label in _DETAIL_LABELS:
        if key in by and label not in out:
            out[label] = by[key]
    return out


def _fact_key(ctx: Any) -> str:
    return hashlib.sha256("|".join(sorted(ctx.fact_ids)).encode()).hexdigest()[:12]


def build_card(tenant_id: UUID, user_id: UUID, investigation_id: UUID) -> dict[str, Any] | None:
    """The preview card for the seller's newest saved titles, or None when they have none."""
    sets = cmo_chat_repo.recent_title_sets(tenant_id)[:MAX_SETS]
    if not sets:
        return None
    rt = cmo_runtime.build_runtime()
    kinds = getattr(rt.generation, "accepted_row_kinds", None)
    svc = TitleAnalysisService(rt.store, clock=rt.clock, **({"accepted_row_kinds": kinds} if kinds else {}))
    actor = Actor(tenant_id, user_id)
    principal = cmo_actions.Principal(tenant_id, user_id)
    today: date = rt.clock().date()
    values = rt.store.load_config(tenant_id, _CONFIG_KEYS, today)
    age = values.get("format_constraint_max_age_days")
    out_sets: list[dict[str, Any]] = []
    product: dict[str, str | None] = {"name": None, "brand": None}
    for s in sets:
        gid = UUID(s["generationId"])
        _ts, ctx, name, brand, kw, _themes = svc.context(tenant_id, gid)
        started, run_id = rt.clock(), uuid4()
        analysis = svc.run(actor, gid, f"preview-{gid}-{_fact_key(ctx)}")
        if not analysis["reused"]:
            cmo_actions.record_free_run(principal, rt, "cmo.listing_preview", run_id, started)
        rules = display_rules(configured_display_rules(values.get(TITLE_DISPLAY_RULES_KEY)), s["marketplace"], today=today, max_age_days=age if isinstance(age, int) else None, policy=_register_policy())
        if not product["name"]:
            product = {"name": name, "brand": brand}
        out_sets.append({"marketplace": s["marketplace"], "generationId": s["generationId"], "analysisId": analysis["analysisId"], "recommendedOptionId": analysis["recommendation"].get("optionId"),
                         "recommendation": analysis["recommendation"].get("text"), "options": set_preview(analysis, kw, details_of(ctx), rules)})
    photo = None
    try:
        photo = cmo_chat_repo.photo_attachment(tenant_id, investigation_id)
    except Exception:  # noqa: BLE001 - the picture is optional; the preview is still shown with a placeholder
        logger.exception("could not look up the product photo")
    return {
        "version": 1, "kind": "PREVIEW", "method": METHOD, "notice": SIMULATION_NOTICE, "investigationId": str(investigation_id), "product": product,
        "image": ({"attachmentId": photo["id"], "filename": photo["filename"]} if photo else None),
        "imageNote": (f"Your photo “{photo['filename']}” from this conversation." if photo else "No product photo was attached for this product in this conversation, so a neutral placeholder is shown. Metrion never generates a product picture."),
        "marketplaces": [s["marketplace"] for s in out_sets], "missingMarketplaces": [m for m in ("AMAZON", "FLIPKART", "MEESHO") if m not in {s["marketplace"] for s in out_sets}],
        "sets": out_sets, "defaultMode": "mobile",
        "limits": ["The score is an internal listing-quality assessment, not a marketplace ranking, search position, conversion rate or sales prediction.",
                   "Marketplace compliance is separate from the score and is NOT_ASSESSED unless a verified marketplace rule exists.",
                   "Where the cut-off is marked ILLUSTRATIVE it is a demonstration value, not an official limit."],
    }


_ASK = (
    r"\b(?:show|see|open|give|display|preview)\b[^.?!]{0,30}\b(?:listing|title|titles|search|mobile|desktop)\b[^.?!]{0,20}\bpreview\b|\bpreview\b[^.?!]{0,20}\b(?:of )?(?:my|the|these)\b[^.?!]{0,20}\b(?:listing|titles?|search result)\b|"
    r"\bhow (?:will|would|does|do) (?:my|the|these|this) (?:listing|titles?)\b[^.?!]{0,30}\blook\b|\b(?:mobile|desktop|phone) (?:search )?(?:preview|view)\b|\blisting preview\b|\btitle preview\b"
)


def is_preview_request(text: str) -> bool:
    import re  # noqa: PLC0415

    t = " ".join(text.split())
    return bool(re.search(_ASK, t, re.IGNORECASE)) and not re.search(r"\b(?:write|generate|create|make|draft)\b", t, re.IGNORECASE)


def chat_text(card: dict[str, Any] | None) -> str:
    if card is None:
        return "You have no saved titles to preview yet. Ask me to write titles for a product first, and I will show you how they could look in a search result. Nothing was used up."
    names = ", ".join(m.title() for m in card["marketplaces"])
    missing = card.get("missingMarketplaces") or []
    tail = (" No saved titles exist yet for " + ", ".join(m.title() for m in missing) + "; ask me to write them to preview those too.") if missing else ""
    return ("Here is your listing preview. It is an illustrative simulation of a search result, not the real marketplace page. "
            f"Use the buttons on the card to switch between {names}, between mobile and desktop, and between your saved titles. Nothing is sent again and nothing is used up." + tail)
