"""The CEO business Q&A question-type catalog v1 — spec agent-needs-and-shared-knowledge.md section 7 (N-C4).

A business question is answered ONLY by reading a fixed list of Business State entries chosen from a CLOSED list of question types (this table). The
`BUSINESS_STATE` route's key is a question-type id; `business_state.read_entry` expands it to its entries. Selection is by the `intent_router` rules first,
then the classifier choosing a value from the closed enum; a value outside the enum is a clarification (`classifier.parse_decision`, AC22 / AC-Q2).

Nothing here reads, computes, queries or generates anything: no SQL, no vector or free-text search, no registry action is run (AC-Q1, AC-Q5, AC26). A missing
result is answered by a sentence WRITTEN BY CODE below ("Not stored yet. ..." plus what to upload or attach) and, where a registered action could produce it,
an action OFFERED to the seller (never run in the answer turn, section 6.13 rule 4). A model never writes a status sentence, so a non-result can never be
narrated as a result (AC-Q3, section 7.4 rule 2).

Adding a question type is a code change plus an edit to the section 7.2 table in the spec, in the same change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

NOT_STORED_PREFIX = "Not stored yet."  # every UNAVAILABLE sentence in this module begins with it (pinned by a test)


@dataclass(frozen=True, slots=True)
class EntryUse:
    """One Business State entry a question type reads. `fact_labels` keeps only the facts with those labels (e.g. the stored goal out of the seller facts);
    `not_stored` overrides the type's sentence for THIS entry when it alone is missing."""

    key: str
    fact_labels: tuple[str, ...] | None = None
    not_stored: str | None = None


@dataclass(frozen=True, slots=True)
class QuestionType:
    id: str
    description: str  # what the classifier is shown (plain language)
    example: str
    entries: tuple[EntryUse, ...]
    not_stored: str  # the code-written sentence when nothing is stored: begins "Not stored yet."
    offer: tuple[str, str] | None = None  # (registry key, label): offered when a result is missing, never run
    available_offer: tuple[str, str] | None = None  # offered when the result exists (e.g. re-show the saved report), never run
    always_gaps: tuple[str, ...] = ()  # sentences that always accompany the answer (a part that is not stored in V1 at all)


_PNL_OFFER = ("cfo.pnl_for_tenant", "Run the profit and loss for a period")

QUESTION_TYPES: Mapping[str, QuestionType] = {
    qt.id: qt
    for qt in (
        QuestionType(
            "QT_PROFIT_BY_PERIOD", "How much profit or revenue the business made in a recent period, from saved profit and loss results",
            "What was my profit in September?",
            (EntryUse("BS_PNL_RECENT"), EntryUse("BS_HEALTH_BANDS", not_stored="Not stored yet. Health bands have not been saved for the latest period.")),
            "Not stored yet. Upload the settlement and order reports for that period on the Finance page, then run the profit and loss (offered below).",
            offer=_PNL_OFFER,
        ),
        QuestionType(
            "QT_LEAKS", "Where the business is losing money: open marketplace leak findings and the inputs still missing",
            "Where am I losing money?",
            (EntryUse("BS_LEAK_OPEN"), EntryUse("BS_DATA_GAPS", not_stored="Not stored yet. No list of missing inputs has been saved.")),
            "Not stored yet. No leak check has been saved; upload your settlement and order reports, then run the leak check (offered below).",
            offer=("cfo.reconcile", "Run the leak check"),
        ),
        QuestionType(
            "QT_DATA_GAPS", "Which data the CEO is missing and which reports were uploaded",
            "What data are you missing?",
            (EntryUse("BS_DATA_GAPS"), EntryUse("BS_INGEST_STATUS")),
            "Not stored yet. No marketplace report has been uploaded; upload your settlement and order reports on the Finance page.",
        ),
        QuestionType(
            "QT_COMPETITORS_PRICES", "What tracked competitors are charging, from saved competitor captures",
            "What are my competitors charging?",
            (EntryUse("BS_COMPETITOR_SNAPSHOT"),),
            "Not stored yet. No competitor is tracked or captured yet; add a competitor on the Competitor Intelligence page.",
        ),
        QuestionType(
            "QT_PRODUCT_IDEAS", "What the latest product research run found",
            "What product ideas did you find?",
            (EntryUse("BS_PI_REPORT_LATEST"),),
            "Not stored yet. No product research has been run; start one (offered below).",
            offer=("pi.discover", "Start a product research run"), available_offer=("pi.report", "Show the latest product research report"),
        ),
        QuestionType(
            "QT_LISTING_CONTENT", "What listing titles, descriptions, keywords or hashtags have been written",
            "What titles did we write?",
            (EntryUse("BS_CMO_WORKFLOW"), EntryUse("BS_CMO_CONTENT_LATEST")),
            "Not stored yet. Nothing has been written; ask for titles, a description, keywords or hashtags (offered below).",
            offer=("cmo.generate_title_sets", "Write title options"),
        ),
        QuestionType(
            "QT_GOALS", "The seller's stated goal",
            "What is my goal?",
            (EntryUse("BS_SELLER_CONTEXT"), EntryUse("BS_SELLER_FACTS", fact_labels=("Your goal (you said)",))),
            "Not stored yet. No goal is stored; set your goal on the CFO page.",
            always_gaps=("Not stored yet. Progress against your goal is not tracked yet.",),
        ),
        QuestionType(
            "QT_AGENT_FINDINGS", "What each agent has found and reported",
            "What has each agent found?",
            (EntryUse("BS_SHARED_FINDINGS"),),
            "Not stored yet. No agent has reported anything yet, or the agents that did are turned off for this conversation.",
        ),
        QuestionType(
            "QT_SELLER_FACTS", "What the seller has told us about their business",
            "What do you know about my business?",
            (EntryUse("BS_SELLER_FACTS"),),
            "Not stored yet. You have not told me about your business; tell me, for example, “my niche is …”.",
        ),
        QuestionType(
            "QT_NOT_STORED", "A question about the seller's own data that no saved result covers (stock, orders, ad spend, customers)",
            "How much stock do I have?",
            (),
            "Not stored yet. I only answer from results saved in Metrion, and that is not one of them. Upload your reports on the Finance page, "
            "or ask what I know about your business.",
        ),
    )
}

# Status sentences, written by code. {agent} is the owning agent's code from the catalog, never model text.
NOT_PERMITTED_TEXT = "You do not have access to this information, so I have not read it."
NOT_ENTITLED_TEXT = "{agent} is not available on your current plan, so I have not read its saved results."
NOT_ATTACHED_TEXT = "{agent} is not attached to this conversation, so I have not read its saved results. Attach {agent} to this conversation and ask again."


def is_question_type(key: str) -> bool:
    return key in QUESTION_TYPES


def descriptions() -> dict[str, str]:
    """The classifier-facing description of every question type (the closed enum the model may choose from)."""
    return {qt.id: qt.description for qt in QUESTION_TYPES.values()}
