"""Catalog Q&A (P4) - the PURE core: question vocabulary, evidence resolution, estimate validation.

Evidence-first, deterministic, no model, no network, no database, no clock (enforced by the
purity test). Every answer carries one basis (spec §6.5); only `SELLER_PROVIDED` and a passed-gate
`IMAGE_OBSERVED` answer may be asserted as fact (C9, AC12, AC20). Recommend-only: nothing here
writes to a marketplace.
"""
