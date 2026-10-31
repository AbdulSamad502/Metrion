"""Backend migration 20261031_0030 (CMO 3.0 M7, acceptance M7-69): the CEO chat may carry a `LISTING_HISTORY` card on an ANSWER. Additive and reversible: upgrade accepts exactly the new value, the downgrade
deletes no message, stops any NEW history card being stored (the older constraint is added NOT VALID because FORCE RLS hides existing rows from the migration role) and leaves every earlier card kind
(including the M6 listing card) untouched, and re-upgrading works. No M6 table is touched by M7."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from backend.repositories import investigation_repo as repo
from tests.integration.ceo_support import T0
from tests.integration.test_accounting_cutover import ROOT, _alembic

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

CARD = {"kind": "LISTING_HISTORY", "view": "HISTORY", "total": 0, "versions": []}
M6_CARD = {"kind": "LISTING", "generationId": "g1"}


def answer(tenant, inv, content, choices):
    return repo.append_message(tenant, inv, role="CEO", content=content, kind="ANSWER", created_by=None, choices=choices, now=T0)


def test_the_constraint_accepts_the_history_card_and_nothing_invented(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    inv = repo.create_investigation(a, created_by=app_user, title="m7", now=T0)
    with migrate_engine.connect() as conn:
        shape = conn.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'investigation_message_choices_shape'")).scalar_one()
    assert "'LISTING_HISTORY'" in shape and "'LISTING'" in shape and "'READINESS'" in shape and "'PREVIEW'" in shape and "'PUBLISHED'" not in shape
    answer(a, inv, "history", CARD)
    with pytest.raises(DBAPIError):
        answer(a, inv, "invented", {"kind": "LISTING_PUBLISHED"})
    assert [m["choices"]["kind"] for m in repo.list_messages(a, inv)] == ["LISTING_HISTORY"]


@pytest.mark.skipif(os.environ.get("METRION_ALLOW_DOWNGRADE_TESTS") != "1", reason="runs alembic downgrade/upgrade against DATABASE_URL: opt in only on a scratch/CI database, never the dev DB")
def test_downgrade_deletes_no_message_refuses_new_history_cards_and_reupgrades(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    inv = repo.create_investigation(a, created_by=app_user, title="m7", now=T0)
    h = answer(a, inv, "your history", CARD)
    m6 = answer(a, inv, "your listing", M6_CARD)
    down = _alembic(ROOT, "downgrade", "20261031_0029")
    assert down.returncode == 0, down.stderr + down.stdout
    try:
        with migrate_engine.connect() as conn:
            shape = conn.execute(text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'investigation_message_choices_shape'")).scalar_one()
        assert "'LISTING_HISTORY'" not in shape and "'LISTING'" in shape
        by = {m["id"]: m for m in repo.list_messages(a, inv)}
        assert set(by) == {h, m6} and by[h]["content"] == "your history"  # no message is lost
        assert by[m6]["choices"] == M6_CARD  # an earlier card kind is untouched
        with pytest.raises(DBAPIError):
            answer(a, inv, "not allowed on the older schema", CARD)  # the older schema stores no new history card
    finally:
        up = _alembic(ROOT, "upgrade", "head")
        assert up.returncode == 0, up.stderr + up.stdout
    answer(a, inv, "again", CARD)
    assert [m["content"] for m in repo.list_messages(a, inv)] == ["your history", "your listing", "again"]
