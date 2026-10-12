"""R5 lease design: evidence that the PostgreSQL primitives the design relies on behave as assumed (lease design §14.1 V1, V3, V4; D-L2, D-L6).

THIS IS A SPIKE, NOT PRODUCT CODE. It builds a throwaway tables (`r5_spike_lease`, `r5_spike_result`; the migrate role cannot create schemas) on the SCRATCH database, exercises raw SQL from several real connections, and drops
the schema. It adds no migration, no table to the application schema and no application code, and it does not accept D-L1/D-L2/D-L10: it only shows what the
database guarantees so the owner's decision can rest on facts. It refuses to run unless the connection is the scratch database on port 5544.

What it demonstrates:
 1. a session-level advisory lock is held for exactly as long as its connection lives: a competing `pg_try_advisory_lock` fails while the owner is alive and
    succeeds once the owner's backend is terminated (crash / dropped connection), with no timeout anywhere;
 2. a check-then-write fence WITHOUT a row lock lets a revoked (stale) owner's write land (the hazard);
 3. the fence `SELECT ... FOR SHARE` + epoch check inside the writing transaction rejects a stale owner and makes a concurrent revoke wait for the write;
 4. completion racing revocation has exactly one winner (compare-and-set on `epoch`/`state`);
 5. a constraint trigger can make terminal states immutable even against a direct `UPDATE` (the D-L6 / Q-A10 shape).
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

TERMINAL = ("SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN", "INTERRUPTED")


@pytest.fixture
def db(migrate_engine):
    if migrate_engine.url.port != 5544:
        pytest.skip("R5 spike runs only against the scratch database on port 5544")
    with migrate_engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS r5_spike_result, r5_spike_lease CASCADE"))
        c.execute(text("DROP FUNCTION IF EXISTS r5_spike_no_leaving_terminal() CASCADE"))
        c.execute(text(f"CREATE TABLE r5_spike_lease (id uuid PRIMARY KEY, epoch int NOT NULL DEFAULT 1, state text NOT NULL DEFAULT 'CLAIMED')"))
        c.execute(text(f"CREATE TABLE r5_spike_result (lease_id uuid NOT NULL, epoch int NOT NULL, payload text NOT NULL)"))
    yield migrate_engine
    with migrate_engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS r5_spike_result, r5_spike_lease CASCADE"))
        c.execute(text("DROP FUNCTION IF EXISTS r5_spike_no_leaving_terminal() CASCADE"))


def new_lease(db) -> uuid.UUID:
    lease_id = uuid.uuid4()
    with db.begin() as c:
        c.execute(text(f"INSERT INTO r5_spike_lease (id) VALUES (:i)"), {"i": str(lease_id)})
    return lease_id


def results(db, lease_id) -> list[int]:
    with db.connect() as c:
        return [r[0] for r in c.execute(text(f"SELECT epoch FROM r5_spike_result WHERE lease_id = :i ORDER BY epoch"), {"i": str(lease_id)})]


def lease_row(db, lease_id) -> tuple[int, str]:
    with db.connect() as c:
        return tuple(c.execute(text(f"SELECT epoch, state FROM r5_spike_lease WHERE id = :i"), {"i": str(lease_id)}).one())  # type: ignore[return-value]


def revoke(db, lease_id) -> bool:
    """Take ownership away: bump the epoch of a non-terminal lease."""
    with db.begin() as c:
        return bool(c.execute(text(f"UPDATE r5_spike_lease SET epoch = epoch + 1, state = 'INTERRUPTED' WHERE id = :i AND state = 'CLAIMED'"), {"i": str(lease_id)}).rowcount)


def fenced_write(db, lease_id, epoch: int, payload: str, *, hold: threading.Event | None = None, entered: threading.Event | None = None) -> bool:
    """The proposed `fenced_scope`: check the epoch under FOR SHARE in the SAME transaction as the write."""
    with db.connect() as c:
        with c.begin():
            row = c.execute(
                text(f"SELECT 1 FROM r5_spike_lease WHERE id = :i AND epoch = :e AND state = 'CLAIMED' FOR SHARE"), {"i": str(lease_id), "e": epoch}
            ).first()
            if row is None:
                return False
            if entered is not None:
                entered.set()
            if hold is not None:
                hold.wait(timeout=10)
            c.execute(text(f"INSERT INTO r5_spike_result (lease_id, epoch, payload) VALUES (:i, :e, :p)"), {"i": str(lease_id), "e": epoch, "p": payload})
            return True


# 1 ----------------------------------------------------------------------------------------------------------------
def test_a_session_lock_is_held_exactly_as_long_as_its_connection_lives(db):
    key = uuid.uuid4().int % (2**62)
    owner = db.connect().execution_options(isolation_level="AUTOCOMMIT")
    probe = db.connect().execution_options(isolation_level="AUTOCOMMIT")
    killer = db.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        assert owner.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar() is True
        pid = owner.execute(text("SELECT pg_backend_pid()")).scalar()
        # alive owner: the lock cannot be taken, however long it has been held (no age is consulted anywhere)
        time.sleep(0.5)
        assert probe.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar() is False
        # the owner's process dies (backend terminated): the lock is released by the server, with no timeout
        assert killer.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid}).scalar() is True
        acquired = False
        for _ in range(50):
            if probe.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar():
                acquired = True
                break
            time.sleep(0.1)
        assert acquired, "a dead owner's session lock must become available"
        with pytest.raises(DBAPIError):  # the dead owner can no longer use that connection at all
            owner.execute(text("SELECT 1"))
    finally:
        for conn in (probe, killer, owner):
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# 2 ----------------------------------------------------------------------------------------------------------------
def test_a_check_then_write_without_a_row_lock_lets_a_revoked_owner_write(db):
    lease = new_lease(db)
    with db.connect() as owner:
        epoch_seen = owner.execute(text(f"SELECT epoch FROM r5_spike_lease WHERE id = :i"), {"i": str(lease)}).scalar()
        owner.commit()  # the pre-check read is over; nothing is locked
        assert epoch_seen == 1  # the pre-check passes ...
        assert revoke(db, lease) is True  # ... then ownership is taken away ...
        with owner.begin():  # ... and the write, unconditional on the epoch, still lands
            owner.execute(text(f"INSERT INTO r5_spike_result (lease_id, epoch, payload) VALUES (:i, :e, 'stale')"), {"i": str(lease), "e": epoch_seen})
    assert results(db, lease) == [1] and lease_row(db, lease) == (2, "INTERRUPTED")  # the hazard the design's FOR SHARE fence exists to remove


# 3 ----------------------------------------------------------------------------------------------------------------
def test_the_fence_rejects_a_stale_owner_after_revocation(db):
    lease = new_lease(db)
    assert fenced_write(db, lease, 1, "first") is True
    assert revoke(db, lease) is True
    assert fenced_write(db, lease, 1, "late") is False  # the stale owner's write is refused inside its own transaction
    assert results(db, lease) == [1]  # only the write made while it still owned the lease


def test_a_revoke_waits_for_an_in_flight_fenced_write_instead_of_interleaving(db):
    lease = new_lease(db)
    entered, hold = threading.Event(), threading.Event()
    outcome: dict[str, object] = {}

    writer = threading.Thread(target=lambda: outcome.update(write=fenced_write(db, lease, 1, "in-flight", hold=hold, entered=entered)))
    writer.start()
    assert entered.wait(timeout=10)  # the writer has passed the check and holds the row share lock
    revoked_at: dict[str, float] = {}

    def do_revoke():
        outcome["revoke"] = revoke(db, lease)
        revoked_at["t"] = time.monotonic()

    revoker = threading.Thread(target=do_revoke)
    revoker.start()
    time.sleep(0.7)
    assert "t" not in revoked_at, "the revoke must wait for the fenced write, not slip between its check and its write"
    released_at = time.monotonic()
    hold.set()
    writer.join(timeout=10)
    revoker.join(timeout=10)
    assert outcome == {"write": True, "revoke": True} and revoked_at["t"] >= released_at
    assert results(db, lease) == [1] and lease_row(db, lease) == (2, "INTERRUPTED")
    assert fenced_write(db, lease, 1, "after") is False  # and from now on the old owner is fenced out


# 4 ----------------------------------------------------------------------------------------------------------------
def test_completion_and_revocation_race_has_exactly_one_winner(db):
    for _ in range(25):
        lease = new_lease(db)
        barrier = threading.Barrier(2)
        won: dict[str, bool] = {}

        def complete():
            barrier.wait(timeout=10)
            with db.begin() as c:
                won["complete"] = bool(c.execute(text(f"UPDATE r5_spike_lease SET state = 'SUCCEEDED' WHERE id = :i AND epoch = 1 AND state = 'CLAIMED'"), {"i": str(lease)}).rowcount)

        def revoke_it():
            barrier.wait(timeout=10)
            won["revoke"] = revoke(db, lease)

        threads = [threading.Thread(target=complete), threading.Thread(target=revoke_it)]
        [t.start() for t in threads]
        [t.join(timeout=10) for t in threads]
        assert sorted(won.values()) == [False, True]  # never both, never neither
        epoch, state = lease_row(db, lease)
        assert (state, epoch) == (("SUCCEEDED", 1) if won["complete"] else ("INTERRUPTED", 2))


# 5 ----------------------------------------------------------------------------------------------------------------
def test_a_constraint_trigger_makes_terminal_states_immutable_even_against_direct_sql(db):
    with db.begin() as c:
        c.execute(text(
            f"CREATE FUNCTION r5_spike_no_leaving_terminal() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            f"IF OLD.state IN ('SUCCEEDED','FAILED','OUTCOME_UNKNOWN','INTERRUPTED') AND (NEW.state <> OLD.state OR NEW.epoch <> OLD.epoch) THEN "
            f"RAISE EXCEPTION 'terminal lease state is immutable' USING ERRCODE = '23514'; END IF; RETURN NEW; END $$"
        ))
        c.execute(text(f"CREATE TRIGGER lease_terminal_immutable BEFORE UPDATE ON r5_spike_lease FOR EACH ROW EXECUTE FUNCTION r5_spike_no_leaving_terminal()"))
    lease = new_lease(db)
    assert revoke(db, lease) is True  # CLAIMED -> INTERRUPTED is allowed
    for sql in (
        f"UPDATE r5_spike_lease SET state = 'SUCCEEDED' WHERE id = :i",  # a late finisher trying to resurrect it as a success
        f"UPDATE r5_spike_lease SET state = 'CLAIMED', epoch = 1 WHERE id = :i",
    ):
        with pytest.raises(DBAPIError, match="terminal lease state is immutable"):
            with db.begin() as c:
                c.execute(text(sql), {"i": str(lease)})
    assert lease_row(db, lease) == (2, "INTERRUPTED")
