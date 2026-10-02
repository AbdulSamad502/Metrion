# Vision price-extraction evaluation

Measures how well the **production** vision extraction (`evidence/vision_extractor.py`: same prompt,
same parser, same model via `CI_VISION_MODEL`) reads prices off listing screenshots whose true
price is known. Built to answer spec open questions **Q7 / Q18** with evidence instead of guesses.

```powershell
# 1. a synthetic set (known prices 99 … 12,999 in several formats, with an MRP and "% off")
.\make_images.ps1 -W 1280 -OutDir .\eval_images

# 2. run the production request against it (resumable; writes eval_<condition>.jsonl next to the images)
python run_eval.py --images .\eval_images\w1280 --condition default
python run_eval.py --images .\eval_images\w1280 --condition json_format --start 9 --limit 21
```

For **real** screenshots (what Q7 actually needs), put them in a folder with a hand-written
`manifest.json` of the same shape: `[{"file": "...", "expected_price_rupees": 1299,
"expected_mrp_rupees": 1999 /* or null */, "style": "real", "rendered_price": "₹1,299"}]`.

## What it found (2026-10-02, llava 7B Q4 via Ollama 0.35, CPU-only i5-12450H, synthetic set)

Small samples on one synthetic layout — evidence, not a population accuracy.

- **Price read correctly 13/31** (default prompt). By length of the true price:
  2-digit 3/6, 3-digit 9/13, **4-digit 1/8, 5-digit 0/4**. Dominant error: dropped digits
  (₹12,999 → ₹1,299; ₹1,999 → ₹199).
- **MRP correct 0/31.** Fields absent from the screenshot were reported anyway: rating 55%,
  rating count 48%, description 42%, bullets 32%, a rupee discount 23%.
- **Resolution does not matter**: first 9 images 6/9 at both 1280 and 640 px. Ollama feeds this
  model a fixed small image input (prompt token count is a constant 974 for every image).
- **No setting fixed it** on the 12 hard (4-5 digit) images: default 1/12, `format: json` 3/12,
  `temperature: 0` 1/12 — same digit-loss pattern in all three.
- **A second, price-only read is not a validator**: it agreed with the main read on 7/22
  images and 4 of those 7 agreements were wrong.
- Latency: see the hardening report; measure on an idle machine — anything else using the CPU
  inflates prompt evaluation several-fold.
