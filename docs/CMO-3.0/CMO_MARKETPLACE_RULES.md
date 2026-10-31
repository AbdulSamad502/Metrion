# CMO 3.0 — Marketplace listing rules: what is verified, what is not (read 2026-10-31)

Machine-readable register: `packages/slim-cmo/rules/marketplace_rules.json`, checked by `slim_cmo.service.marketplace_rules` (`problems`, `promotable_row`) and `tests/unit/test_marketplace_rules.py`.
Policy: a rule is **verified** only when an **official marketplace page** states it, the page is named by https URL on an official host, and the date it was read is recorded. A figure from a blog,
a forum answer or a service provider is a **hint**, kept with `value: null`, never enforced. Nothing reaches `format_constraint` (the only table generation and the audit trust) unless **every** field
a constraint row needs is verified for one marketplace and scope. **Today none is, so B1 stays open and the unverified-draft restriction stays.** No limit was invented.

## What was read

| Marketplace | Rule | Result | Source | Status |
|---|---|---|---|---|
| Amazon India | Title length | "titles may not exceed 200 characters, including spaces" for **most** categories, effective 2025-01-21; category- and store-specific limits are on the "Product title requirements" help page, behind the seller login | [Amazon India seller-forum announcement, "New product title requirements effective from January 21, 2025"](https://sellercentral.amazon.in/seller-forums/discussions/t/6cae8579-d09f-484d-98ca-a2b057c175a2) | OFFICIAL_PARTIAL — not promoted: scope is "most categories", and a third-party blog reports a later, lower limit that no readable Amazon page confirms or denies |
| Amazon India | Disallowed title characters (`! $ ? _ { } ^ ¬ ¦` unless part of the brand), a word at most twice | same announcement | same | OFFICIAL_PARTIAL — recorded; the audit does not enforce it yet |
| Amazon India | Bullet count and length, description length, backend-term bytes, required attributes, category rules | Style guides and limits are per category inside Seller Central; only third-party figures were found (500 per bullet, 2,000 description) | none official | THIRD_PARTY_ONLY / NOT_FOUND — hints only |
| Flipkart | Title, description, bullets, attributes | No official page was readable. Third parties say titles are built from category attributes and quote 10,000 characters for descriptions (2023) | none official | NOT_FOUND / THIRD_PARTY_ONLY — hints only; the attribute form stays `NEEDS_SELLER_INPUT` |
| Meesho | Name, description, attributes | The public learning hub gives a naming principle (generic name as on the packaging, plus the brand) but no length; limits live in supplier-panel templates and policies behind the login | [Meesho supplier learning hub](https://supplier.meesho.com/learning-hub/lessons/legal-methodology) | NOT_FOUND for limits |

## Consequences in the product (unchanged by design)

* No `VERIFIED` `format_constraint` row exists for any of the three marketplaces. A complete listing runs only as a labelled **unverified draft** (flag `listing_unverified_rules_enabled`), every marketplace check `NOT_ASSESSED`; the same flag gates the title step inside a listing request. Without the flag it is refused before any plan card.
* Title **display** (B6): previews show an `ILLUSTRATIVE` cut-off unless a platform config row `title_display_rules` carries an https source and a check date. No marketplace publishes a display rule I could read, so every preview stays `ILLUSTRATIVE`; the app says so on the card.

## How to clear B1 (by a person with seller logins)

1. Read the current rule on the official page inside Seller Central / Seller Hub / the supplier panel for each category you sell in.
2. Add an entry to `marketplace_rules.json` with the exact value, the page's https URL, the date read and the scope; run `pytest packages/slim-cmo/tests/unit/test_marketplace_rules.py`.
3. When all required fields (`title.max_chars`, `bullet_count`, `bullet.max_chars`, `description.max_chars`, `backend_terms.max_bytes`) are `OFFICIAL_VERIFIED` for one marketplace, `promotable_row` returns the values; insert them as a `VERIFIED` `format_constraint` row (the existing review path), and re-run `verify_cmo_readiness.py`.
