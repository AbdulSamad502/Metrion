# CMO 3.0 — Evidence requests for the owner and sellers (B1, B6, B8)

No passwords are needed or should be shared. Provide exports, screenshots or copied text with the page URL (or template name) and the date read. Store files in a folder the owner chooses; the assistant records the source, date, marketplace, category and scope in `packages/slim-cmo/rules/marketplace_rules.json`.

## B1 — listing rules (per marketplace and category sold)
| Marketplace | Provide | Fields it must show | Closes |
|---|---|---|---|
| Amazon India (Seller Central) | "Product title requirements" article; the style guide or flat-file template for each category | title limit, bullet count and length, description limit, search-terms byte limit, required attributes | `title.max_chars`, `bullet_count`, `bullet.max_chars`, `description.max_chars`, `backend_terms.max_bytes` |
| Flipkart (Seller Hub) | category listing template (sample catalogue file) and the listing-quality/guidelines page | mandatory attributes, any limit in the instruction row, title and description rules | same fields |
| Meesho (supplier panel) | catalog upload template for each category; catalog-quality guide | name and description limits, mandatory fields | same fields |
A rule is promotable only when all five fields are verified for one marketplace and scope; until then drafts stay unverified.

## B6 — title display (truncation)
Preferred: an official page that states the display length (give URL and date). Otherwise, measurements from the owner's own authorized live test listings. Per observation record: marketplace, category, device (mobile/desktop), surface (search results or product page), listing URL, date, method (device width, browser, signed in/out), full title length, characters visible before the cut-off, whether it was cut. Minimum for a reviewable summary: 5 observations over at least 3 different listings per marketplace, category, device and surface (`measured_display_summary`). A submission limit is not a display limit; do not mix them. A preview becomes "measured" only after a person reviews the summary and M4 is extended for a measured label (not built, since no measurement exists).

## B8 — performance reports and confirmations
For each marketplace, export the report that shows **per-day, per-SKU** impressions/views, clicks, orders, units and sales (name the report and its menu path as seen in your account) for at least 8 weeks around a listing change, in the file's original CSV/XLSX form (do not re-save). Also provide: the SKU(s) that identify each product; the date each new listing version went live; and the marketplace's statement (help page URL and date) on whether a day or SKU absent from the report means zero activity. Until a real export has been imported and checked, native Amazon/Flipkart/Meesho support is **not claimed**; only the documented column synonyms are accepted. Real data is used only with the owner's explicit authorization.

## B7
See `CMO_B7_BROWSER_WALKTHROUGH.md` (test tenant and permission).

## B1 / M9 - marketplace image requirements

From each seller account (no passwords): the official image requirements page or listing-template instructions for each category sold (minimum and maximum pixel sizes, number of images, main-image background and content rules, file-type and size limits, text or watermark rules), with the page URL and the date read. Until then M9 reports every marketplace image requirement as NOT_ASSESSED. Real seller product pictures are used only with the owner's explicit authorization; development uses synthetic pictures.

## M10 - what makes news and opportunities useful
1. A saved market-trend report (the existing paid, approved step) so there is something to read; without one M10 shows nothing.
2. The operator-configured official policy domains for Amazon India, Flipkart and Meesho (open question Q5), so official sources can be recognised.
3. Real seller reports and listings stay out of development: synthetic data only; real data only with the owner's explicit authorization.
