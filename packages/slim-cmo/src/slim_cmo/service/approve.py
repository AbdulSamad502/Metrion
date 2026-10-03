"""`cmo.approve_title` - persist the seller's approval (spec C8, §6.4 step 3, AC11, E8, E10).

No LLM, no unit. Two paths, exactly one per call:

* an OPTION of a COMPLETE title set of this tenant -> approval row (`edited_by_seller = false`);
* the seller's OWN edited text -> re-validated by `validators.check_title` against the CURRENT
  resolved constraint for that marketplace, under the SAME category context the title set was
  resolved with (persisted with the set; there is no caller-supplied hint, so the validation
  context cannot be changed at approval time) (decision 5): the historical constraint of the title set
  is not trusted, and if no current constraint can be resolved the approval is REFUSED (E5). A
  violation is refused with the rule ids and counts (E10); no row is written.

Cross-tenant, unknown or non-title-set ids raise `NotFound` (E8, AC19). CEO can never approve on
the seller's behalf: this takes the authenticated seller's `Actor` and an explicit choice.
Re-approving creates a NEW row; earlier approvals and the packs built on them stay intact.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from slim_cmo.config import FORMAT_CONSTRAINT_MAX_AGE_DAYS
from slim_cmo.constraints import ConstraintUnavailable, resolve_constraint
from slim_cmo.service.errors import InvalidApproval, NotFound
from slim_cmo.service.models import Actor, GenerationStore
from slim_cmo.types import ConstraintRowKind, OutputType
from slim_cmo.validators import check_title


@dataclass(frozen=True, slots=True)
class Approved:
    approval_id: UUID
    generation_id: UUID
    option_id: UUID | None
    approved_text: str
    edited_by_seller: bool


@dataclass(frozen=True, slots=True)
class ApprovalRefused:
    code: str  # CONSTRAINT_BLOCKED | TITLE_INVALID
    detail: str
    violations: tuple[str, ...] = ()  # rule ids and counts only, e.g. 'title: TOO_LONG (62>40)'


class ApprovalService:
    def __init__(
        self,
        store: GenerationStore,
        *,
        clock: Callable[[], datetime],
        accepted_row_kinds: frozenset[ConstraintRowKind] = frozenset({ConstraintRowKind.VERIFIED}),
    ) -> None:
        self._store = store
        self._clock = clock
        self._kinds = accepted_row_kinds

    def approve_title(
        self,
        actor: Actor,
        generation_id: UUID,
        *,
        option_id: UUID | None = None,
        edited_text: str | None = None,
    ) -> Approved | ApprovalRefused:
        if (option_id is None) == (edited_text is None):
            raise InvalidApproval("approve exactly one of option_id or edited_text")
        title_set = self._store.load_title_set(actor.tenant_id, generation_id)
        if title_set is None:
            raise NotFound("title set not found")

        if option_id is not None:
            option = next((o for o in title_set.options if o.id == option_id), None)
            if option is None:
                raise NotFound("option not found in this title set")  # E8
            return self._save(actor, generation_id, option.id, option.title_text, edited=False)

        assert edited_text is not None
        text = edited_text.strip()
        if not text:
            raise InvalidApproval("edited_text is empty")
        values = self._store.load_config(actor.tenant_id, (FORMAT_CONSTRAINT_MAX_AGE_DAYS,), self._clock().date())
        rows = self._store.load_constraints(actor.tenant_id, title_set.marketplace, self._kinds)
        max_age = values.get(FORMAT_CONSTRAINT_MAX_AGE_DAYS)
        resolved = resolve_constraint(
            rows, marketplace=title_set.marketplace, category=title_set.category_hint, output_type=OutputType.TITLE_SET,
            now=self._clock(), max_age_days=max_age if isinstance(max_age, int) else None, accepted_row_kinds=self._kinds,
        )
        if isinstance(resolved, ConstraintUnavailable):
            return ApprovalRefused("CONSTRAINT_BLOCKED", resolved.detail)
        check = check_title(text, resolved.row, field="title")
        if not check.valid:
            return ApprovalRefused(
                "TITLE_INVALID", "the edited title does not meet this marketplace's current rules",
                tuple(str(v) for v in check.violations),
            )
        return self._save(actor, generation_id, None, check.text, edited=True)

    def _save(self, actor: Actor, generation_id: UUID, option_id: UUID | None, text: str, *, edited: bool) -> Approved:
        approval_id = self._store.save_approval(
            actor.tenant_id, generation_id=generation_id, option_id=option_id, approved_text=text,
            edited_by_seller=edited, approved_by=actor.user_id,
        )
        return Approved(approval_id, generation_id, option_id, text, edited)
