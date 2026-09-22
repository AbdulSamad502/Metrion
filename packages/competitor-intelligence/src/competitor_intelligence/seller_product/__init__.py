"""`SellerProduct` — competitor-intelligence-agent.md §5.5/§5.5.1/§5.5.2, C30/C31, D8.

A read-only baseline contract CI reads and never writes. Two legitimate sources populate
it — a read-only derivation over `packages/data-foundation`'s `sales_line` (`derive.py`)
and a seller-maintained manual profile (`repositories/seller_product_profile_repo.py`,
owned by this package since CI is its sole consumer today) — merged by `merge.py` with the
same "manual entry supersedes" precedent already established in
`evidence/merge.py::apply_manual_entries` (§5.3 rule 4).
"""

from __future__ import annotations
