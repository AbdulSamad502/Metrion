"""Tests for `sources/rate_limiter.py` — the process-wide outbound-call throttle (PI build
plan Context, "Queue outbound calls against a fixed rate cap"). Proves the limiter actually
bounds concurrency and reports a real wait, not just that the module imports."""

from __future__ import annotations

import threading
import time

from product_intelligence.sources import rate_limiter


def test_bounds_concurrent_calls_to_the_configured_cap() -> None:
    source = "test_source_bound"
    rate_limiter._semaphores[source] = threading.Semaphore(2)

    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal in_flight, max_in_flight
        with rate_limiter.throttle(source):
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            time.sleep(0.05)
            with lock:
                in_flight -= 1

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert max_in_flight <= 2


def test_waited_is_false_when_a_slot_is_immediately_free() -> None:
    source = "test_source_immediate"
    rate_limiter._semaphores[source] = threading.Semaphore(5)

    with rate_limiter.throttle(source) as outcome:
        assert outcome.waited is False


def test_waited_is_true_when_the_caller_had_to_block_for_a_slot() -> None:
    source = "test_source_wait"
    rate_limiter._semaphores[source] = threading.Semaphore(1)

    holder_ready = threading.Event()
    release_holder = threading.Event()
    second_caller_outcome: dict[str, bool] = {}

    def holder() -> None:
        with rate_limiter.throttle(source):
            holder_ready.set()
            release_holder.wait(timeout=5)

    def second_caller() -> None:
        holder_ready.wait(timeout=5)
        with rate_limiter.throttle(source) as outcome:
            second_caller_outcome["waited"] = outcome.waited

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=second_caller)
    t1.start()
    t1_ready = holder_ready.wait(timeout=5)
    assert t1_ready
    t2.start()
    time.sleep(0.05)  # give t2 time to block on acquire before we release
    release_holder.set()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert second_caller_outcome.get("waited") is True


def test_slot_is_released_even_if_the_wrapped_call_raises() -> None:
    source = "test_source_release_on_error"
    rate_limiter._semaphores[source] = threading.Semaphore(1)

    try:
        with rate_limiter.throttle(source):
            raise ValueError("boom")
    except ValueError:
        pass

    # If the slot weren't released, this would block forever — timeout proves it wasn't.
    acquired = rate_limiter._semaphores[source].acquire(blocking=True, timeout=1)
    assert acquired is True
    rate_limiter._semaphores[source].release()


def test_default_sources_are_preconfigured() -> None:
    assert rate_limiter.DEFAULT_MAX_CONCURRENT_BY_SOURCE.keys() == {"tavily", "youtube", "google_places"}
    assert all(limit > 0 for limit in rate_limiter.DEFAULT_MAX_CONCURRENT_BY_SOURCE.values())
