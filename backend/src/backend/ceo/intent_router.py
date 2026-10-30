"""Explicit intent-to-action mapping — spec §6.35.

A small, ordered set of plain rules that recognise requests whose meaning is unmistakable ("hashtags for my bottle", "top trending products, my niche is mens shoes").
They run BEFORE the model: they are instant, they are the same every time, and they cannot be talked out of the closed catalog, because the result goes through
`classifier.parse_decision` exactly like a model verdict (a key outside the member's catalog becomes a clarification, never an execution).

The rules choose a route and offer slot TEXT only. Every value is still parsed by the guided input session's own parsers; a rule never supplies a number, never writes
anything, and anything it does not recognise falls through to the model. When the rule's target agent is not in this member's catalog (detached, not on the plan, no
permission) the result is an ADVISORY turn naming the agent, so the seller is told plainly why it cannot run instead of being asked an unrelated question.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from backend.ceo import expense_chat
from backend.ceo.classifier import Catalog, Decision, parse_decision
from backend.ceo.plans import PLAYBOOKS

_MARKETPLACE = re.compile(r"\b(amazon|flipkart|meesho)\b", re.IGNORECASE)
_WRITE = r"(?:write|give|generate|create|make|suggest|need|want|get|draft|find|show)"


# A general "how should I think about..." question has no data in it: it is answered as general guidance (ADVISORY), never turned into a request for a marketplace or period.
_GENERAL_ASK = re.compile(r"^\W*(?:tell me about\b|what makes (?:a|an|the) (?:good|great|best|effective)\b|how (?:should|do|can|would|could) (?:i|we)\b|what(?:'s| is) the best way to\b|any tips\b|tips (?:for|on)\b|explain\b|why is it important\b|what should i (?:think|know) about\b)", re.IGNORECASE)
_DATA_WORDS = re.compile(r"\b(?:my|our|mine)\b.*\b(?:profit|margin|sales?|revenue|orders?|returns?|data|reports?|stock|inventory|costs?|competitors?|settlements?|gst|skus?)\b|\b(?:september|october|august|july|june|last month|this month|last week|today|yesterday)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Rule:
    key: str
    agent: str
    pattern: re.Pattern[str]
    kind: str = "ACTION"  # a decision playbook is routed the same way (spec 6.36)
    addons: tuple[str, ...] = ()  # need keys the matching request also asks for (spec agent-needs 5.3)
    flags: tuple[str, ...] = ()  # decision flags this rule adds (for example EXPENSE_MENTION)


# Common misspellings of the CMO keywords are accepted; the wording is only used to pick a route, every value is still parsed by the session's own parsers.
_DESC = r"(?:descriptions?|discriptions?|descriptons?|descriptoins?|descrip\w*|desc)"
_BULLETS = r"(?:bullet[- ]?points?|bulletpoints?|bullets?|bulet\w*)"
_TITLES = r"(?:titles?|titels?|tittles?)"
_KEYWORDS = r"(?:key ?words?|keyowrds?|keywrds?)"
_HASHTAGS = r"(?:hash ?tags?|hastags?|hashtgs?)"


def _rx(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


# Business Q&A (spec agent-needs-and-shared-knowledge.md section 7.2): a plain question about the seller's own saved results routes to its QUESTION TYPE
# (`question_types`), a closed id the Business State read expands to a fixed list of entries. These come FIRST because their wording ("what product ideas
# did you FIND", "what titles did we WRITE") would otherwise match the verbs of the work rules below and start a new, possibly metered, run. They are question
# phrasings about what is already saved (past tense, "my ...", "where am I ..."); a request to DO the work still falls through to the rules below.
_NOT_A_WHY = r"^(?!.*\b(?:why|drop|dropped|fall|fell|declin\w*|decreas\w*|increas\w*|improv\w*|compar\w*)\b)"
STATE_RULES: tuple[Rule, ...] = (
    Rule("QT_PROFIT_BY_PERIOD", "CFO", _rx(
        _NOT_A_WHY + r".*(?:\b(?:what|how much)\b.*\b(?:profit|revenue|earnings|income)\b|\b(?:my|our) (?:profit|revenue|earnings|income)\b|\b(?:my|our) (?:latest |recent |last |current )?(?:p&l|pnl|profit (?:and|&) loss)\b|\bhow much (?:did i|have i|did we) (?:make|made|earn|earned)\b)"), "BUSINESS_STATE"),
    Rule("QT_LEAKS", "CFO", _rx(
        r"\bwhere (?:am i|are we) (?:losing|leaking|bleeding)\b|\b(?:losing|leaking) money\b|\b(?:my|our|open) (?:leaks?|leak findings?)\b|\bwhat(?:'s| is| are) (?:my )?leaks?\b"
        r"|\b(?:investigate|identify|find|review|analy[sz]e|check)\b.*\b(?:losing|leaking|leaks?)\b|\bprofit leaks?\b"), "BUSINESS_STATE"),
    Rule("QT_DATA_GAPS", "CFO", _rx(
        r"\bwhat (?:data|inputs?|information|reports?|details?) (?:are you|is|do you) (?:still )?(?:missing|need|needed|required)\b|\bwhat (?:are you|do you) (?:still )?(?:missing|need)\b|\bwhat(?:'s| is) missing\b|\bdata gaps?\b"), "BUSINESS_STATE"),
    Rule("QT_COMPETITORS_PRICES", "CI", _rx(
        r"^(?!.*\b(?:margin|scenarios?)\b).*(?:\bwhat(?:'s| is| are)? (?:my |our |the )?competitors?\b.*\b(?:charg\w*|pric\w*|sell\w* (?:at|for))\b|\bcompetitors?'? prices?\b|\bhow much (?:are|is|do) (?:my |our |the )?competitors?\b.*\b(?:charg\w*|sell\w*)\b)"), "BUSINESS_STATE"),
    # A status question about the seller's saved product research ("status of my Product Intelligence brief ... do not run discovery") is a READ of the latest saved run.
    Rule("QT_PRODUCT_IDEAS", "PI", _rx(
        r"\b(?:status|progress|state)\b.*\b(?:product intelligence|product research|research run|discovery|niche brief|brief)\b|\b(?:product intelligence|product research|niche brief)\b.*\b(?:status|progress)\b"), "BUSINESS_STATE"),
    Rule("QT_PRODUCT_IDEAS", "PI", _rx(
        r"\bwhat (?:product )?(?:ideas?|products?)\b.*\b(?:did you|have you|you) (?:find|found|list|listed|come up with)\b|\bproduct ideas? (?:you|we) (?:found|listed|have)\b|\bwhat did (?:you|the (?:product )?research|product intelligence) (?:find|found)\b"), "BUSINESS_STATE"),
    Rule("QT_LISTING_CONTENT", "CMO", _rx(
        r"\bwhat (?:titles?|descriptions?|hashtags?|keywords?|listing (?:content|copy)|content)\b.*\b(?:did|have) (?:we|you|i)\b.*\b(?:write|wrote|written|generat\w+|made|create\w*)\b|\b(?:titles?|descriptions?|hashtags?) (?:we|you) (?:wrote|made|generated|created)\b"), "BUSINESS_STATE"),
    Rule("QT_LISTING_CONTENT", "CMO", _rx(
        r"\b(?:show|see|give|tell|what|which|where)\b[^.?!]{0,60}\b(?:selected|approved|chosen|chose|picked|previously (?:selected|approved|chosen))\b[^.?!]{0,40}\b(?:titles?|descriptions?|bullets?|listing)\b"
        r"|\b(?:which|what) (?:titles?|description) (?:did|have) (?:i|we) (?:select|choose|chose|pick|approve)\w*\b"), "BUSINESS_STATE"),
    Rule("QT_GOALS", "CFO", _rx(r"\bwhat(?:'s| is| are) (?:my|our) (?:goals?|targets?|target margin)\b|\bwhat (?:goal|target) (?:did i|have i|did we) (?:set|give|gave)\b"), "BUSINESS_STATE"),
    Rule("QT_AGENT_FINDINGS", "CFO", _rx(
        r"\bwhat (?:has|have|did) (?:each|every|the|all)(?: of the)? (?:agents?|specialists?)\b.*\b(?:found|find|report\w*)\b|\bwhat (?:has|have) (?:the )?agents? found\b"), "BUSINESS_STATE"),
    Rule("QT_SELLER_FACTS", "CFO", _rx(
        r"\bwhat do you (?:know|remember) about (?:my|our) (?:business|store|brand|company|shop)\b|\bwhat have i told you\b|\bwhat do you know about me\b"), "BUSINESS_STATE"),
    # The seller's own operational data that no saved result covers: answered "not stored yet", never from general knowledge.
    Rule("QT_NOT_STORED", "CFO", _rx(
        r"\b(?:my|our) (?:inventory|stock levels?|ad spend|advertising spend|customers?|order count|sales volume|best[- ]?selling (?:sku|product)s?)\b|\bhow (?:much|many) (?:stock|inventory|orders?|units|customers?)\b.*\b(?:do i|have i|did i|do we|have we|did we)\b"), "BUSINESS_STATE"),
)

# An overview request is the BUSINESS_BRIEFING playbook (saved results only, no slot). It comes BEFORE the state rules because a briefing prompt usually also says
# "what data is missing", which would otherwise be read as the narrower data-gaps question.
BRIEFING_RULES: tuple[Rule, ...] = (
    Rule("BUSINESS_BRIEFING", "CFO", _rx(
        r"\b(?:business|cross[- ]domain|overall|overview|executive|morning)\s+(?:briefing|brief|overview|summary|snapshot)\b|\bbriefing\b.*\b(?:business|my (?:store|company|shop))\b|\bbrief me\b"
        r"|\b(?:overview|summary|snapshot) of (?:my|the|our) (?:whole |entire )?(?:business|store|company|shop)\b"
        r"|\b(?:complete|full|overall|whole)\s+(?:financial|finance)\s+(?:health|position|picture|report|review|performance)\b|\bhow (?:is|am|are|did|was) (?:my |our )?(?:business|i doing|we doing)\b"
        r"|\bwhat should i (?:focus on|fix first|work on)\b[^.?!]*\b(?:profit\w*|grow\w*|financ\w*|business)\b|\bimprove (?:my |our )?(?:profit\w*|margins?)\b[^.?!]*\bgrow\w*\b"), "PLAYBOOK"),
)

# Ordered: the first match wins. Each pattern needs a clear verb or noun for the work, not just a keyword anywhere.
_PRICE_DECISION = _rx(
    r"\b(?:should i|can i|could i|what if i|what happens if i|if i|is it worth|do i need to|how (?:can|do) i|what should i do)\b[^.?!]*\b(?:reduce|lower|cut|drop|decrease|raise|increase|match|beat|undercut|reprice|change|conquer|compete)\b[^.?!]*\b(?:price|prices|pricing)\b"
    r"|\b(?:conquer|beat|win against|compete with)\b[^.?!]*\b(?:competitors?|rivals?)\b[^.?!]*\b(?:price|pricing)\b|\bwhat should i do\b[^.?!]*\bpricing\b")

# The expense ledger through the CEO (docs/specs/ceo-expense-tracker-chat.md). Plain rules, first: a request to add, change, remove or mark an expense, a question about recorded
# expenses, and - last of these - a first-person payment STATEMENT, which only starts a question ("is this your expense?"), never a save.
_EXP_NOUN = r"(?:an? |the |my |our |that |this |these |those |one |some |new )*expenses?"
_NOT_HOWTO = r"^(?!\s*(?:how (?:do|does|can|to|would)|where|what (?:is|are|does)|why|is it|are there)\b)"
# Adding ATTACHED data to the financial records ("add the verified information to my CFO dashboard", "import these files"). Reading an attachment is a different request and matches nothing here.
_IMPORT_PATTERN = (
    r"^(?!\s*(?:how (?:do|does|can|to|would)|where|what (?:is|are|does)|why|is it|are there)\b)(?!.*\bexpenses?\b)"
    r"(?=.*\b(?:import|add|upload|load|save|put|bring|ingest|record|sync)\b)"
    r"(?=.*\b(?:these|those|this|that|them|it|files?|reports?|attach\w*|spreadsheets?|csv|xlsx|data|information|figures)\b)"
    r"(?=.*\b(?:dashboard|records?|ledger|cfo|finance|financial|profit|books|accounts?)\b)"
)


def is_import_request(text: str) -> bool:
    return bool(re.search(_IMPORT_PATTERN, " ".join((text or "").split()), re.IGNORECASE))


# Cash: what the seller expects to receive from the marketplaces and what they owe. Not the leak check (missing money), not funding or loans, not an expense request.
_CASH_PATTERN = (
    r"^(?!.*\b(?:leaks?|leaking|discrepanc\w*|reconcil\w*|claims?|loan|borrow\w*|funding|fund(?:s|ed)?\b|what if|what happens|delayed?|invest\w*|expenses?|spent|spend|gst|tcs|tds|competitors?)\b)"
    r"(?=.*\b(?:cash(?:[- ]?flow)?|cash position|cash runway|runway|settlements?|payables?|receivables?|(?:money|payments?|payouts?) (?:i )?(?:expect|will receive|coming|due|owed|to receive|to make|do i need)"
    r"|(?:expect|receive|get paid)\b[^.?!]*\b(?:from|in|over|within|next)\b|upcoming payments|what (?:do )?i (?:owe|need to pay)|bills? (?:due|to pay)|short of cash|run out of cash)\b)"
)


# How the business performed (sales, performance, financial health) with figures from the imported reports. Profit-only questions stay the saved-result read they have always been.
_PERFORMANCE_PATTERN = (
    r"^(?!.*\b(?:expenses?|spent|spend|cash|settlements?|payables?|loan|borrow\w*|fund\w*|leaks?|claims?|gst|competitors?|listings?|hashtags?|titles?|import|upload\w*|files?|attach\w*|what if|plan|forecast)\b)"
    r"(?=.*\b(?:perform(?:ed|ance)?|how much did (?:i|we) (?:sell|make|earn)|total sales|my sales|sales (?:by|across|for|in|of)|financial health|how (?:is|was|did) my business|business doing)\b)"
)


def is_cash_question(text: str) -> bool:
    return bool(re.search(_CASH_PATTERN, " ".join((text or "").split()), re.IGNORECASE))


_EXPENSE_RULES: tuple[Rule, ...] = (
    Rule("cfo.import_attachments", "CFO", _rx(_IMPORT_PATTERN)),
    Rule("cfo.cash_position", "CFO", _rx(_CASH_PATTERN)),
    Rule("cfo.performance", "CFO", _rx(_PERFORMANCE_PATTERN)),
    Rule("cfo.expense_void", "CFO", _rx(_NOT_HOWTO + r"(?=.*\b(?:remove|delete|void|undo|discard|cancel)\b)(?=.*\b" + _EXP_NOUN + r"\b)(?!.*\b(?:competitors?|rivals?)\b)")),
    Rule("cfo.expense_paid", "CFO", _rx(_NOT_HOWTO + r"(?=.*\b(?:mark|set|update|change|make)\b)(?=.*\b" + _EXP_NOUN + r"\b)(?=.*\b(?:as |to )?(?:paid|unpaid|partially paid|partly paid)\b)")),
    Rule("cfo.expense_correct", "CFO", _rx(_NOT_HOWTO + r"(?=.*\b(?:edit|change|correct|update|fix|modify|amend)\b)(?=.*\b" + _EXP_NOUN + r"\b)")),
    Rule("cfo.expense_add", "CFO", _rx(_NOT_HOWTO + r"(?=.*\b(?:add|record|log|enter|save|put|book|note down|insert)\b)(?=.*\b" + _EXP_NOUN + r"\b)")),
    Rule("cfo.expense_add", "CFO", _rx(
        _NOT_HOWTO + r"(?!.*(?:\?|\bshould i\b|\bif i\b|\bwhat if\b|\bcan i\b|\bwould i\b|\bplanning to\b|\bwill (?:pay|spend)\b|\bsold\b|\breceived\b|\brefund))"
        r"(?=.*\b(?:add|record|log|enter|book|note down|insert)\b)(?=.*(?:₹|\brs\.?\s*\d|\binr\b|\d\s*(?:rupees?|rs\b|inr\b)))"
        r"(?=.*\b(?:as|for|towards|under)\b[^.?!]*\b(?:rent|salary|salaries|wages|electricity|utility|utilities|internet|software|subscription|packaging|packing|tape|courier|freight|warehouse|storage|office|stationery|insurance|maintenance|transport|fuel|fees?|charges|interest|emi|tax(?:es)?)\b)")),
    Rule("cfo.expense_summary", "CFO", _rx(
        r"^(?!.*\b(?:profit|revenue|sales|returns?|risks?|health|briefing|overview|performance|growth|grow)\b)(?!.*\b(?:ad|ads|advertising) spend\b)(?!.*\b(?:add|record|log|enter|remove|delete|void|correct|edit|mark)\b)(?:"
        r".*\bhow much\b[^.?!]*\b(?:spen[dt]|spending|expenses?)\b|.*\b(?:show|list|view|see|give|tell|what(?:'s| is| are| was| were)|display)\b[^.?!]*\b(?:my |our |the |all )?expenses?\b"
        r"|.*\b(?:month[- ]?wise|monthly|date[- ]?wise|day[- ]?wise|daily)\b[^.?!]*\bexpenses?\b|.*\bexpenses?\b[^.?!]*\b(?:month[- ]?wise|monthly|date[- ]?wise|day[- ]?wise|daily)\b"
        r"|.*\bexpense (?:summary|report|breakdown|list|history)\b|.*\bwhat did (?:i|we) spend\b)")),
    Rule("cfo.expense_add", "CFO", re.compile(
        r"^(?!.*(?:\?|\bshould i\b|\bif i\b|\bwhat if\b|\bcan i\b|\bcould i\b|\bwould i\b|\bdo i\b|\bdid i\b|\bplanning to\b|\bgoing to\b|\bwant to\b|\bthinking of\b|\bwill (?:pay|spend)\b|\bsold\b|\breceived\b|\brefund))"
        r"(?=.*\b(?:i|we)(?:'ve| have)?\s+(?:just\s+|already\s+|recently\s+)?(?:paid|spent|bought|purchased|booked|recharged|renewed|ordered)\b)"
        r"(?=.*(?:₹|\brs\.?\s*\d|\binr\b|\d\s*(?:rupees?|rs\b|inr\b)))", re.IGNORECASE), flags=("EXPENSE_MENTION",)),
)
RULES: tuple[Rule, ...] = _EXPENSE_RULES + (Rule("COMPETITOR_PRICE_IMPACT", "CI", _PRICE_DECISION, kind="PLAYBOOK"),) + BRIEFING_RULES + STATE_RULES + (
    Rule("cmo.generate_description", "CMO", _rx(rf"(?=.*\b{_DESC}\b)(?=.*\bgst\b)(?=.*\b(?:with|along|also|and|plus|together)\b)"), "ACTION", ("GST_RATE_FOR_PRODUCT",)),
    # Description AND bullets together: the listing copy pack already writes both (plus keywords) as ONE artefact, one approval, one CMO unit.
    Rule("cmo.generate_listing_copy", "CMO", _rx(rf"^(?!.*\bgst\b)(?!\s*(?:tell me about|explain|what|how|why|were|are|is|do|does|did)\b)(?=.*\b{_BULLETS}\b)(?=.*\b{_DESC}\b)(?=.*\b{_WRITE}\b|.*\b(?:and|together|also|with|plus)\b)")),
    Rule("gst_lookup", "CFO", _rx(r"\bgst\b.*\b(?:rate|percent|percentage|%|slab|apply|applies|applicable|charge)\b|\b(?:rate|percent|percentage|slab)\b.*\bgst\b|\bgst (?:on|for|of)\b")),
    Rule("NEW_PRODUCT_DECISION", "CFO", _rx(r"\bworth (?:stocking|buying|importing|selling)\b|\bshould i (?:stock|buy|import|order)\b"), "PLAYBOOK"),
    Rule("COMPETITOR_PRICE_IMPACT", "CI", _rx(r"(?=.*\bmargin\b)(?:.*\b(?:at|match|matched|matching|beat|undercut)\b.*\bprice\b|.*\b(?:is|are|dropped|cut|lowered)\b.*\b(?:at|to)\s*(?:₹|rs\.?)?\s*\d)"), "PLAYBOOK"),
    # A price scenario for ONE competitor (the saved list of competitor prices is a state read, matched earlier and excluded when the word "scenario" is used).
    Rule("ci.request_price_scenario", "CI", _rx(r"\bprice scenarios?\b|\bscenarios?\b.*\bprices?\b|\bprices?\b.*\bscenarios?\b|\bprice positioning\b")),
    Rule("ci.request_price_scenario", "CI", _rx(r"^(?=.*(?:₹|\brs\.?\s*\d|\binr\b))(?=.*\bcompare\b)(?=.*\b(?:with|against|versus|vs\.?)\b)(?=.*\bprice\b)(?!.*\b(?:margin|profitable)\b).*$")),
    Rule("ci.request_price_scenario", "CI", _rx(r"\b(?:compare|compared|versus|vs\.?|against)\b.*(?:₹|\brs\.?\s*\d|\binr\b).*\b(?:competitors?|rivals?)\b|\b(?:competitors?|rivals?)\b.*\b(?:cheaper|pricier)\b.*(?:₹|\brs\.?\s*\d)|(?:₹|\brs\.?\s*\d).*\bhow much (?:cheaper|pricier|more|less)\b.*\b(?:competitors?|rivals?)\b")),
    # CI (CI spec 6.21.3). The seller talks to the CEO only: finding, re-checking and dropping competitors are fixed actions chosen by plain rules, never by a model guess.
    Rule("ci.competitor_remove", "CI", _rx(r"\b(?:remove|untrack|stop tracking|stop following|delete|drop)\b.*\bcompetitors?\b|\bstop tracking\b|\buntrack\b")),
    Rule("ci.monitor_competitors", "CI", _rx(r"\b(?:monitor|re-?check|refresh|see how)\b.*\b(?:my )?(?:competitors?|rivals?)\b|\bhow are (?:my )?(?:competitors?|rivals?)\b|\bany (?:changes|news|updates?) (?:from|with|on) (?:my )?(?:competitors?|rivals?)\b|\bcheck\b[^.?!]*\b(?:my )?(?:tracked )?(?:competitors?|rivals?)\b")),
    Rule("ci.review_findings", "CI", _rx(r"\b(?:complaints?|complain\w*|reviews?)\b.*\bcompetitors?\b|\bcompetitors?\b.*\b(?:complaints?|reviews?)\b|\bwhat do customers (?:say|complain)\b.*\b(?:about|of)\b.*\b(?:competitor|rival)|\banaly[sz]e\b[^.?!]*\breviews?\b|\breview screenshots?\b|\bcustomer reviews?\b")),
    Rule("ci.discover_competitors", "CI", _rx(r"^(?!.*\b(?:screenshots?|uploaded|upload|research now|reviews?|complaints?)\b).*\b(?:find|discover|research|look for|search for|identify)\b.*\b(?:new |more |my |the )?(?:competitors?|rivals?)\b|\b(?:new|more|other) competitors?\b.*\b(?:for|of)\b|^(?!.*https?://)(?!.*\b(?:stop|remove|untrack)\b).*\b(?:track|add|follow)\b[^.?!]*\b(?:a|an|new|another)\s+(?:new\s+)?(?:competitors?|rivals?)\b")),
    # CMO 3.0 M0: choosing one of the title options CMO wrote ("use option 2", "I like title 3", "approve this title"). It only records the seller's own choice.
    Rule("cmo.approve_title", "CMO", _rx(
        r"^(?!.*\b(?:write|generate|create|make|suggest|draft)\b)(?=.*\b(?:option|title|number|choice)s?\s*#?\s*(?:\d|one|two|three|four|five|first|second|third|fourth|fifth)\b)"
        r".*\b(?:i (?:like|choose|pick|want|prefer|will use)|i'll use|let'?s (?:use|go with)|use|choose|pick|select|approve|go with|take|finali[sz]e)\b"
        r"|^(?!.*\b(?:write|generate|create|make|suggest|draft)\b).*\b(?:approve|select|choose|pick|finali[sz]e)\b (?:this|that|the) (?:title|one)\b")),
    Rule("cmo.catalog_answer", "CMO", _rx(
        r"\bcatalog (?:details?|attributes?|answers?|info\w*|questions?)\b|\b(?:what|which) (?:is|are|'s)? ?(?:the )?(?:category|colou?r|material|brand|dimensions|weight)\b.{0,40}\b(?:of|for|on) (?:my|our|this)\b")),
    # CMO 3.0 M2: researching which keywords fit a product (evidence for each, no search volume). Writing keywords for a listing stays cmo.generate_keywords.
    Rule("cmo.keyword_intelligence", "CMO", _rx(r"\bkeyword (?:research|intelligence|analysis|candidates?)\b|\b(?:research|analy[sz]e|evaluate|compare)\b[^.?!]*\bkeywords?\b|\b(?:which|what) (?:search )?keywords (?:should|do|fit|work|are)\b")),
    # B. hashtags: only an explicit request to GENERATE them. A question ABOUT hashtags (tell me about, what makes, how do, why, were those any good...) is not one.
    Rule(
        "cmo.generate_hashtags", "CMO",
        _rx(
            r"^(?!\s*(?:tell me about|explain|what (?:is|are|makes?)|what's|how (?:do|does|should|many|to|can)|why|were|are|is|do|does|did)\b)"
            rf"(?:.*\b(?:write|give|generate|create|make|suggest|draft|need|want|get)\b.*\b{_HASHTAGS}\b|.*\b{_HASHTAGS}\s+(?:for|ideas?)\b)"
        ),
    ),
    Rule("cmo.generate_listing_copy", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:listing copy|copy pack|full listing|complete listing)\b|\b(?:listing copy|copy pack)\b.*\bfor\b")),
    Rule("cmo.generate_backend_terms", "CMO", _rx(rf"\b{_WRITE}\b.*\bbackend (?:search )?(?:terms|keywords)\b|\bbackend (?:search )?(?:terms|keywords)\b.*\bfor\b")),
    Rule("cmo.generate_bullets", "CMO", _rx(rf"\b{_WRITE}\b.*\b{_BULLETS}\b|\b{_BULLETS}\b.*\bfor\b")),
    Rule("cmo.generate_title_sets", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:listing |product |amazon |flipkart |meesho )?{_TITLES}\b|\b{_TITLES} (?:options?|ideas?|for)\b")),
    # "improve my listing": the first step of listing work is title options (the copy pack is grounded on an approved title); competitor themes are brokered into it by the CEO when the seller has saved some.
    Rule("cmo.generate_title_sets", "CMO", _rx(r"\b(?:improve|improving|optimi[sz]e|optimi[sz]ing|rewrite|enhance|upgrade)\b[^.?!]*\blistings?\b|\b(?:write|make|create)\b[^.?!]*\b(?:my|our)\s+listings?\b[^.?!]*\b(?:competitors?|rivals?)\b")),
    Rule("cmo.generate_description", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:product |listing )?{_DESC}\b")),
    Rule("cmo.generate_keywords", "CMO", _rx(rf"\b{_WRITE}\b.*\b(?:search |seo )?{_KEYWORDS}\b|\b{_KEYWORDS} (?:for|ideas?)\b")),
    Rule("cmo.market_trends", "CMO", _rx(
        r"\b(?:market|niche|category|marketplace) trends?\b|\btrend (?:report|research|analysis)\b|\bwhat(?:'s| is) (?:happening|trending|new) in (?:my|the) (?:market|niche|category)\b"
        # News phrasings (a main feature): the seller wants CURRENT public news, which only the market-research flow can fetch, source and date.
        r"|\b(?:e-?commerce|amazon|flipkart|meesho|marketplace|market|seller|online selling)\s+(?:news|updates)\b"
        r"|\bnews\b.*\b(?:e-?commerce|amazon|flipkart|meesho|marketplaces?|online sell\w*|sellers?|market)\b"
        r"|\b(?:e-?commerce|amazon|flipkart|meesho|marketplaces?)\b.*\bnews\b"
        r"|\b(?:latest|current|recent|today'?s|fresh) (?:e-?commerce |market |seller |marketplace )?news\b|\b(?:latest|current|recent) (?:e-?commerce|market|seller|marketplace) updates\b"
        r"|\bwhat(?:'s| is) (?:happening|going on|new) (?:in|on|with) (?:the )?(?:e-?commerce|amazon|flipkart|meesho|online selling|marketplaces?)\b"
        r"|\bupdates? (?:in|on|about|from) (?:the )?(?:e-?commerce|amazon|flipkart|meesho|marketplaces?)\b")),
    Rule("pi.report", "PI", _rx(r"\b(?:show|see|open|view|display|get|give)\b.*\b(?:research|discovery|product ideas?|ideas)\b.*\b(?:report|results?|details?|run)\b|\b(?:latest|last|previous)\b.*\b(?:product )?research\b.*\b(?:report|results?)\b|\bresearch report\b")),
    Rule(
        "pi.discover", "PI",
        _rx(
            # asking to SEE an earlier run (report, status, latest, saved...) is not a request to start a new one
            r"^(?!.*\b(?:report|status|latest|last|previous|saved|earlier)\b)"
            # not for competitors (Competitor Intelligence), the seller's OWN sales, or a question about a result that is already saved
            r"(?!.*\bcompetitors?\b)(?!.*\b(?:my|our)\b[^?.]*\b(?:top|best)[- ]?sell\w*)(?!.*\b(?!(?:amazon|flipkart|meesho|india|the market)\b)\w+['\u2019]s\s+(?:top|best)[- ]?sell)"  # "Acme's top sellers": a named party, not the market
            r"(?!.*\bwhat did\b.*\b(?:research|find|found)\b).*(?:"
            r"\b(?:trending|top[- ]selling|best[- ]selling|best ?sellers?|winning|hot|top)\b.*\bproducts?\b"
            r"|\bproducts? (?:to|i can|i should) sell\b|\bwhat (?:should|can|do) i sell\b|\bproduct (?:ideas?|research|discovery)\b"
            r"|\b(?:find|discover|suggest|research|recommend)\b.*\b(?:products?|niche)\b|\bniche research\b)"
        ),
    ),
)

_PRODUCT_AFTER_FOR = re.compile(r"\bfor (?:my|the|a|an|our)?\s*([\w][\w \-'()&/+#]{1,80}?)(?=\s+(?:on|in|at)\s+(?:amazon|flipkart|meesho)\b|[.,?!]|$)", re.IGNORECASE)
_NICHE = re.compile(r"\b(?:niche|nich|category|segment)\s*(?:is|:|=|-)?\s*(?!(?:under|below|within|upto|up to|budget|on|in|with|for)\b)([\w][\w \-']{1,60}?)(?=[.,?!]|\s+(?:on|in|with|under|budget)\b|$)", re.IGNORECASE)
_NICHE_BEFORE = re.compile(r"\b(?:in|for|of|within)\s+(?:the |a |an |my )?([\w][\w \-']{1,60}?)\s+(?:niche|category|segment)\b", re.IGNORECASE)
_BUDGET = re.compile(r"(?:under|below|within|upto|up to|budget(?: of| is)?|max(?:imum)?)\s*((?:₹|rs\.?|inr)?\s*[\d,]+(?:\.\d+)?)", re.IGNORECASE)


_ADDON_TAIL = re.compile(r"\s+(?:along\s+|together\s+)?(?:with|and|plus|also)\b.*$", re.IGNORECASE)
_GST_PRODUCT_AFTER = re.compile(r"\bgst\b.*?\b(?:on|for|of|to|in)\s+(?:my\s+|the\s+|a\s+|an\s+|our\s+)?(?P<p>[\w][\w \-']{1,80}?)(?=\s+(?:is|are|apply|applies|be)\b|[?.!,]|$)", re.IGNORECASE)
_GST_PRODUCT_BEFORE = re.compile(r"^\W*(?:ok\s+|so\s+)?(?P<p>[\w][\w \-']{1,60}?)\s+gst\b", re.IGNORECASE)
_REQUEST_WORDS = frozenset({"tell", "give", "show", "what", "which", "how", "can", "could", "please", "ok", "okay", "so", "and", "also", "now", "is", "are", "does", "do", "whats", "what's"})
_NOT_A_PRODUCT = frozenset({"this", "that", "it", "these", "those", "them", "this product", "that product", "the product", "my product", "my products", "products"})


def _product_text(raw: str | None) -> str | None:
    """A product named in the message, or None when it is a pronoun, a bare number or a rate (then the CEO asks which product instead of guessing). A name that merely CONTAINS digits is a product (a model number such as "Pegasus 41")."""
    v = " ".join((raw or "").split()).strip(" .,'\"")
    if not v or v.casefold() in _NOT_A_PRODUCT or "%" in v or not re.search(r"[^\W\d_]", v) or len(v.split()) > 8 or v.split()[0].casefold() in _REQUEST_WORDS:
        return None
    return v


_SCENARIO_AMOUNT = re.compile(r"\b(?:at|to|@)\s*((?:(?i:₹|rs\.?|inr))?\s*\d[\d,]*(?:\.\d+)?)")
_SCENARIO_COMPETITOR = re.compile(r"\b(?:against|versus|vs\.?|for|with|from)\s+(?:the\s+)?(?:(?:verified|tracked|competitor)\s+)*([A-Z][\w\-']*(?:\s+[A-Z][\w\-']*)*)")  # a named competitor only; never guessed
_RIVAL_PRICE_OF = re.compile(r"\b(?:at|if i match(?:ed)?|matching|match|beat|undercut)\s+(?:the\s+)?(?P<c>[\w][\w \-']{1,40}?)(?:'s|\u2019s|s')\s+(?:new\s+|current\s+)?price", re.IGNORECASE)
_RIVAL_AT_PRICE = re.compile(r"^\W*(?:so\s+|ok\s+)?(?P<c>[\w][\w \-']{1,40}?)\s+(?:is|are|dropped|cut|lowered)\b.*?\b(?:at|to)\s*(?P<p>(?:₹|rs\.?)?\s*\d+(?:,\d+)*(?:\.\d+)?)", re.IGNORECASE)
_STOCK_BEFORE = re.compile(r"^\W*(?:is|are)\s+(?:the\s+|my\s+|a\s+)?(?P<p>[\w][\w \-']{1,60}?)\s+worth\s+(?:stocking|buying|importing|selling)", re.IGNORECASE)
_STOCK_AFTER = re.compile(r"\bshould i (?:stock|buy|import|order)\s+(?:the\s+|some\s+|a\s+|an\s+|my\s+)?(?P<p>[\w][\w \-']{1,60}?)(?=\s*(?:[?.!,]|or not\b|from\b|$))", re.IGNORECASE)


def _slots(rule: Rule, text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if rule.kind == "BUSINESS_STATE":
        return out  # a state read takes no slots: the question type decides what is read
    if rule.key == "cfo.expense_summary":
        return expense_chat.read_slots(text)
    if rule.key == "cfo.expense_add":
        return expense_chat.slots_for_add(text)
    if rule.key in ("cfo.expense_correct", "cfo.expense_void", "cfo.expense_paid"):
        return expense_chat.entry_hint(text)
    if rule.key == "COMPETITOR_PRICE_IMPACT" and rule.pattern is _PRICE_DECISION:
        decided: dict[str, str] = {}
        target = re.search(r"\bto\s+((?:₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d+)?)", text, re.IGNORECASE)
        if target:
            decided["amount"] = target.group(1).strip().rstrip(",.")
        rival = _SCENARIO_COMPETITOR.search(text)
        if rival:
            decided["competitor"] = rival.group(1).strip()
        return decided
    if rule.key == "COMPETITOR_PRICE_IMPACT":
        m = _RIVAL_PRICE_OF.search(text)
        if m:
            c = _product_text(m.group("c"))
            return {"competitor": c} if c else {}
        m = _RIVAL_AT_PRICE.search(text)
        c = _product_text(m.group("c")) if m else None
        return {"competitor": c, "amount": m.group("p").strip()} if m and c else {}
    if rule.key == "ci.discover_competitors":  # only the product the seller named ("for my 1L steel bottle"); never guessed, the plan asks when it is missing
        product = _product_text(_PRODUCT_AFTER_FOR.search(text).group(1)) if _PRODUCT_AFTER_FOR.search(text) else None
        return {"product": product} if product else {}
    if rule.key == "ci.competitor_remove":  # the competitor named after the verb; resolved against the tracked list by code, an unknown name is asked about
        m = re.search(r"\b(?:remove|untrack|stop tracking|stop following|delete|drop)\s+(?:the\s+|my\s+)?(?:competitor\s+)?(?P<c>[\w][\w \-']{1,40}?)(?=\s+(?:from|as|please|for)\b|[.,?!]|$)", text, re.IGNORECASE)
        c = _product_text(m.group("c")) if m else None
        return {"competitor": c} if c and c.casefold() not in ("competitor", "competitors") else {}
    if rule.key == "ci.request_price_scenario":  # only what the seller said: no competitor and no price is ever assumed (the plan asks for what is missing)
        amount, rival = _SCENARIO_AMOUNT.search(text), _SCENARIO_COMPETITOR.search(text)
        return {**({"competitor": rival.group(1).strip()} if rival else {}), **({"amount": amount.group(1).strip()} if amount else {})}
    if rule.key == "NEW_PRODUCT_DECISION":
        m = _STOCK_BEFORE.search(text) or _STOCK_AFTER.search(text)
        product = _product_text(m.group("p") if m else None)
        return {"product": product} if product else {}
    if rule.key == "gst_lookup":
        m = _GST_PRODUCT_AFTER.search(text) or _GST_PRODUCT_BEFORE.search(text)
        product = _product_text(m.group("p") if m else None)
        return {"product": product} if product else {}
    m = _MARKETPLACE.search(text)
    if m:
        out["marketplace"] = m.group(1)
    if rule.agent == "PI":
        niche = _NICHE_BEFORE.search(text) or _NICHE.search(text)
        if niche:
            out["product"] = niche.group(1).strip()
        budget = _BUDGET.search(text)
        if budget:
            out["amount"] = budget.group(1).strip()
    else:
        product = _PRODUCT_AFTER_FOR.search(_ADDON_TAIL.sub("", text) if rule.addons else text)  # "... for a steel bottle along with the GST %": the add-on is not part of the product
        if product:
            out["product"] = product.group(1).strip()
    return out


def matches_a_rule(text: str) -> bool:
    """True when the message is plainly a request of its own (one of the plain rules reads it), so it is never taken as the answer to a question that was open."""
    return any(r.pattern.search(text) for r in RULES)


def route(text: str, cat: Catalog) -> Decision | None:
    """A decision when a rule recognises the request, else None (the model decides)."""
    t = " ".join(text.split())
    if _GENERAL_ASK.search(t) and not _DATA_WORDS.search(t) and not any(r.pattern.search(t) for r in RULES):
        d = parse_decision(json.dumps({"route": "ADVISORY", "route_key": None, "slots": {}, "needs_agent": None, "clarify_for": None}), cat)
        return Decision(d.parse_ok, d.raw_route, d.raw_key, d.route, d.key, d.slots, d.needs_agent, d.clarify_for, frozenset({*d.flags, "RULE_ROUTED"}))
    for rule in RULES:
        if not rule.pattern.search(t):
            continue
        if rule.kind == "PLAYBOOK" and PLAYBOOKS[rule.key].required_slots and not _slots(rule, t):
            continue  # no product named ("find products worth stocking"): the model decides, nothing is guessed
        item = cat.item(rule.kind, rule.key)
        if item is None:  # the member cannot run it here: say why, do not ask something unrelated
            payload: Mapping[str, object] = {"route": "ADVISORY", "route_key": None, "slots": {}, "needs_agent": rule.agent, "clarify_for": None}
        else:
            payload = {"route": rule.kind, "route_key": rule.key, "slots": _slots(rule, t), "needs_agent": None, "clarify_for": None}
        d = parse_decision(json.dumps(payload), cat)
        extra = {"GST_UNAVAILABLE"} if item is None and rule.key == "gst_lookup" else set()  # the wall for GST is code, never general knowledge
        if item is not None:
            extra |= set(rule.flags)
        return Decision(d.parse_ok, d.raw_route, d.raw_key, d.route, d.key, d.slots, d.needs_agent, d.clarify_for, frozenset({*d.flags, "RULE_ROUTED", *extra}),
                        addons=rule.addons if item is not None else ())
    return None
