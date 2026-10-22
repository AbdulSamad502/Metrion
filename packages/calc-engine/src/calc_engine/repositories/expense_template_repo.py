"""expense_template repository — engine §5.18.1 / §5.18.2; migration `20261022_0014_expense_template.py`.

Templates are standing instructions, stored as immutable versions (INSERT and SELECT only). `materialise` turns them into ordinary ledger records through
`expense_ledger_repo.insert_record`: each is a `pending_review` record (X10: nothing recurring is counted until the seller confirms it), dated the first of its month, flagged
`recurring`, with the idempotency key `template:<template_key>:<yyyy-mm>` — so materialising again creates nothing twice and a voided entry is not silently recreated.
The amounts come from `calc_engine/formulas/expense_templates.py`; this module only selects the version that applies to a month and routes the result.

Per-order and per-unit templates need the engine's own order / unit count for the month (§5.10.1); until that count source is wired they are NEVER materialised with a made-up
amount: they are reported as skipped with the engine's reason (`ORDERS_UNAVAILABLE` / `UNITS_UNAVAILABLE`), not zero.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from calc_engine.formulas import expense_templates as engine
from calc_engine.repositories import expense_ledger_repo as ledger
from calc_engine.repositories.expense_ledger_repo import NewRecord
from calc_engine.repositories.tenant_context import tenant_scope

KINDS = ("MONTHLY", "AMORTIZED", "PER_ORDER", "PER_UNIT")


@dataclass(frozen=True, slots=True)
class NewTemplate:
    kind: str
    category: str
    cost_class: str
    effective_from: date
    treatment: str = "incremental"
    vendor: str | None = None
    description: str | None = None
    amount_paise: int | None = None
    rate_paise: int | None = None
    amortization_months: int | None = None
    start_month: date | None = None
    channel_scope: str | None = None
    sku: str | None = None
    effective_to: date | None = None
    ended: bool = False


@dataclass(slots=True)
class MaterialiseResult:
    created: list[UUID] = field(default_factory=list)
    replayed: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (template_key, reason)


_COLUMNS = (
    "id, template_key, version, kind, vendor, description, category, cost_class, treatment, amount_paise, rate_paise, amortization_months, start_month, channel_scope, sku, "
    "effective_from, effective_to, ended, created_by, created_at"
)


def _insert(conn: Any, tenant_id: UUID, key: UUID, version: int, t: NewTemplate, created_by: UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO expense_template (id, tenant_id, template_key, version, kind, vendor, description, category, cost_class, treatment, amount_paise, rate_paise, "
            "amortization_months, start_month, channel_scope, sku, effective_from, effective_to, ended, created_by) VALUES (:id, :tenant, :key, :version, :kind, :vendor, "
            ":description, :category, :cost_class, :treatment, :amount, :rate, :months, :start, :channel, :sku, :efrom, :eto, :ended, :user)"
        ),
        {
            "id": str(uuid4()), "tenant": str(tenant_id), "key": str(key), "version": version, "kind": t.kind, "vendor": t.vendor, "description": t.description,
            "category": t.category, "cost_class": t.cost_class, "treatment": t.treatment, "amount": t.amount_paise, "rate": t.rate_paise, "months": t.amortization_months,
            "start": engine.first_of_month(t.start_month) if t.start_month else None, "channel": t.channel_scope, "sku": t.sku, "efrom": t.effective_from,
            "eto": t.effective_to, "ended": t.ended, "user": str(created_by),
        },
    )


def create(tenant_id: UUID, template: NewTemplate, *, created_by: UUID) -> UUID:
    """A new template: version 1 of a new key. Returns the key."""
    key = uuid4()
    with tenant_scope(tenant_id) as conn:
        _insert(conn, tenant_id, key, 1, template, created_by)
    return key


def new_version(tenant_id: UUID, template_key: UUID, template: NewTemplate, *, created_by: UUID) -> int:
    """A change (a new rate or amount, or ending the template) is a NEW version; earlier versions are untouched. Raises LookupError for an unknown key."""
    with tenant_scope(tenant_id) as conn:
        current = conn.execute(
            text("SELECT max(version) FROM expense_template WHERE tenant_id = :tenant AND template_key = :key"), {"tenant": str(tenant_id), "key": str(template_key)}
        ).scalar_one()
        if current is None:
            raise LookupError(f"no template {template_key} for this tenant")
        _insert(conn, tenant_id, template_key, int(current) + 1, template, created_by)
    return int(current) + 1


def versions(tenant_id: UUID, template_key: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(f"SELECT {_COLUMNS} FROM expense_template WHERE tenant_id = :tenant AND template_key = :key ORDER BY version"),
            {"tenant": str(tenant_id), "key": str(template_key)},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def list_current(tenant_id: UUID) -> list[dict[str, Any]]:
    """The newest version of every template key."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM expense_template t WHERE tenant_id = :tenant AND version = "
                "(SELECT max(version) FROM expense_template m WHERE m.tenant_id = t.tenant_id AND m.template_key = t.template_key) ORDER BY created_at, template_key"
            ),
            {"tenant": str(tenant_id)},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def _all_versions(tenant_id: UUID) -> dict[UUID, list[dict[str, Any]]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text(f"SELECT {_COLUMNS} FROM expense_template WHERE tenant_id = :tenant ORDER BY template_key, version"), {"tenant": str(tenant_id)}).fetchall()
    out: dict[UUID, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(UUID(str(r.template_key)), []).append(dict(r._mapping))
    return out


def _version_for_month(vs: list[dict[str, Any]], month: date) -> dict[str, Any] | None:
    """The version effective in the month: the latest `effective_from` on or before the month's last day... evaluated on the month's first day, whose `effective_to` has not
    passed. An `ended` version covers nothing after its `effective_to`."""
    closed = [v["effective_to"] for v in vs if v["ended"] and v["effective_to"] is not None]
    if closed and month > max(closed):
        return None  # an ended template closes every earlier version too
    covering = [v for v in vs if engine.first_of_month(v["effective_from"]) <= month and (v["effective_to"] is None or month <= v["effective_to"])]
    return max(covering, key=lambda v: (v["effective_from"], v["version"])) if covering else None


CountProvider = Callable[[date, date, str], engine.CountOutcome]
"""`(period_start, period_end, "ORDER" | "UNIT") -> CountOutcome`: the engine's own count of the tenant's sales lines in that window (supplied by the caller, which owns the sales
data; see `backend/services/expense_template_counts.py`). Without one, per-order and per-unit templates are skipped as unavailable."""


def _segments(vs: list[dict[str, Any]], month: date) -> list[tuple[dict[str, Any], date, date]]:
    """The slices of one month and the template version in force on each (a rate change mid-month splits it): a version covers from its `effective_from` until the next
    version's `effective_from` (or its own `effective_to`, or the end of the month)."""
    last = date(month.year, month.month, monthrange(month.year, month.month)[1])
    closed = [v["effective_to"] for v in vs if v["ended"] and v["effective_to"] is not None]
    horizon = min(last, max(closed)) if closed else last
    ordered = sorted({v["effective_from"]: v for v in sorted(vs, key=lambda v: v["version"])}.values(), key=lambda v: v["effective_from"])  # latest version per start date
    out: list[tuple[dict[str, Any], date, date]] = []
    for i, v in enumerate(ordered):
        end = horizon if i + 1 == len(ordered) else min(horizon, ordered[i + 1]["effective_from"].fromordinal(ordered[i + 1]["effective_from"].toordinal() - 1))
        if v["effective_to"] is not None:
            end = min(end, v["effective_to"])
        begin = max(month, v["effective_from"])
        if begin <= end:
            out.append((v, begin, end))
    return out


def _per_count_entry(
    vs: list[dict[str, Any]], month: date, counts: CountProvider, per: str, any_rate_missing: list[bool]
) -> tuple[int, str] | str:
    """`(amount_paise, description)` for one month of a per-order or per-unit template, or the engine's reason string when the month cannot be priced (never a partial sum)."""
    total = 0
    parts: list[str] = []
    for version, begin, end in _segments(vs, month):
        outcome = counts(begin, end, per)
        priced = engine.per_count_amount(version["rate_paise"], outcome.count, per=per, any_sales_lines=outcome.any_lines)
        if priced.amount is None:
            return outcome.reason or priced.reason or (engine.ORDERS_UNAVAILABLE if per == "ORDER" else engine.UNITS_UNAVAILABLE)
        total += priced.amount.value
        rupees, paise = divmod(int(version["rate_paise"]), 100)
        parts.append(f"{outcome.count} {'orders' if per == 'ORDER' else 'units'} x Rs {rupees}.{paise:02d}")
    if not parts:
        return engine.NO_ORDERS_IN_PERIOD
    return total, " + ".join(parts)


def _schedule_of(vs: list[dict[str, Any]]) -> engine.AmortizationSchedule:
    """The amortization schedule in force: version 1 is the original; a later version (a refund) restarts the remainder from its own start month."""
    parts = [(v["start_month"], int(v["amount_paise"]), v["amortization_months"]) for v in vs if v["kind"] == "AMORTIZED"]
    if any(m is None or not isinstance(m, int) or isinstance(m, bool) for _, _, m in parts):
        return engine.amortization_schedule(0, None, None)
    return engine.effective_schedule(parts)


def schedule_of(tenant_id: UUID, template_key: UUID) -> engine.AmortizationSchedule:
    """The current amortization schedule of a template (empty and invalid for an unknown key or a template that is not amortized)."""
    vs = versions(tenant_id, template_key)
    if not vs or vs[0]["kind"] != "AMORTIZED":
        return engine.amortization_schedule(0, None, None)
    return _schedule_of(vs)


def refund_amortized(tenant_id: UUID, template_key: UUID, *, refund_date: date, refund_paise: int, created_by: UUID) -> engine.RefundOutcome:
    """A refund of an amortized expense (section 5.18.1, Q31): reduces what is left to amortize from the refund month forward, as a NEW template version, so earlier months and
    the entries already made from them are never restated. Returns the engine's outcome; nothing is written unless it carries no reason. Raises LookupError for an unknown or
    non-amortized template."""
    vs = versions(tenant_id, template_key)
    if not vs or vs[0]["kind"] != "AMORTIZED":
        raise LookupError(f"no amortized template {template_key} for this tenant")
    outcome = engine.refund_remaining(_schedule_of(vs), refund_paise, refund_date)
    if outcome.reason is not None:
        return outcome
    latest = vs[-1]
    new_version(
        tenant_id, template_key,
        NewTemplate(
            kind="AMORTIZED", category=latest["category"], cost_class=latest["cost_class"], treatment=latest["treatment"], effective_from=latest["effective_from"],
            effective_to=latest["effective_to"], vendor=latest["vendor"], description=latest["description"], amount_paise=outcome.remaining_total.value,  # type: ignore[union-attr]
            amortization_months=outcome.months, start_month=outcome.start, channel_scope=latest["channel_scope"], sku=latest["sku"], ended=latest["ended"],
        ),
        created_by=created_by,
    )
    return outcome


def materialise(tenant_id: UUID, *, through_month: date, created_by: UUID, counts: CountProvider | None = None, today: date | None = None) -> MaterialiseResult:
    """Creates the `pending_review` entries for every month up to and including `through_month` that has none yet. Safe to repeat.

    A per-order or per-unit template needs `counts` (the engine's count of the month's sales lines) and a FINISHED month (`today` after the month's last day), because an entry
    made from a half-uploaded month would stay at that count: otherwise it is skipped with the engine's reason (`ORDERS_UNAVAILABLE`, `UNITS_UNAVAILABLE`, `NO_ORDERS_IN_PERIOD`,
    `MONTH_NOT_FINISHED`), never with a made-up amount."""
    result = MaterialiseResult()
    through = engine.first_of_month(through_month)
    for key, vs in _all_versions(tenant_id).items():
        first = vs[0]
        if first["kind"] in ("PER_ORDER", "PER_UNIT"):
            per = "ORDER" if first["kind"] == "PER_ORDER" else "UNIT"
            skipped: list[str] = []
            for month in engine.months_inclusive(min(v["effective_from"] for v in vs), through):
                if not _segments(vs, month):
                    continue
                if counts is None:
                    reason: str | None = engine.ORDERS_UNAVAILABLE if per == "ORDER" else engine.UNITS_UNAVAILABLE
                    priced: tuple[int, str] | str = reason
                elif today is not None and date(month.year, month.month, monthrange(month.year, month.month)[1]) >= today:
                    priced = engine.MONTH_NOT_FINISHED
                else:
                    priced = _per_count_entry(vs, month, counts, per, [])
                if isinstance(priced, str):
                    if priced not in skipped:
                        skipped.append(priced)
                        result.skipped.append((str(key), priced))
                    continue
                version = _segments(vs, month)[-1][0]
                amount, why = priced
                res = ledger.insert_record(
                    tenant_id,
                    NewRecord(
                        effective_date=month, category=version["category"], cost_class=version["cost_class"], amount_paise=amount, treatment=version["treatment"],
                        vendor=version["vendor"], description=(f"{version['description']}: {why}" if version["description"] else why),
                        channel_scope=version["channel_scope"], sku=version["sku"], source_reference=f"template:{key}:{month:%Y-%m}", recurring=True,
                    ),
                    review_state="pending_review", created_by=created_by, idempotency_key=f"template:{key}:{month:%Y-%m}",
                )
                if res.replayed:
                    result.replayed += 1
                else:
                    result.created.append(res.expense_id)
            continue
        start = engine.first_of_month(min(v["effective_from"] for v in vs))
        schedule = None
        if first["kind"] == "AMORTIZED":
            schedule = _schedule_of(vs)
            if not schedule.valid:
                result.skipped.append((str(key), engine.AMORTIZATION_INVALID))
                continue
            start = schedule.months[0]
        for month in engine.months_inclusive(start, through):
            version = _version_for_month(vs, month)
            if version is None:
                continue  # not covered (before it started or after it ended): nothing is created, which is not a zero
            if schedule is not None:
                if month not in schedule.months:
                    continue
                amount = schedule.shares[schedule.months.index(month)].value
            else:
                amount = int(version["amount_paise"])
            res = ledger.insert_record(
                tenant_id,
                NewRecord(
                    effective_date=month, category=version["category"], cost_class=version["cost_class"], amount_paise=amount, treatment=version["treatment"],
                    vendor=version["vendor"], description=version["description"], channel_scope=version["channel_scope"], sku=version["sku"],
                    source_reference=f"template:{key}:{month:%Y-%m}", recurring=True,
                ),
                review_state="pending_review", created_by=created_by, idempotency_key=f"template:{key}:{month:%Y-%m}",
            )
            if res.replayed:
                result.replayed += 1
            else:
                result.created.append(res.expense_id)
    return result
