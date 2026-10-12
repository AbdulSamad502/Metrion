"""READ-ONLY inventory of what the database holds for one tenant, by table, with the data category each table belongs to.

This is the factual basis for the retention / erasure decision (docs/planning/stages-3-4-5-report-2026-10-12.md, "Retention and erasure"). It deletes and changes nothing: it only
counts rows, as the OWNER role, under that tenant's context (FORCE RLS applies to the owner as well).

    python scripts/tenant_data_inventory.py <tenant-uuid>          # DATABASE_URL = the owner role; the database it reads is printed first
"""

from __future__ import annotations

import os
import sys
from uuid import UUID

from sqlalchemy import create_engine, make_url, text

# Category per table. A table with a tenant_id column that is not listed shows as "UNCLASSIFIED" so a new table cannot be silently left out of the retention discussion.
CATEGORY = {
    "CONVERSATION": ("investigation", "investigation_message", "investigation_turn", "investigation_finding", "investigation_agent", "investigation_attachment", "ceo_need"),
    "SELLER_MEMORY_AND_SHARED_FACTS": ("agent_memory", "shared_finding", "seller_fact"),
    "EXECUTION_RECORD": ("agent_run", "agent_data_request"),
    "BILLING_AND_AUDIT": ("metered_event", "auth_audit", "cmo_quota_reservation", "tenant_plan", "tenant_cart_item", "member_entitlement_allocation"),
    "UPLOADED_FINANCIAL_DATA": ("report_file", "ingestion_run", "sales_line", "settlement_line", "line_component", "validation_finding", "report_period", "manual_adjustment"),
    "DERIVED_FINANCIAL_RESULTS": ("metric_result", "leak_finding", "reconciliation_run", "reconciliation_match", "reconciliation_exception", "gst_lookup_result", "product_feasibility_estimate"),
    "COMPETITOR_AND_PRODUCT_DATA": (
        "competitor_url", "competitor_snapshot", "competitor_snapshot_field", "competitor_evidence", "competitor_price_event", "competitor_listing_insight",
        "competitor_review_insight", "ci_candidate", "ci_candidate_relevance", "ci_capture_run", "ci_discovery_run", "ci_search_query", "ci_search_result",
        "ci_digest_subscription", "ci_tenant_config", "niche_brief", "pi_research_run", "product_candidate", "product_embedding", "product_review_insight", "supplier_lead",
        "pi_tenant_config", "seller_product_profile",
    ),
    "CREATIVE_AND_IMAGES": ("cmo_generation", "cmo_title_approval", "cmo_title_option", "cmo_trend_report", "cmo_niche_term", "product_image_analysis", "seller_image_asset"),
    "ACCOUNT": ("membership", "whatsapp_binding", "whatsapp_message", "whatsapp_alert_subscription", "whatsapp_pending_action"),
}
CONFIG_OR_OTHER = ("anomaly_detection_config", "financial_health_config", "reconciliation_tolerance_config", "severity_config", "discount_bearer_config", "entitlement_cap_config",
                   "capability_entitlement_rule", "metered_event_meter_map", "cmo_platform_config")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    tenant = UUID(argv[1])
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL (the owner role) is not set", file=sys.stderr)
        return 2
    target = make_url(url)
    print(f"database: host={target.host} port={target.port} name={target.database}  tenant={tenant}  (read-only)")
    by_table = {t: c for c, tables in CATEGORY.items() for t in tables}
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            tables = [r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'tenant_id' ORDER BY table_name"))]
        rows: list[tuple[str, str, int]] = []
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            conn.execute(text("SET TRANSACTION READ ONLY"))
            for t in tables:
                n = conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()  # noqa: S608 - names come from the catalog
                rows.append((by_table.get(t, "CONFIGURATION" if t in CONFIG_OR_OTHER else "UNCLASSIFIED"), t, n))
    finally:
        engine.dispose()
    current = None
    for cat, t, n in sorted(rows):
        if cat != current:
            print(f"\n[{cat}]")
            current = cat
        print(f"  {t:36s} {n:>8d}")
    unclassified = [t for c, t, _ in rows if c == "UNCLASSIFIED"]
    if unclassified:
        print(f"\nUNCLASSIFIED tables (add them to CATEGORY): {', '.join(unclassified)}")
    print("\nFiles outside the database (not counted here): CFO uploads (CFO_REPORT_DIR), CI evidence images (CI_EVIDENCE_DIR), CMO images (CMO_IMAGE_DIR).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
