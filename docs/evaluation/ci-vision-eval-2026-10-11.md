# Competitor-evidence vision extraction: measured accuracy (2026-10-11)

**Status: PARTIALLY FIXED. No trustworthy accuracy improvement is demonstrated, and the candidate prompt is NOT adopted.** Real-model measurement, one model, one run per condition, 36 synthetic images. Production-adoption review: 2026-10-11 (second pass; every number below was re-derived from the recorded raw replies, see "Re-verification").

## What this pipeline is (and is not)

Product Intelligence (`packages/product-intelligence`) contains **no image understanding**. Its images are Tavily/YouTube hotlinks matched to candidates by text containment
(`candidate_synthesis.py`, spec C8); its embeddings are text-only (`nomic-embed-text` over derived title attributes). The only code that reads **pixels** for product/price facts is
Competitor Intelligence's evidence extractor: `competitor_intelligence/evidence/vision_extractor.py` (+ `ollama_client.py`), reached through the CI evidence flow and the old
`/ceo-hub` research session. `ci.research_now` stays unwired and was not touched. Slim CMO has a separate vision path (listing image hints) that was not evaluated.

Pipeline: stored image bytes → one Ollama `/api/generate` call (`CI_VISION_MODEL`, fixed prompt, default sampling, no preprocessing; Ollama feeds the model a fixed-size image,
974 prompt tokens regardless of resolution) → first JSON object in the reply → typed parsing (rupees→paise in Python) → fields labelled `VISION_EXTRACTED` → disagreement across screenshots
becomes UNAVAILABLE (`merge.py`). There is no OCR stage. Extracted values never carry a verified label.

## Dataset and scoring (reproducible)

* `scripts/vision_price_eval/make_images_v2.py --out <dir>`: 36 deterministic synthetic listing screenshots, labels known by construction (not hand-typed). Cases 1-22 reproduce the
  previous evaluation's price-format cases (re-rendered with Pillow, so **not byte-identical and not directly comparable** to the historical 13/31; that 31-image set and its result files
  are not in the repository). Plus 14 harder cases: 5-digit decimals, no MRP, rating shown, other prices on the page, blur, rotation, and **2 images with the price cropped out**.
* **Synthetic and clean: this is not real seller screenshots** (spec Q7/Q18 still needs those). It measures digit reading and unsupported-value behaviour on one template.
* `run_eval_v2.py` records raw replies; `score_v2.py` scores offline. Rule per (image, field): CORRECT / WRONG / MISSED / CORRECT_ABSENT / FALSE_EXTRACTION. Exact match; prices integer paise;
  a plausible guess is never correct; model confidence is never used. Denominators: **34** images show a price. The **2 excluded** (v2_34, v2_35) have the price cropped out, so the right
  answer is "unknown"; they are scored separately as unreadable-value handling.
* Model: `llava:latest` (7B Q4) through local Ollama, CPU only. (`CI_VISION_MODEL=qwen2.5vl-manual` in `.env.example` is not installed on this machine.) Roughly 60-140 s per image.
* Data preserved: `docs/evaluation/ci-vision-eval-2026-10-11/` (manifest, both raw reply files, both prompts, every score JSON).

## Results: four comparisons, full 36 images

| | Price exact (of 34) | Price wrong | Price missed | Unreadable→unknown (of 2) | Extraction failures (of 36) | False extractions (of 220 absent fields) |
|---|---|---|---|---|---|---|
| A. baseline prompt, original extractor | **8** | 26 | 0 | 0 | 0 | 98 |
| B. baseline replies, validator | 8 | 26 | 0 | 0 | 0 | 89 |
| C. candidate prompt, original extractor | **12** | 20 | 2 | 1 (artifact, see below) | 3 | 92 |
| D. candidate replies, validator | 12 | 20 | 2 | 1 (artifact) | 3 | 71 |

