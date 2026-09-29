"""seed gst_slab_reference + partial fee_reference — real, publicly-sourced rates only.

**gst_slab_reference (§8.2.1, U7).** Seeds the four GST 2.0 slabs — Nil, 5%, 18%, 40% — that
replaced the prior five-slab structure (0/5/12/18/28%) effective 22 Sep 2025, per the 56th GST
Council meeting (3 Sep 2025) implemented via Notification 9/2025-Central Tax (Rate), dated
17 Sep 2025 — the same notification `hsn_gst_reference`'s seed
(`20260925_0007_hsn_gst_reference.py`) already cites. This is a well-corroborated, structural
fact (four numbers, one effective date), independently confirmed across CBIC's own rate-schedule
portal reference and multiple tax-advisory sources (Cashfree, ClearTax, WiseMonk, TaxAJ) — unlike
the 12/28% predecessor slabs, which were retired for nearly all items, both are seeded here too
with an `effective_to` of 2025-09-21 so `gst_slabs_effective_on` correctly returns only the
current four for any `as_of_date` on or after the reform, while still letting a query for an
earlier date see the pre-reform structure. All rows seeded at `confidence = 'PROVISIONAL'`
(secondary tax-advisory corroboration, not the raw notification PDF text) — same honest posture
as `hsn_gst_reference`.

**fee_reference (§5.14, U8) — deliberately, mostly NOT seeded this pass.** Marketplace commission
schedules are private commercial data: Amazon's own official announcement
(aboutamazon.in/news/small-business/amazon-seller-fee-reduction-zero-referral-march-2026) and
Flipkart's official seller.flipkart.com/fees-and-commission page were both checked directly and
neither discloses exact per-category percentages without seller-account login — only illustrative
examples (e.g. "a ₹798 earphone sale saves ₹139"), not a citable `rate_pct`. Secondary
seller-tools sources (Shiprocket, ListingPilot, WareIQ, SellerShip, etc.) give ranges that
disagree with each other by category, which this table's schema (`rate_pct`) cannot honestly
express as a single number. Per CLAUDE.md's hard rule, none of that ambiguity is seeded.

The one exception: Meesho's 0% seller commission is a structural, headline fact stated
identically and specifically across every independent source checked (gonukkad.com, sellership.in,
swcybernetics.in, zesmack.com, blooprint.in, ecomvanshika.com) — not a per-category number in
dispute, so it is seeded at `confidence = 'PROVISIONAL'`, `category = '*'` (applies platform-wide).
Meesho's shipping/RTO/platform fees are explicitly NOT seeded — every source agrees they are
tiered by seller level, category, weight slab and pincode zone, with no single citable rate.

**Explicitly, deliberately NOT seeded — real gaps, not oversights:**
1. Amazon referral fee by category — gated behind Seller Central login on Amazon's own official
   pages; no primary source publishes the current post-March-2026 category rate card publicly.
2. Flipkart commission by category — same login-gating on Flipkart's own official seller page;
   secondary sources give wide, mutually inconsistent ranges (e.g. "3%-25%", "8%-15%" for the
   same category depending on source).
3. Meesho shipping/RTO/platform fees — explicitly tiered/variable per every source found, no
   single number to cite.
`resolve_fee_reference` correctly keeps returning `None` -> `UNAVAILABLE` for all of the above,
by design, not as a defect — `compute_pricing_curve` and any fee-dependent formula must keep
surfacing that gap honestly until a real marketplace agreement or verified rate card closes it.

Revision ID: 20260929_0011
Revises: 20260927_0010
Create Date: 2026-09-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260929_0011"
down_revision = "20260927_0010"
branch_labels = None
depends_on = None

_RETRIEVED_AT = "2026-09-29 00:00:00+00"
_REFORM_EFFECTIVE_FROM = "2025-09-22"
_REFORM_SOURCE_URL = "https://www.gstcouncil.gov.in/cgst-rate-notification"
_REFORM_SOURCE_TITLE = (
    "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
    "dated 17 Sep 2025, per the 56th GST Council meeting) — GST Council / CBIC rate-notification "
    "portal, corroborated by Cashfree, ClearTax, WiseMonk, TaxAJ"
)

# (rate_pct, label, effective_from, effective_to)
_GST_SLAB_ROWS: list[tuple[str, str, str, str | None]] = [
    ("0.0000", "Nil-rated", _REFORM_EFFECTIVE_FROM, None),
    ("5.0000", "Merit rate", _REFORM_EFFECTIVE_FROM, None),
    ("18.0000", "Standard rate", _REFORM_EFFECTIVE_FROM, None),
    ("40.0000", "Luxury / sin-goods rate", _REFORM_EFFECTIVE_FROM, None),
    # Pre-reform slabs, bounded to before the reform's effective date so a current-date query
    # never sees them (gst_slabs_effective_on's effective_to gate) — kept for historical as_of_date lookups only.
    ("12.0000", "Pre-reform standard rate (retired 2025-09-22)", "2017-07-01", "2025-09-21"),
    ("28.0000", "Pre-reform luxury rate (retired 2025-09-22)", "2017-07-01", "2025-09-21"),
]

_INSERT_SLAB_SQL = sa.text(
    """
    INSERT INTO gst_slab_reference
        (rate_pct, label, source_url, source_title, retrieved_at, effective_from, effective_to,
         version, confidence)
    VALUES
        (:rate_pct, :label, :source_url, :source_title, :retrieved_at, :effective_from,
         :effective_to, 1, 'PROVISIONAL')
    """
)

_INSERT_FEE_SQL = sa.text(
    """
    INSERT INTO fee_reference
        (marketplace, category, fee_type, rate_pct, effective_from, source, confidence, version,
         last_verified_at)
    VALUES
        (:marketplace, :category, :fee_type, :rate_pct, :effective_from, :source, 'PROVISIONAL', 1,
         :last_verified_at)
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    for rate_pct, label, effective_from, effective_to in _GST_SLAB_ROWS:
        bind.execute(
            _INSERT_SLAB_SQL,
            {
                "rate_pct": rate_pct,
                "label": label,
                "source_url": _REFORM_SOURCE_URL,
                "source_title": _REFORM_SOURCE_TITLE,
                "retrieved_at": _RETRIEVED_AT,
                "effective_from": effective_from,
                "effective_to": effective_to,
            },
        )

    bind.execute(
        _INSERT_FEE_SQL,
        {
            "marketplace": "meesho",
            "category": "*",
            "fee_type": "COMMISSION",
            "rate_pct": "0.0000",
            "effective_from": "2026-09-29",
            "source": (
                "Meesho charges 0% seller commission across all categories — corroborated "
                "identically across gonukkad.com, sellership.in, swcybernetics.in, "
                "tool.zesmack.com, blooprint.in and ecomvanshika.com seller-fee guides "
                "(checked 2026-09-29). Meesho's shipping/RTO/platform fees are NOT included: "
                "every source describes them as tiered by seller level, category, weight and "
                "pincode zone, with no single citable rate."
            ),
            "last_verified_at": _RETRIEVED_AT,
        },
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM fee_reference WHERE marketplace = 'meesho' AND category = '*' "
        "AND fee_type = 'COMMISSION';"
    )
    op.execute(f"DELETE FROM gst_slab_reference WHERE retrieved_at = '{_RETRIEVED_AT}';")
