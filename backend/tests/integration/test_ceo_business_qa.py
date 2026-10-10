"""CEO business Q&A against a real Postgres (spec agent-needs-and-shared-knowledge.md sections 7 and 12, AC-Q1..Q4, Q6; T-Q1..T-Q4).

Seeded through the real repositories as `metrion_app`. Pinned: each new Business State entry (BS_PNL_RECENT, BS_SELLER_FACTS, BS_CMO_CONTENT_LATEST) is available /
partial / unavailable with the sentence code writes; tenant isolation; permission, attachment and entitlement filtering; every figure's ref re-resolves through the
provenance gate; each of the nine question types reads exactly its entries; an unknown question gets "not stored yet", never an invention; a state read computes and
writes nothing; the whole turn (rules router -> read -> template) states only figures that carry refs.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.auth.permissions import AGENT_CEO, AGENT_CFO
from backend.ceo import business_state as bs
from backend.ceo import memory, orchestrator, provenance, question_types
from backend.ceo.contract import EntryStatus, RefKind, Register
from backend.repositories import investigation_repo as repo
from tests.integration.ceo_support import ALL_AGENTS, ctx_for, insert_leak, later, partner_ctx, row_counts, save_metric, seed_platform_cap
from tests.integration.test_ceo_state_specialists import NOW, _scope, seed  # noqa: F401  (fixture + constants)
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SEP, AUG, JUL, JUN = "2026-09-01/2026-09-30", "2026-08-01/2026-08-31", "2026-07-01/2026-07-31", "2026-06-01/2026-06-30"
QT = question_types.QUESTION_TYPES


def read(ctx, key, *, attached=ALL_AGENTS, **kw):
    return bs.read_entry(ctx, key, attached=frozenset(attached), now=kw.pop("now", later(10)), **kw)


def seed_period(tenant, period, *, profit=100000, revenue=500000, fees=70000, at=1):
    return {
        "profit": save_metric(tenant, "CONTRIBUTION_PROFIT", period=period, value_paise=profit, computed_at=later(at)),
        "revenue": save_metric(tenant, "NET_REALIZED_REVENUE", period=period, value_paise=revenue, computed_at=later(at)),
        "fees": save_metric(tenant, "MARKETPLACE_FEES", period=period, value_paise=fees, computed_at=later(at)),
    }


def tenant_fact(tenant, user, *, kind="BUSINESS_NAME", key="business_name", value="Zyquora"):
    memory.promote(tenant, agent="CEO", kind=kind, key=key, value=value, basis="SELLER_STATED", source_ref={"message_id": str(uuid.uuid4())}, created_by=user)


@pytest.fixture
def cmo_rows(migrate_engine, app_user):
    """cmo_generation (+ title options) inserted as the table owner; removed again, children first."""
    made: list[tuple[uuid.UUID, uuid.UUID]] = []
    constraints: list[uuid.UUID] = []

    def constraint_ref() -> uuid.UUID:
        """A constraint-bound artefact (a title set) must cite the format rule it was written under: a TEST_FIXTURE rule, platform data with no tenant."""
        cid = uuid.uuid4()
        with migrate_engine.begin() as conn:
            conn.execute(text("INSERT INTO format_constraint (id, marketplace, category, title_max_chars, title_option_count, source_url, verified_at, version, row_kind) "
                              "VALUES (:id, 'AMAZON', :cat, 200, 5, 'https://example.com/rule', now(), 1, 'TEST_FIXTURE')"), {"id": str(cid), "cat": f"qa-{cid}"})
        constraints.append(cid)
        return cid

    def add(tenant, *, output_type="HASHTAGS", sku="SKU-1", marketplace="AMAZON", status="COMPLETE", output_text=None, options=(), created_at=NOW):
        gid = uuid.uuid4()
        with _scope(migrate_engine, tenant) as c:
            c.execute(text("INSERT INTO cmo_generation (id, tenant_id, sku, marketplace, output_type, input_mode, output_text, output_structured, format_constraint_ref, status, failure_reason, request_key, generated_by, created_at) "
                           "VALUES (:id, :t, :sku, :mp, :ot, 'INDEPENDENT', :txt, CAST(:structured AS jsonb), :fc, :st, :why, :rk, :by, :ts)"),
                      {"id": str(gid), "t": str(tenant), "sku": sku, "mp": marketplace, "ot": output_type, "txt": output_text, "structured": "{}" if options else None, "fc": str(constraint_ref()) if options else None, "st": status,
                       "why": "seeded failure" if status == "FAILED" else None, "rk": f"rk-{gid}", "by": str(app_user), "ts": created_at})
            for rank, title in enumerate(options, start=1):
                c.execute(text("INSERT INTO cmo_title_option (tenant_id, generation_id, rank, title_text, char_count, constraint_check) VALUES (:t, :g, :r, :title, :n, CAST('{}' AS jsonb))"),
                          {"t": str(tenant), "g": str(gid), "r": rank, "title": title, "n": len(title)})
        made.append((tenant, gid))
        return gid

    yield add
    for tenant, gid in made:
        with _scope(migrate_engine, tenant) as c:
            c.execute(text("DELETE FROM cmo_title_option WHERE generation_id = :id"), {"id": str(gid)})
            c.execute(text("DELETE FROM cmo_generation WHERE id = :id"), {"id": str(gid)})
    for cid in constraints:
        with migrate_engine.begin() as conn:
            conn.execute(text("DELETE FROM format_constraint WHERE id = :id"), {"id": str(cid)})


# ------------------------------------------------------------------------------------------- BS_PNL_RECENT
def test_pnl_recent_with_no_data_is_unavailable_never_zero(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), "BS_PNL_RECENT")
    assert entry.status is EntryStatus.UNAVAILABLE and entry.figures == () and entry.as_of is None and entry.gaps[0].code == "NO_PNL"


def test_pnl_recent_lists_the_newest_periods_each_figure_naming_its_own_period_and_citing_an_engine_result(two_tenants, app_user):
    a, _ = two_tenants
    seed_period(a, JUN, profit=1)
    jul, aug = seed_period(a, JUL, profit=200000), seed_period(a, AUG, profit=300000)
    stale = save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, value_paise=999, computed_at=later(1))
    sep = seed_period(a, SEP, profit=14230000, revenue=99999900, fees=1500050, at=3)  # a recompute of September supersedes the stale row

    entry = read(ctx_for(a, user_id=app_user), "BS_PNL_RECENT")

    assert entry.status is EntryStatus.PARTIAL and entry.period == SEP
    assert [g.code for g in entry.gaps] == ["TRUNCATED"]  # June is older than the three newest periods: said, not silently dropped
    labels = [f.label for f in entry.figures]
    assert len(labels) == 9 and all(re.search(r"\(\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}\)$", label) for label in labels)  # a figure never loses its period
    assert not any(JUN in label for label in labels)
    by_label = {f.label: f for f in entry.figures}
    assert by_label[f"Contribution profit ({SEP})"].formatted_value == "₹142,300.00" and by_label[f"Contribution profit ({SEP})"].ref.id == sep["profit"]
    assert by_label[f"Contribution profit ({AUG})"].ref.id == aug["profit"] and by_label[f"Contribution profit ({JUL})"].ref.id == jul["profit"]
    assert stale not in {f.ref.id for f in entry.figures}
    assert all(f.ref.kind is RefKind.ENGINE_RESULT and f.register is Register.DERIVED and f.as_of is not None for f in entry.figures)
    assert provenance.gate_figures(a, entry.figures).kept == entry.figures  # every ref re-resolves for THIS tenant (AC-Q4)


def test_pnl_recent_names_a_metric_not_computed_and_an_unavailable_one_but_never_shows_a_zero(two_tenants, app_user):
    a, _ = two_tenants
    save_metric(a, "CONTRIBUTION_PROFIT", period=SEP, available=False, unavailable_reason="COGS missing", value_paise=None)
    save_metric(a, "NET_REALIZED_REVENUE", period=SEP, value_paise=100)
    entry = read(ctx_for(a, user_id=app_user), "BS_PNL_RECENT")
    assert entry.status is EntryStatus.PARTIAL
    assert {g.code for g in entry.gaps} == {"UNAVAILABLE_CONTRIBUTION_PROFIT", "NO_MARKETPLACE_FEES"}
    profit = next(f for f in entry.figures if f.label.startswith("Contribution profit"))
    assert profit.formatted_value == "UNAVAILABLE" and profit.register is Register.UNAVAILABLE and "COGS missing" in (profit.note or "")
    assert not any(f.label.startswith("Marketplace fees") for f in entry.figures)


def test_pnl_recent_is_tenant_scoped_and_permission_attachment_and_entitlement_filtered(two_tenants, app_user, migrate_engine):
    a, b = two_tenants
    seed_period(a, SEP, profit=14230000)
    assert read(ctx_for(b, user_id=app_user), "BS_PNL_RECENT").status is EntryStatus.UNAVAILABLE  # another tenant's books are invisible
    no_perm = read(partner_ctx(a, AGENT_CEO), "BS_PNL_RECENT")
    assert no_perm.status is EntryStatus.NOT_PERMITTED and no_perm.figures == () and "142" not in repr(no_perm)
    detached = read(ctx_for(a, user_id=app_user), "BS_PNL_RECENT", attached={"CI", "PI", "CMO"})
    assert detached.status is EntryStatus.NOT_ATTACHED and detached.figures == ()
    seed_platform_cap(migrate_engine, agent_code="CFO", meter_code="cfo.business_state_read", cap_value=0)
    gated = read(ctx_for(a, user_id=app_user), "BS_PNL_RECENT")
    assert gated.status is EntryStatus.NOT_ENTITLED and gated.preview_hint == "cfo.preview" and gated.figures == ()


# ------------------------------------------------------------------------------------------- BS_SELLER_FACTS
def test_seller_facts_with_nothing_told_is_unavailable(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), "BS_SELLER_FACTS")
    assert entry.status is EntryStatus.UNAVAILABLE and entry.facts == () and entry.figures == () and entry.gaps[0].code == "NO_SELLER_FACTS"


def test_seller_facts_are_quoted_you_said_text_never_a_figure_and_never_agent_notes(two_tenants, app_user):
    a, _ = two_tenants
    tenant_fact(a, app_user)
    tenant_fact(a, app_user, kind="NICHE", key="niche", value="mens shoes")
    memory.note(a, agent="PI", key="last_category", value="AGENT PRIVATE NOTE", basis="AGENT_NOTE", source_ref=None, created_by=None)
    entry = read(ctx_for(a, user_id=app_user), "BS_SELLER_FACTS", attached=set())  # CEO-owned: attachment is irrelevant
    assert entry.status is EntryStatus.AVAILABLE and entry.figures == ()
    assert {f.label: f.text for f in entry.facts} == {"Business name (you said)": "“Zyquora”", "Your niche (you said)": "“mens shoes”"}
    assert all(f.basis == "SELLER_PROVIDED" for f in entry.facts) and "AGENT PRIVATE NOTE" not in repr(entry)


def test_a_forgotten_fact_is_not_reported_and_another_tenants_facts_are_invisible(two_tenants, app_user):
    a, b = two_tenants
    tenant_fact(a, app_user)
    [row] = [r for r in memory.repo.list_active(a, scope="SHARED")]
    assert memory.forget(a, row["id"], app_user)
    assert read(ctx_for(a, user_id=app_user), "BS_SELLER_FACTS").status is EntryStatus.UNAVAILABLE
    tenant_fact(a, app_user, value="Newname")
    assert read(ctx_for(b, user_id=app_user), "BS_SELLER_FACTS").status is EntryStatus.UNAVAILABLE


def test_seller_facts_need_agent_ceo(two_tenants, app_user):
    a, _ = two_tenants
    tenant_fact(a, app_user)
    assert read(partner_ctx(a, AGENT_CFO), "BS_SELLER_FACTS").status is EntryStatus.NOT_PERMITTED


# ------------------------------------------------------------------------------------------- BS_CMO_CONTENT_LATEST
def test_cmo_content_unavailable_when_nothing_was_written(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), "BS_CMO_CONTENT_LATEST")
    assert entry.status is EntryStatus.UNAVAILABLE and entry.artefacts == () and entry.gaps[0].code == "NO_CONTENT"


def test_cmo_content_is_quoted_and_labelled_never_a_figure_and_failed_attempts_are_not_shown(two_tenants, app_user, cmo_rows):
    a, _ = two_tenants
    cmo_rows(a, output_type="TITLE_SET", marketplace="AMAZON", options=("Steel Bottle Leakproof", "Steel Bottle Insulated"), created_at=NOW)
    cmo_rows(a, output_type="HASHTAGS", sku="SKU-2", marketplace=None, output_text="#steel #bottle", created_at=datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))
    cmo_rows(a, output_type="DESCRIPTION", sku="SKU-3", status="FAILED", output_text="SHOULD NOT APPEAR")
    entry = read(ctx_for(a, user_id=app_user), "BS_CMO_CONTENT_LATEST")
    assert entry.status is EntryStatus.AVAILABLE and entry.figures == () and entry.facts == () and entry.conflicts == ()
    titles = {title: items for title, items, _ in entry.artefacts}
    assert any(t.startswith("Written by Slim CMO: title options for SKU SKU-1 on Amazon") and items == ("Steel Bottle Leakproof", "Steel Bottle Insulated") for t, items in titles.items())
    assert any("hashtags" in t and items == ("#steel #bottle",) for t, items in titles.items())
    assert "SHOULD NOT APPEAR" not in repr(entry) and all("not verified" in (note or "") for _, _, note in entry.artefacts)


def test_cmo_content_is_tenant_scoped_and_needs_the_cmo_permission_attachment_and_entitlement(two_tenants, app_user, cmo_rows):
    a, b = two_tenants
    cmo_rows(a, output_text="#secret")
    assert read(ctx_for(b, user_id=app_user), "BS_CMO_CONTENT_LATEST").status is EntryStatus.UNAVAILABLE
    leaked = read(partner_ctx(a, AGENT_CEO), "BS_CMO_CONTENT_LATEST")
    assert leaked.status is EntryStatus.NOT_PERMITTED and leaked.artefacts == () and "#secret" not in repr(leaked)
    detached = read(ctx_for(a, user_id=app_user), "BS_CMO_CONTENT_LATEST", attached={"CFO", "CI", "PI"})
    assert detached.status is EntryStatus.NOT_ATTACHED and detached.artefacts == () and "#secret" not in repr(detached)


def test_the_cmo_workflow_entry_still_never_relays_the_copy(two_tenants, app_user, cmo_rows):
    a, _ = two_tenants
    cmo_rows(a, output_text="THE COPY ITSELF")
    assert "THE COPY ITSELF" not in repr(read(ctx_for(a, user_id=app_user), "BS_CMO_WORKFLOW"))  # R9: the old entry is unchanged; only the new one quotes, labelled


# ------------------------------------------------------------------------------------------- question types: empty tenant
EMPTY_STATUS = {
    "QT_PROFIT_BY_PERIOD": EntryStatus.UNAVAILABLE, "QT_LEAKS": EntryStatus.PARTIAL, "QT_DATA_GAPS": EntryStatus.PARTIAL, "QT_COMPETITORS_PRICES": EntryStatus.UNAVAILABLE,
    "QT_PRODUCT_IDEAS": EntryStatus.UNAVAILABLE, "QT_LISTING_CONTENT": EntryStatus.UNAVAILABLE, "QT_GOALS": EntryStatus.UNAVAILABLE, "QT_AGENT_FINDINGS": EntryStatus.UNAVAILABLE,
    "QT_SELLER_FACTS": EntryStatus.UNAVAILABLE, "QT_NOT_STORED": EntryStatus.UNAVAILABLE,
}
# QT_LEAKS and QT_DATA_GAPS are PARTIAL on an empty tenant because "no inputs are currently being requested" is itself a stored, true statement (BS_DATA_GAPS).


@pytest.mark.parametrize("qt_id", list(QT))
def test_every_question_type_on_an_empty_tenant_says_not_stored_in_the_code_written_sentence_and_shows_no_figure(two_tenants, app_user, qt_id):
    a, _ = two_tenants
    entry = read(ctx_for(a, user_id=app_user), qt_id)
    qt = QT[qt_id]
    assert entry.key == qt_id and entry.status is EMPTY_STATUS[qt_id] and entry.figures == () and entry.artefacts == ()
    messages = [g.message for g in entry.gaps]
    expected = {qt.not_stored, *(u.not_stored for u in qt.entries if u.not_stored)}
    assert expected & set(messages), (qt_id, messages)  # the sentence code writes, verbatim
    if qt.offer is not None:
        assert entry.offers == (qt.offer,)  # the action that could produce it is offered, never run


def test_the_goals_type_always_says_progress_is_not_stored(two_tenants, app_user):
    from backend.services.cfo_actions import set_seller_goal

    a, _ = two_tenants
    set_seller_goal(a, target_margin_pct="12.5", priority_category=None, note=None, created_by=app_user, now=NOW)
    entry = read(ctx_for(a, user_id=app_user), "QT_GOALS")
    assert entry.status is EntryStatus.PARTIAL and [f.formatted_value for f in entry.figures] == ["12.5%"]
    assert "Not stored yet. Progress against your goal is not tracked yet." in [g.message for g in entry.gaps]


def test_the_findings_type_is_unavailable_until_its_entry_exists_and_reads_it_when_it_does(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    assert "BS_SHARED_FINDINGS" not in bs.ENTRIES  # built by the findings slice
    assert read(ctx_for(a, user_id=app_user), "QT_AGENT_FINDINGS").gaps[0].message == QT["QT_AGENT_FINDINGS"].not_stored
    spec = bs.StateEntrySpec("BS_SHARED_FINDINGS", None, "test", "test", lambda ctx, now: bs.StateRead(EntryStatus.AVAILABLE, as_of=NOW, facts=(bs.Fact("Reported by CFO, not verified", "A leak was found.", "SOURCE_DERIVED"),)))
    monkeypatch.setitem(bs.ENTRIES, "BS_SHARED_FINDINGS", spec)  # the extension point: registering the entry is all that is needed
    entry = read(ctx_for(a, user_id=app_user), "QT_AGENT_FINDINGS")
    assert entry.status is EntryStatus.AVAILABLE and entry.facts[0].label == "Reported by CFO, not verified"


# ------------------------------------------------------------------------------------------- question types: populated
def test_profit_by_period_reads_pnl_recent_and_health_bands_and_cites_engine_results(two_tenants, app_user):
    a, _ = two_tenants
    ids = seed_period(a, SEP, profit=14230000)
    entry = read(ctx_for(a, user_id=app_user), "QT_PROFIT_BY_PERIOD")
    assert entry.status is EntryStatus.PARTIAL  # the band metrics are not stored: named, not guessed
    assert {f.ref.id for f in entry.figures} == set(ids.values())
    assert "Not stored yet. Health bands have not been saved for the latest period." in [g.message for g in entry.gaps]
    assert entry.offers == ()  # the P&L exists: the "run the profit and loss" chip is not offered for the missing bands
    assert provenance.gate_figures(a, entry.figures).kept == entry.figures


def test_leaks_reads_the_open_findings_and_the_data_gaps(two_tenants, app_user):
    a, _ = two_tenants
    leak = insert_leak(a, severity="HIGH", amount_paise=1840000)
    entry = read(ctx_for(a, user_id=app_user), "QT_LEAKS")
    assert entry.status is EntryStatus.AVAILABLE and [f.ref.id for f in entry.figures] == [leak] and entry.figures[0].formatted_value == "₹18,400.00"
    assert provenance.gate_figures(a, entry.figures).kept == entry.figures


def test_data_gaps_reads_requests_and_uploads(two_tenants, app_user):
    from cfo.repositories import agent_data_request_repo

    a, _ = two_tenants
    agent_data_request_repo.insert(a, requested_field="cogs.SKU-1", reason="COGS needed to compute margin", blocking_metric="CONTRIBUTION_PROFIT")
    entry = read(ctx_for(a, user_id=app_user), "QT_DATA_GAPS")
    assert any("cogs.SKU-1" in g.message for g in entry.gaps) and "Not stored yet. No marketplace report has been uploaded; upload your settlement and order reports on the Finance page." in [g.message for g in entry.gaps]


def test_competitor_prices_and_product_ideas_and_listing_content_read_their_entries(two_tenants, app_user, seed, cmo_rows):
    a, _ = two_tenants
    snap = seed.snapshot(a, seed.url(a, "Rival One"), 49900)
    prices = read(ctx_for(a, user_id=app_user), "QT_COMPETITORS_PRICES")
    assert prices.status is EntryStatus.AVAILABLE and prices.figures[0].ref.id == snap and prices.figures[0].formatted_value == "₹499.00"
    seed.run(a, "COMPLETE")
    ideas = read(ctx_for(a, user_id=app_user), "QT_PRODUCT_IDEAS")
    assert ideas.status is EntryStatus.AVAILABLE and ideas.offers == (QT["QT_PRODUCT_IDEAS"].available_offer,)  # the saved report can be re-shown: offered, not run
    cmo_rows(a, output_text="#steel #bottle")
    content = read(ctx_for(a, user_id=app_user), "QT_LISTING_CONTENT")
    assert content.status is EntryStatus.AVAILABLE and content.artefacts and content.figures == ()


def test_seller_facts_type_reads_what_the_seller_said(two_tenants, app_user):
    a, _ = two_tenants
    tenant_fact(a, app_user)
    entry = read(ctx_for(a, user_id=app_user), "QT_SELLER_FACTS")
    assert entry.status is EntryStatus.AVAILABLE and entry.facts[0].text == "“Zyquora”"


# ------------------------------------------------------------------------------------------- question types: gates
def test_a_type_applies_permission_attachment_and_entitlement_with_the_code_written_sentence(two_tenants, app_user, migrate_engine):
    a, b = two_tenants
    seed_period(a, SEP, profit=14230000)
    no_ceo = read(partner_ctx(a, AGENT_CFO), "QT_PROFIT_BY_PERIOD")
    assert no_ceo.status is EntryStatus.NOT_PERMITTED and no_ceo.figures == () and no_ceo.gaps[0].message == question_types.NOT_PERMITTED_TEXT
    no_cfo = read(partner_ctx(a, AGENT_CEO), "QT_PROFIT_BY_PERIOD")
    assert no_cfo.status is EntryStatus.NOT_PERMITTED and no_cfo.figures == () and "142" not in repr(no_cfo) and no_cfo.preview_hint is None  # the wall, not the preview
    ci_gone = read(ctx_for(a, user_id=app_user), "QT_COMPETITORS_PRICES", attached={"CFO", "PI", "CMO"})
    assert ci_gone.status is EntryStatus.NOT_ATTACHED and ci_gone.gaps[0].message == question_types.NOT_ATTACHED_TEXT.format(agent="CI") and ci_gone.figures == ()
    assert read(ctx_for(b, user_id=app_user), "QT_PROFIT_BY_PERIOD").figures == ()  # tenant isolation holds through the composite
    seed_platform_cap(migrate_engine, agent_code="CFO", meter_code="cfo.business_state_read", cap_value=0)
    gated = read(ctx_for(a, user_id=app_user), "QT_PROFIT_BY_PERIOD")
    assert gated.status is EntryStatus.NOT_ENTITLED and gated.preview_hint == "cfo.preview" and gated.figures == ()
    assert gated.gaps[0].message == question_types.NOT_ENTITLED_TEXT.format(agent="CFO")


def test_a_mixed_type_shows_what_is_permitted_and_names_what_is_not(two_tenants, app_user):
    a, _ = two_tenants
    entry = read(partner_ctx(a, AGENT_CEO, "files.view"), "QT_DATA_GAPS")
    messages = [g.message for g in entry.gaps]
    assert entry.status is EntryStatus.NOT_PERMITTED and entry.figures == ()  # nothing readable has a result, so the most restrictive reason leads
    assert question_types.NOT_PERMITTED_TEXT in messages  # BS_DATA_GAPS is CFO-owned: named, not read
    assert any(m.startswith("Not stored yet.") for m in messages)  # the upload status (files.view) WAS read, and is empty: also said


def test_an_unknown_question_type_is_never_read(two_tenants, app_user):
    a, _ = two_tenants
    with pytest.raises(KeyError):
        read(ctx_for(a, user_id=app_user), "QT_EVERYTHING")


def test_reading_every_question_type_computes_and_writes_nothing(two_tenants, app_user):
    a, _ = two_tenants
    seed_period(a, SEP)
    before = row_counts(a, "metric_result", "leak_finding", "agent_run", "manual_adjustment", "agent_data_request", "metered_event", "investigation")
    for qt_id in QT:
        read(ctx_for(a, user_id=app_user), qt_id)
    assert row_counts(a, "metric_result", "leak_finding", "agent_run", "manual_adjustment", "agent_data_request", "metered_event", "investigation") == before  # AC-Q1


# ------------------------------------------------------------------------------------------- the whole turn
def ask(tenant, user, message, *, attached=None):
    ctx = ctx_for(tenant, user_id=user)
    cls, comp = Scripted({}), Grounded()
    rt = runtime(cls, comp)
    if attached is None:
        inv = orchestrator.start_investigation(ctx, rt)
    else:
        inv = repo.create_investigation(tenant, created_by=user, attached_agents=tuple(attached), detached_agents=tuple(ALL_AGENTS - set(attached)), now=NOW)
    res = orchestrator.run_turn(ctx, rt, inv, message)
    assert cls.calls == 0 and comp.calls == 0  # routed by rule, answered by the template: no model in the Q&A path
    return res, inv


def test_a_profit_question_is_answered_from_cited_figures_only(two_tenants, app_user):
    a, _ = two_tenants
    ids = seed_period(a, SEP, profit=14230000, revenue=99999900, fees=1500050)
    res, inv = ask(a, app_user, "What was my profit in September?")
    assert (res.status, res.route, res.composition_mode) == ("DELIVERED", "BUSINESS_STATE", "TEMPLATE")
    assert "₹142,300.00" in res.answer and "₹999,999.00" in res.answer and "₹15,000.50" in res.answer
    [finding] = repo.list_findings(a, inv)
    assert (finding["source"], finding["action_key"]) == ("BUSINESS_STATE", "QT_PROFIT_BY_PERIOD")
    assert {r["id"] for r in finding["figure_refs"]} == {str(i) for i in ids.values()}  # every figure shown carries a ref
    shown = {f["value"] for f in finding["presentation"]["figures"]}
    assert shown == {"₹142,300.00", "₹999,999.00", "₹15,000.50"}
    numbers_in_answer = set(re.findall(r"₹[\d,]+\.\d\d", res.answer))
    assert numbers_in_answer <= shown  # the answer states no currency amount that is not a cited figure


def test_an_empty_profit_question_says_not_stored_offers_the_run_and_states_no_number(two_tenants, app_user):
    a, _ = two_tenants
    res, inv = ask(a, app_user, "What was my profit in September?")
    assert res.status == "DELIVERED" and QT["QT_PROFIT_BY_PERIOD"].not_stored in res.answer and "[Offered, not run: Run the profit and loss for a period]" in res.answer
    [finding] = repo.list_findings(a, inv)
    assert finding["presentation"]["offers"] == [{"key": "cfo.pnl_for_tenant", "label": "Run the profit and loss for a period"}] and finding["presentation"]["figures"] == []
    assert "₹" not in res.answer and not re.search(r"[0-9]", res.answer)  # a non-result states no number at all


def test_an_unknown_own_data_question_gets_not_stored_not_an_invention(two_tenants, app_user):
    a, _ = two_tenants
    seed_period(a, SEP, profit=14230000)
    res, _ = ask(a, app_user, "How much stock do I have?")
    assert (res.route, res.status) == ("BUSINESS_STATE", "DELIVERED") and QT["QT_NOT_STORED"].not_stored in res.answer
    assert "₹" not in res.answer  # the books in the database are not used to invent a stock figure


def test_a_detached_agents_question_says_to_attach_it(two_tenants, app_user, seed):
    a, _ = two_tenants
    seed.snapshot(a, seed.url(a, "Rival One"), 49900)
    res, _ = ask(a, app_user, "What are my competitors charging?", attached={"CFO", "PI", "CMO"})
    assert question_types.NOT_ATTACHED_TEXT.format(agent="CI") in res.answer and "₹499.00" not in res.answer


def test_a_member_without_the_cfo_permission_gets_the_wall_not_a_figure(two_tenants, app_user):
    a, _ = two_tenants
    seed_period(a, SEP, profit=14230000)
    ctx = partner_ctx(a, AGENT_CEO, "investigation.create", "investigation.view")
    rt = runtime(Scripted({}), Grounded())
    inv = orchestrator.start_investigation(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "What was my profit in September?")
    assert question_types.NOT_PERMITTED_TEXT in res.answer and "142" not in res.answer


def test_a_classified_question_type_is_read_the_same_way(two_tenants, app_user):
    """The classifier path (no rule matches): a closed-enum value naming a type is read; the model supplied no figure, SQL or slot."""
    from tests.integration.test_ceo_turn import decision

    a, _ = two_tenants
    seed_period(a, SEP, profit=14230000)
    msg = "Give me a quick sense of the money side"
    ctx = ctx_for(a, user_id=app_user)
    cls = Scripted({msg: decision(route="BUSINESS_STATE", route_key="QT_PROFIT_BY_PERIOD")})
    rt = runtime(cls, Grounded())
    res = orchestrator.run_turn(ctx, rt, orchestrator.start_investigation(ctx, rt), msg)
    assert (res.route, res.status, res.composition_mode) == ("BUSINESS_STATE", "DELIVERED", "TEMPLATE") and "₹142,300.00" in res.answer and cls.calls == 1


def test_the_classifier_naming_an_unknown_type_is_a_clarification_and_reads_nothing(two_tenants, app_user):
    from tests.integration.test_ceo_turn import decision

    a, _ = two_tenants
    seed_period(a, SEP, profit=14230000)
    msg = "Tell me the money side please"
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({msg: decision(route="BUSINESS_STATE", route_key="QT_EVERYTHING_IN_THE_DATABASE")}), Grounded())
    inv = orchestrator.start_investigation(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, msg)
    assert res.status == "CLARIFIED" and "₹" not in res.answer and repo.list_findings(a, inv) == []
