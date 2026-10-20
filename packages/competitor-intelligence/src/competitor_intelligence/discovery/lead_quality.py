"""What makes a search lead worth showing a seller as a competitor (owner decision 2026-10-20: the top matches must be genuine, branded businesses, not junk listings).

Pure, deterministic text rules over the title a search returned (nothing is fetched or scraped):

* `clean_title` - the name as a seller would say it: no "Buy ...", no site suffix, no trailing "...".
* `is_junk` - books / e-books, keyword-stuffed titles, and titles too short to name a product are never surfaced.
* `brand_of` - the business or trademark name a title starts with ("MILTON", "Reebok", "The Better Home"), or None when the title starts with generic words ("Budget Men's Shoes").
* `KNOWN_BRANDS` - well-known brands sellers in these categories actually compete with; a small, explicit boost list (not a verification of anything).
* `lead_label` - the name a tracked competitor is shown under: the brand first, then a short product name.

None of this proves a business is genuine or successful (only the marketplace could say that); it removes what is plainly not a competing brand and puts the recognisable ones first."""

from __future__ import annotations

import re

_GENERIC = frozenset("""
a an the best top new latest buy cheap budget premium pack set of for with and or in on at by from your my our all any one two three four five six
men mens men's man women womens women's woman ladies girls girl boys boy kids kid unisex adult
stainless steel water bottle bottles shoes shoe sneakers sneaker running walking casual sports sport formal party daily wear footwear sandals slippers slipper flip flops
comfortable stylish trendy flexible lightweight ultralight elegant designer fashion fashionable branded original genuine quality durable portable leak proof leakproof insulated
black white blue red green grey gray brown silver gold pink yellow orange purple navy tan beige
kitchen item items utensil utensils jewellery jewelry jewellries jewelleries artificial earrings necklace bracelet ring rings set combo
tshirt t-shirt tshirts shirt shirts polo polos jeans pants trouser trousers jacket hoodie
free delivery sale offer deal discount size large medium small
""".split())
_JUNK = re.compile(r"\b(?:e-?book|kindle|paperback|hardcover|audiobook|pdf|novel|guide to|how to)\b", re.IGNORECASE)
_SITE_SUFFIX = re.compile(r"\s*(?:[:|\-–]\s*)?(?:amazon\.in|flipkart\.com|meesho)\b.*$", re.IGNORECASE)
_PREFIX = re.compile(r"^(?:buy|shop|order|get)\s+|^amazon brand\s*[-–:]\s*", re.IGNORECASE)

KNOWN_BRANDS = frozenset(b.casefold() for b in """
Milton Cello Borosil Tupperware Prestige Hawkins Pigeon Wonderchef Butterfly Bajaj Philips Havells Usha Crompton Nippon Signoraware Jaypee Solimo Amazon Basics Lock&Lock Thermos Stanley Hydro
Puma Nike Adidas Reebok Skechers Campus Bata Liberty Paragon Sparx Asian Woodland Red Tape Lee Cooper Fila Under Armour New Balance Crocs Relaxo Walkaroo Metro Mochi Aldo
Wildcraft Safari Skybags American Tourister Samsonite VIP Aristocrat Lavie
Allen Solly Van Heusen Peter England Louis Philippe Raymond Levis Wrangler Pepe Jeans US Polo Assn Jockey Roadster Highlander HRX Wrogn Flying Machine Spykar Mufti
Zaveri Pearls Tanishq Kalyan Voylla Sukkhi Giva Fabindia Biba Libas W Aurelia
Cult Boat Noise Mi Samsung Realme OnePlus Sony Prestige
""".replace("\n", " ").split(" ") if b)
# multi-word names above were split on spaces on purpose: a lead matches when its FIRST word is one of these (e.g. "Peter", "Under", "New"), which is the usual shape of a brand-first title


def clean_title(title: str | None) -> str:
    t = " ".join((title or "").split())
    t = _PREFIX.sub("", t)
    t = _SITE_SUFFIX.sub("", t)
    t = re.sub(r"\s*(?:\.{2,}|…)\s*$", "", t).strip(" |-–:,")
    return t


def is_junk(title: str | None) -> bool:
    """True for a lead that is plainly not a competing product listing: a book, a keyword-stuffed title, or a title too short to name a product."""
    t = clean_title(title)
    if not t:
        return False  # no title came back: there is nothing to judge, and the identity check treats it as uncertain
    if len(t.split()) < 3 or _JUNK.search(t):
        return True
    if t.count(",") >= 3 or t.count("|") >= 4:  # "men casual shoes, men sneakers, stylish shoes for ..." is a search-keyword dump, not a product name
        return True
    return False


def brand_of(title: str | None) -> str | None:
    """The brand a title leads with, or None. A title that starts with generic product words has no brand to speak of."""
    words = clean_title(title).split()
    if not words:
        return None
    first = words[0].strip(",.:;|()[]")
    if first.casefold() == "the" and len(words) >= 3:
        return " ".join(w.strip(",.:;|()[]") for w in words[:3])  # "The Better Home"
    if not first or first.casefold() in _GENERIC or first[0].isdigit() or len(first) < 2:
        return None
    return first


def is_known_brand(title: str | None) -> bool:
    b = brand_of(title)
    return bool(b) and b.split()[0].casefold() in KNOWN_BRANDS


def lead_label(title: str | None, max_len: int = 70) -> str:
    """The name a competitor is tracked under: the brand first, then a short product name ("MILTON Glide 1000 Stainless Steel Water Bottle")."""
    t = clean_title(title)
    t = re.split(r"\s+[|]\s+", t)[0]
    if len(t) > max_len:
        t = t[:max_len].rsplit(" ", 1)[0]
    return t.strip(" ,-–:") or "Competitor"


def rank_key(title: str | None, relevance: int) -> tuple[int, int, int]:
    """Sort key (higher first): recognisable brand, then any brand, then how well the title matches the category."""
    return (1 if is_known_brand(title) else 0, 1 if brand_of(title) else 0, relevance)
