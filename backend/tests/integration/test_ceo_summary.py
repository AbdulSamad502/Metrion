"""D2 rolling summary (spec 6.6, 6.14, AC27): regenerated every 10 messages, one bounded call, never sees a CEO answer, may contain no figure,
and a bad draft changes nothing."""

from __future__ import annotations

import dataclasses
import os
import threading
import time

import pytest

from backend.ceo import summary
from backend.ceo.turn_lock import investigation_turn_lock
from backend.llm.model import ScriptedModel
from backend.repositories import investigation_repo as repo
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start  # noqa: F401

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]

CEO_ANSWER_WITH_FIGURE = "Your net revenue was ₹482,150.00 (DERIVED, as of 2026-10-01)."


class Writer:
    def __init__(self, text: str) -> None:
        self.text, self.prompts = text, []

    def model(self) -> ScriptedModel:
        def script(prompt, schema):
            self.prompts.append(prompt)
            return self.text

        return ScriptedModel(script, name="scripted-summariser")


def _rt(writer: Writer | None):
    rt = runtime(Scripted({}), Grounded())
    return dataclasses.replace(rt, composer=writer.model() if writer else None)


def _fill(tenant, inv, user_id, pairs: int, *, user_text="Why did profit drop?"):
    for i in range(pairs):
        repo.append_message(tenant, inv, role="USER", content=f"{user_text} ({i})", created_by=user_id, now=None)
        repo.append_message(tenant, inv, role="CEO", kind="ANSWER", content=CEO_ANSWER_WITH_FIGURE, now=None)


@pytest.fixture
def inv_ctx(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, runtime(Scripted({}), Grounded()))
    return a, ctx, inv, app_user


def test_not_due_below_ten_messages_and_no_model_call(inv_ctx):
    a, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 4)  # 8 messages
    w = Writer("The seller asked about profit.")
    assert summary.regenerate_if_due(a, inv, _rt(w)).status == "NOT_DUE"
    assert w.prompts == [] and repo.get_investigation(a, inv)["summary"] is None


def test_due_at_ten_messages_writes_the_summary_and_moves_the_pointer(inv_ctx):
    a, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 5)  # exactly 10
    w = Writer("The seller asked why profit dropped and what to focus on.")
    assert summary.regenerate_if_due(a, inv, _rt(w)).status == "REGENERATED"
    row = repo.get_investigation(a, inv)
    assert row["summary"] == "The seller asked why profit dropped and what to focus on."
    assert row["summary_covers_through"] == repo.list_messages(a, inv)[-1]["id"]
    assert len(w.prompts) == 1  # one bounded call
    # the window restarts: nothing is due again until ten MORE messages exist
    assert summary.regenerate_if_due(a, inv, _rt(w)).status == "NOT_DUE"
    _fill(a, inv, uid, 5)
    assert summary.regenerate_if_due(a, inv, _rt(Writer("Second summary text."))).status == "REGENERATED"


def test_the_model_never_sees_a_ceo_answer_or_any_figure(inv_ctx):
    a, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 5)
    w = Writer("The seller asked about profit.")
    summary.regenerate_if_due(a, inv, _rt(w))
    prompt = w.prompts[0]
    assert "482,150" not in prompt and "₹" not in prompt and "DERIVED" not in prompt  # CEO answers carry verified figures: never an input
    assert "Why did profit drop?" in prompt  # the seller's own words are


@pytest.mark.parametrize("bad", [
    "The seller asked about a loss of 5 percent.",   # digit
    "The seller mentioned about a lakh in fees.",     # amount word
    "The seller stated ₹499 as their price.",         # currency
    "",                                               # empty
    "x" * 1300,                                       # too long
    "<think>hidden</think> The seller asked.",        # reasoning leaked
])
def test_a_bad_draft_changes_nothing(inv_ctx, bad):
    a, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 5)
    before = repo.get_investigation(a, inv)
    out = summary.regenerate_if_due(a, inv, _rt(Writer(bad)))
    assert out.status == "REJECTED", out
    after = repo.get_investigation(a, inv)
    assert (after["summary"], after["summary_covers_through"]) == (before["summary"], before["summary_covers_through"])


def test_a_model_error_keeps_the_old_summary(inv_ctx):
    a, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 5)

    def boom(prompt, schema):
        raise RuntimeError("model down")

    rt = dataclasses.replace(runtime(Scripted({}), Grounded()), composer=ScriptedModel(boom, name="x"))
    assert summary.regenerate_if_due(a, inv, rt).status == "FAILED"
    assert repo.get_investigation(a, inv)["summary"] is None


def test_no_composer_configured_means_no_regeneration(inv_ctx):
    a, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 5)
    assert summary.regenerate_if_due(a, inv, _rt(None)).status == "NO_MODEL"


def test_system_notes_do_not_count_toward_the_cadence(inv_ctx):
    a, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 4)
    for i in range(6):
        repo.append_message(a, inv, role="SYSTEM", kind="SYSTEM_NOTE", content=f"note {i}", now=None)
    assert summary.regenerate_if_due(a, inv, _rt(Writer("x"))).status == "NOT_DUE"


def test_the_locked_runner_skips_when_a_turn_is_running_and_tries_again_later(inv_ctx):
    a, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 5)
    w = Writer("The seller asked about profit.")
    with investigation_turn_lock(inv, None):  # a turn is running
        assert summary.regenerate_if_due_locked(a, inv, _rt(w)).status == "BUSY"
    assert w.prompts == [] and repo.get_investigation(a, inv)["summary"] is None
    assert summary.regenerate_if_due_locked(a, inv, _rt(w)).status == "REGENERATED"  # the turn finished: due again, so it runs


def test_the_summary_is_what_later_turns_read_as_context(inv_ctx):
    """AC9: after regeneration only messages since the pointer are re-read."""
    a, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 5)
    summary.regenerate_if_due(a, inv, _rt(Writer("The seller asked about profit.")))
    row = repo.get_investigation(a, inv)
    assert repo.list_messages(a, inv, after_message_id=row["summary_covers_through"]) == []


def test_another_tenant_cannot_read_or_write_the_summary(inv_ctx, two_tenants):
    a, b = two_tenants
    _, _, inv, uid = inv_ctx
    _fill(a, inv, uid, 5)
    summary.regenerate_if_due(a, inv, _rt(Writer("The seller asked about profit.")))
    assert repo.get_investigation(b, inv) is None  # RLS: not found for tenant B
    assert summary.regenerate_if_due(b, inv, _rt(Writer("INJECTED"))).status == "NOT_DUE"
    assert repo.get_investigation(a, inv)["summary"] == "The seller asked about profit."


def test_the_background_runner_never_raises(inv_ctx):
    a, _, inv, _ = inv_ctx
    assert summary.regenerate_if_due_locked(a, inv, _rt(Writer("x"))).status == "NOT_DUE"
