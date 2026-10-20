"""business_profile: the seller's own description of their business (docs/specs/business-profile.md section 5)

One row per tenant. Tenant-owned: ENABLE + FORCE ROW LEVEL SECURITY with the same `tenant_isolation` policy as the other tables. The database re-enforces the
all-fields-mandatory rule: every column is NOT NULL with no default and every text/enum/set has a CHECK, so a blank or missing field cannot be stored even by a code path
that skipped the API's validation. The application role may SELECT, INSERT and UPDATE only (no DELETE / TRUNCATE; the 0007 / 0014 lesson that default privileges
hand it full CRUD on a new table).

Revision ID: 20261020_0022
Revises: 20261014_0021
Create Date: 2026-10-20
"""
from __future__ import annotations

from alembic import op

revision = "20261020_0022"
down_revision = "20261014_0021"
branch_labels = None
depends_on = None

# Keep in step with backend.services.business_profile.STATES (a unit test compares them).
STATES = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
)
_TENANT = "tenant_id = current_setting('app.current_tenant_id', true)::uuid"


def upgrade() -> None:
    states = ",".join("'" + s + "'" for s in STATES)
    op.execute(
        """
        CREATE FUNCTION business_profile_markets_ok(m text[]) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
          SELECT m IS NOT NULL AND cardinality(m) BETWEEN 1 AND 3 AND m <@ ARRAY['AMAZON','FLIPKART','MEESHO']::text[]
                 AND cardinality(m) = (SELECT count(DISTINCT x) FROM unnest(m) AS x)
        $$
        """
    )
    op.execute(
        f"""
        CREATE TABLE business_profile (
          tenant_id        uuid primary key references tenant(id),
          business_name    text not null,
          description      text not null,
          categories       text not null,
          marketplaces     text[] not null,
          price_segment    text not null,
          target_customer  text not null,
          business_stage   text not null,
          state            text not null,
          created_at       timestamptz not null default now(),
          updated_at       timestamptz not null default now(),
          updated_by       uuid,
          CONSTRAINT business_profile_name_check     CHECK (btrim(business_name) <> '' AND char_length(business_name) <= 120),
          CONSTRAINT business_profile_desc_check     CHECK (char_length(btrim(description)) >= 10 AND char_length(description) <= 300),
          CONSTRAINT business_profile_cats_check     CHECK (char_length(btrim(categories)) >= 2 AND char_length(categories) <= 150),
          CONSTRAINT business_profile_customer_check CHECK (char_length(btrim(target_customer)) >= 2 AND char_length(target_customer) <= 150),
          CONSTRAINT business_profile_markets_check  CHECK (business_profile_markets_ok(marketplaces)),
          CONSTRAINT business_profile_segment_check  CHECK (price_segment IN ('BUDGET','MID_RANGE','PREMIUM')),
          CONSTRAINT business_profile_stage_check    CHECK (business_stage IN ('JUST_STARTING','GROWING','ESTABLISHED')),
          CONSTRAINT business_profile_state_check    CHECK (state IN ({states}))
        );
        ALTER TABLE business_profile ENABLE ROW LEVEL SECURITY;
        ALTER TABLE business_profile FORCE  ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON business_profile
          USING      ({_TENANT})
          WITH CHECK ({_TENANT});
        REVOKE DELETE, TRUNCATE ON business_profile FROM metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS business_profile")
    op.execute("DROP FUNCTION IF EXISTS business_profile_markets_ok(text[])")
