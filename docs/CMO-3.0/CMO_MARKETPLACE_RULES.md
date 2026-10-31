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

## Access attempts (final production-readiness pass, 2026-10-31)

Recorded in the register as `access_attempts` so the next reader does not repeat them:

| Marketplace | Page | Result |
|---|---|---|
| Amazon India | [Seller-forum announcement of the title requirements](https://sellercentral.amazon.in/seller-forums/discussions/t/6cae8579-d09f-484d-98ca-a2b057c175a2) | Read. The only official rule text reachable (200 characters for most categories; disallowed characters; repeated words). |
| Amazon India | `sellercentral.amazon.in/help/hub/reference/external/GYTR6SYGFA5E3EQC` (Product title requirements) | Read; navigation only, no article text without a seller session. |
| Flipkart | `seller.flipkart.com/sell-online/listing-guidelines` | Read; only the page title, no rules in the public body. |
| Meesho | `supplier.meesho.com/learning-hub` | HTTP 403 for an automated reader. |

## Exactly what an authorized seller account must supply (per marketplace)

The register carries this as `evidence_needed_from_a_seller_account`; the validator fails if a marketplace has no list.

* **Amazon India (Seller Central):** the *Product title requirements* article (limit per category and store, with the date shown); the style guide or flat-file template of each category sold in (bullet count, characters per bullet, description limit, search-terms byte limit, required attributes); the URL as seen signed in and the date read, for each.
* **Flipkart (Seller Hub):** the category listing template (sample catalogue file) of each category sold in (mandatory attributes and any length stated in its instruction row); the listing-quality / guidelines page (title if typed, description, highlights); the URL or template name and the date read, for each.
* **Meesho (supplier panel):** the catalog upload template of each category (product name and description limits, mandatory fields as printed); the Legal and Policies / catalog quality guide; the page or template name and the date read, for each.

## How a verified rule reaches the product (maintenance procedure)

1. Add or change the entry in `packages/slim-cmo/rules/marketplace_rules.json` (value, https URL on an official host, `checked_on`, scope; status `OFFICIAL_VERIFIED` only if the page states it completely for that scope). `test_marketplace_rules.py` fails the build if an official rule lacks an https URL on an official host, a value or a date, or if a third-party figure carries a value.
2. **Listing rules:** when every field in `required_for_constraint_row` is verified for one marketplace and scope, `promotable_row` returns the values; a person inserts them as a `VERIFIED` `format_constraint` row through the existing review path. Nothing is copied automatically.
3. **Title display rules (B6):** an `OFFICIAL_VERIFIED` `title.display_chars.mobile|desktop` entry with scope containing `ALL_CATEGORIES` is turned into the preview's `title_display_rules` shape by `display_rules_config`; a platform-config row of the same name overrides it. Either way the preview simulator re-checks, on every request, that the source is https **on an official host**, that the rule is declared for all categories, that the date is valid and not stale, and the character count is a positive integer. Anything else is shown as `ILLUSTRATIVE` with the reason. Today no entry is verified, so every preview is illustrative.
4. **Staleness:** a verified listing rule or display rule older than the configured window (`format_constraint_max_age_days`) is ignored and the product falls back to the unverified-draft restriction or the illustrative preview.

## Status (unchanged conclusion)

Nothing is promotable for any marketplace. Complete listings remain labelled unverified drafts with every marketplace check `NOT_ASSESSED`, and no draft can be shown as marketplace-compliant: the verdict vocabulary has no "compliant" or "ready" value, the banner states the rules are not verified, and the audit marks each marketplace check not assessed.
