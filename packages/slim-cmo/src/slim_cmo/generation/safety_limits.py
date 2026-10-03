"""Technical PARSE-SAFETY ceilings - implementation limits, NOT marketplace or business rules.

These exist only so that a runaway or hostile provider reply cannot exhaust memory or bloat a
database row. They are deliberately NOT presented to the seller as a marketplace limit, are never
written into `constraint_check`, never appear in `unverified_limits`, and never stand in for a
`format_constraint` value that is missing: a limit the verified row does not state remains
"not enforced and not guessed" (spec §6.3/§6.4) - this ceiling merely refuses absurd output.

Exceeding a ceiling makes the reply unusable (`OUTPUT_TOO_LARGE`); the output is never truncated
into something that looks valid. All values live here and nowhere else.
"""

from __future__ import annotations

PARSE_SAFETY_MAX_RESPONSE_CHARS = 60_000   # whole provider reply
PARSE_SAFETY_MAX_LIST_ITEMS = 200          # entries in any one list (titles, bullets, keywords, terms, hashtags)
PARSE_SAFETY_MAX_ITEM_CHARS = 5_000        # one title / bullet / keyword / term / hashtag
PARSE_SAFETY_MAX_DESCRIPTION_CHARS = 20_000

# Seller-facing "facts to supply" lists (NEEDS_FACTS): bounded so the message stays readable.
MAX_DECLARED_MISSING_FACTS = 10
MAX_FACT_NAME_CHARS = 40
# Retry feedback lines sent back to the model.
MAX_FEEDBACK_LINES = 12
