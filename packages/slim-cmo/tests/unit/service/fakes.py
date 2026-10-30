"""In-memory `GenerationStore` for service tests. It mimics what the database guarantees that the
service relies on: tenant isolation on every lookup and the partial unique idempotency index over
COMPLETE rows. (The real SQL is exercised by tests/integration/test_p3_postgres_store.py.)"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from slim_cmo.billing import ExistingArtefact
from slim_cmo.constraints import FormatConstraint
from slim_cmo.generation.facts import FactInput
from slim_cmo.service.models import (
    Actor,
    DuplicateArtefact,
    GenerationRecord,
    NewFact,
    StoredAnalysis,
    StoredApproval,
    StoredOption,
    StoredTitleSet,
)
from slim_cmo.types import ConstraintRowKind, GenerationStatus, Marketplace, OutputType, SellerFactType

from ..factories import NOW, constraint

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
USER = uuid.uuid4()
ACTOR = Actor(TENANT_A, USER)

GOOD_CONFIG: dict[str, Any] = {"format_constraint_max_age_days": 30, "internal_retry_bound": 1, "hashtag_set_size": 3}


def all_constraints() -> list[FormatConstraint]:
    return [constraint(mp) for mp in Marketplace]


@dataclass
class StoredFactRow:
    tenant: UUID
    sku: str | None
    fact: NewFact
    provided_at: datetime
    id: UUID


@dataclass
class InMemoryStore:
    constraints: list[FormatConstraint] = field(default_factory=all_constraints)
    config: dict[str, Any] = field(default_factory=lambda: dict(GOOD_CONFIG))
    generations: list[tuple[UUID, UUID, GenerationRecord]] = field(default_factory=list)  # (tenant, id, record)
    option_ids: dict[UUID, list[UUID]] = field(default_factory=dict)
    facts: list[StoredFactRow] = field(default_factory=list)
    approvals: dict[UUID, StoredApproval] = field(default_factory=dict)
    approval_rows: list[dict[str, Any]] = field(default_factory=list)
    analyses: dict[tuple[UUID, UUID], StoredAnalysis] = field(default_factory=dict)
    before_save: Callable[[GenerationRecord], None] | None = None
    _tick: int = 0

    # ---- reads
    def load_config(self, tenant_id: UUID, keys: Sequence[str], as_of: date) -> Mapping[str, Any]:
        return {k: self.config[k] for k in keys if k in self.config}

    def load_constraints(self, tenant_id: UUID, marketplace: Marketplace, kinds: frozenset[ConstraintRowKind]) -> Sequence[FormatConstraint]:
        return [c for c in self.constraints if c.marketplace is marketplace and c.row_kind in kinds]

    def find_artefacts(self, tenant_id: UUID, request_key: str) -> Sequence[ExistingArtefact]:
        return [ExistingArtefact(gid, r.output_type, r.marketplace, r.request_key, r.status)
                for t, gid, r in self.generations if t == tenant_id and r.request_key == request_key]

    def load_facts(self, tenant_id: UUID, sku: str | None) -> Sequence[FactInput]:
        if not sku:
            return []
        rows = sorted((f for f in self.facts if f.tenant == tenant_id and f.sku == sku), key=lambda f: (f.provided_at, str(f.id)))
        return [FactInput(f.fact.fact_type, f.fact.fact_value, f.fact.attribute_name, f.provided_at, str(f.id)) for f in rows]

    def load_approval(self, tenant_id: UUID, approval_id: UUID) -> StoredApproval | None:
        a = self.approvals.get(approval_id)
        return a if a is not None and a.tenant_id == tenant_id else None

    def load_title_set(self, tenant_id: UUID, generation_id: UUID) -> StoredTitleSet | None:
        for t, gid, r in self.generations:
            if t == tenant_id and gid == generation_id and r.output_type is OutputType.TITLE_SET and r.status is GenerationStatus.COMPLETE:
                assert r.marketplace is not None
                opts = tuple(StoredOption(oid, o.rank, o.text) for oid, o in zip(self.option_ids[gid], r.options, strict=True))
                ctx = (r.output_structured or {}).get("category_context") or {}
                return StoredTitleSet(gid, r.marketplace, r.sku, opts, ctx.get("category_hint"), (r.output_structured or {}).get("workflow"))
        return None

    def load_image_analysis(self, tenant_id: UUID, analysis_id: UUID) -> StoredAnalysis | None:
        return self.analyses.get((tenant_id, analysis_id))

    def load_sibling_packs(self, tenant_id: UUID, request_key: str, exclude: Marketplace) -> Mapping[Marketplace, Mapping[str, Any]]:
        return {r.marketplace: r.output_structured or {} for t, _g, r in self.generations
                if t == tenant_id and r.request_key == request_key and r.output_type is OutputType.LISTING_COPY
                and r.status is GenerationStatus.COMPLETE and r.marketplace not in (None, exclude)}  # type: ignore[misc]

    # ---- writes
    def save_facts(self, tenant_id: UUID, user_id: UUID, facts: Sequence[NewFact]) -> Sequence[FactInput]:
        out = []
        for f in facts:
            self._tick += 1
            when = datetime(2026, 10, 3, 12, 0, self._tick, tzinfo=UTC)
            row = StoredFactRow(tenant_id, f.sku, f, when, uuid.uuid4())
            self.facts.append(row)
            out.append(FactInput(f.fact_type, f.fact_value, f.attribute_name, when, str(row.id)))
        return out

    def save_generation(self, tenant_id: UUID, record: GenerationRecord) -> UUID:
        if self.before_save is not None:
            hook, self.before_save = self.before_save, None
            hook(record)
        if record.status is GenerationStatus.COMPLETE:
            for t, _g, r in self.generations:
                if (t, r.request_key, r.output_type, r.marketplace, r.status) == (
                        tenant_id, record.request_key, record.output_type, record.marketplace, GenerationStatus.COMPLETE):
                    raise DuplicateArtefact()
        gid = uuid.uuid4()
        self.generations.append((tenant_id, gid, record))
        self.option_ids[gid] = [uuid.uuid4() for _ in record.options]
        return gid

    def save_approval(self, tenant_id: UUID, *, generation_id: UUID, option_id: UUID | None, approved_text: str,
                      edited_by_seller: bool, approved_by: UUID) -> UUID:
        aid = uuid.uuid4()
        gen = next(r for t, g, r in self.generations if g == generation_id and t == tenant_id)
        assert gen.marketplace is not None
        self.approvals[aid] = StoredApproval(aid, tenant_id, generation_id, gen.marketplace, gen.sku, approved_text, edited_by_seller)
        self.approval_rows.append({"id": aid, "option_id": option_id, "edited": edited_by_seller, "by": approved_by})
        return aid

    # ---- helpers for assertions
    def rows(self, tenant: UUID = TENANT_A) -> list[GenerationRecord]:
        return [r for t, _g, r in self.generations if t == tenant]

    def id_of(self, record: GenerationRecord) -> UUID:
        return next(g for _t, g, r in self.generations if r is record)

    def with_constraints(self, *rows: FormatConstraint) -> InMemoryStore:
        self.constraints = list(rows)
        return self


def clock(now: datetime = NOW) -> Callable[[], datetime]:
    return lambda: now


__all__ = ["replace", "NOW"]
