"""Source identity for trend evidence (spec §6.8.4): what counts as one independent source.

Pure functions. No network: the Public Suffix List ships inside the `publicsuffixlist` wheel and
is read from disk. Nothing here fetches a URL; it only reads the string it was handed.

The rule everything else rests on: **several items from one source are one source**. So the
independence key is deliberately COARSE - when ownership cannot be established the key merges
rather than splits, which can only under-count independence, never over-count it:

* Web: the registrable domain of the URL as returned (`news.bbc.co.uk` and `www.bbc.co.uk` ->
  `bbc.co.uk`; `a.blogspot.com` and `b.blogspot.com` stay distinct because the PSL's private
  section treats each blog as its own site; `medium.com/@x` and `medium.com/@y` merge because
  Medium is one domain). Redirects are not followed; syndication across different domains
  is handled separately by title (see evidence.collapse_syndicated).
* Video: the channel (id if available, else the normalised channel title); a video with
  neither is grouped with every other anonymous video from the same platform.
* IP-literal hosts are their own key; single-label hosts (`localhost`) are their own key.

Known, printed limitation: two different domains owned by one company are counted as two
sources. That cannot be detected offline and is stated in the evidence section of every report.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum
from functools import lru_cache
from urllib.parse import urlsplit

from publicsuffixlist import PublicSuffixList

from slim_cmo.textnorm import dedupe_key


class SourceType(str, Enum):
    WEB = "WEB"
    VIDEO = "VIDEO"


class SourceClass(str, Enum):
    OFFICIAL_MARKETPLACE = "OFFICIAL_MARKETPLACE"
    THIRD_PARTY = "THIRD_PARTY"


@dataclass(frozen=True, slots=True)
class SourceItem:
    url: str
    source_type: SourceType
    retrieved_at: datetime
    title: str | None = None
    published_at: datetime | None = None
    channel_id: str | None = None
    channel_title: str | None = None


# Hosts that are the same platform under different registrable domains.
_PLATFORM_ALIASES: dict[str, str] = {
    "youtu.be": "youtube.com",
    "youtube-nocookie.com": "youtube.com",
}


@lru_cache(maxsize=1)
def _psl() -> PublicSuffixList:
    return PublicSuffixList()


def _host(url: str) -> str | None:
    """Lower-cased ASCII (IDNA) hostname of an http(s) URL, or None if it is not a usable URL."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host:
        return None
    host = host.rstrip(".")
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        return host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None


def registrable_domain(url: str) -> str | None:
    """The registrable domain ('eTLD+1', private suffixes honoured) of `url`, or None if the URL
    is unusable. IP literals and single-label hosts return the host itself."""
    host = _host(url)
    if host is None:
        return None
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    domain = _psl().privatesuffix(host)
    domain = domain if domain else host
    return _PLATFORM_ALIASES.get(domain, domain)


def is_citable(item: SourceItem) -> bool:
    """A source can be cited only if it has a real http(s) URL. A finding with no citable
    source is dropped, not asserted (spec §6.8.7 rule 2)."""
    return registrable_domain(item.url) is not None


def independence_key(item: SourceItem) -> str:
    domain = registrable_domain(item.url)
    if domain is None:
        raise ValueError("an uncitable item has no independence key")
    if item.source_type is SourceType.WEB:
        return f"web:{domain}"
    channel_id = (item.channel_id or "").strip()
    if channel_id:
        return f"video:{domain}:channel:{channel_id}"
    channel = dedupe_key(item.channel_title or "")
    if channel:
        return f"video:{domain}:channel_title:{channel}"
    return f"video:{domain}:unknown"


def normalise_title(title: str | None) -> str:
    """Equality key for syndicated-copy detection: identical words in identical order, ignoring
    case, punctuation, spacing and Unicode form. Empty if there is nothing to compare (an
    untitled item is never collapsed into another)."""
    return dedupe_key(title) if title else ""


def classify_source(item: SourceItem, official_domains: frozenset[str]) -> SourceClass:
    """OFFICIAL_MARKETPLACE only if the item's host is, or is a subdomain of, a configured
    official domain. With no configured domains nothing is ever official (fail-safe)."""
    host = _host(item.url)
    if host is None or not official_domains:
        return SourceClass.THIRD_PARTY
    for d in official_domains:
        d = d.strip().lower().rstrip(".")
        if host == d or host.endswith("." + d):
            return SourceClass.OFFICIAL_MARKETPLACE
    return SourceClass.THIRD_PARTY


def parse_published_date(raw: str | None) -> datetime | None:
    """Parse a provider's publication-date string into an aware UTC datetime, or None.

    ISO-8601 (including a trailing 'Z' and date-only) and RFC-2822 are understood. Date-only
    values become midnight UTC. A value with no timezone is taken as UTC. Anything else - empty,
    garbage, an impossible date - is None: an unparseable date is NEVER guessed, and the item is
    then treated as DATE_UNKNOWN (spec §6.8.4)."""
    if raw is None or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
