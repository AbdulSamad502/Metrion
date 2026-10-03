"""The permission grid — auth.md §5.2. A fixed enum, not a config file: the key space is
part of the spec, not something an operator edits at runtime.

D4: a new PARTNER's `membership.permissions` starts as `{}` (deny-all). OWNER holds every
permission implicitly and is never checked against the grid at all (§5.2: "OWNER holds every
permission implicitly and is not configurable").
"""

from __future__ import annotations

# fmt: off
DASHBOARD_VIEW = "dashboard.view"
FILES_UPLOAD = "files.upload"
FILES_VIEW = "files.view"
FILES_DELETE = "files.delete"
INVESTIGATION_CREATE = "investigation.create"
INVESTIGATION_VIEW = "investigation.view"
AGENT_CEO = "agent.ceo"
AGENT_PI = "agent.pi"
AGENT_CI = "agent.ci"
AGENT_CFO = "agent.cfo"
AGENT_CMO = "agent.cmo"
REPORT_DOWNLOAD = "report.download"
FINANCIALS_ADJUST = "financials.adjust"
SERVICE_GST_LOOKUP = "service.gst_lookup"
RESEARCH_NICHE_RUN = "research.niche_run"
RESEARCH_MARKET_TRENDS = "research.market_trends"  # auth.md §5.2 (2026-10-03): shared Market Signal Retrieval service
WHATSAPP_USE = "whatsapp.use"
USAGE_VIEW = "usage.view"
BILLING_VIEW = "billing.view"
TEAM_MANAGE = "team.manage"
# fmt: on

ALL_KEYS = frozenset(
    {
        DASHBOARD_VIEW, FILES_UPLOAD, FILES_VIEW, FILES_DELETE, INVESTIGATION_CREATE,
        INVESTIGATION_VIEW, AGENT_CEO, AGENT_PI, AGENT_CI, AGENT_CFO, AGENT_CMO,
        REPORT_DOWNLOAD, FINANCIALS_ADJUST, SERVICE_GST_LOOKUP, RESEARCH_NICHE_RUN,
        RESEARCH_MARKET_TRENDS, WHATSAPP_USE, USAGE_VIEW, BILLING_VIEW, TEAM_MANAGE,
    }
)

OWNER_ROLE = "OWNER"
PARTNER_ROLE = "PARTNER"

DENY_ALL_GRID: dict[str, bool] = {}


def has_permission(*, role: str, permissions: dict[str, object], key: str) -> bool:
    """§5.2: OWNER holds every permission implicitly, unconditionally. PARTNER is checked
    against their stored grid, where an absent key means denied (D4)."""
    if role == OWNER_ROLE:
        return True
    return bool(permissions.get(key, False))
