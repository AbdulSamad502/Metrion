"""Greetings and "what can you do?" questions, answered by code (QA diary tests 06, 14, 15, 18, 19).

Neither needs the classifier model: a greeting has no data in it, and the capability list is a fact about this member's catalog (`Capabilities`), not a judgement. Answering them
here means they work when the model is slow or unreachable, and they can never state a number or start a specialist. Nothing here reads seller data or runs an action; every
sentence is fixed text, and the capability lines are chosen from the member's own catalog so the answer cannot promise something that would be refused.
"""

from __future__ import annotations

import re

from backend.ceo.capabilities import NOT_ATTACHED, NOT_ENTITLED, NOT_PERMITTED, PRESENT, Capabilities

_GREETING = re.compile(r"^\W*(?:hi+|hello+|hey+|hiya|namaste|namaskar|good (?:morning|afternoon|evening)|greetings)\b", re.IGNORECASE)
_WELCOME_ASK = re.compile(r"\bwelcome\b.*\bask\b|\bgreet\w*\b", re.IGNORECASE)
_SHORT_GREETING_WORDS = 4  # "hi", "hello there", "hey metrion!": anything longer is a request that merely starts with a greeting and goes to the normal router

_CAPABILITY_Q = re.compile(
    r"\bwhat(?:'s| is| are) metrion\b|\bwhat (?:can|could) (?:i|you) (?:currently |actually )?(?:do|ask|help)\b|\bwhat do you do\b|\bwhat can metrion do\b|"
    r"\b(?:your|the|main|available|current) (?:agents|capabilities|features)\b|\bwhich agents\b|\bhow (?:do|does) (?:i|this|metrion) work\b",
    re.IGNORECASE,
)
# A message that names the seller's own data is a question about it, never "what can you do".
_OWN_DATA = re.compile(r"\b(?:my|our)\b.*\b(?:profit|margin|sales?|revenue|orders?|returns?|reports?|settlements?|competitors? prices?)\b", re.IGNORECASE)

WELCOME_TEXT = (
    "Welcome to Metrion: which part of your business would you like to work on today: your profit and payments, your competitors, product ideas, or your listings?"
)

_AGENTS: tuple[tuple[str, str, str], ...] = (  # code, name, what it is for
    ("CFO", "Finance (CFO)", "turns your uploaded marketplace reports into profit, finds money you are losing, and checks whether you are being paid what you are owed"),
    ("CI", "Competitor Intelligence (CI)", "tracks competitor prices and shows where your price stands"),
    ("PI", "Product Intelligence (PI)", "researches product ideas for a niche and budget"),
    ("CMO", "Marketing (Slim CMO)", "writes listing titles, descriptions, keywords and hashtags"),
)
_STATUS_WORDS = {
    PRESENT: "available in this conversation",
    NOT_ATTACHED: "not attached to this conversation",
    NOT_PERMITTED: "not allowed for your role",
    NOT_ENTITLED: "not on your current plan",
}
_CHAT_ACTIONS: tuple[tuple[str, str], ...] = (  # registry/action key -> what the seller can ask for; listed only when this member's catalog has it
    ("cfo.strategic_briefing", "a finance briefing for a period"), ("cfo.reconcile", "a leak check against your orders"), ("cfo.financial_health", "financial health bands"),
    ("cfo.cash_reconciliation", "whether the marketplace has paid what it owes"), ("gst_lookup", "a provisional GST rate lookup"),
    ("ci.request_price_scenario", "a price scenario against one named competitor"), ("pi.discover", "a product research run (shown to you for approval where it applies)"),
    ("pi.report", "the latest product research report"), ("cmo.generate_title_sets", "listing titles"), ("cmo.generate_description", "a product description"),
    ("cmo.generate_keywords", "search keywords"), ("cmo.generate_bullets", "listing bullet points"), ("cmo.generate_backend_terms", "Amazon backend search terms"),
    ("cmo.generate_listing_copy", "a full listing copy pack"), ("cmo.generate_full_listing", "a complete, audited listing"), ("cmo.rewrite_listing_section", "a rewrite of one bullet or the description of your saved listing"), ("cmo.generate_hashtags", "hashtags"), ("cmo.market_trends", "a market-trends search (with the searches shown first)"),
)
NOT_YET_TEXT = (
    "Not available from chat yet: reading a competitor screenshot (those go on the Competitors page) or an image attached to anything other than a titles or listing-copy request (a product photo attached to such a request is read only after you approve it), "
    "stored-plan approval for work that uses your plan or sends text to an outside service (so those runs start from the agent's own page), starting competitor research, pricing "
    "curves, landed cost and supplier ranking. I only recommend: I never change anything on a marketplace."
)


def is_greeting(text: str) -> bool:
    t = " ".join(text.split())
    if not _GREETING.search(t):
        return False
    return len(re.findall(r"\w+", t)) <= _SHORT_GREETING_WORDS or bool(_WELCOME_ASK.search(t) and not _OWN_DATA.search(t))


def is_capability_question(text: str) -> bool:
    t = " ".join(text.split())
    return bool(_CAPABILITY_Q.search(t)) and not _OWN_DATA.search(t)


def capability_answer(caps: Capabilities) -> str:
    lines = ["Metrion turns the marketplace reports you upload (Amazon, Flipkart, Meesho) into true profit, finds where you are losing money, and recommends what to do next. "
             "I answer from your saved results and I never write to a marketplace.", "", "Agents:"]
    for code, name, purpose in _AGENTS:
        lines.append(f"- {name}: {purpose} ({_STATUS_WORDS.get(caps.agent_status.get(code, NOT_ATTACHED), 'not available')}).")
    can = [label for key, label in _CHAT_ACTIONS if key in caps.allowed_actions]
    lines += ["", "You can ask me from this chat for: " + (", ".join(can) if can else "nothing that runs a specialist right now") +
              "; a business briefing from saved results; and what is saved or missing (for example “where am I losing money?” or “what data are you missing?”).",
              "", NOT_YET_TEXT]
    return "\n".join(lines)
