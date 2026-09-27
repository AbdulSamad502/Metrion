"""GST fetch allowlist — deterministic-engine.md §8.4.1's two named tiers. Hardcoded, not
configurable per tenant, not extendable at runtime — "No domain outside these two named lists
is ever added at runtime, by an LLM suggestion, or by following an off-allowlist redirect
target — the same rule `competitor_intelligence.capture.allowlist` already enforces for its
own domains."

This check runs before any fetch call in `lookup.py`, mirroring
`competitor_intelligence.capture.allowlist.is_allowed_host`'s role as "the first thing
evaluated in the capture pipeline."

`_HOST_TO_TIER` is the single source of truth for both "is this host trusted" and "which tier
does it belong to" — needed because §8.4.1 requires a consuming surface to treat a Tier 2 hit
as lower confidence than a Tier 1 hit, and `gst_lookup_result`'s own schema deliberately has no
tier column (§8.4.1: "until a following checkpoint adds one, the tier is inferable from
`source_url`'s host against the two named lists").
"""

from __future__ import annotations

from urllib.parse import urlsplit

TIER_1 = "TIER_1"  # official government sources
TIER_2 = "TIER_2"  # named secondary publishers

# Tier 1 — official government sources (§8.4.1). Included despite this session's own direct
# evidence that two of the three are stale/unreachable — see §8.4.1's "Judgment call" note;
# `known_pages.py` correspondingly has no Tier 1 known page yet.
_TIER_1_HOSTS: tuple[str, ...] = (
    "cbic-gst.gov.in",
    "taxinformation.cbic.gov.in",
    "gst.gov.in",
)

# Tier 2 — named secondary publishers (§8.4.1), the same seven domains already used as real
# seed sources in `hsn_gst_reference` (20260925_0007_hsn_gst_reference.py).
_TIER_2_HOSTS: tuple[str, ...] = (
    "cleartax.in",
    "taxguru.in",
    "getswipe.in",
    "busy.in",
    "gimbooks.com",
    "rushtax.app",
    "taxgarden.in",
)

_HOST_TO_TIER: dict[str, str] = {
    **{host: TIER_1 for host in _TIER_1_HOSTS},
    **{host: TIER_2 for host in _TIER_2_HOSTS},
}

ALLOWED_HOSTS: frozenset[str] = frozenset(_HOST_TO_TIER)


def _matching_allowed_host(host: str) -> str | None:
    host = host.lower()
    for allowed in _HOST_TO_TIER:
        if host == allowed or host.endswith(f".{allowed}"):
            return allowed
    return None


def is_allowed_gst_host(url: str) -> bool:
    """True if `url`'s host is one of `ALLOWED_HOSTS` or a subdomain of one. Anything else — a
    different TLD, a look-alike domain, a redirect target outside the allowlist — is
    rejected."""
    host = urlsplit(url).hostname
    if not host:
        return False
    return _matching_allowed_host(host) is not None


def tier_for_host(url: str) -> str | None:
    """The tier (`TIER_1`/`TIER_2`) a trusted host belongs to, or `None` if `url`'s host isn't
    allowed. Never raises — callers that need a refusal on `None` own that presentation
    choice, this function only classifies (same contract as
    `competitor_intelligence.capture.allowlist.marketplace_for_host`)."""
    host = urlsplit(url).hostname
    if not host:
        return None
    allowed = _matching_allowed_host(host)
    return _HOST_TO_TIER[allowed] if allowed else None
