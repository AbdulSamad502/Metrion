"""A guard so the integration suite cannot be pointed at the development database by accident.

The suite's cleanup fixtures delete rows (platform config, and tenants and users the test created), and several modules run unscoped `DELETE`s. They are written for the
throwaway scratch database (`backend/scripts/scratch_db.sh`, port 5544). The development database listens on 5432, which is also what a URL with no port means, so
both are refused unless `METRION_TESTS_ALLOW_DEV_DB=1` is set on purpose."""

from __future__ import annotations

import os
from collections.abc import Mapping

from sqlalchemy.engine import make_url

DEV_DB_PORT = 5432
OVERRIDE = "METRION_TESTS_ALLOW_DEV_DB"
URL_VARIABLES = ("DATABASE_URL_APP", "DATABASE_URL")


def development_database_urls(env: Mapping[str, str] | None = None) -> list[str]:
    """The names of the configured database variables that point at the development port (or at no port, which defaults to it)."""
    env = os.environ if env is None else env
    out = []
    for name in URL_VARIABLES:
        value = env.get(name)
        if not value:
            continue
        try:
            port = make_url(value).port
        except Exception:  # an unparsable URL is not one we can call safe
            out.append(name)
            continue
        if port is None or port == DEV_DB_PORT:
            out.append(name)
    return out


def refusal(env: Mapping[str, str] | None = None) -> str | None:
    """The message to stop the session with, or None when the configuration is acceptable."""
    env = os.environ if env is None else env
    if env.get(OVERRIDE) == "1":
        return None
    bad = development_database_urls(env)
    if not bad:
        return None
    return (
        f"Refusing to run the integration suite: {', '.join(bad)} points at port {DEV_DB_PORT} (the development database, or a URL with no port). "
        "Use the scratch database: `bash backend/scripts/scratch_db.sh up`, then `eval \"$(bash backend/scripts/scratch_db.sh env)\"` (port 5544). "
        f"Set {OVERRIDE}=1 only if you really mean it."
    )
