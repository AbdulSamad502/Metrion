"""Who owns a RUNNING `agent_run`? (R5)

A run row written `RUNNING` says only "no terminal write yet", never "somebody is still working on it". This module supplies the missing ownership
evidence without a schema change and without a timeout: while a process works on a run it holds a Postgres SESSION-level advisory lock keyed by the run id.

* The lock is taken BEFORE the row is inserted (`agent_run_repo.insert_run`), so a visible `RUNNING` row always had an owner at that moment.
* It is released AFTER the terminal write (`finish_run*`), so a finisher that wins can never be mistaken for a dead one.
* A process that dies (kill, crash, lost connection) releases it automatically: the session ends. A run that is slow or hung inside a LIVE process keeps it, and is
  therefore never touched here (a hung live leg is the separate, opt-in hard-deadline policy in `ceo/deadlines.py`).
* All locks of a process share ONE dedicated autocommit connection (not one pooled connection per run), so a busy process cannot exhaust the pool through this.

If that connection is lost while the process lives, the next claim/release re-opens it and re-takes the locks of the runs still held. In the gap those runs look
ownerless; a sweep that lands there settles them `INTERRUPTED`, which is the conservative outcome (a late real result can no longer overwrite it).

`is_owned_elsewhere(run_id)` is the question a sweeper asks: it probes with a SEPARATE session, so it answers correctly even for a lock held by its own process.
"""

from __future__ import annotations

import logging
import threading
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.repositories.ceo_runtime_repo import AdvisoryLock
from backend.tenant_context import get_engine

logger = logging.getLogger(__name__)

_SQL_TRY = text("SELECT pg_try_advisory_lock(hashtextextended(:k, 0))")
_SQL_UNLOCK = text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))")

_mutex = threading.RLock()
_conn: Connection | None = None
_held: set[str] = set()


def _key(run_id: UUID, kind: str = "agent_run") -> str:
    return f"{kind}:{run_id}"


def _connection() -> Connection:
    """The process's liveness connection; (re)opened on demand, re-taking the locks of runs still held."""
    global _conn
    if _conn is not None and not _conn.closed:
        try:
            _conn.execute(text("SELECT 1"))
            return _conn
        except Exception:  # noqa: BLE001 — the session is gone: its locks are gone with it
            logger.warning("run-liveness connection lost; re-opening and re-taking %d lock(s)", len(_held))
            try:
                _conn.close()
            except Exception:  # noqa: BLE001
                pass
            _conn = None
    _conn = get_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
    for k in sorted(_held):
        _conn.execute(_SQL_TRY, {"k": k})
    return _conn


def claim(run_id: UUID, kind: str = "agent_run") -> None:
    """Take ownership of `run_id` for this process. Call BEFORE the row is inserted. Raises when the database is unreachable (no row is then written either)."""
    with _mutex:
        k = _key(run_id, kind)
        got = bool(_connection().execute(_SQL_TRY, {"k": k}).scalar())
        if not got:  # a fresh uuid cannot already be held: refuse rather than start a run whose ownership is unprovable
            raise RuntimeError(f"run {run_id} is already owned")
        _held.add(k)


def release(run_id: UUID, kind: str = "agent_run") -> None:
    """Give up ownership after the terminal write. Never raises: a failed release only means the lock ends with the session."""
    with _mutex:
        k = _key(run_id, kind)
        if k not in _held:
            return
        _held.discard(k)
        try:
            _connection().execute(_SQL_UNLOCK, {"k": k})
        except Exception:  # noqa: BLE001
            logger.warning("could not release the liveness lock of run %s; it ends with the session", run_id)


def is_owned_elsewhere(run_id: UUID, kind: str = "agent_run") -> bool:
    """True when some live session holds the run's lock (the run has an owner). False when the lock is free: nobody is working on it."""
    with AdvisoryLock(_key(run_id, kind)) as probe:  # `with` releases a lock it took BEFORE the pooled connection goes back (closing does not end a pooled session)
        return not probe.try_acquire()


def held_count() -> int:
    """Runs this process currently owns (diagnostics)."""
    with _mutex:
        return len(_held)


def _reset_for_tests() -> None:
    global _conn
    with _mutex:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:  # noqa: BLE001
                pass
        _conn = None
        _held.clear()


# The specialist packages never import the backend. They expose `ownership.claim` / `ownership.release` (no-ops by default) around their own RUNNING rows;
# the backend plugs these in so every row they start is owned exactly like an `agent_run`.
PACKAGE_RUN_KINDS = ("reconciliation_run", "ci_capture_run")


def install_package_ownership() -> None:
    """Idempotent. Plugs the liveness lock into calc-engine's `reconciliation_run` and competitor-intelligence's `ci_capture_run`."""
    from calc_engine import ownership as calc_ownership
    from competitor_intelligence import ownership as ci_ownership

    for module, kind in ((calc_ownership, "reconciliation_run"), (ci_ownership, "ci_capture_run")):
        module.claim = lambda run_id, _k=kind: claim(run_id, _k)
        module.release = lambda run_id, _k=kind: release(run_id, _k)
