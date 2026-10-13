"""Configuration of the read-only CMO showcase (docs/specs/ceo-cmo-delegation.md 6.9, 6.10, OQ-19). NO value has a code default: the spec leaves them to the owner,
so an unset value means "not configured", never a guessed number. Read on every call (cheap; keeps tests and operators honest).

  CMO_SHOWCASE_PAGE_LIMIT        cap (and default) page size of the list routes. Unset -> the list routes answer 503 CMO_NOT_CONFIGURED.
  CMO_FREQUENT_MIN_COUNT         minimum COPIED + MARKED_USED count for an item to count as "frequently used". Unset -> the frequent view is UNAVAILABLE.
  CMO_FREQUENT_LOOKBACK_DAYS     look-back window (days) for those events. Unset -> the frequent view is UNAVAILABLE.
  CMO_USAGE_EVENT_DEDUP_SECONDS  identical (actor, generation, option, part, kind) events inside this window collapse into one. Unset -> only the spec's
                                 fallback applies: an exact repeat within the same second is dropped, nothing wider.
A value that is present but not a positive integer is a configuration error (ValueError), never silently ignored."""

from __future__ import annotations

import os


def _optional_positive_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return value


def page_limit() -> int | None:
    return _optional_positive_int("CMO_SHOWCASE_PAGE_LIMIT")


def frequent_min_count() -> int | None:
    return _optional_positive_int("CMO_FREQUENT_MIN_COUNT")


def frequent_lookback_days() -> int | None:
    return _optional_positive_int("CMO_FREQUENT_LOOKBACK_DAYS")


def usage_dedup_seconds() -> int | None:
    return _optional_positive_int("CMO_USAGE_EVENT_DEDUP_SECONDS")
