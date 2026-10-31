# CMO 3.0 — M9: Product Image Quality Advisor

Status: built and tested at API, chat and component level on synthetic pictures. **Not verified in a browser** (needs a signed-in test tenant, the same dependency as B7). Marketplace image requirements are **NOT_ASSESSED**: no verified official image rule exists.

## 1. What it does

A seller uploads their own product pictures for a product on a marketplace, labels the main image and the kind of each shot, and gets a transparent image quality review: a score out of 100 (only when every dimension could be assessed), per-image findings ranked by severity with why they matter and what to do, suggestions for missing shots, and the status of marketplace image requirements. It works on the images page (`/dashboard/cmo/images`) and in the CEO chat. It is free (zero units), uses **no AI model at all** (not even the vision model), and never edits, replaces or publishes an image.

## 2. Design decisions (owner-approved)

1. **Readiness:** the photo item stays at 10 points and the readiness formula and its tests are unchanged. Image quality is shown *beside* readiness as information (`imageQuality` on each marketplace result); it never changes the score, verdict or any item. A main image uploaded on the images page counts as the photo being *present* (the same presence rule as before); missing images stay MISSING, and a missing or unreviewed set is "not assessed", never a pass.
2. **No model:** deterministic Pillow-only measurements with integer arithmetic. The text/logo/watermark check is a rough heuristic, labelled low-confidence, and answers `POSSIBLE_OVERLAY`, `NOT_DETECTED` (which is *not* a statement that there is no text) or `NOT_ASSESSED`.
3. **Chat photos:** a photo attached in the chat never enters a product's images by itself. When the seller asks to add it, the CEO shows a card with product, marketplace, role and shot pickers and an **Add to my product images** button; only that button (the same route as the page) adds it. Typing "yes" adds nothing.

## 3. Method (`slim_cmo.imagequality`)

Measurement (`measure.py`), on the stored, metadata-stripped PNG, resized deterministically to a 512-pixel long side: dimensions, megapixels, aspect ratio; sharpness (variance of a Laplacian over the subject region); exposure (mean luminance, shadow and highlight clipping, contrast range, measured on the subject so a white backdrop is not read as over-exposed); background plainness (share of border pixels within a tolerance of the border colour) and busyness; the subject (pixels that differ from the border colour), its share of the frame, centring and contact with the frame edges; marks separated from the product by a clear gap in the top or bottom 15% (possible overlay). When the border is not plain the subject cannot be separated, and everything that depends on it is `None` (NOT_ASSESSED with the reason), never guessed.

Scoring (`review.py`), per image, each dimension a 0–100 percentage or NOT_ASSESSED; the main image counts 60% and the additional images 40% of a dimension:

| Dimension | Weight | Based on |
|---|---|---|
| Image clarity | 20 | long side in pixels (40%) and sharpness (60%) |
| Lighting and exposure | 15 | subject brightness band, shadow/highlight clipping, contrast |
| Product visibility | 20 | share of the frame the product fills; a possible overlay on the main image reduces it |
| Composition and cropping | 15 | centring, contact with the frame edge (possible cut-off), unusual aspect ratio |
| Background quality | 15 | plain border, busy surroundings, possible overlay |
| Image-set consistency and coverage | 15 | coverage of main + angle + detail + size + usage shots (8 points); same shape, similar size, similar light and backdrop across images (7 points, needs two or more images) |

A number is shown only when the main image exists and **every** dimension was assessed (`COMPLETE`). Otherwise the state is `PARTIAL` (points earned out of points assessable are shown; no score) or `NOT_CALCULABLE` (no main image). Detail and usage shots are not marked down for a busy or off-centre frame. The score is image quality only: not marketplace compliance, not listing readiness. Thresholds are fixed constants in `review.py`, calibrated on synthetic pictures; they are general advice, not marketplace rules.

Findings: image number and kind of shot, problem, severity (HIGH, MEDIUM, LOW), why it matters to the buyer, a specific recommendation, and the measured evidence; sorted by severity, then main image first. Missing angles, details, size and usage visuals are **suggestions** (`isMarketplaceRequirement: false`).

## 4. Marketplace requirements

