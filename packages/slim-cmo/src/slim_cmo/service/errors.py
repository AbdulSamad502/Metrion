"""Request-level errors: raised BEFORE a request is accepted, so nothing is persisted for them
(P3 decision 4). Per-artefact failures after acceptance are `Failure` outcomes and DO persist."""

from __future__ import annotations


class NotFound(LookupError):
    """A referenced id does not exist for this tenant (cross-tenant ids look identical, AC19/E8)."""


class GroundingRequired(ValueError):
    """A grounded artefact needs EXACTLY ONE explicit anchor: `approval_id` or `seller_title`
    (C8, AC10, E9, decision 6). Never inferred, never 'the latest approval'."""


class InvalidApproval(ValueError):
    """Approve exactly one of: an option id, or the seller's own edited text."""


class InvalidConfirmation(ValueError):
    """`cmo.confirm_image_hint` needs a sku, a hint that exists on the analysis, and a non-empty
    confirmed value."""

