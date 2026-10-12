"""R0 (approval prerequisites): durable accounting cut-over records, and the PI columns that let a run be dated and decided once.

Legacy rows must be recognisable and left alone: the cut-over table is read-only for the application, an unknown record is never
"post-cut-over", and a legacy PI run (no created_at) can never receive an accounting decision."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from backend.repositories import accounting_cutover_repo as cutover
from backend.repositories import investigation_repo as repo
from product_intelligence.repositories import niche_brief_repo, pi_research_run_repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import T0, ctx_for
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

pytestmark = pytest.mark.usefixtures("two_tenants")

CODES = ("CEO_UNIT_RULE_2", "NICHE_RUN_USAGE_1", "PI_USAGE_1")
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_the_three_cutovers_are_recorded_and_not_in_the_future():
    now = datetime.now(timezone.utc)
    for code in CODES:
        at = cutover.effective_at(code)
        assert at is not None and at <= now + timedelta(seconds=5), code
    assert cutover.effective_at("NO_SUCH_RULE") is None


def test_the_application_role_can_read_but_never_change_a_cutover(app_engine):
    with app_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM accounting_cutover")).scalar_one() >= 3
    for sql in (
        "INSERT INTO accounting_cutover (code, effective_at, note) VALUES ('X', now(), 'x')",
        "UPDATE accounting_cutover SET effective_at = now() + interval '1 year'",
        "DELETE FROM accounting_cutover",
        "TRUNCATE accounting_cutover",
    ):
        with pytest.raises((ProgrammingError, DBAPIError)):
            with app_engine.begin() as conn:
                conn.execute(text(sql))


def test_post_cutover_is_conservative():
    at = cutover.effective_at("PI_USAGE_1")
    assert cutover.is_post_cutover("PI_USAGE_1", at + timedelta(seconds=1)) is True
    assert cutover.is_post_cutover("PI_USAGE_1", at) is True
    assert cutover.is_post_cutover("PI_USAGE_1", at - timedelta(seconds=1)) is False  # legacy
    assert cutover.is_post_cutover("PI_USAGE_1", None) is False  # no timestamp = legacy
    assert cutover.is_post_cutover("NO_SUCH_RULE", at + timedelta(days=1)) is False  # a rule that is not in effect never applies


def _brief(a, app_user) -> uuid.UUID:
    return niche_brief_repo.create_draft(a, created_by=app_user, category_text="steel water bottle")


def test_a_new_pi_run_is_dated_and_decided_once_while_a_legacy_run_never_is(two_tenants, app_user):
    a, _ = two_tenants
    brief = _brief(a, app_user)
    run = pi_research_run_repo.create_run(a, niche_brief_id=brief, depth="SHALLOW", trigger="DIRECT_UI", candidate_cap=5)
    assert pi_research_run_repo.get_run(a, run)["created_at"] is not None
    assert pi_research_run_repo.record_outcome(a, run, outcome_code="USABLE", usage_due=True) is True
    assert pi_research_run_repo.record_outcome(a, run, outcome_code="EMPTY_RESULT", usage_due=False) is False  # first writer wins
    row = pi_research_run_repo.get_run(a, run)
    assert (row["outcome_code"], row["usage_due"]) == ("USABLE", True)

    legacy = pi_research_run_repo.create_run(a, niche_brief_id=brief, depth="SHALLOW", trigger="DIRECT_UI", candidate_cap=5)
    with tenant_scope(a) as conn:  # make it look like a row from before the migration: no created_at, no decision
        conn.execute(text("UPDATE pi_research_run SET created_at = NULL WHERE id = :i"), {"i": str(legacy)})
    assert pi_research_run_repo.get_run(a, legacy)["created_at"] is None
    assert pi_research_run_repo.record_outcome(a, legacy, outcome_code="USABLE", usage_due=True) is False  # legacy: never decided, never billable
    row = pi_research_run_repo.get_run(a, legacy)
    assert (row["outcome_code"], row["usage_due"]) == (None, None)


def test_operational_counts_are_separate_from_usage_and_from_the_legacy_started_count(two_tenants, app_user):
    a, _ = two_tenants
    brief = _brief(a, app_user)
    ok = pi_research_run_repo.create_run(a, niche_brief_id=brief, depth="SHALLOW", trigger="DIRECT_UI", candidate_cap=5)
    bad = pi_research_run_repo.create_run(a, niche_brief_id=brief, depth="SHALLOW", trigger="DIRECT_UI", candidate_cap=5)
    stuck = pi_research_run_repo.create_run(a, niche_brief_id=brief, depth="SHALLOW", trigger="DIRECT_UI", candidate_cap=5)
    pi_research_run_repo.finish_run(a, ok, status="COMPLETE", finished_at=T0)
    pi_research_run_repo.record_outcome(a, ok, outcome_code="USABLE", usage_due=True)
    pi_research_run_repo.finish_run(a, bad, status="FAILED", finished_at=T0)
    pi_research_run_repo.record_outcome(a, bad, outcome_code="FAILED", usage_due=False)
    counts = pi_research_run_repo.operational_counts(a)
    assert counts == {"started": 3, "failed": 1, "interrupted": 0, "successful": 1}
    assert pi_research_run_repo.count_runs_for_tenant(a) == 3  # the existing field keeps its meaning: rows ever started
    assert pi_research_run_repo.get_run(a, stuck)["status"] == "QUEUED"


def _alembic(cwd: str, *args: str):
    return subprocess.run([sys.executable, "-m", "alembic", *args], capture_output=True, text=True, cwd=cwd, timeout=240)


@pytest.mark.skipif(
    os.environ.get("METRION_ALLOW_DOWNGRADE_TESTS") != "1",
    reason="runs alembic downgrade/upgrade against DATABASE_URL: opt in with METRION_ALLOW_DOWNGRADE_TESTS=1, only on a scratch/CI database, never the dev DB",
)
def test_the_downgrades_refuse_to_destroy_stored_accounting_decisions(two_tenants, app_user):
    a, _ = two_tenants
    pi_dir = os.path.join(ROOT, "..", "packages", "product-intelligence")
    brief = _brief(a, app_user)
    run = pi_research_run_repo.create_run(a, niche_brief_id=brief, depth="SHALLOW", trigger="DIRECT_UI", candidate_cap=5)
    pi_research_run_repo.record_outcome(a, run, outcome_code="USABLE", usage_due=True)
    refused = _alembic(pi_dir, "downgrade", "20261001_0001")
    assert refused.returncode != 0 and "accounting decisions" in (refused.stderr + refused.stdout)
    assert pi_research_run_repo.get_run(a, run)["usage_due"] is True  # untouched

    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded())
    inv = start(ctx, rt)
    from backend.ceo.dispatch import open_turn

    msg = repo.append_message(a, inv, role="USER", content="x", created_by=app_user, now=T0)
    anchor = open_turn(ctx, investigation_id=inv, now=T0).anchor_run_id
    turn = repo.create_turn(a, inv, user_message_id=msg, agent_run_id=anchor, route="ACTION", route_key="cfo.reconcile", status="PLAN_VALIDATED", now=T0)
    repo.update_turn(a, turn, status="DELIVERED", safety_result={"billing": {"ceoUnit": "DUE"}}, completed_at=T0)
    refused = _alembic(ROOT, "downgrade", "20261011_0016")
    assert refused.returncode != 0 and "billing decisions" in (refused.stderr + refused.stdout)
    assert cutover.effective_at("CEO_UNIT_RULE_2") is not None  # the cut-over survived

    # with the decisions gone the chains round-trip and the cut-over table comes back (a NEW, later effective_at)
    repo.update_turn(a, turn, status="DELIVERED", safety_result={}, completed_at=T0)
    with tenant_scope(a) as conn:
        conn.execute(text("UPDATE pi_research_run SET usage_due = NULL, outcome_code = NULL WHERE id = :i"), {"i": str(run)})
    try:
        assert _alembic(pi_dir, "downgrade", "20261001_0001").returncode == 0
        assert _alembic(ROOT, "downgrade", "20261011_0016").returncode == 0
    finally:
        assert _alembic(ROOT, "upgrade", "head").returncode == 0
        assert _alembic(pi_dir, "upgrade", "head").returncode == 0
    assert cutover.effective_at("PI_USAGE_1") is not None
