"""The periodic ownership sweep (R5): runs on a configurable interval, can be turned off, survives a failing pass and stops when asked."""

from __future__ import annotations

import os
import threading

os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")

import pytest

from backend import config, main
from backend.ceo import recovery


def test_default_interval_and_overrides(monkeypatch):
    monkeypatch.delenv("RECOVERY_SWEEP_INTERVAL_SECONDS", raising=False)
    assert config.recovery_sweep_interval_seconds() == 300
    monkeypatch.setenv("RECOVERY_SWEEP_INTERVAL_SECONDS", "45")
    assert config.recovery_sweep_interval_seconds() == 45
    monkeypatch.setenv("RECOVERY_SWEEP_INTERVAL_SECONDS", "0")
    assert config.recovery_sweep_interval_seconds() is None  # off


@pytest.mark.parametrize("bad", ["-5", "abc", "1.5"])
def test_an_invalid_interval_is_an_error_not_a_silent_default(monkeypatch, bad):
    monkeypatch.setenv("RECOVERY_SWEEP_INTERVAL_SECONDS", bad)
    with pytest.raises(ValueError):
        config.recovery_sweep_interval_seconds()


def test_off_returns_immediately_and_never_sweeps(monkeypatch):
    monkeypatch.setenv("RECOVERY_SWEEP_INTERVAL_SECONDS", "0")
    calls = []
    monkeypatch.setattr(recovery, "sweep_all", lambda **_k: calls.append(1))
    main._sweep_ownerless_runs_forever()
    assert calls == []


def test_an_invalid_interval_turns_the_pass_off_without_crashing(monkeypatch):
    monkeypatch.setenv("RECOVERY_SWEEP_INTERVAL_SECONDS", "nope")
    monkeypatch.setattr(recovery, "sweep_all", lambda **_k: pytest.fail("must not sweep"))
    main._sweep_ownerless_runs_forever()


def test_it_sweeps_repeatedly_survives_a_failing_pass_and_stops(monkeypatch):
    monkeypatch.setenv("RECOVERY_SWEEP_INTERVAL_SECONDS", "1")
    stop, done, calls = threading.Event(), threading.Event(), []

    def fake_sweep(**_k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database interrupted")  # the first pass fails; the loop must carry on
        if len(calls) >= 3:
            done.set()
        return recovery.RecoveryReport()

    monkeypatch.setattr(recovery, "sweep_all", fake_sweep)
    t = threading.Thread(target=main._sweep_ownerless_runs_forever, args=(stop,))
    t.start()
    assert done.wait(15)
    stop.set()
    t.join(5)
    assert not t.is_alive() and len(calls) >= 3
