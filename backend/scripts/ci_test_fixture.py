"""Development-only: one clearly labelled, seller-entered TEST product for manual Competitor Intelligence testing, and its cleanup.

It writes ONE row to `seller_product_profile` (the seller-entered product profile, CI spec 5.5.1 source 2 / C31). It never writes `sales_line`, orders, revenue, costs or
inventory, so the CFO, profit and every financial report are untouched. The row is marked by its title ending "(CI TEST)" and its SKU prefix CI-TEST-.

    python backend/scripts/ci_test_fixture.py create  --tenant <tenant uuid>
    python backend/scripts/ci_test_fixture.py status  --tenant <tenant uuid>
    python backend/scripts/ci_test_fixture.py remove  --tenant <tenant uuid> [--archive-competitors]

Uses DATABASE_URL (the migration role) from the environment or backend/.env. Refuses to run unless the database host is local.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import create_engine, text

SKU = "CI-TEST-BOTTLE-001"
TITLE = "Steel Water Bottle 1L (CI TEST)"
MARKER = "(CI TEST)"  # the fixture is recognised by this suffix in its own title (never searched: query building drops bracketed notes)
ATTRIBUTES = [
    {"key": "title", "value": TITLE},
    {"key": "material", "value": "Stainless Steel"},
    {"key": "capacity", "value": "1 Litre"},
]
KEYWORDS = ["steel water bottle", "1 litre bottle", "stainless steel bottle"]
PRICE_PAISE = 39900


def _url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        env = Path(__file__).resolve().parents[1] / ".env"
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip()
    if not url:
        sys.exit("DATABASE_URL is not set")
    host = urlparse(url.replace("postgresql+psycopg", "postgresql")).hostname
    if host not in ("localhost", "127.0.0.1", "::1"):
        sys.exit(f"refusing to run against a non-local database host: {host}")
    return url


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("create", "status", "remove"))
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--archive-competitors", action="store_true", help="with remove: also archive competitors tracked for the test product")
    a = ap.parse_args()
    tenant = str(UUID(a.tenant))
    engine = create_engine(_url())
    with engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant})
        existing = conn.execute(text("SELECT product_id, attributes FROM seller_product_profile WHERE tenant_id = :t AND product_id = :p"), {"t": tenant, "p": SKU}).first()
        if a.action == "status":
            print("present" if existing else "absent", "| tracked competitors:", conn.execute(text("SELECT count(*) FROM competitor_url WHERE tenant_id = :t AND linked_sku = :p AND status = 'ACTIVE'"), {"t": tenant, "p": SKU}).scalar_one())
            return 0
        if a.action == "create":
            if existing is not None and not any(MARKER in str((x or {}).get("value", "")) for x in (existing[1] or [])):
                sys.exit(f"a profile with product id {SKU} already exists and is NOT a test fixture; refusing to overwrite it")
            owner = conn.execute(text("SELECT app_user_id FROM membership WHERE tenant_id = :t AND status = 'ACTIVE' ORDER BY (role = 'OWNER') DESC, joined_at LIMIT 1"), {"t": tenant}).scalar()
            if owner is None:
                sys.exit("that tenant has no member to attribute the profile to; check the tenant id")
            conn.execute(
                text(
                    "INSERT INTO seller_product_profile (tenant_id, product_id, category, attributes, keywords, price_paise, fulfillment_type, updated_by, updated_at) "
                    "VALUES (:t, :p, 'Water Bottles', CAST(:attrs AS jsonb), CAST(:kw AS text[]), :price, NULL, :by, now()) "
                    "ON CONFLICT (tenant_id, product_id) DO UPDATE SET category = EXCLUDED.category, attributes = EXCLUDED.attributes, keywords = EXCLUDED.keywords, "
                    "price_paise = EXCLUDED.price_paise, updated_at = now()"
                ),
                {"t": tenant, "p": SKU, "attrs": json.dumps(ATTRIBUTES), "kw": KEYWORDS, "price": PRICE_PAISE, "by": str(owner)},
            )
            print(f"created test product {SKU!r} ({TITLE}) for tenant {tenant}")
            return 0
        # remove
        if existing is not None and not any(MARKER in str((x or {}).get("value", "")) for x in (existing[1] or [])):
            sys.exit(f"the profile {SKU} is not marked as a test fixture; refusing to delete it")
        n = conn.execute(text("DELETE FROM seller_product_profile WHERE tenant_id = :t AND product_id = :p"), {"t": tenant, "p": SKU}).rowcount
        arch = 0
        if a.archive_competitors:
            arch = conn.execute(text("UPDATE competitor_url SET status = 'ARCHIVED' WHERE tenant_id = :t AND linked_sku = :p AND status = 'ACTIVE'"), {"t": tenant, "p": SKU}).rowcount
        print(f"removed {n} test profile row(s); archived {arch} competitor(s) tracked for it")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
