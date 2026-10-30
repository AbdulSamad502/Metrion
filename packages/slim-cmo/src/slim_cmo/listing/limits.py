"""Fixed numbers for the M6 listing audit and the seller's section-edit sentence (docs/specs/slim-cmo-agent.md sections 6.18.5a and 6.18.7a).

The repetition thresholds are READABILITY checks on the seller's own text. They are not marketplace rules and not ranking rules. Changing any number is a documented spec change and a
new `METHOD_VERSION` (recorded on every audit row); they are never a per-request setting. The edit ceilings are technical parse limits, also not marketplace rules.
"""

from __future__ import annotations

METHOD_VERSION = "listing-audit-v1"

# W1-W7 (a rule triggers at the value, not below it)
W1_SAME_CANDIDATE_IN_ONE_BULLET = 2
W2_SAME_CANDIDATE_IN_BULLETS = 4  # in this many DIFFERENT bullets
W3_SAME_CANDIDATE_IN_DESCRIPTION = 4
W4_SAME_CANDIDATE_IN_LISTING = 8  # title + bullets + description
W6_BARE_KEYWORD_LIST_ITEMS = 4  # a sentence made only of this many candidates

# The seller's section-edit sentence (technical ceilings)
EDIT_BULLET_MAX = 500
EDIT_DESCRIPTION_MAX = 2000
EDIT_LIST_MAX_TERMS = 20
EDIT_TERM_MAX = 80
