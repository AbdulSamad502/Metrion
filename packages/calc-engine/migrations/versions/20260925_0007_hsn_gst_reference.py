"""hsn_gst_reference (§8.2.2) — curated HSN/SAC -> GST rate knowledge base, platform-owned,
seeded with real, publicly-sourced GST 2.0 reform rates.

**Table shape.** Mirrors `gst_slab_reference`/`fee_reference`'s precedent for platform-owned
reference data (`20260917_0001_engine_tables.py`): no `tenant_id` column, no RLS policy, and
`metrion_app` is granted `SELECT` only — this package never writes to it at application-code
time, seeding is a `metrion_migrate`-run data migration, same as `formula_definition`'s seed
(`20260917_0003_seed_formula_definitions.py`). Per §8.2.2, RLS context (`tenant_scope()`) is
still required to open any connection that reads this table, even though `tenant_id` plays no
role in its `WHERE` clause — the resolver enforces that, not this migration.

`hsn_code` is stored at whatever precision its real public source publishes (2-8 digits, not
forced to a fixed length) and matched by prefix in `resolve_hsn_gst_reference`
(`config_repo.py`), per §8.2.2's matching rule.

**Real, sourced seed data — why this table is seeded while `fee_reference` (§5.14) is not.**
GST rates by HSN chapter are public, government-published statutory law (CBIC notifications,
GST Council rate schedules), the same class of source `gst_slab_reference` already draws on —
unlike marketplace commission rates, which are private commercial data nobody can verify
without a real marketplace agreement. Every row below cites a real `source_url`, `retrieved_at`
= this migration's authoring date (2026-09-25), and `effective_from` = 2025-09-22, the real GST
2.0 reform's effective date confirmed via Notification 9/2025-Central Tax (Rate), dated
17 Sep 2025. Every row is seeded at `confidence = 'PROVISIONAL'` (the schema's own default) —
not `VERIFIED` — because the sources cited are secondary tax-advisory compilations (GetSwipe,
TaxGarden, RushTax, Busy, GimBooks), not the raw CBIC notification PDF text itself; that
distinction is honestly reflected in confidence, not smoothed over.

**Explicitly, deliberately NOT seeded in this pass — a real schema gap, not an oversight:**

1. **Apparel (HSN 61/62) and footwear (HSN 64).** The real, confirmed GST 2.0 rate for both is
   *price-conditional*, not a flat per-code rate: <=Rs.2,500 per piece/pair -> 5%, >Rs.2,500 -> 18%
   (Notification 9/2025, corroborated by businesstoday.in and caclubindia.com). This table's
   schema (§8.2.2) has no price-threshold column — seeding a single `rate_pct` for either code
   would silently misrepresent roughly half of all real transactions in that category. Not
   seeded this pass; the schema gap is a real, named follow-up, not something to force a wrong
   answer into.
2. **Toys (HSN 9503).** A same-code ambiguity of a different kind: non-electronic toys are 5%,
   electronic/battery-operated toys are 18%, both under the same HSN 9503 code (busy.in's toy
   rate page). The schema has no attribute qualifier to distinguish them. Not seeded, for the
   same reason as apparel/footwear.
3. **Notebooks vs. files/registers (HSN 4820).** The SAME 4-digit code covers both nil-rated
   notebooks/exercise books AND 18%-rated files/folders/registers per busy.in's own stationery
   page — a genuine sub-item ambiguity at 4-digit precision that would require a more specific
   8-digit code this research did not confidently source. Not seeded.

Nobody should re-add these three without first closing the underlying schema gap (a
price-threshold / attribute-qualifier column, and a more specific source for HSN 4820's
sub-items).

Revision ID: 20260925_0007
Revises: 20260925_0006
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260925_0007"
down_revision = "20260925_0006"
branch_labels = None
depends_on = None

_RETRIEVED_AT = "2026-09-25 00:00:00+00"
_EFFECTIVE_FROM = "2025-09-22"

# (hsn_code, description, rate_pct, source_url, source_title)
_SEED_ROWS: list[tuple[str, str, str, str, str]] = [
    (
        "8517",
        "Mobile phones and telephone sets",
        "18.0000",
        "https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — GetSwipe",
    ),
    (
        "8471",
        "Automatic data processing machines (laptops, computers, tablets, servers)",
        "18.0000",
        "https://taxgarden.in/blog/gst-on-mobile-phones-laptops-electronics-india-2026",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — TaxGarden",
    ),
    (
        "8528",
        "Monitors and television sets",
        "18.0000",
        "https://rushtax.app/gst-rates/electronics-appliances/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — RushTax",
    ),
    (
        "9608",
        "Pens, markers and highlighters (ball, gel, fountain pens; whiteboard markers; "
        "highlighters)",
        "18.0000",
        "https://busy.in/gst-rates/stationery/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — Busy Accounting Software",
    ),
    (
        "9609",
        "Pencils",
        "0.0000",
        "https://busy.in/gst-rates/stationery/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — Busy Accounting Software",
    ),
    (
        "4016",
        "Erasers (vulcanised rubber articles)",
        "0.0000",
        "https://busy.in/gst-rates/stationery/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — Busy Accounting Software",
    ),
    (
        "8214",
        "Pencil sharpeners",
        "0.0000",
        "https://busy.in/gst-rates/stationery/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — Busy Accounting Software",
    ),
    (
        "8305",
        "Paper clips and similar office articles of base metal",
        "18.0000",
        "https://busy.in/gst-rates/stationery/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — Busy Accounting Software",
    ),
    (
        "8213",
        "Scissors, tailors' shears and similar shears",
        "18.0000",
        "https://busy.in/gst-rates/stationery/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — Busy Accounting Software",
    ),
    (
        "3919",
        "Adhesive tape (self-adhesive plastic sheets/tape)",
        "18.0000",
        "https://busy.in/gst-rates/stationery/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — Busy Accounting Software",
    ),
    (
        "8470",
        "Calculators",
        "18.0000",
        "https://busy.in/gst-rates/stationery/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — Busy Accounting Software",
    ),
    (
        "8472",
        "Office machines (stapling machines and similar)",
        "18.0000",
        "https://busy.in/gst-rates/stationery/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — Busy Accounting Software",
    ),
    (
        "3401",
        "Soap and organic surface-active products for washing the skin",
        "5.0000",
        "https://www.gimbooks.com/blog/new-gst-rates-in-india-2025/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — GimBooks",
    ),
    (
        "3305",
        "Hair preparations (shampoo, hair oil)",
        "5.0000",
        "https://www.gimbooks.com/blog/new-gst-rates-in-india-2025/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — GimBooks",
    ),
    (
        "3306",
        "Oral or dental hygiene preparations (toothpaste)",
        "5.0000",
        "https://www.gimbooks.com/blog/new-gst-rates-in-india-2025/",
        "GST 2.0 rate reform, effective 22 Sep 2025 (Notification 9/2025-Central Tax (Rate), "
        "dated 17 Sep 2025) — GimBooks",
    ),
]

_INSERT_SQL = sa.text(
    """
    INSERT INTO hsn_gst_reference
        (hsn_code, description, rate_pct, source_url, source_title, retrieved_at,
         effective_from, version, confidence)
    VALUES
        (:hsn_code, :description, :rate_pct, :source_url, :source_title, :retrieved_at,
         :effective_from, 1, 'PROVISIONAL')
    """
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE hsn_gst_reference (
          id              uuid primary key default gen_random_uuid(),
          hsn_code        text not null,
          description     text not null,
          rate_pct        numeric(7,4) not null,
          source_url      text not null,
          source_title    text,
          retrieved_at    timestamptz not null,
          effective_from  date not null,
          effective_to    date,
          version         int not null,
          confidence      text not null default 'PROVISIONAL'
        );
        CREATE INDEX hsn_gst_reference_hsn_code_idx ON hsn_gst_reference (hsn_code);
        """
    )
    op.execute("GRANT SELECT ON hsn_gst_reference TO metrion_app;")

    bind = op.get_bind()
    for hsn_code, description, rate_pct, source_url, source_title in _SEED_ROWS:
        bind.execute(
            _INSERT_SQL,
            {
                "hsn_code": hsn_code,
                "description": description,
                "rate_pct": rate_pct,
                "source_url": source_url,
                "source_title": source_title,
                "retrieved_at": _RETRIEVED_AT,
                "effective_from": _EFFECTIVE_FROM,
            },
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hsn_gst_reference;")
