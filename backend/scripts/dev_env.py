"""Pure helpers for `run_dev.py`: say which database the dev backend will use, and warn when a stale shell variable overrides `backend/.env`.

`load_dotenv` never overrides a variable that is already set (the documented way to point a run at the scratch database), so a leftover `DATABASE_URL*` in a PowerShell session
silently wins over the file. These helpers print where each URL points (host, port, database and role: never the password) and flag a shell value that differs from the file."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

DATABASE_KEYS = ("DATABASE_URL", "DATABASE_URL_APP")


def target(url: str | None) -> str:
    """`role@host:port/database` of a database URL, without the password; 'not set' / 'unreadable' otherwise."""
    if not url:
        return "not set"
    try:
        parts = urlsplit(url)
        return f"{parts.username or '?'}@{parts.hostname or '?'}:{parts.port or '?'}/{parts.path.lstrip('/') or '?'}"
    except ValueError:
        return "unreadable"


def database_report(effective: Mapping[str, str | None], shell_before_load: Mapping[str, str | None], file_values: Mapping[str, str | None]) -> list[str]:
    """Lines to print at startup: where each URL points, and a WARNING for each one whose value came from the shell and differs from `backend/.env`."""
    lines = [f"[run_dev] {key} -> {target(effective.get(key))}" for key in DATABASE_KEYS]
    for key in DATABASE_KEYS:
        shell, from_file = shell_before_load.get(key), file_values.get(key)
        if shell and from_file and shell != from_file:
            lines.append(
                f"[run_dev] WARNING: {key} is set in this shell ({target(shell)}) and overrides backend/.env ({target(from_file)}). "
                f"To use the file, run: Remove-Item Env:DATABASE_URL,Env:DATABASE_URL_APP -ErrorAction SilentlyContinue"
            )
    return lines
