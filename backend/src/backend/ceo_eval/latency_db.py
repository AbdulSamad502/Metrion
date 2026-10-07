"""Real-stack latency of the CEO's deterministic stages (spec §6.26 L1) — measured against a real Postgres, as `metrion_app`.

What it times (each stage separately, N repetitions, wall milliseconds):

    cap_check            `resolve_ceo_entitlement` alone
    open_turn            permission + cap check + anchor `agent_run` insert (the full "turn admission")
    state_read:<ENTRY>   one Business State read through the full gating order (permission -> attachment -> entitlement -> read -> provenance gate)
    state_reads_sequential / state_reads_parallel   all six entries, one after another vs on a thread pool (an upper bound for L6 prefetch / B4)
    dispatch:<ACTION>    one real specialist leg through the choke point (child `agent_run`, provenance, finding)
    dispatch_denied      a leg refused at the permission step (the cost of a refusal)
    legs_sequential / legs_parallel   three real legs one after another vs concurrently (the CEO -> N specialists -> synthesis shape)

Honest limits (recorded in the report): this is a scratch Postgres on the same machine as the model server, with a small
synthetic tenant (a few hundred rows) — it measures the code path and query cost, not production data volume, network
or contention. It never runs against a database unless `--db-ok` is given, and prints which one.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from backend.ceo_eval.runner import stats

_REPO_ROOT = Path(__file__).resolve().parents[4]
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
_PERIODS = [(date(2026, m, 1), date(2026, m, 28)) for m in range(1, 10)]


def _ms(fn: Callable[[], Any]) -> tuple[int, Any]:
    t = time.perf_counter()
    out = fn()
    return int((time.perf_counter() - t) * 1000), out


def describe_target() -> str:
    from urllib.parse import urlparse

    u = urlparse(os.environ["DATABASE_URL_APP"].replace("+psycopg", ""))
    return f"{u.hostname}:{u.port}{u.path}"


def seed(migrate_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    from calc_engine.api.compute_metric import MetricResult
    from calc_engine.repositories import metric_result_repo
    from calc_engine.types import RecognitionState
    from cfo.repositories import leak_finding_repo

    tenant, user = uuid.uuid4(), uuid.uuid4()
    eng = create_engine(migrate_url)
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO tenant (id, clerk_org_id, business_name, status, created_at) VALUES (:i, :o, 'ceo-eval latency seed', 'ACTIVE', now())"), {"i": str(tenant), "o": f"org_{tenant}"})
        conn.execute(text("INSERT INTO app_user (id, clerk_user_id, email, auth_provider, created_at) VALUES (:i, :c, :e, 'EMAIL_PASSWORD', now())"), {"i": str(user), "c": f"user_{user}", "e": f"{user}@example.com"})
    eng.dispose()

    def save(code: str, period: str, *, paise: int | None = None, fraction: tuple[int, int] | None = None) -> None:
        metric_result_repo.save(
            tenant,
            MetricResult(
                id=uuid.uuid4(), metric_code=code, value_paise=paise if fraction is None else None, recognition_state=RecognitionState.RECOGNISED, confidence="DERIVED",
                calculation_basis="latency seed", formula_version="seed.v1", canonical_data_version="non-canonical", as_of_date=date(2026, 10, 1), input_refs=(),
                exclusions=(), computed_at=T0, is_available=True, value_fraction=Fraction(*fraction) if fraction else None, unavailable_reason=None,
            ),
            grain="TENANT_PERIOD", target_ref=str(tenant), period=period, config_version="1",
        )

    for i, (start, end) in enumerate(_PERIODS):
        period = f"{start.isoformat()}/{end.isoformat()}"
        save("NET_REALIZED_REVENUE", period, paise=48_215_000 + i * 100_000)
        save("CONTRIBUTION_PROFIT", period, paise=6_132_000 + i * 10_000)
        save("MARKETPLACE_FEES", period, paise=7_104_400 + i * 5_000)
        save("CONTRIBUTION_MARGIN_PCT", period, fraction=(254, 20))
        save("FEE_RATIO_PCT", period, fraction=(295, 20))
        save("RETURN_RATE_PCT", period, fraction=(70, 20))
    for i in range(60):
        leak_finding_repo.insert(
            tenant, reconciliation_exception_id=uuid.uuid4(), engine_result_ref=uuid.uuid4(), marketplace="FLIPKART" if i % 2 else "AMAZON",
            leak_category="COMMISSION_OVERCHARGE", severity=("HIGH", "MEDIUM", "LOW")[i % 3], amount_paise=100_000 + i * 1_000, affected_line_count=1,
            first_observed_at=T0 - timedelta(days=i), age_days=i, status="NEW", confidence="DERIVED", formula_version="seed.v1", sku=f"SKU-{i}",
        )
    return tenant, user


HEALTH = {"period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-10-01"}
BRIEFING = {"period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-10-01"}
ANOMALY = {"target_ref": "TENANT", "period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-10-01", "include_narration": False}
LEGS = (("cfo.financial_health", HEALTH), ("cfo.strategic_briefing", BRIEFING), ("cfo.anomaly_check", ANOMALY))


def run(repeat: int = 20, migrate_url: str | None = None) -> dict[str, Any]:
    sys.path.insert(0, str(_REPO_ROOT / "tools"))
    from testkit.tenant_cleanup import TRACKER

    from backend.auth.context import AuthContext
    from backend.auth.permissions import OWNER_ROLE, PARTNER_ROLE
    from backend.ceo import business_state
    from backend.ceo.dispatch import dispatch, open_turn
    from backend.entitlement import resolve_ceo_entitlement

    migrate_url = migrate_url or os.environ["DATABASE_URL"]
    TRACKER.install()
    TRACKER.reset()
    tenant, user = seed(migrate_url)
    attached = frozenset({"CFO", "CI", "PI", "CMO"})

    def ctx(role: str = OWNER_ROLE, perms: dict[str, object] | None = None) -> AuthContext:
        return AuthContext(app_user_id=user, clerk_user_id="user_eval", email_verified=True, tenant_id=tenant, membership_status="ACTIVE", role=role,
                           permissions=perms or {}, onboarding_state="ACTIVE")

    owner = ctx()
    out: dict[str, Any] = {"database": describe_target(), "repeat": repeat, "seed": {"periods": len(_PERIODS), "metric_rows": len(_PERIODS) * 6, "leak_findings": 60}, "stages": {}, "notes": []}
    rec = out["stages"]

    def timed(name: str, fn: Callable[[], Any], n: int = repeat) -> list[Any]:
        fn()  # one untimed warm-up: connection pool + planner caches (a steady-state seller session, not the first request after boot)
        vals, outs = [], []
        for _ in range(n):
            ms, o = _ms(fn)
            vals.append(ms)
            outs.append(o)
        rec[name] = stats(vals)
        return outs

    try:
        timed("cap_check", lambda: resolve_ceo_entitlement(tenant, occurred_at=T0))

        def admit() -> None:
            turn = open_turn(owner)
            turn.close(status="COMPLETE")

        timed("open_turn", admit)
        for key in business_state.catalog_keys():
            timed(f"state_read:{key}", lambda k=key: business_state.read_entry(owner, k, attached=attached))
        timed("state_reads_sequential", lambda: business_state.read_entries(owner, business_state.catalog_keys(), attached=attached))

        def parallel_reads() -> None:
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(lambda k: business_state.read_entry(owner, k, attached=attached), business_state.catalog_keys()))

        timed("state_reads_parallel", parallel_reads)

        def leg(key: str, slots: dict[str, Any], turn: Any) -> Any:
            return dispatch(turn, key, slots)

        statuses: dict[str, list[str]] = {}
        for key, slots in LEGS:
            def one(key: str = key, slots: dict[str, Any] = slots) -> str:
                turn = open_turn(owner)
                res = leg(key, slots, turn)
                turn.close(status=turn.derive_status())
                return res.status.value

            statuses[key] = timed(f"dispatch:{key}", one)
        out["leg_statuses"] = {k: sorted(set(v)) for k, v in statuses.items()}

        def denied() -> None:
            c = ctx(PARTNER_ROLE, {"agent.ceo": True})  # CEO key only: the CFO key is missing
            turn = open_turn(c)
            dispatch(turn, "cfo.financial_health", HEALTH)
            turn.close(status=turn.derive_status())

        timed("dispatch_denied", denied)

        def legs_seq() -> None:
            turn = open_turn(owner)
            for key, slots in LEGS:
                dispatch(turn, key, slots)
            turn.close(status=turn.derive_status())

        def legs_par() -> None:
            turn = open_turn(owner)
            with ThreadPoolExecutor(max_workers=len(LEGS)) as pool:
                list(pool.map(lambda ks: dispatch(turn, ks[0], ks[1]), LEGS))
            turn.close(status=turn.derive_status())

        timed("legs_sequential(3)", legs_seq, max(5, repeat // 2))
        timed("legs_parallel(3)", legs_par, max(5, repeat // 2))
    finally:
        # the tracker recorded exactly the tenant/app_user this run created; nothing else can be purged
        migrate = create_engine(migrate_url)
        try:
            TRACKER.purge(migrate)
        finally:
            migrate.dispose()
            TRACKER.uninstall()
    return out
