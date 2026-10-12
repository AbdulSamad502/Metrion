"""Database outage behaviour (Stage 4 follow-up): a database that stalls or disappears must produce a BOUNDED, controlled failure, and the same process must recover when the
database returns, with no application restart.

Real PostgreSQL (the scratch database) reached through a small TCP forwarder the test controls, so an outage can be simulated honestly on any machine:
  * `stall`   : the forwarder accepts connections and never answers (the failure seen when a database container was stopped behind Docker's port proxy; before
                `connect_timeout` this hung every request, health probes included, until the client gave up);
  * `refuse`  : nothing is listening (fast failure);
  * `reset`   : every established connection is dropped (what a restart does to a pool);
  * `restore` : traffic flows again.
The engine is built with the SAME `engine_options()` the application uses."""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from backend.tenant_context import engine_options

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP"), reason="needs the scratch database")


class Forwarder:
    def __init__(self, host: str, port: int) -> None:
        self.target = (host, port)
        self.mode = "restore"
        self._listener: socket.socket | None = None
        self._pairs: list[socket.socket] = []
        self._stop = False
        self.port = 0
        self._open_listener()

    def _open_listener(self, port: int = 0) -> None:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(32)
        self._listener = s
        self.port = s.getsockname()[1]
        threading.Thread(target=self._accept, args=(s,), daemon=True).start()

    def _accept(self, listener: socket.socket) -> None:
        while not self._stop:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            self._pairs.append(client)
            if self.mode == "stall":
                continue  # accepted, never answered
            threading.Thread(target=self._pipe, args=(client,), daemon=True).start()

    def _pipe(self, client: socket.socket) -> None:
        try:
            upstream = socket.create_connection(self.target, timeout=5)
        except OSError:
            client.close()
            return
        self._pairs.append(upstream)

        def pump(a: socket.socket, b: socket.socket) -> None:
            try:
                while data := a.recv(65536):
                    b.sendall(data)
            except OSError:
                pass
            finally:
                for s in (a, b):
                    try:
                        s.close()
                    except OSError:
                        pass

        threading.Thread(target=pump, args=(client, upstream), daemon=True).start()
        threading.Thread(target=pump, args=(upstream, client), daemon=True).start()

    def drop_connections(self) -> None:
        for s in self._pairs:
            try:
                s.close()
            except OSError:
                pass
        self._pairs.clear()

    def set(self, mode: str) -> None:
        port = self.port
        self.mode = mode
        if mode == "refuse":
            self.drop_connections()
            if self._listener is not None:
                self._listener.close()
                self._listener = None
        elif mode == "reset":
            self.drop_connections()
        elif mode in ("stall", "restore"):
            self.drop_connections()
            if self._listener is None:
                self._open_listener(port)

    def close(self) -> None:
        self._stop = True
        self.drop_connections()
        if self._listener is not None:
            self._listener.close()


@pytest.fixture
def through_forwarder(monkeypatch):
    url = make_url(os.environ["DATABASE_URL_APP"])
    assert url.port == 5544, "outage tests run against the scratch database only"
    fwd = Forwarder(url.host or "127.0.0.1", url.port)
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "3")
    engine = create_engine(url.set(host="127.0.0.1", port=fwd.port), **engine_options())
    yield fwd, engine
    engine.dispose()
    fwd.close()


def _ok(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT 1")).scalar_one()


def test_a_stalled_database_fails_within_the_connect_timeout_and_the_process_recovers(through_forwarder):
    fwd, engine = through_forwarder
    assert _ok(engine) == 1
    fwd.set("stall")
    started = time.monotonic()
    with pytest.raises(OperationalError):
        _ok(engine)
    assert time.monotonic() - started < 10  # bounded (connect_timeout 2 s here); before the fix this waited for the client to give up
    fwd.set("restore")
    assert _ok(engine) == 1  # same engine, same process, no restart


def test_a_refused_database_fails_fast_and_recovers(through_forwarder):
    fwd, engine = through_forwarder
    assert _ok(engine) == 1
    fwd.set("refuse")
    started = time.monotonic()
    with pytest.raises(OperationalError):
        _ok(engine)
    assert time.monotonic() - started < 10
    fwd.set("restore")
    assert _ok(engine) == 1


def test_dropped_pooled_connections_do_not_fail_the_next_request(through_forwarder):
    fwd, engine = through_forwarder
    for _ in range(3):
        assert _ok(engine) == 1  # pool warmed
    fwd.set("reset")  # every established connection is dead; the listener is still up
    for _ in range(3):
        assert _ok(engine) == 1


def test_pool_exhaustion_is_a_bounded_error_not_a_wait_forever(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "1")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "1")
    engine = create_engine(os.environ["DATABASE_URL_APP"], **engine_options())
    try:
        a, b = engine.connect(), engine.connect()  # size 1 + overflow 1 = both slots taken
        started = time.monotonic()
        with pytest.raises(PoolTimeout):
            engine.connect()
        assert 0.8 < time.monotonic() - started < 6
        a.close()
        b.close()
        assert _ok(engine) == 1  # and it works again as soon as a slot is free
    finally:
        engine.dispose()
