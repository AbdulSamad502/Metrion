"""Explains a Clerk rejection that is really a CLOCK problem.

A Clerk session token is only valid between its own `nbf`/`iat` and `exp` (a ~60s window), judged
against THIS machine's clock. If the machine's clock is off by more than the allowed leeway the
SDK rejects a perfectly good token as `token-not-active-yet`, `token-iat-in-the-future` or
`token-expired` — the signature, key and secret are all fine, so the generic 401 gives no hint.

This module reads ONLY the timing claims from the (unverified) token — never logs the token or any
other claim — and turns that into one actionable sentence for the server log. The client still
only ever sees the generic 401.
"""

from __future__ import annotations

import time

import jwt

# `TokenVerificationErrorReason` values (compared by name so this module has no SDK import cycle).
TIME_RELATED_REASONS = frozenset({"TOKEN_NOT_ACTIVE_YET", "TOKEN_IAT_IN_THE_FUTURE", "TOKEN_EXPIRED"})


def _reason_name(reason: object) -> str:
    return getattr(reason, "name", None) or str(reason).rsplit(".", 1)[-1].upper().replace("-", "_")


def is_time_related(reason: object) -> bool:
    return _reason_name(reason) in TIME_RELATED_REASONS


def clock_hint(authorization_header: str | None, *, leeway_ms: int, now: float | None = None) -> str | None:
    """A one-line explanation of how far this machine's clock is from the token's own timestamps, or
    None when there is nothing useful to say (no/undecodable token). `now` is injectable for tests."""
    if not authorization_header:
        return None
    token = authorization_header.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(token, options={"verify_signature": False, "verify_exp": False, "verify_nbf": False, "verify_iat": False})
    except jwt.PyJWTError:
        return None
    current = time.time() if now is None else now
    iat, exp = claims.get("iat"), claims.get("exp")
    if not isinstance(iat, (int, float)):
        return None

    ahead = iat - current  # >0: the token was issued "in the future" of this machine's clock
    if ahead > leeway_ms / 1000:
        return (
            f"The token was issued {ahead:.0f}s AFTER this machine's current time, so this machine's clock is about "
            f"{ahead:.0f}s BEHIND real time (allowed leeway {leeway_ms / 1000:.0f}s). Sync the system clock "
            "(Windows: `w32tm /resync`), or raise CLERK_CLOCK_SKEW_MS for local development."
        )
    if isinstance(exp, (int, float)) and current - exp > leeway_ms / 1000 and current - iat < 3600:
        late = current - exp
        return (
            f"The token expired {late:.0f}s ago by this machine's clock (allowed leeway {leeway_ms / 1000:.0f}s). If the "
            "browser just fetched it, this machine's clock is running AHEAD of real time; otherwise the page held a stale "
            "token. Sync the system clock, or raise CLERK_CLOCK_SKEW_MS for local development."
        )
    return None
