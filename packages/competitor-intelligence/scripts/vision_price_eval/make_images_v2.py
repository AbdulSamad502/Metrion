"""Synthetic, fully-labelled evaluation set for the CI vision extractor (v2). Deterministic: no randomness, same output every run.

Why synthetic: the truth of every field is known BY CONSTRUCTION, so nothing here is a guess or a hand-typed label. It is NOT a substitute for real seller screenshots (spec Q7/Q18):
the layout is one clean template and the fonts are crisp. Read results as "can this model/prompt read digits off a clean listing", not as a population accuracy.

36 images in the same layout as `make_images.ps1` (that script's 22 price-format cases are cases 1-22 here) plus 14 harder categories. Pillow is used only by this script (it is already
a dependency of the slim-cmo package in this repository; nothing is added to any package).

    python make_images_v2.py --out <dir>      # writes <dir>/manifest.json and 36 PNGs
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 800
FONT_DIR = Path("C:/Windows/Fonts")
RUPEE = "\u20b9"
NAMES = ["Cotton Floral Kurti for Women", "Wireless Bluetooth Earbuds with Mic", "Stainless Steel Water Bottle 1L", "Men Running Shoes Lightweight"]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / ("segoeuib.ttf" if bold else "segoeui.ttf")), size)


def fmt(value: float, style: str) -> str:
    whole = int(value)
    commas = f"{whole:,}"
    if style == "symbol_comma":
        return f"{RUPEE}{commas}"
    if style == "rs_comma":
        return f"Rs. {commas}"
    if style == "plain":
        return str(whole)
    if style == "symbol_plain":
        return f"{RUPEE}{whole}"
    if style == "decimal":
        return f"{RUPEE}{commas}.00"
    if style == "decimal50":
        return f"{RUPEE}{commas}.50"
    raise ValueError(style)


def draw_listing(case: dict) -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((60, 50), f"{case['name']} - Pack of 2", font=font(30, True), fill="black")
    d.text((60, 140), case["price_text"], font=font(54, True), fill=(139, 0, 0))
    y = 240
    if case.get("mrp_text"):
        label = "M.R.P.: " + case["mrp_text"]
        d.text((60, y), label, font=font(26), fill=(105, 105, 105))
        box = d.textbbox((60, y), label, font=font(26))
        mid = (box[1] + box[3]) // 2
        d.line((box[0], mid, box[2], mid), fill=(105, 105, 105), width=2)
        d.text((60, 310), f"{case['pct']}% off", font=font(26), fill=(0, 100, 0))
    if case.get("rating_text"):
        d.text((60, 310 if not case.get("mrp_text") else 520), case["rating_text"], font=font(26), fill="black")
    d.text((60, 380), "In stock", font=font(26), fill=(0, 100, 0))
    d.text((60, 450), "Free delivery by Tuesday. Sold by StyleHub Retail.", font=font(26), fill="black")
    if case.get("also_bought"):
        d.text((60, 580), "Frequently bought together", font=font(24, True), fill="black")
        for i, p in enumerate(case["also_bought"]):
            d.text((60 + i * 360, 630), f"Other item {i + 1}", font=font(22), fill="black")
            d.text((60 + i * 360, 665), p, font=font(34, True), fill="black")
    return img


def truth(case: dict) -> dict:
    """Every field of the production schema, exactly as it is visible in the image (None = not shown, so a reported value is a false extraction)."""
    visible = not case.get("unreadable")
    return {
        "title": f"{case['name']} - Pack of 2" if visible else None,
        "listed_price_paise": round(case["price"] * 100) if visible else None,
        "mrp_paise": round(case["mrp"] * 100) if (visible and case.get("mrp")) else None,
        "visible_discount_paise": None,  # no rupee discount is ever printed; "NN% off" is a percentage
        "rating": case.get("rating"),
        "rating_count": case.get("rating_count"),
        "availability": "IN_STOCK",
        "seller_name": "StyleHub Retail",
        "description": None, "observed_category": None, "bullets": None,
    }


def cases() -> list[dict]:
    out: list[dict] = []

    def add(price, style, *, tags, mrp="auto", **extra):
        i = len(out)
        mrp_v = None if mrp is None else (round(price * 1.5 / 10) * 10 if mrp == "auto" else mrp)
        if mrp_v is not None and mrp_v <= price:
            mrp_v = price + 50
        pct = round(100 * (mrp_v - price) / mrp_v) if mrp_v else None
        out.append({"name": NAMES[i % 4], "price": price, "style": style, "mrp": mrp_v, "pct": pct, "price_text": fmt(price, style), "mrp_text": fmt(mrp_v, style) if mrp_v else None, "tags": tags, **extra})

    for p in (99, 129, 999, 1299, 1999, 12999):  # 1-18: the price-format cases of the previous evaluation
        for s in ("symbol_comma", "rs_comma", "plain"):
            add(p, s, tags=[f"digits{len(str(p))}", "format"])
    add(1299, "symbol_plain", tags=["digits4", "format"])  # 19-22
    add(12999, "symbol_plain", tags=["digits5", "format"])
    add(1299, "decimal", tags=["digits4", "format", "decimal"])
    add(999, "decimal", tags=["digits3", "format", "decimal"])
    add(24999, "decimal", tags=["digits5", "decimal"])  # 23-26: more 4/5-digit strings with decimals and separators
    add(10499.5, "decimal50", tags=["digits5", "decimal"])
    add(7499, "symbol_comma", tags=["digits4"])
    add(4599, "decimal", tags=["digits4", "decimal"])
    add(1299, "symbol_comma", mrp=None, tags=["digits4", "no_mrp"])  # 27-28: no MRP and no discount shown
    add(12999, "symbol_comma", mrp=None, tags=["digits5", "no_mrp"])
    add(899, "symbol_comma", tags=["digits3", "rating"], rating="4.3", rating_count=1234, rating_text="4.3 out of 5 stars   (1,234 ratings)")  # 29-30
    add(2499, "symbol_comma", tags=["digits4", "rating"], rating="3.8", rating_count=12408, rating_text="3.8 out of 5 stars   (12,408 ratings)")
    add(1299, "symbol_comma", tags=["digits4", "multi_price"], also_bought=[fmt(499, "symbol_comma"), fmt(1999, "symbol_comma")])  # 31-32: other prices on the page
    add(12999, "symbol_comma", tags=["digits5", "multi_price"], also_bought=[fmt(24999, "symbol_comma"), fmt(799, "symbol_comma")])
    add(1299, "symbol_comma", tags=["digits4", "blurred"], transform="blur")  # 33-34: degraded
    add(12999, "symbol_comma", tags=["digits5", "rotated"], transform="rotate")
    add(1299, "symbol_comma", tags=["digits4", "unreadable_price"], unreadable=True, transform="crop_bottom")  # 35-36: the price is not in the image at all
    add(12999, "symbol_comma", tags=["digits5", "unreadable_price"], unreadable=True, transform="crop_bottom")
    return out


def render(case: dict) -> Image.Image:
    img = draw_listing(case)
    t = case.get("transform")
    if t == "blur":
        img = img.filter(ImageFilter.GaussianBlur(radius=2.2))
    elif t == "rotate":
        img = img.rotate(4, expand=False, fillcolor="white", resample=Image.BICUBIC)
    elif t == "crop_bottom":
        img = img.crop((0, 300, W, H)).resize((W, H - 300))  # only the lower part of the page: no title, no price, no MRP
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, case in enumerate(cases()):
        name = f"v2_{i:02d}.png"
        render(case).save(args.out / name)
        expected = truth(case)
        if case.get("unreadable"):
            expected["rating"] = expected["rating_count"] = None
        manifest.append({"file": name, "tags": case["tags"], "price_text": case["price_text"], "expected": expected})
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(manifest)} images written to {args.out}")


if __name__ == "__main__":
    main()