`compliance()` reads only rules in `packages/slim-cmo/rules/marketplace_rules.json` with status `OFFICIAL_VERIFIED`, scope containing `ALL_CATEGORIES`, an https source on an official host, a date within the configured age, and an integer value, for the fields `image.min_long_side_px`, `image.main.min_long_side_px`, `image.min_count`, `image.max_count`. Today **none exists**, so every marketplace returns `NOT_ASSESSED` with a message and a list of what is not assessed. When a rule exists the result lists each check with its source URL, date and scope, and says it is not a statement that the images meet every requirement. Background colour, aspect ratio, file size, overlay/text rules and category-specific rules are never checked without a verified rule (file size is measured on Metrion's stored copy, not the seller's original, so it is deliberately not offered). To close this, see `CMO_EVIDENCE_REQUESTS.md` (image section) and B1.

## 5. Data and API

Tables (slim-cmo migration `20261101_0011`): `cmo_product_image` (append-only assignment events: stored image, SKU, marketplace, PRIMARY / SECONDARY / REMOVED, shot type, position, who, when; newest event per image is current) and `cmo_image_review` (immutable report keyed by a hash of the exact set, roles, shot types and method version; score is NULL unless COMPLETE). Both are tenant-owned, FORCE RLS, `SELECT, INSERT` only for the application role, with a composite foreign key to `seller_image_asset (tenant_id, id)`. The existing `seller_image_asset` and `product_image_analysis` are untouched. Backend migration `20261031_0032` widens the chat message check for the `IMAGE_QUALITY` card.

Routes (`/api/v1/cmo/product-images`, all zero-unit; permission `agent.cmo`, uploads also `files.upload`): `GET /products`, `GET ?sku&marketplace`, `POST /upload` (up to 8 files; labels per file; each file goes through the existing validated, metadata-stripping upload), `POST /assign`, `POST /review`, `POST /from-chat`, `GET /{asset_id}/file` (only for an image the seller attached to a product; any other is 404). An image can be attached only to a product the seller has told Metrion about. At most one main image (promoting another demotes the old one in the same transaction); at most 12 images per product and marketplace. Identical pictures are one stored image; identical assignments write nothing; the same set reviewed twice returns the stored review.

CEO chat (`ceo/cmo_image_chat.py`): "Analyze my product images", "Check my main product image", "Which image has the lowest quality?", "What is wrong with image 2?", "What additional product photos should I upload?", "Are my images suitable for Amazon?", "Show my image quality report". It resolves the product and marketplace, asks one short question when ambiguous (which product, which marketplace, which image number), and returns an `IMAGE_QUALITY` card. Competitor or screenshot wording is never routed here.

## 6. Security and audit

Tenant isolation: RLS (FORCE) on both tables, `tenant_scope` on every query, composite foreign key, no client-supplied tenant, files served only after a tenant-scoped lookup of an attached image. Stored pictures are the normalised copies (EXIF/GPS removed). Every accepted assignment batch and every new review writes an `agent_run` (`cmo.assign_images`, `cmo.review_images`) and the event rows record who and when. No metered event, no reservation, no model or vision call (asserted in tests).

## 7. Known limits

* Measurements are rule-based and calibrated on synthetic pictures; a flat-coloured product with no texture can read as soft, a genuinely dark product as dark, and a busy lifestyle background as "cannot separate the product". Each such case is reported as NOT_ASSESSED or as a finding with its evidence, not hidden.
* Text, logo and watermark detection is a low-confidence heuristic that notices marks separated from the product in the top or bottom of the frame; it cannot read text.
* Near-duplicate detection compares small perceptual fingerprints (section 8); it flags images that look almost the same, never images the seller labelled as different views, and reports an alike-but-uncertain pair as NOT_ASSESSED.
* No browser verification, no real-seller pictures, no verified marketplace image rules.

## 8. Near-duplicate detection

Per image (`measure.fingerprint`): a 64-bit difference hash (a 9 x 8 greyscale thumbnail; does each pixel get darker to its right) and an 8 x 8 colour thumbnail; both integers, both independent of size and re-encoding. Per pair (`review.duplicate_check`): Hamming distance of the hashes (of 64) and the average colour difference of the thumbnails (of 255).

