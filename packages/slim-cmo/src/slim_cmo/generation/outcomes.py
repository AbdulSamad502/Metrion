"""What a generator returns. A generator never raises for a data condition: it returns
`Delivered` (the artefact passed every deterministic check) or `Failed` (0 units, plain reason).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from slim_cmo.types import OutputType
from slim_cmo.validators import AcceptedOption


class FailureCode(str, Enum):
    CONFIG_MISSING = "CONFIG_MISSING"
    CONSTRAINT_BLOCKED = "CONSTRAINT_BLOCKED"          # spec E5 / E16 / E17 / C13
    GROUNDING_INVALID = "GROUNDING_INVALID"            # no / wrong approval or title (C8, AC10, AC23)
    NEEDS_FACTS = "NEEDS_FACTS"                        # spec E18
    VALIDATION_FAILED = "VALIDATION_FAILED"            # retries exhausted; deterministic checks still failing
    PROVIDER_ERROR = "PROVIDER_ERROR"
    UNPARSEABLE_OUTPUT = "UNPARSEABLE_OUTPUT"
    OUTPUT_TOO_LARGE = "OUTPUT_TOO_LARGE"              # parse-safety ceiling (an implementation limit)
    IMAGE_ANALYSIS_NEEDS_CONFIRMATION = "IMAGE_ANALYSIS_NEEDS_CONFIRMATION"  # spec E7


@dataclass(frozen=True, slots=True)
class Failure:
    code: FailureCode
    reason: str                                   # plain, seller-safe; becomes cmo_generation.failure_reason
    missing_facts: tuple[str, ...] = ()           # NEEDS_FACTS only; screened names, never free text
    detail: dict[str, Any] = field(default_factory=dict)  # counts and rule ids only - never seller text

    def structured(self) -> dict[str, Any]:
        """Persisted in `cmo_generation.output_structured` of the FAILED row (the table has no
        failure-code column)."""
        return {"failure_code": self.code.value, "missing_facts": list(self.missing_facts), "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Delivered:
    output_type: OutputType
    structured: dict[str, Any]
    output_text: str | None
    attempts: int
    options: tuple[AcceptedOption, ...] = ()      # TITLE_SET only -> cmo_title_option rows


@dataclass(frozen=True, slots=True)
class Failed:
    output_type: OutputType
    failure: Failure
    attempts: int


Outcome = Delivered | Failed
