"""M8 defect found in the production-readiness review: `history()` pages newest-first across the WHOLE account, so reading it once with the page limit dropped the older versions of a quiet product when a
busy one had more than a page of versions. Products are now read group by group. Pure test: a stub history that truncates exactly like the real one."""

from __future__ import annotations

import uuid

from backend.services import cmo_perf_view


class StubHistory:
    MAX_PAGE = 3

    def __init__(self) -> None:
        self.rows = [{"id": f"a{i}", "number": i, "sku": "busy", "marketplace": "AMAZON", "createdAt": f"2026-10-{10 + i:02d}"} for i in range(1, 6)] + \
                    [{"id": f"q{i}", "number": i, "sku": "quiet", "marketplace": "AMAZON", "createdAt": f"2026-10-0{i}"} for i in (1, 2)]

    def history(self, tenant, *, sku=None, marketplace=None, limit=20, offset=0):
        rows = [r for r in self.rows if (sku is None or r["sku"] == sku) and (marketplace is None or r["marketplace"] == marketplace)]
        rows.sort(key=lambda r: r["createdAt"], reverse=True)
        limit = min(limit, self.MAX_PAGE)
        groups = [{"sku": k, "product": k.title(), "marketplace": "AMAZON"} for k in sorted({r["sku"] for r in rows})]
        return {"versions": rows[offset:offset + limit], "groups": groups}

    def product_versions(self, tenant, sku, marketplace):
        """Every version of ONE product, oldest first: no page limit (the real function reads that product in one query)."""
        return sorted((r for r in self.rows if r["sku"] == sku and r["marketplace"] == marketplace), key=lambda r: (r["number"], r["id"]))


def test_every_product_keeps_its_own_versions_even_when_another_product_fills_the_page(monkeypatch):
    monkeypatch.setattr(cmo_perf_view, "cmo_history", StubHistory())
    got = cmo_perf_view._products(uuid.uuid4())
    assert [v["number"] for v in got[("quiet", "AMAZON")]["versions"]] == [1, 2]  # the old single read returned only the newest 3 rows, all of them "busy"
    assert [v["number"] for v in got[("busy", "AMAZON")]["versions"]] == [1, 2, 3, 4, 5]  # all five, although the account-wide page holds only three: the one-page cap is gone