* **Same kind of shot label:** REPEAT when the distance is at most 4 and the colour difference at most 12.
* **Different kind of shot label** (for example front and back): never REPEAT, because the same product shot from another side is legitimately alike. An alike pair is reported as NOT_ASSESSED.
* **Uncertain** (distance at most 10 and colour difference at most 30, but not a REPEAT): NOT_ASSESSED, with the reason; no finding.
* Anything else is different and is not listed. Fewer than two images: NOT_ASSESSED.
* A REPEAT produces one LOW finding ("Image 1 and image 2 look almost the same") naming both images and the two measured numbers, with the advice to replace one with a different angle, detail, size or in-use photo. It never changes the score and is not marketplace compliance.

Limits: it sees shapes and colours at a very coarse scale. Two photos of the same plain product from slightly different positions, labelled the same, can look alike enough to be a REPEAT; an identical-looking product in a different colour is NOT_ASSESSED; it cannot tell that two different-looking photos show the same item. Thresholds were calibrated on synthetic pictures only.

## 9. Status (vocabulary: IMPLEMENTED, AUTOMATED TESTED, INTEGRATION TESTED, BROWSER VERIFIED, PARTIAL, NOT TESTED)

| # | Capability | Status | Evidence on record |
|---|---|---|---|
| M9-1 | Upload several pictures, attach to product, SKU and marketplace; main and additional roles | IMPLEMENTED, INTEGRATION TESTED | backend `test_cmo_m9_images.py` 30 passed together with the chat file (before the duplicate-detection change); upload, labels, limits, idempotency, removal |
| M9-2 | Previews, upload status, validation (type, size, readability) | IMPLEMENTED, AUTOMATED TESTED (component level) | frontend `images.test.tsx`; backend validation reuses the existing upload path. Not BROWSER VERIFIED |
| M9-3 | Deterministic measurements and 0-100 score with the six weights; score withheld when a dimension cannot be assessed | IMPLEMENTED, AUTOMATED TESTED | slim-cmo `tests/unit/imagequality` (full slim-cmo suite 2775 passed, 237 skipped, after the duplicate change) |
| M9-4 | Main image review separate from additional images | IMPLEMENTED, AUTOMATED TESTED | same |
| M9-5 | Missing angle, detail, size, usage suggestions (not requirements); inconsistent set | IMPLEMENTED, AUTOMATED TESTED | same |
| M9-6 | Text, logo and watermark detection | PARTIAL | low-confidence heuristic only; it cannot read text and answers POSSIBLE_OVERLAY, NOT_DETECTED or NOT_ASSESSED |
| M9-7 | Near-duplicate detection | IMPLEMENTED, AUTOMATED TESTED (analyzer); the resized-copy backend integration test was run on the scratch database and passed | analyzer tests inside the 2775; thresholds calibrated on synthetic pictures |
| M9-8 | Findings with image number and kind, severity, why, fix; ranked | IMPLEMENTED, AUTOMATED TESTED | same |
| M9-9 | Marketplace requirements: verified official rules only, with source and date; otherwise NOT_ASSESSED | IMPLEMENTED, AUTOMATED TESTED. Marketplace image compliance is **NOT_ASSESSED** in the product today | no verified official image rule exists |
| M9-10 | Readiness: image quality beside readiness, photo points unchanged at 10 | IMPLEMENTED, AUTOMATED TESTED, INTEGRATION TESTED | slim-cmo readiness tests; backend M5 integration 20 passed and M9 chat file (before the duplicate change) |
| M9-11 | CEO chat: seven requests, one clarification, structured card, explicit photo-attachment button | IMPLEMENTED, INTEGRATION TESTED | `test_ceo_cmo_m9_images_chat.py` (with the 30 above) |
| M9-12 | Images page, gallery, score, dimensions, findings, compliance, history | IMPLEMENTED, AUTOMATED TESTED (component level) | full frontend suite 1166 passed after the duplicate change. **BROWSER VERIFIED: NO (NOT TESTED)** |
| M9-13 | Tenant isolation, FORCE RLS, append-only, audit, zero units, no model | IMPLEMENTED, INTEGRATION TESTED | privilege, RLS-flag, cross-tenant and zero-footprint assertions in the M9 integration files; migration up, down, up and refused-with-data on the scratch database |
| M9-14 | Regression of M6, M7 and M8 backend suites after M9 | NOT TESTED | the batch was not completed; M5 and the image-path suites were run earlier |
| M9-15 | Browser end-to-end | NOT TESTED | needs a signed-in test tenant (B7) |
