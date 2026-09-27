"""Known static reference pages per allowlisted domain — §8.4.1's "fetch known static
reference pages, let the LLM extract from within the fetched content" mechanism (option (b),
the chosen V1 shape).

Per §8.4.1: "The concrete set of known pages per domain [...] is an implementation-time
artefact, not enumerated exhaustively in this spec [...] expected to grow/be corrected as
pages are actually inspected." Seeded here from the exact `source_url`s this session already
verified fetchable once, cited in
`packages/calc-engine/migrations/versions/20260925_0007_hsn_gst_reference.py`'s real seed
rows — not invented. No Tier 1 known page is seeded: this session's own direct evidence
(§8.4.1's own domain-status table) is that `cbic-gst.gov.in` returns only a stub redirect and
`taxinformation.cbic.gov.in` fails TLS verification, and `gst.gov.in`'s fetchability was never
verified — seeding a guessed Tier 1 URL would violate the "do not invent URLs you haven't
verified exist" instruction. Per §8.4.1's own fallback ("G2's V1 behaviour degrades to Tier 2
only for that query [...] rather than blocking"), this is the expected V1 shape, not an
oversight.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KnownPage:
    """One hardcoded static reference page. `category` is a free-text hint matched against
    `GstLookupQuery.category`/`product_title` in `lookup.py` (case-insensitive substring) to
    decide which known pages are relevant to a given query — not a controlled vocabulary,
    since the underlying pages themselves cover an open-ended set of product categories."""

    domain: str
    category: str
    url: str
    source_title: str


# Every URL below is a real `source_url` already cited in the G1 migration
# (20260925_0007_hsn_gst_reference.py) — this session's own verified-fetchable set, not a
# guess. Order here has no significance; `lookup.py` sorts by tier (Tier 1 before Tier 2, per
# §8.4.1's "Tier 1 then Tier 2 order") before iterating.
KNOWN_PAGES: tuple[KnownPage, ...] = (
    KnownPage(
        domain="getswipe.in",
        category="mobile phones and telephone sets",
        url="https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517",
        source_title="GetSwipe — Telephone/mobile phone GST rate and HSN code",
    ),
    KnownPage(
        domain="taxgarden.in",
        category="electronics: mobile phones, laptops, computers, tablets",
        url="https://taxgarden.in/blog/gst-on-mobile-phones-laptops-electronics-india-2026",
        source_title="TaxGarden — GST on mobile phones, laptops and electronics",
    ),
    KnownPage(
        domain="rushtax.app",
        category="electronics and appliances: monitors, television sets",
        url="https://rushtax.app/gst-rates/electronics-appliances/",
        source_title="RushTax — GST rates on electronics and appliances",
    ),
    KnownPage(
        domain="busy.in",
        category=(
            "stationery: pens, pencils, erasers, sharpeners, paper clips, scissors, "
            "adhesive tape, calculators, office machines"
        ),
        url="https://busy.in/gst-rates/stationery/",
        source_title="Busy Accounting Software — GST rates on stationery",
    ),
    KnownPage(
        domain="gimbooks.com",
        category="personal care: soap, hair preparations, oral/dental hygiene preparations",
        url="https://www.gimbooks.com/blog/new-gst-rates-in-india-2025/",
        source_title="GimBooks — New GST rates in India 2025",
    ),
)
