"""CMO 3.0 M8 in the CEO chat: "how are my listings performing?", "which listing has the lowest CTR?", "what changed after I updated my title?", "connect SKU AQ-1 to my bottle", "version 2 went live on 3 October",
"what performance data is missing?" (docs/specs/ceo-cmo-delegation.md section 6.18). Free: no model, no AI credit, nothing generated.

Every figure comes from `services.cmo_perf_view` (the seller's own imported reports, deterministic). The CEO only works out WHICH product, marketplace, version or date the seller means, asks ONE short question
when the words leave that open, and says the stored answer in plain words. A statement the seller makes here (a SKU link, a go-live date, a comparison length) is shown back as a card with a Save button that
calls the same route as the performance page; typing "yes" never saves anything. Nothing is published or edited."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from slim_cmo.history import metrics as mx
from slim_cmo.history import report_import

logger = logging.getLogger(__name__)
KIND = "LISTING_PERFORMANCE"
MP_NAME = {"AMAZON": "Amazon", "FLIPKART": "Flipkart", "MEESHO": "Meesho"}
MARKETPLACES = {"amazon": "AMAZON", "flipkart": "FLIPKART", "meesho": "MEESHO"}
PAGE = "/dashboard/cmo/performance"
FAILED = "I could not read your performance data just now. Nothing was changed. Please try again."
NO_LISTING = "You do not have a saved listing yet, so there is nothing to attach performance to. Ask me to “write my complete listing” first."
NO_DATA = ("You have not imported a performance report yet, so I have no impressions, clicks or orders to show. Upload a CSV or Excel report on the performance page"
           f" ({PAGE}); it needs a Date column, a SKU column and at least one of Impressions, Clicks, Orders, Units Sold or Sales. Nothing is estimated in its place.")
_FOLD = lambda t: " ".join(re.sub(r"[?!.,;\"“”']", " ", t.casefold()).split())  # noqa: E731

OVERVIEW, RANK, IMPROVE, VERSIONS, MISSING, GOLIVE, LINK, WINDOW, IMPORT, CORRECT = "OVERVIEW", "RANK", "IMPROVE", "VERSIONS", "MISSING", "GOLIVE", "LINK", "WINDOW", "IMPORT", "CORRECT"
_PERF = r"(?:perform\w*|ctr|click[- ]?through|conversion\w*|impressions?|clicks?|orders?|sales|revenue|traffic)"
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (CORRECT, re.compile(r"\b(?:correct|fix|change|edit|undo|redo)\b.{0,30}\b(?:imported|uploaded)\b.{0,25}\b(?:record|records|row|rows|number|numbers|data|value|values|figures?)\b|\bi (?:imported|uploaded)\b.{0,30}\b(?:wrong|incorrect|bad|mistake)\b|\b(?:show|list|see)\b.{0,15}\b(?:my )?corrections\b|\bwhat corrections\b")),
    (GOLIVE, re.compile(r"\bgo(?:es|ne)?[- ]live\b|\bwent live\b|\b(?:is|was|been) live (?:on|since|from)\b|\bconfirm\b.*\b(?:live|published)\b|\b(?:i )?(?:put|made|set)\b.*\blive\b|\bpublished (?:it |this |the |my )?(?:listing|version|title)?\s*on\b")),
    (LINK, re.compile(r"\b(?:connect|link|map|match|attach|confirm)\b.{0,40}\bsku\b|\bsku\b.{0,40}\b(?:to|is|means|for)\b.{0,30}\b(?:product|listing|bottle|item)\b|\bwhich sku\b")),
    (WINDOW, re.compile(r"\b(?:compare|comparison|compar\w+|window|period)\b.{0,40}\b(\d{1,3})\s*days?\b|\b(\d{1,3})[- ]days? (?:window|period|comparison)\b")),
    (MISSING, re.compile(r"\b(?:what|which)\b.{0,30}\b(?:performance )?(?:data|information|details)\b.{0,25}\b(?:missing|need|required|lacking)\b|\bwhat (?:else )?do you need\b.{0,30}\b(?:performance|compare)\b|\bperformance data\b.{0,20}\bmissing\b")),
    (IMPROVE, re.compile(r"\bwhich (?:listing|product)\b.{0,25}\b(?:improve|fix|optimi[sz]e|work on)\b.{0,15}\bfirst\b|\bimprove first\b|\bwhat should i improve first\b")),
    (RANK, re.compile(rf"\bwhich (?:listing|product)\b.{{0,30}}\b(?:lowest|worst|weakest|highest|best|top)\b.{{0,15}}\b(?:ctr|click[- ]?through|conversion\w*)\b|\b(?:lowest|worst|weakest) (?:ctr|click[- ]?through|conversion\w*)\b")),
    (VERSIONS, re.compile(rf"\bwhat changed after\b.{{0,30}}\b(?:updat\w+|chang\w+|edit\w+|rewr\w+|revis\w+)\b|\bafter (?:i|we) (?:updat\w+|chang\w+|edit\w+|rewr\w+|revis\w+)\b.{{0,30}}\b(?:title|listing|bullets?|description|version)\b"
                          rf"|\b(?:compare|comparison)\b.{{0,40}}\bversion\w*\b.{{0,60}}\b{_PERF}\b|\b{_PERF}\b.{{0,40}}\b(?:before|after)\b.{{0,40}}\b(?:version|listing|update|change)\w*\b|\bversion\w*\b.{{0,40}}\b{_PERF}\b")),
    (IMPORT, re.compile(r"\b(?:import|upload|add)\b.{0,30}\b(?:performance|traffic|sales|business|ads?)\b.{0,15}\breport\b|\bhow (?:do i|can i|to)\b.{0,15}\b(?:import|upload)\b.{0,30}\breport\b")),
    (OVERVIEW, re.compile(rf"\bhow (?:are|is) my (?:listings?|products?|sales|ctr|conversion)\b.{{0,25}}\b(?:perform\w*|doing)\b|\b(?:listing|product) performance\b|\bsales and conversion\b|\b(?:conversion|sales|ctr|impressions?|clicks?|orders?) trends?\b"
                          rf"|\bsummari[sz]e\b.{{0,30}}\b(?:perform\w*|sales|listing)\b|\bshow my (?:ctr|conversion|impressions?|clicks?|orders|sales|revenue|performance)\b|\bperformance (?:this|last) (?:month|week|quarter)\b|\bhow (?:is|are) my {_PERF}\b")),
)


def classify(text: str) -> str | None:
    t = _FOLD(text or "")
    if not t or len(t) > 400:
        return None
    return next((k for k, rx in _RULES if rx.search(t)), None)


# ------------------------------------------------------------------------------------------------ small readers
def _prior(tenant: UUID, investigation_id: UUID) -> dict[str, Any] | None:
    from backend.repositories import investigation_repo as inv_repo  # noqa: PLC0415

    try:
        for m in reversed(inv_repo.list_messages(tenant, investigation_id)):
            if m["role"] != "CEO":
                continue
            c = m.get("choices")
            return c if isinstance(c, dict) and c.get("kind") == KIND else None
    except Exception:  # noqa: BLE001
        logger.exception("could not read the conversation for performance context")
    return None


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.casefold()))


def _products(mappings: Mapping[str, Any]) -> dict[str, str]:
    return {i["sku"]: i["product"] for i in mappings["items"]}


def _find_product(text: str, names: Mapping[str, str]) -> list[str]:
    """The saved products the message names ('my AquaNest bottle' names 'AquaNest steel bottle' when “AquaNest” belongs to that product alone)."""
    t = _words(text)
    drop = {"my", "our", "the", "a", "an", "of", "for"}
    toks = {s: _words(n) - drop for s, n in names.items()}
    seen: dict[str, int] = {}
    for ws in toks.values():
        for w in ws:
            seen[w] = seen.get(w, 0) + 1
    return [s for s, ws in toks.items() if any(seen[w] == 1 and w in t for w in ws)]  # a word that belongs to exactly one product's name names that product; shared words (“bottle”) name none


def _mp_in(text: str) -> str | None:
    t = text.casefold()
    return next((v for k, v in MARKETPLACES.items() if re.search(rf"\b{k}\b", t)), None)


def _card(view: str, **kw: Any) -> dict[str, Any]:
    return {"version": 1, "kind": KIND, "view": view, "page": PAGE, "aiCredits": 0, **kw}


def _clarify(question: str, ask: Mapping[str, Any], options: Sequence[Mapping[str, Any]]) -> tuple[str, dict[str, Any]]:
    return question, _card("CLARIFY", question=question, options=list(options), ask=dict(ask))


def _parse_when(text: str, today: date) -> date | None:
    t = _FOLD(text)
    if re.search(r"\byesterday\b", t):
        return today - timedelta(days=1)
    if re.search(r"\btoday\b", t):
        return today
    if (m := re.search(r"\b(\d{1,3}) days? ago\b", t)):
        return today - timedelta(days=int(m[1]))
    if (m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b|\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b", text)):
        return report_import.parse_date(m[1] or m[2])
    if (m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:,? (\d{4}))?\b", t)):
        mon = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec").index(m[2]) + 1
        try:
            d = date(int(m[3]) if m[3] else today.year, mon, int(m[1]))
        except ValueError:
            return None
        return d if m[3] or d <= today else date(d.year - 1, d.month, d.day)
    return None


def _version_in(text: str, versions: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    t = _FOLD(text)
    if (m := re.search(r"\b(?:version|v|revision)\s*#?\s*(\d{1,3})\b", t)):
        return next((v for v in versions if v["number"] == int(m[1])), None)
    if re.search(r"\b(?:original|first)\b", t):
        return versions[0]
    if re.search(r"\b(?:latest|newest|current|last|new|this|updated|revised|rewritten)\b", t) or len(versions) == 1:
        return versions[-1]
    return None


# ------------------------------------------------------------------------------------------------ the entry point
def reply(ctx: Any, text: str, investigation_id: UUID) -> tuple[str, dict[str, Any]] | None:
    """A code-written answer for a performance request, or None when the message is not one (it then goes on to the rest of the CEO unchanged)."""
    from backend.services import cmo_perf_view, cmo_performance, cmo_runtime  # noqa: PLC0415

    tenant = ctx.tenant_id
    prior = _prior(tenant, investigation_id)
    pending = prior.get("ask") if isinstance(prior, dict) and prior.get("view") == "CLARIFY" and isinstance(prior.get("ask"), dict) else None
    kind = classify(text)
    if kind is None and pending is not None and len(_FOLD(text).split()) <= 8:
        kind = pending.get("kind")  # a short answer to the question I just asked
    if kind is None:
        return None
    try:
        today = cmo_runtime.build_runtime().clock().date()
        return _answer(ctx, tenant, kind, text, prior if isinstance(prior, dict) else None, pending, today, cmo_perf_view, cmo_performance)
    except cmo_performance.PerformanceRefused as exc:
        return exc.detail, _card("REFUSED", message=exc.detail, code=exc.code)
    except Exception:  # noqa: BLE001
        logger.exception("performance request failed")
        return FAILED, _card("REFUSED", message=FAILED, code="FAILED")


def _answer(ctx: Any, tenant: UUID, kind: str, text: str, prior: Mapping[str, Any] | None, pending: Mapping[str, Any] | None, today: date, view: Any, perf: Any) -> tuple[str, dict[str, Any]]:
    maps = view.mappings(tenant)
    names = _products(maps)
    scope_sku = (pending or {}).get("sku") or (prior or {}).get("sku")
    if kind == CORRECT:
        from backend.services import cmo_perf_correction  # noqa: PLC0415

        recent = cmo_perf_correction.history(tenant, marketplace=None, report_sku=None, limit=3)["corrections"]
        tail = (" Your latest corrections: " + " | ".join(f"{c['at'].date().isoformat()} {MP_NAME.get(c['marketplace'], c['marketplace'])} {c['reportSku']} {c['date']} ({', '.join(c['changed'])}; reason: {c['reason']})" for c in recent) + ".") if recent else " You have not made any corrections yet."
        return ("I do not change imported numbers from chat. On the performance page, open “Correct an imported record”, find the record, enter the right value and your reason, and press Save. "
                "The imported value is kept for good and shown beside the corrected one, and your numbers then use the corrected value. A blank stays “not reported”, never zero." + tail), \
            _card("CORRECTION_HELP", message="Corrections are made on the performance page with a reason and an explicit Save. Nothing is changed from chat." + tail)
    if kind == IMPORT:
        return ("To import a performance report: open the performance page, choose the marketplace, and pick your CSV or Excel file. You will see exactly what would be saved before anything is. "
                "Rows are only added; the same file or an existing record is never imported twice, and a blank cell stays blank."), _card("IMPORT_HELP")
    if kind == WINDOW:
        m = re.search(r"\b(\d{1,3})\s*[- ]?days?\b", _FOLD(text))
        if m is None:
            return _clarify("How many days should each comparison period be? Choose a number from 7 to 90.", {"kind": WINDOW}, [{"label": f"{n} days", "days": n} for n in (7, 14, 28)])
        n = int(m[1])
        if not perf.MIN_WINDOW <= n <= perf.MAX_WINDOW:
            return f"A comparison period must be {perf.MIN_WINDOW} to {perf.MAX_WINDOW} days. Which length do you want?", _card("REFUSED", message="window out of range", code="BAD_WINDOW")
        cur = maps["windowDays"]
        line = f"Compare listing versions over {n}-day periods" + (f" (it is {cur} days now; the earlier choice stays in your history)." if cur and cur != n else ".")
        return line + " Press Save to confirm.", _card("CONFIRM_WINDOW", proposal={"days": n}, current=cur)
    if kind == MISSING:
        have = maps["hasImports"]
        lines = ([] if have else ["a performance report imported (impressions, clicks, orders, units or sales)"]) + list(maps["missing"])
        if not names:
            return NO_LISTING, _card("MISSING", missing=lines)
        if not lines:
            return "Nothing is missing: your reports are imported, every product has a confirmed SKU and every version a go-live date.", _card("MISSING", missing=[])
        return "To assess performance I still need:\n" + "\n".join(f"• {x}" for x in lines[:8]), _card("MISSING", missing=lines, mappings=maps["items"])
    if kind in (OVERVIEW, RANK, IMPROVE) and not maps["hasImports"]:
        return NO_DATA, _card("NO_DATA")
    if kind == OVERVIEW:
        found = _find_product(text, names)
        sku = found[0] if len(found) == 1 else (scope_sku if scope_sku in names and not found else None)
        if len(found) > 1:
            return _clarify("Which product do you mean?", {"kind": kind}, [{"label": names[s], "sku": s} for s in found])
        mp = _mp_in(text)
        d = view.dashboard(tenant, marketplace=mp, sku=sku, start=None, end=None)
        m, comp = d["current"]["metrics"], d["comparison"]
        tiles = [{"key": k, "label": mx.LABEL[k], "value": mx.fmt(k, m[k]["value"]), "change": mx.describe_change(k, comp[k])} for k in (*mx.COUNTS, *mx.RATES) if m[k]["state"] == mx.AVAILABLE]
        not_shown = [mx.LABEL[k].lower() for k in (*mx.COUNTS, *mx.RATES) if m[k]["state"] != mx.AVAILABLE]
        return _overview_text(d, names.get(sku or "", None)), _card("OVERVIEW", dashboard={k: v for k, v in d.items() if k not in ("trend", "imports", "products")}, sku=sku, tiles=tiles, notShown=not_shown,
                                                                  period={"start": d["current"]["periodStart"], "end": d["current"]["periodEnd"], "covered": d["current"]["coveredDays"], "days": d["current"]["days"], "source": d["source"]})
    if kind in (RANK, IMPROVE):
        metric = "cvr" if re.search(r"conversion", _FOLD(text)) else "ctr"
        r = view.ranking(tenant, metric)
        if not r["ranked"]:
            why = (r["notAssessed"][0]["reason"] if r["notAssessed"] else "no listing has a confirmed SKU link yet")
            return f"I cannot rank your listings by {r['label'].lower()} yet: {why}", _card("RANK", ranking=r)
        top = r["ranked"][0]
        listing = f"{top['product']} on {MP_NAME.get(top['marketplace'], top['marketplace'])}"
        body = f"Lowest {r['label'].lower()} among your listings, {r['periodStart']} to {r['periodEnd']}: " + "; ".join(
            f"{x['product']} ({MP_NAME.get(x['marketplace'], x['marketplace'])}) {x['text']}" for x in r["ranked"][:5]) + "."
        if r["notAssessed"]:
            body += f" Not assessed: {', '.join(x['product'] for x in r['notAssessed'][:4])} (incomplete or missing data)."
        action = mx.ACTIONS["TITLE" if metric == "ctr" else "CONTENT"]
        if kind == IMPROVE:
            body = (f"By your own imported reports, {listing} has the lowest {r['label'].lower()} ({top['text']}) over {r['periodStart']} to {r['periodEnd']}, so I would look at it first: {action['label'].lower()}. "
                    "That ranks your listings against each other only; it does not show what would raise it, and nothing is guaranteed.")
        return body + " " + r["note"], _card("RANK", ranking=r, action=action)
    # the rest need ONE saved listing
    if not names:
        return NO_LISTING, _card("NO_LISTING")
    found = _find_product(text, names)
    sku = found[0] if len(found) == 1 else (scope_sku if scope_sku in names and not found else (next(iter(names)) if len(names) == 1 and not found else None))
    ask = {"kind": kind, "sku": sku}
    if sku is None:
        opts = [{"label": names[s], "sku": s} for s in (found or list(names))[:6]]
        return _clarify("Which product do you mean? " + "; ".join(f"“{o['label']}”" for o in opts) + ".", ask, opts)
    mps = sorted({i["marketplace"] for i in maps["items"] if i["sku"] == sku})
    carried = (pending or {}).get("marketplace") or (prior or {}).get("marketplace")
    mp = _mp_in(text) or (carried if carried in mps else None) or (mps[0] if len(mps) == 1 else None)
    if mp is None:
        return _clarify("Which marketplace — " + " or ".join(MP_NAME.get(m, m) for m in mps) + "?", ask, [{"label": MP_NAME.get(m, m), "marketplace": m} for m in mps])
    if mp not in mps:
        return f"You have no saved {MP_NAME.get(mp, mp)} listing for {names[sku]}.", _card("REFUSED", message="no listing", code="NO_LISTING")
    ask = {**ask, "marketplace": mp}
    item = next(i for i in maps["items"] if i["sku"] == sku and i["marketplace"] == mp)
    if kind == LINK:
        return _link(tenant, text, item, ask, pending, perf)
    if kind == GOLIVE:
        return _golive(text, item, ask, pending, today)
    v = view.versions(tenant, sku, mp)
    return _versions_text(v, text), _card("VERSIONS", sku=sku, marketplace=mp, analysis=v)


# ------------------------------------------------------------------------------------------------ the words
def _overview_text(d: Mapping[str, Any], product: str | None) -> str:
    cur, comp = d["current"], d["comparison"]
    who = product or "your listings"
    if d["needs"]:
        return f"I cannot show performance for {who} yet: I need {d['needs'][0]}."
    parts = [f"{mx.LABEL[m]} {mx.fmt(m, cur['metrics'][m]['value'])}" for m in (*mx.COUNTS, *mx.RATES) if cur["metrics"][m]["state"] == mx.AVAILABLE]
    head = f"{product or 'Your listings'}, {cur['periodStart']} to {cur['periodEnd']} (from your imported reports): "
    if not parts:
        why = next((cur["metrics"][m]["reason"] for m in mx.COUNTS if cur["metrics"][m]["reason"]), "no figures are available")
        return head + "no figure can be shown yet. " + why
    out = [head + "; ".join(parts) + "."]
    seen = [mx.sentence(m, comp[m], "than in the previous period") for m in ("impressions", "clicks", "orders", "ctr", "cvr") if comp[m]["state"] == mx.AVAILABLE]
    if seen:
        out.append(" ".join(seen[:4]))
    elif d["limits"]:
        out.append(d["limits"][0])
    first = d["insights"][0] if d["insights"] else None
    if first and first["kind"] != "INSUFFICIENT_DATA":
        out.append(f"{first['what']} {first['nextStep']}")
    out.append(mx.NEVER_CAUSE)
    return "\n".join(out)


def _versions_text(v: Mapping[str, Any], text: str) -> str:
    rows = v["versions"]
    if not rows:
        return "This listing has no saved versions."
    ok = [r for r in rows if r["state"] == "OBSERVED_COMPARABLE"]
    pick = _version_in(text, rows) or (ok[-1] if ok else rows[-1])
    if pick and pick["state"] == "OBSERVED_COMPARABLE":
        obs = " ".join(pick["observations"][:5])
        what = f" (changed: {str(pick['changedSection']).lower().replace('_', ' ')})" if pick.get("changedSection") else ""
        return (f"Version {pick['number']}{what}, which you said went live on {pick['wentLiveOn']}, over {v['windowDays']}-day periods before and after: {obs} {pick['note']}")
    if pick and pick["state"] == "INCOMPARABLE":
        return f"I cannot compare the periods around version {pick['number']}: {pick.get('note', 'they overlap another version.')}"
    needs = list(dict.fromkeys([*v["needs"], *((pick or {}).get("needs") or [n for r in rows for n in r["needs"]][:3])]))
    return "I cannot show what happened around this listing's versions yet. I need: " + "; ".join(needs[:4]) + "."


def _link(tenant: UUID, text: str, item: Mapping[str, Any], ask: Mapping[str, Any], pending: Mapping[str, Any] | None, perf: Any) -> tuple[str, dict[str, Any]]:
    cands = perf.sku_candidates(tenant, item["marketplace"])["candidates"]
    mk = {c["reportSku"].casefold(): c["reportSku"] for c in cands}
    toks = re.findall(r"[A-Za-z0-9][\w\-./]*", text)
    token = next((mk[t.casefold()] for t in toks if t.casefold() in mk), None)
    if token is None:
        if not cands:
            return "I cannot see any SKU in your uploaded reports for that marketplace yet, so there is nothing to connect. Import a report first.", _card("NO_DATA")
        return _clarify(f"Which SKU in your reports is {item['product']} on {MP_NAME.get(item['marketplace'])}? I will not guess.", ask, [{"label": c["reportSku"], "reportSku": c["reportSku"]} for c in cands[:8]])
    prev = item["reportSku"]
    line = f"Connect {item['product']} on {MP_NAME.get(item['marketplace'])} to the SKU “{token}” in your reports" + (f", replacing “{prev}” (the earlier statement stays in your history)." if prev and prev != token else ".")
    return line + " Press Save to confirm.", _card("CONFIRM_LINK", proposal={"sku": item["sku"], "marketplace": item["marketplace"], "reportSku": token}, replaces=prev if prev and prev != token else None, product=item["product"])


def _golive(text: str, item: Mapping[str, Any], ask: Mapping[str, Any], pending: Mapping[str, Any] | None, today: date) -> tuple[str, dict[str, Any]]:
    vs = item["versions"]
    num = (pending or {}).get("version")
    chosen = next((v for v in vs if v["number"] == num), None) if num else _version_in(text, [{"number": v["number"], **v} for v in vs])
    if chosen is None:
        return _clarify(f"Which version of {item['product']} do you mean?", ask, [{"label": f"Version {v['number']} ({v['createdAt']})", "version": v["number"]} for v in vs[-6:]])
    when = _parse_when(text, today)
    ask = {**ask, "version": chosen["number"]}
    if when is None:
        return _clarify(f"On what date did version {chosen['number']} of {item['product']} go live on {MP_NAME.get(item['marketplace'])}? Metrion cannot see the marketplace, so I need your date.", ask, [])
    if when > today:
        return "A go-live date cannot be in the future. Which date did it really go live?", _clarify("Which date did it really go live?", ask, [])[1]
    if when.isoformat() < chosen["createdAt"]:
        return (f"Version {chosen['number']} was created on {chosen['createdAt']}, so it cannot have gone live on {when.isoformat()}. Which date did it go live?"), _clarify("Which date did it go live?", ask, [])[1]
    prev = chosen["wentLiveOn"]
    line = f"Record that version {chosen['number']} of {item['product']} went live on {MP_NAME.get(item['marketplace'])} on {when.isoformat()}" + (f", replacing {prev} (the earlier date stays in your history)." if prev and prev != when.isoformat() else ".")
    return line + " Press Save to confirm. Metrion uses the date you give and cannot verify it.", _card(
        "CONFIRM_GOLIVE", proposal={"generationId": chosen["versionId"], "wentLiveOn": when.isoformat(), "number": chosen["number"]}, replaces=prev if prev and prev != when.isoformat() else None, product=item["product"],
        marketplace=item["marketplace"], sku=item["sku"])
