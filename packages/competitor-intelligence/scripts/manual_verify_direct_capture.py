"""Manual verification script for Step 5 of the CI implementation plan.

Exercises the direct-path capture flow (ci.capture_run) end-to-end against a REAL local
Postgres, using an in-memory fixture Fetcher/Parser — never a real request to amazon.in,
flipkart.com, or meesho.com, per the explicit constraint on this pass. Prints each check's
result; exits non-zero if any assertion fails.

Requires DATABASE_URL / DATABASE_URL_APP set, and migrations already applied to head.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from competitor_intelligence.capture.fetcher import FetchError, RawPage
from competitor_intelligence.capture.parser import ParseError, ParsedListing
from competitor_intelligence.direct_path.capture_run import run_direct_capture
from competitor_intelligence.repositories import competitor_url_repo
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import Availability, Confidence, Marketplace, RunStatus


@dataclass
class FixtureFetcher:
    responses: dict[str, RawPage | FetchError] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def fetch(self, url: str) -> RawPage | FetchError:
        self.calls.append(url)
        return self.responses.get(url, FetchError(reason="no fixture registered"))


@dataclass
class FixtureParser:
    responses: dict[str, ParsedListing | ParseError] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def parse(self, page: RawPage, marketplace) -> ParsedListing | ParseError:
        self.calls.append(page.url)
        return self.responses.get(page.url, ParseError(reason="no fixture registered"))


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Manual verification FAILED at: {label}")


def main() -> None:
    tenant_id = uuid.uuid4()
    requested_by = uuid.uuid4()
    fetcher = FixtureFetcher()
    parser = FixtureParser()

    print(f"tenant_id = {tenant_id}")

    # --- 1. Confirm a non-allowlisted domain is rejected before any network call --------
    bad_url = "https://not-a-real-marketplace.example/listing"
    bad_url_id = competitor_url_repo.create_url(
        tenant_id, marketplace=Marketplace.AMAZON, url=bad_url, added_by=requested_by
    )
    result = run_direct_capture(
        tenant_id,
        requested_by=requested_by,
        url_ids=[bad_url_id],
        permission_check="PASS",
        entitlement_check="PASS",
        fetcher=fetcher,
        parser=parser,
        now=datetime.now(timezone.utc),
    )
    check("non-allowlisted URL rejected: fetcher never called", fetcher.calls == [])
    check("non-allowlisted URL rejected: parser never called", parser.calls == [])
    with tenant_scope(tenant_id) as conn:
        snap = conn.execute(
            text("SELECT capture_status FROM competitor_snapshot WHERE id = :id"),
            {"id": str(result.snapshot_ids[0])},
        ).mappings().one()
    check("non-allowlisted URL snapshot marked BLOCKED", snap["capture_status"] == "BLOCKED")

    # --- 2. First capture (allowlisted, fixture page) -> baseline snapshot, no event ----
    url = "https://amazon.in/dp/manual-verify-fixture"
    url_id = competitor_url_repo.create_url(
        tenant_id, marketplace=Marketplace.AMAZON, url=url, added_by=requested_by
    )
    t0 = datetime.now(timezone.utc)
    fetcher.responses[url] = RawPage(url=url, status_code=200, body="<html/>", fetched_at=t0)
    parser.responses[url] = ParsedListing(
        seller_name="Fixture Seller",
        observed_category="Footwear",
        category_confidence=Confidence.OBSERVED,
        listed_price_paise=100000,
        mrp_paise=120000,
        visible_discount_paise=0,
        rating=Decimal("4.0"),
        rating_count=10,
        availability=Availability.IN_STOCK,
        variant_key=None,
    )
    first = run_direct_capture(
        tenant_id,
        requested_by=requested_by,
        url_ids=[url_id],
        permission_check="PASS",
        entitlement_check="PASS",
        fetcher=fetcher,
        parser=parser,
        now=t0,
    )
    check("first capture status COMPLETE", first.status == RunStatus.COMPLETE)
    check("first capture wrote exactly one snapshot", len(first.snapshot_ids) == 1)
    check("first capture created no price event (baseline only, E5)", first.price_event_ids == [])

    with tenant_scope(tenant_id) as conn:
        snap = conn.execute(
            text(
                "SELECT capture_status, listed_price_paise, confidence FROM competitor_snapshot WHERE id = :id"
            ),
            {"id": str(first.snapshot_ids[0])},
        ).mappings().one()
    check("first snapshot capture_status OK", snap["capture_status"] == "OK")
    check("first snapshot listed_price_paise == 100000", snap["listed_price_paise"] == 100000)
    check("first snapshot confidence OBSERVED", snap["confidence"] == "OBSERVED")

    with tenant_scope(tenant_id) as conn:
        run_row = conn.execute(
            text(
                "SELECT agent_id, trigger_type, parent_run_id, status FROM agent_run WHERE id = :id"
            ),
            {"id": str(first.agent_run_id)},
        ).mappings().one()
    check("agent_run.agent_id == 'CI'", run_row["agent_id"] == "CI")
    check("agent_run.trigger_type == 'DIRECT'", run_row["trigger_type"] == "DIRECT")
    check("agent_run.parent_run_id IS NULL", run_row["parent_run_id"] is None)
    check("agent_run.status == 'COMPLETE'", run_row["status"] == "COMPLETE")

    # --- 3. Second capture, price drops 20% -> price event, threshold breached ----------
    t1 = t0 + timedelta(hours=6)
    parser.responses[url] = ParsedListing(
        seller_name="Fixture Seller",
        observed_category="Footwear",
        category_confidence=Confidence.OBSERVED,
        listed_price_paise=80000,
        mrp_paise=120000,
        visible_discount_paise=0,
        rating=Decimal("4.0"),
        rating_count=10,
        availability=Availability.IN_STOCK,
        variant_key=None,
    )
    second = run_direct_capture(
        tenant_id,
        requested_by=requested_by,
        url_ids=[url_id],
        permission_check="PASS",
        entitlement_check="PASS",
        fetcher=fetcher,
        parser=parser,
        now=t1,
    )
    check("second capture created exactly one price event", len(second.price_event_ids) == 1)
    with tenant_scope(tenant_id) as conn:
        event = conn.execute(
            text(
                "SELECT delta_pct, direction, threshold_breached FROM competitor_price_event WHERE id = :id"
            ),
            {"id": str(second.price_event_ids[0])},
        ).mappings().one()
    check("price event delta_pct == -20.00", Decimal(str(event["delta_pct"])) == Decimal("-20.00"))
    check("price event direction == DECREASE", event["direction"] == "DECREASE")
    check("price event threshold_breached == True", event["threshold_breached"] is True)

    # --- 4. Third capture, price moves 1% -> event created but NOT breached -------------
    t2 = t1 + timedelta(hours=6)
    parser.responses[url] = ParsedListing(
        seller_name="Fixture Seller",
        observed_category="Footwear",
        category_confidence=Confidence.OBSERVED,
        listed_price_paise=79200,  # -1% from 80000
        mrp_paise=120000,
        visible_discount_paise=0,
        rating=Decimal("4.0"),
        rating_count=10,
        availability=Availability.IN_STOCK,
        variant_key=None,
    )
    third = run_direct_capture(
        tenant_id,
        requested_by=requested_by,
        url_ids=[url_id],
        permission_check="PASS",
        entitlement_check="PASS",
        fetcher=fetcher,
        parser=parser,
        now=t2,
    )
    check("third capture (below threshold) still created one event", len(third.price_event_ids) == 1)
    with tenant_scope(tenant_id) as conn:
        event3 = conn.execute(
            text("SELECT threshold_breached FROM competitor_price_event WHERE id = :id"),
            {"id": str(third.price_event_ids[0])},
        ).mappings().one()
    check("third event threshold_breached == False", event3["threshold_breached"] is False)

    print("\nAll manual verification checks PASSED.")


if __name__ == "__main__":
    main()