Failure accounting for C/D (3 extraction failures of 36): `v2_18` and `v2_20` (priced images) were unparseable replies (the model echoed the prompt's angle-bracket placeholders as pseudo-XML), counted as MISSED prices; `v2_35` (a price-cropped image) hit the 900 s read timeout, so no value was produced. A timeout is an
**extraction failure, not a judgement that the price is unreadable**: the "1 of 2" in the unreadable column is that timeout. Genuine unreadable-value handling is therefore A/B 0 of 2 and C/D 0 of 1 answered (plus 1 timeout excluded); baseline had 0 timeouts and 0 unparseable replies.

By price length (correct incl. correct-unknown), A → C: 2-digit 1/3 → 1/3, 3-digit 6/8 → 4/8, **4-digit 1/15 → 7/15**, 5-digit 0/10 → 1/10.
Other fields (A → C): availability 19/36 → 26/36; MRP exact 0/32 → 1/32 but **MRP wrong 2/32 → 18/32** (the candidate reports an MRP far more often, mostly wrongly);
`visible_discount` false extraction 7/36 → 18/36; title exact ≈ 0 in both (1/34, 0/34).

12-image coverage subset (fixed by category before scoring: indexes 0,3,9,15,20,23,26,28,30,32,33,35; 11 show a price): A 1/11, B 1/11, C 3/11, D 3/11; false extractions 40/74, 38/74, 17/74, 14/74. Same direction as the full set.

## Is the candidate's gain real? (paired analysis, same 34 priced images)

Both right 5; only the baseline right 3; only the candidate right 7. Exact McNemar two-sided p = 0.34 (Fisher exact on 8/34 vs 12/34: p = 0.43). With one run per condition and default sampling the +4 cannot be told from run-to-run variation.
Reported-price precision (correct among prices actually reported): A 8/36 = 22 %, C 12/33 = 36 %; the candidate reports more prices and also more wrong MRPs (18/32) and invented discounts (18/36 vs 7/36).

## What can and cannot be claimed

* **Candidate prompt: +4 exact prices of 34 (8 → 12).** Concentrated in 4-digit prices; 3-digit prices got worse. One run, n = 34, default sampling, no repeat to estimate variance: this is
  **not** evidence of a real improvement. It also has new defects: 3 extraction failures (two replies echoed the angle-bracket placeholders as pseudo-XML, `<number>1,299</number>`, which is not
  JSON; one call hit the 900 s timeout), many more wrong MRPs, and more invented discounts. **It was not adopted.** Production still uses the baseline prompt.
* **Unreadable-value handling did not improve.** The "1 of 2" in C/D comes entirely from the timeout (no reply counts as no value). On the cropped images the baseline invented a price
  both times (999, the number in the prompt's own example) and the candidate invented 2,500 on the one it answered. Genuine result: 0/2 for both.
* **Prompt contamination is real.** 17 of 36 baseline prices were 999 or 199 (the prompt's example neighbourhood), including for ₹99 and ₹129 images.
* **Digit loss is real.** ₹12,999 read as 1,299; ₹1,999 as 199. Exact 4/5-digit accuracy in production configuration is 1/15 and 0/10.

## The deterministic validator (production change) - rule-by-rule decision

Every removal returns in `ReplyAnalysis.suppressed`, is logged against the screenshot, and is scored by `score_v2.py` as right / wrong / unsupported. A rule only ever REMOVES a value; none changes or adds one (property test).
Independent audit of each rule against the labelled replies (the audit re-parses every recorded reply with the original and the current parser and attributes each difference; no inference):

| Rule | Baseline replies: removed (correct / wrong / unsupported) | Candidate replies: removed (correct / wrong / unsupported) | Decision |
|---|---|---|---|
| zero `rating` ("not shown" written as 0) | 0 / 1 / 3 | 0 / 0 / 6 | **Kept**: removes only placeholders; no correct value lost |
| zero `rating_count` | 0 / 1 / 2 | 0 / 0 / 6 | **Kept**; known limitation: a true "no ratings yet" (0) becomes unknown, never a stored zero (no such case in the set) |
| `visible_discount` <= 0 or >= price | 0 / 0 / 4 | 0 / 0 / 9 | **Kept**: logically impossible readings; 13 unsupported values removed, 0 correct |
| price > MRP (drop both) | never fired (0 of 3 replies with both fields) | never fired (0 of 20) | **NOT adopted** (see below) |
| price / MRP / "NN% off" cross-check | (measured on candidate replies: 4 correct, 11 wrong removed, precision unchanged) | | **Removed** earlier, absent from production code (asserted by a test) |

**`price > MRP` is implemented but not a production rule** (`OPTIONAL_RULES`, enabled only per call). It never fired, so no benefit is measured, and its failure mode is the one that retired the percent rule: when it fires, the MRP is the field the model misreads most (18 of 32 on the candidate prompt),
so it would discard a correct price together with a wrong MRP. Hiding a possibly-correct price on no evidence is not justified. The stored score files are unchanged by this decision (the rule never fired); re-scoring all eight combinations reproduces them byte for byte.

Net effect of the shipped validator on the baseline prompt (A to B): false extractions 98 to 89 of 220, **no change in exact price accuracy (8/34), no correct value lost**. It does not make prices more accurate; it stops some unsupported values from being stored.
Two parser defects found by adversarial tests were fixed (a JSON object or list was read as a number, so `{"a":1}` became rupee 1; a negative percentage read as positive).

## Tests

Mocked/hand-written (no model): `tests/unit/test_vision_validation.py` (legitimate values kept, contradictions removed visibly, boundary and hostile inputs, a property test that validation never
alters or adds a value) and the existing `test_vision_extractor.py`. Real-model: only the scripts above; no test asserts model accuracy.

## Re-verification (2026-10-11)

* All eight scoring combinations (full and 12-image subset x baseline/candidate replies x original/current extractor) were re-run offline from `raw_baseline.jsonl` / `raw_cand1.jsonl` and are identical to the stored `score_*.json`.
* Per-rule attribution and the price>MRP firing count come from `scripts/vision_price_eval` code paths plus a throw-away audit that imports the legacy snapshot and the production extractor; it needs no model.
* Not measured: any configuration with a different prompt, model, image preprocessing or repeat run; variance of any condition; real seller screenshots.

## Production adoption decision

| Change | Decision | Why |
|---|---|---|
| Candidate prompt (`prompt_candidate1.txt`) | **Rejected, artifacts preserved** | +4 exact prices (p = 0.34, one run), but 3 extraction failures (2 pseudo-XML, 1 timeout), MRP wrong 2 to 18 of 32, invented discounts 7 to 18 of 36, 3-digit prices worse, unreadable handling not improved |
| Zero-placeholder drops, discount rule, safer number parsing, suppression logging | **Adopted** | 0 correct values removed on 72 replies; false extraction 98 to 89 of 220 |
| `price > MRP` rule | **Not adopted (opt-in only)** | never fired; failure mode unmeasured |
| Percent cross-check | **Removed** | measured to remove correct values as often as wrong ones |
| Image preprocessing / tiling, other vision model, OCR | **Not done** | each needs a dependency or provider decision |

Real-model accuracy improvement demonstrated: **none**. Safety improvement demonstrated: unsupported placeholder values are no longer stored (9 of 220 absent-field extractions on the baseline replies, 21 of 220 on the candidate replies), with no correct value lost.

## Remaining gaps and decisions

* Real seller screenshots (Q7/Q18) are needed; this set cannot say how the model does on messy listings.
* The 4/5-digit failure is a model/input-resolution limit. Candidate remedies need decisions: cropping/tiling the image (needs an image library in the CI package: a dependency), a different local vision
  model (the configured `qwen2.5vl-manual` is not installed; `qwen3.5:4b` is installed but untested), or OCR (new engine). None was added.
* A prompt re-test would need a prompt without angle-bracket placeholders and ≥3 repeat runs per condition (about 75 minutes each on this CPU) to separate a real gain from run-to-run variation.
* Until accuracy is shown, extracted prices must stay labelled `VISION_EXTRACTED` (they are) and must not be presented as verified.
