"""CEO conversation message order is deterministic (migration 20261031_0029).

`created_at` is stamped once per turn, so a seller's message and the CEO's reply to it can carry the identical timestamp. The order used to fall back to the RANDOM message id, which could put the
CEO's open question before the seller's message that came first; the seller's next answer then went to the intent classifier instead of the open question (intermittent failures in the chat suites).
`seq` is an identity column the database assigns in insertion order; messages are read by `(created_at, seq)`."""

from __future__ import annotations

import os
import sys
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.repositories import investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import T0
from tests.integration.test_accounting_cutover import ROOT, _alembic

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def inv_of(tenant, user):
    return repo.create_investigation(tenant, created_by=user, title="order", now=T0)


def say(tenant, inv, role, content, user=None, kind="TEXT", choices=None, now=T0):
    return repo.append_message(tenant, inv, role=role, content=content, kind=kind, created_by=user if role == "USER" else None, choices=choices, now=now)


def test_two_messages_with_identical_timestamps_come_back_in_the_order_they_were_written(two_tenants, app_user):
    a, _ = two_tenants
    for i in range(30):  # the random id used to decide this; it is a coin flip per pair, so many pairs make a vacuous pass impossible
        inv = inv_of(a, app_user)
        first = say(a, inv, "USER", f"ask {i}", app_user)
        second = say(a, inv, "CEO", f"question {i}", kind="CLARIFICATION", choices={"kind": "INPUT"})
        assert [m["id"] for m in repo.list_messages(a, inv)] == [first, second]
        assert repo.list_messages(a, inv)[0]["created_at"] == repo.list_messages(a, inv)[1]["created_at"]  # the tie is real


def test_the_insertion_order_decides_a_tie_in_both_directions_never_the_id(two_tenants, app_user):
    a, _ = two_tenants
    wrong_way = 0
    for _ in range(30):
        inv = inv_of(a, app_user)
        ceo = say(a, inv, "CEO", "first written", kind="ANSWER")
        user = say(a, inv, "USER", "second written", app_user)
        order = [m["id"] for m in repo.list_messages(a, inv)]
        assert order == [ceo, user]
        wrong_way += 0 if str(ceo) < str(user) else 1
    assert 0 < wrong_way < 30  # the ids really were in both relative orders, so the id could not have produced these results


def test_the_last_message_is_the_open_question_so_the_next_answer_goes_to_it(two_tenants, app_user):
    a, _ = two_tenants
    for i in range(30):
        inv = inv_of(a, app_user)
        say(a, inv, "USER", f"create my complete listing {i}", app_user)
        say(a, inv, "CEO", "Which marketplace?", kind="CLARIFICATION", choices={"kind": "INPUT", "slot": "marketplace"})
        last = repo.list_messages(a, inv)[-1]
        assert last["role"] == "CEO" and last["kind"] == "CLARIFICATION" and (last["choices"] or {}).get("kind") == "INPUT"  # the orchestrator's open-question test


def test_a_normal_conversation_stays_chronological_and_earlier_stamped_history_stays_first(two_tenants, app_user):
    a, _ = two_tenants
    inv = inv_of(a, app_user)
    ids = [say(a, inv, "USER" if i % 2 == 0 else "CEO", f"m{i}", app_user, now=T0 + timedelta(seconds=i)) for i in range(8)]
    assert [m["id"] for m in repo.list_messages(a, inv)] == ids  # every message survived the round trip, in order
    older = say(a, inv, "SYSTEM", "backdated", now=T0 - timedelta(hours=1))  # an earlier timestamp written later still sorts by time
    assert repo.list_messages(a, inv)[0]["id"] == older and [m["id"] for m in repo.list_messages(a, inv)][1:] == ids
    window = repo.list_messages(a, inv, after_message_id=ids[3])
    assert [m["id"] for m in window] == ids[4:]  # the "after" window uses the same order


def test_concurrent_writers_never_corrupt_the_order(two_tenants, app_user):
    a, _ = two_tenants
    inv = inv_of(a, app_user)
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        try:
            for j in range(4):
                say(a, inv, "USER", f"t{n}-{j}-u", app_user)  # the same timestamp for every writer
                say(a, inv, "CEO", f"t{n}-{j}-c", kind="ANSWER")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    rows = repo.list_messages(a, inv)
    assert len(rows) == 64
    with tenant_scope(a) as conn:
        seqs = {r[0]: r[1] for r in conn.execute(text("SELECT id, seq FROM investigation_message WHERE investigation_id = :i"), {"i": str(inv)})}
    assert len(set(seqs.values())) == 64  # unique, database-assigned
    assert [seqs[m["id"]] for m in rows] == sorted(seqs.values())  # read order == write order
    where = {m["content"]: i for i, m in enumerate(rows)}
    for n in range(8):
        for j in range(4):
            assert where[f"t{n}-{j}-u"] < where[f"t{n}-{j}-c"]  # each writer's own question always follows its own message


def test_the_order_is_stable_across_reloads(two_tenants, app_user):
    a, _ = two_tenants
    inv = inv_of(a, app_user)
    for i in range(12):
        say(a, inv, "USER" if i % 2 == 0 else "CEO", f"m{i}", app_user)
    first = [m["id"] for m in repo.list_messages(a, inv)]
    assert all([m["id"] for m in repo.list_messages(a, inv)] == first for _ in range(5))


def test_a_writer_cannot_choose_the_sequence_number_and_another_tenant_sees_nothing(two_tenants, app_user):
    a, b = two_tenants
    inv = inv_of(a, app_user)
    say(a, inv, "USER", "mine", app_user)
    with pytest.raises(DBAPIError):
        with tenant_scope(a) as conn:
            conn.execute(text("INSERT INTO investigation_message (id, investigation_id, tenant_id, role, kind, content, created_at, seq) "
                              "VALUES (:id, :i, :t, 'SYSTEM', 'SYSTEM_NOTE', 'x', now(), 1)"), {"id": str(uuid.uuid4()), "i": str(inv), "t": str(a)})
    assert repo.list_messages(b, inv) == []


@pytest.mark.skipif(os.environ.get("METRION_ALLOW_DOWNGRADE_TESTS") != "1", reason="runs alembic downgrade/upgrade against DATABASE_URL: opt in only on a scratch/CI database, never the dev DB")
def test_the_migration_downgrades_and_upgrades_cleanly_with_messages_present(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    inv = inv_of(a, app_user)
    ids = [say(a, inv, "USER" if i % 2 == 0 else "CEO", f"m{i}", app_user, now=T0 + timedelta(seconds=i)) for i in range(4)]
    down = _alembic(ROOT, "downgrade", "20261030_0028")
    assert down.returncode == 0, down.stderr + down.stdout
    try:
        with migrate_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'investigation_message' AND column_name = 'seq'")).scalar_one() == 0
    finally:
        up = _alembic(ROOT, "upgrade", "head")
        assert up.returncode == 0, up.stderr + up.stdout
    with migrate_engine.connect() as conn:
        assert conn.execute(text("SELECT attidentity FROM pg_attribute WHERE attrelid = 'investigation_message'::regclass AND attname = 'seq'")).scalar_one() == "a"  # GENERATED ALWAYS
    assert [m["id"] for m in repo.list_messages(a, inv)] == ids  # every message survived the round trip, in order
