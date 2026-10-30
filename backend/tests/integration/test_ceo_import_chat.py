"""Attached reports -> approved import -> CFO records, through the CEO (docs/specs/cfo-3-growth-advisor.md Phase 0). Real Postgres, the real registry, approval flow and upload pipeline.

Reading an attachment writes nothing. The import is a card the seller approves; a typed yes does nothing; the same file is never added twice; a file the importer does not know is not guessed at."""

from __future__ import annotations

import pytest

from tests.integration.test_ceo_cmo_delegation import approve, chat, new_investigation, say  # noqa: F401
from tests.integration.test_cfo_uploads_jobs import known, unknown, with_runner  # noqa: F401
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401


@pytest.fixture(autouse=True)
def _attachment_limits(monkeypatch):
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_BYTES", "1000000")
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_FILES", "5")
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_PAGES", "5")


def attach(c, inv, name, data):
    r = c.client.post(f"/api/v1/ceo/investigations/{inv}/attachments", files={"file": (name, data, "text/csv")}, headers=c.env.headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def turn(c, inv, text, ids=()):
    r = c.client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": text, "attachment_ids": list(ids)}, headers=c.env.headers)
    assert r.status_code == 200, r.text
    return r.json()


def files_in_records(c) -> int:
    return c.env.n("report_file")


def test_reading_a_file_imports_nothing_and_adding_it_is_a_card_the_seller_approves(chat, with_runner):  # noqa: F811
    c = chat
    with_runner(proposer=None)
    inv = new_investigation(c)
    a = attach(c, inv, "meesho_orders_sep.csv", known(6))
    read = turn(c, inv, "Please read what I attached.", [a])
    assert files_in_records(c) == 0 and "nothing was imported" in read["answer"].lower()  # reading is not importing

    asked = turn(c, inv, "Analyze them and add the verified information to my CFO dashboard.", [a])
    assert asked["status"] == "PLANNED", asked
    plan = asked["plan"]
    leg = plan["plan"]["legs"][0]
    assert leg["action_key"] == "cfo.import_attachments" and leg["slots"]["files"][0]["marketplace"] == "MEESHO" and leg["slots"]["files"][0]["adapter_id"] == "meesho.orders.v1"
    card = " ".join(plan["plan"]["compact_lines"])
    assert "meesho_orders_sep.csv" in card and "I recognise" in card and "Nothing is added until you press Approve" in card
    assert files_in_records(c) == 0  # the card is only a promise
    for typed in ("yes", "go ahead"):
        say(c, inv, typed)
    assert files_in_records(c) == 0  # typing yes is only text

    done = approve(c, inv, plan)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "DELIVERED" and "added to your financial records" in body["answer"] and "6 of 6 rows saved" in body["answer"]
    assert files_in_records(c) == 1 and c.env.n("sales_line") == 6
    again = approve(c, inv, plan)  # a double click
    assert again.status_code == 200 and files_in_records(c) == 1 and c.env.n("sales_line") == 6


def test_the_same_file_attached_again_is_recognised_and_not_added_twice(chat, with_runner):  # noqa: F811
    c = chat
    with_runner(proposer=None)
    inv = new_investigation(c)
    a = attach(c, inv, "meesho_orders_sep.csv", known(4))
    plan = turn(c, inv, "Add this to my financial records.", [a])["plan"]
    approve(c, inv, plan)
    inv2 = new_investigation(c)
    b = attach(c, inv2, "meesho_orders_sep_copy.csv", known(4))
    plan2 = turn(c, inv2, "Add this to my financial records.", [b])["plan"]
    body = approve(c, inv2, plan2).json()
    assert "imported before" in body["answer"] or "0 of" in body["answer"] or "already" in body["answer"].lower()
    assert c.env.n("sales_line") == 4  # nothing was counted twice


def test_a_file_the_importer_does_not_know_is_not_guessed_at_and_the_answer_says_how_to_map_it(chat, with_runner):  # noqa: F811
    c = chat
    with_runner(proposer=None)
    inv = new_investigation(c)
    a = attach(c, inv, "mystery.csv", unknown(40))
    asked = turn(c, inv, "Import these files into my records.", [a])
    assert asked["status"] == "CLARIFIED" and "Which marketplace" in asked["answer"]  # the file name does not say which marketplace, so the seller is asked
    plan = turn(c, inv, "Flipkart")["plan"]
    assert "do not recognise this column layout" in " ".join(plan["plan"]["compact_lines"])
    body = approve(c, inv, plan).json()
    assert "not added" in body["answer"] and "Map the columns yourself" in body["answer"]
    assert c.env.n("sales_line") == 0  # nothing was saved from a layout nobody confirmed


def test_with_no_spreadsheet_there_is_nothing_to_import_and_it_says_so(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "Add the verified information to my CFO dashboard")
    assert "do not see a spreadsheet attached" in r["answer"] and files_in_records(c) == 0
