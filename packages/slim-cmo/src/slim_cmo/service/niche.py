"""Catalog-seeded niche flow (spec §6.8.3, C15, AC30, AC34; P7d). Zero-unit, no model, no network.

`suggest` reads ONLY distinct `item_title` strings (bounded by `catalog_titles_read_cap`) and the seller's own
CATEGORY / NICHE facts, derives candidate terms deterministically (`trends.screening.suggest_terms`), screens every
candidate with the outbound screen, and stores the survivors as `SUGGESTED`. Nothing is confirmed by the system.

`confirm` records the seller's decisions: confirm, reject, or edit a stored term, plus terms the seller types. A typed
or edited term is the seller's own assertion made in that very call, so it is stored `SELLER_STATED` and `CONFIRMED`
(an edit also marks the original `REJECTED`). Every typed/edited text passes the same outbound screen, and the whole
request is applied atomically against the CONFIRMED-term cap (`max_confirmed_niche_terms`), re-checked inside the
store's locked transaction so concurrent requests cannot exceed it.

`confirmed_terms` is the ONLY accessor the research layer (7e) may use to obtain terms that can leave Metrion: it
returns CONFIRMED terms and nothing else (C15, AC30, E26).

Stored `origin_note` never contains raw titles (only counts). Suggestions that were REJECTED are never re-offered.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Protocol
from uuid import UUID

from slim_cmo import config as cfg
from slim_cmo.service.errors import NotFound
from slim_cmo.service.models import Actor
from slim_cmo.trends.screening import ScreenReason, normalise_term, screen_term, suggest_terms
from slim_cmo.types import NicheTermOrigin, NicheTermStatus, SellerFactType

NO_TITLES_REASON = "No usable item titles were found in your catalog. Type a niche term to research instead."


class NicheConfigMissing(Exception):
    def __init__(self, problem: cfg.ConfigMissing) -> None:
        super().__init__(problem.describe())
        self.problem = problem


class InvalidNicheRequest(ValueError):
    """Empty request, repeated ids, or two decisions about one term."""


class InvalidNicheTerms(ValueError):
    """One or more typed/edited terms failed the outbound screen. Nothing was changed."""

    def __init__(self, rejected: Sequence[tuple[str, tuple[ScreenReason, ...]]]) -> None:
        super().__init__("; ".join(f"{t!r}: {', '.join(r.value for r in why)}" for t, why in rejected))
        self.rejected = tuple(rejected)


class TooManyConfirmedTerms(ValueError):
    def __init__(self, maximum: int, requested: int) -> None:
        super().__init__(f"at most {maximum} niche terms may be confirmed (this change would leave {requested})")
        self.maximum, self.requested = maximum, requested


class DecisionKind(str, Enum):
    CONFIRM = "CONFIRM"
    REJECT = "REJECT"
    EDIT = "EDIT"


@dataclass(frozen=True, slots=True)
class Decision:
    kind: DecisionKind
    term_id: UUID
    new_text: str | None = None


@dataclass(frozen=True, slots=True)
class StoredTerm:
    id: UUID
    term: str
    origin: NicheTermOrigin
    origin_note: str | None
    status: NicheTermStatus


@dataclass(frozen=True, slots=True)
class TermInsert:
    term: str
    origin: NicheTermOrigin
    origin_note: str | None
    status: NicheTermStatus  # SUGGESTED or CONFIRMED


@dataclass(frozen=True, slots=True)
class StatusChange:
    term_id: UUID
    status: NicheTermStatus


@dataclass(frozen=True, slots=True)
class Plan:
    inserts: tuple[TermInsert, ...] = ()
    changes: tuple[StatusChange, ...] = ()


PlanFn = Callable[[Sequence[StoredTerm]], Plan]


class NicheStore(Protocol):
    def load_config(self, tenant_id: UUID, keys: Sequence[str], as_of: date) -> Mapping[str, object]: ...

    def read_catalog_titles(self, tenant_id: UUID, cap: int) -> Sequence[str]:
        """DISTINCT item_title strings only, at most `cap` (most frequently sold first). No other field."""
        ...

    def read_seller_fact_terms(self, tenant_id: UUID, cap: int) -> Sequence[str]: ...

    def list_terms(self, tenant_id: UUID) -> Sequence[StoredTerm]: ...

    def apply_plan(self, tenant_id: UUID, user_id: UUID, plan_fn: PlanFn) -> Sequence[StoredTerm]:
        """ONE transaction holding a per-tenant lock: load the current terms, call `plan_fn`, execute the plan, return
        the resulting terms. An exception from `plan_fn` rolls everything back."""
        ...


@dataclass(frozen=True, slots=True)
class SuggestedTerm:
    id: UUID
    term: str
    origin: NicheTermOrigin
    origin_note: str | None
    document_frequency: int | None  # distinct catalog titles containing it (this call only; None for older/fact terms)
    status: NicheTermStatus = NicheTermStatus.SUGGESTED


@dataclass(frozen=True, slots=True)
class SuggestOutcome:
    status: str  # OK | UNAVAILABLE
    reason: str | None
    suggestions: tuple[SuggestedTerm, ...]  # status SUGGESTED, awaiting the seller
    confirmed: tuple[StoredTerm, ...]
    titles_read: int


@dataclass(frozen=True, slots=True)
class ConfirmOutcome:
    confirmed: tuple[StoredTerm, ...]
    suggestions: tuple[StoredTerm, ...]
    rejected_count: int


class NicheService:
    def __init__(self, store: NicheStore, *, clock: Callable[[], datetime]) -> None:
        self._store, self._clock = store, clock
        self.clock = clock  # public: the route stamps its agent_run with the same clock

    # ---- config ----------------------------------------------------------------------------------
    def _config(self, tenant_id: UUID) -> cfg.NicheConfig:
        keys = (*cfg.NICHE_REQUIRED_KEYS, cfg.NICHE_STOPWORDS_EXTRA, cfg.NICHE_STOPWORDS_EXCLUDE)
        loaded = cfg.load_niche_config(self._store.load_config(tenant_id, keys, self._clock().date()))
        if isinstance(loaded, cfg.ConfigMissing):
            raise NicheConfigMissing(loaded)
        return loaded

    # ---- suggest ---------------------------------------------------------------------------------
    def suggest(self, actor: Actor) -> SuggestOutcome:
        config = self._config(actor.tenant_id)
        titles = list(self._store.read_catalog_titles(actor.tenant_id, config.catalog_titles_read_cap))[: config.catalog_titles_read_cap]
        fact_terms = list(self._store.read_seller_fact_terms(actor.tenant_id, config.catalog_titles_read_cap))

        df: dict[str, int] = {}
        candidates: list[tuple[str, NicheTermOrigin, str]] = []  # (normalised term, origin, note)
        for raw in fact_terms:
            screened = screen_term(raw, max_chars=config.max_term_chars)
            if screened.ok:
                candidates.append((screened.term, NicheTermOrigin.SELLER_FACT, "from a category or niche you stated for a product"))
        distinct_titles = len({normalise_term(t) for t in titles if isinstance(t, str) and normalise_term(t)})
        for s in suggest_terms(
            titles, stopwords=config.niche_stopwords, max_terms=config.max_confirmed_niche_terms, max_term_chars=config.max_term_chars
        ):
            df[s.term] = s.document_frequency
            candidates.append(
                (s.term, NicheTermOrigin.CATALOG_DERIVED,
                 f"derived from {distinct_titles} distinct item titles in your catalog; appears in {s.document_frequency}")
            )

        def plan(existing: Sequence[StoredTerm]) -> Plan:
            known = {normalise_term(t.term) for t in existing}  # any status: a REJECTED term is never re-offered
            inserts: list[TermInsert] = []
            for term, origin, note in candidates:
                if term in known:
                    continue
                known.add(term)
                inserts.append(TermInsert(term, origin, note, NicheTermStatus.SUGGESTED))
            return Plan(inserts=tuple(inserts))

        terms = self._store.apply_plan(actor.tenant_id, actor.user_id, plan)
        suggestions = tuple(
            SuggestedTerm(t.id, t.term, t.origin, t.origin_note, df.get(t.term))
            for t in terms if t.status is NicheTermStatus.SUGGESTED
        )
        confirmed = tuple(t for t in terms if t.status is NicheTermStatus.CONFIRMED)
        if not titles and not fact_terms:
            return SuggestOutcome("UNAVAILABLE", NO_TITLES_REASON, suggestions, confirmed, 0)
        return SuggestOutcome("OK", None, suggestions, confirmed, len(titles))

    # ---- confirm ---------------------------------------------------------------------------------
    def confirm(self, actor: Actor, decisions: Sequence[Decision], new_terms: Sequence[str] = ()) -> ConfirmOutcome:
        config = self._config(actor.tenant_id)
        if not decisions and not new_terms:
            raise InvalidNicheRequest("nothing to confirm, edit, reject or add")
        ids = [d.term_id for d in decisions]
        if len(set(ids)) != len(ids):
            raise InvalidNicheRequest("a term may have only one decision per request")

        screened_edits: dict[UUID, str] = {}
        screened_new: list[str] = []
        failures: list[tuple[str, tuple[ScreenReason, ...]]] = []
        for d in decisions:
            if d.kind is DecisionKind.EDIT:
                if d.new_text is None:
                    raise InvalidNicheRequest("an EDIT needs the new text")
                r = screen_term(d.new_text, max_chars=config.max_term_chars)
                if r.ok:
                    screened_edits[d.term_id] = r.term
                else:
                    failures.append((str(d.new_text), r.reasons))
            elif d.new_text is not None:
                raise InvalidNicheRequest("only an EDIT carries new text")
        for raw in new_terms:
            r = screen_term(raw, max_chars=config.max_term_chars)
            if r.ok:
                screened_new.append(r.term)
            else:
                failures.append((str(raw), r.reasons))
        if failures:
            raise InvalidNicheTerms(failures)
        if len(set(screened_new)) != len(screened_new):
            raise InvalidNicheRequest("the same new term was given twice")

        def plan(existing: Sequence[StoredTerm]) -> Plan:
            by_id = {t.id: t for t in existing}
            status: dict[UUID, NicheTermStatus] = {t.id: t.status for t in existing}
            by_term: dict[str, UUID | None] = {normalise_term(t.term): t.id for t in existing}  # None = a planned insert
            inserts: dict[str, TermInsert] = {}

            def confirm_text(text: str) -> None:
                existing_id = by_term.get(text)
                if existing_id is not None:
                    status[existing_id] = NicheTermStatus.CONFIRMED
                elif text in inserts:
                    return
                else:
                    by_term[text] = None
                    inserts[text] = TermInsert(text, NicheTermOrigin.SELLER_STATED, "typed by the seller", NicheTermStatus.CONFIRMED)

            for d in decisions:
                if d.term_id not in by_id:
                    raise NotFound(str(d.term_id))  # unknown and cross-tenant look identical
                if d.kind is DecisionKind.CONFIRM:
                    status[d.term_id] = NicheTermStatus.CONFIRMED
                elif d.kind is DecisionKind.REJECT:
                    status[d.term_id] = NicheTermStatus.REJECTED
                else:
                    edited = screened_edits[d.term_id]
                    if edited == normalise_term(by_id[d.term_id].term):
                        status[d.term_id] = NicheTermStatus.CONFIRMED  # an edit that changes nothing is a confirmation
                    else:
                        status[d.term_id] = NicheTermStatus.REJECTED  # replaced by the seller's own wording
                        confirm_text(edited)
            for text in screened_new:
                confirm_text(text)

            confirmed_after = sum(1 for s in status.values() if s is NicheTermStatus.CONFIRMED) + len(inserts)
            if confirmed_after > config.max_confirmed_niche_terms:
                raise TooManyConfirmedTerms(config.max_confirmed_niche_terms, confirmed_after)
            changes = tuple(StatusChange(i, s) for i, s in status.items() if s is not by_id[i].status)
            return Plan(inserts=tuple(inserts.values()), changes=changes)

        terms = self._store.apply_plan(actor.tenant_id, actor.user_id, plan)
        return ConfirmOutcome(
            confirmed=tuple(t for t in terms if t.status is NicheTermStatus.CONFIRMED),
            suggestions=tuple(t for t in terms if t.status is NicheTermStatus.SUGGESTED),
            rejected_count=sum(1 for t in terms if t.status is NicheTermStatus.REJECTED),
        )

    # ---- reads -----------------------------------------------------------------------------------
    def list_terms(self, actor: Actor) -> tuple[StoredTerm, ...]:
        return tuple(self._store.list_terms(actor.tenant_id))

    def confirmed_terms(self, actor: Actor) -> tuple[str, ...]:
        """The ONLY terms allowed to leave Metrion for research (C15): CONFIRMED rows, nothing else."""
        return tuple(
            sorted(t.term for t in self._store.list_terms(actor.tenant_id) if t.status is NicheTermStatus.CONFIRMED)
        )


SELLER_FACT_TYPES: tuple[str, ...] = (SellerFactType.CATEGORY.value, SellerFactType.NICHE.value)
