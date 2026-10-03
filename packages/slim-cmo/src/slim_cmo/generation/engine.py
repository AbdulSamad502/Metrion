"""The bounded retry loop shared by every generator, and failure classification.

`retry_bound` is configuration (`internal_retry_bound`): attempts = 1 + retry_bound; an explicit
0 means exactly one attempt. There is no default - a caller that has no configured value must not
call a generator (the service returns CONFIG_MISSING first). Provider errors, unparseable replies
and validation failures all spend an attempt; none consumes a billing unit (spec §8.3).

The provider is called with NO database connection open (the service guarantees that); this
module cannot open one.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from slim_cmo.generation.outcomes import Failure, FailureCode
from slim_cmo.generation.parse import ParseFailure, Parsed, parse_reply
from slim_cmo.generation.provider import LlmProvider
from slim_cmo.generation.safety import screen_fact_names


@dataclass(frozen=True, slots=True)
class Evaluation:
    """The verdict on one parsed reply. `feedback` and `violation_ids` carry rule ids/counts only."""

    done: bool
    feedback: tuple[str, ...] = ()
    violation_ids: tuple[str, ...] = ()
    ineligible_names: tuple[str, ...] = ()


@dataclass(slots=True)
class AttemptLog:
    attempts: int = 0
    provider_errors: int = 0
    parse_failures: int = 0
    last_parse_too_large: bool = False
    last_declared: tuple[str, ...] = ()
    last_ineligible: tuple[str, ...] = ()
    violations: Counter[str] = field(default_factory=Counter)
    stopped_needs_facts: bool = False


def _check_bound(retry_bound: object) -> int:
    if type(retry_bound) is not int or retry_bound < 0:
        raise ValueError(f"retry_bound must be a non-negative integer, got {retry_bound!r}")
    return retry_bound


def run_attempts(
    *,
    provider: LlmProvider,
    model: str,
    retry_bound: int,
    make_prompt: Callable[[tuple[str, ...]], str],
    content_types: Mapping[str, type],
    evaluate: Callable[[Parsed], Evaluation],
    already_done: Callable[[], bool] = lambda: False,
) -> AttemptLog:
    total = 1 + _check_bound(retry_bound)
    log = AttemptLog()
    feedback: tuple[str, ...] = ()
    for _ in range(total):
        if already_done():
            break
        log.attempts += 1
        try:
            raw = provider.complete(model=model, prompt=make_prompt(feedback))
        except Exception:  # noqa: BLE001 - any provider failure is an attempt, never a crash
            log.provider_errors += 1
            continue
        parsed = parse_reply(raw, content_types)
        if isinstance(parsed, ParseFailure):
            log.parse_failures += 1
            log.last_parse_too_large = parsed.too_large
            feedback = ("the previous reply was not a single valid JSON object in the required shape",)
            continue
        log.last_parse_too_large = False
        log.last_declared = parsed.needs_facts
        if parsed.payload is None:  # the model declared it lacks facts and wrote no content
            log.stopped_needs_facts = True
            break
        verdict = evaluate(parsed)
        log.last_ineligible = verdict.ineligible_names
        log.violations.update(verdict.violation_ids)
        if verdict.done:
            break
        feedback = verdict.feedback
    return log


def _noun(parts: list[str]) -> str:
    return ", ".join(parts)


def classify_failure(log: AttemptLog, *, what: str) -> Failure:
    """Why an artefact could not be delivered. `what` is a plain noun phrase ('the title set')."""
    detail: dict[str, object] = {
        "attempts": log.attempts,
        "provider_errors": log.provider_errors,
        "parse_failures": log.parse_failures,
        "violations": dict(sorted(log.violations.items())),
    }
    names = screen_fact_names([*log.last_declared, *log.last_ineligible])
    if names:
        return Failure(
            FailureCode.NEEDS_FACTS,
            f"needs more confirmed product facts: {_noun(list(names))}",
            missing_facts=names,
            detail=detail,
        )
    non_provider = log.attempts - log.provider_errors
    if log.provider_errors == log.attempts:
        return Failure(FailureCode.PROVIDER_ERROR, f"the writing service was unavailable, so {what} could not be produced", detail=detail)
    if log.last_parse_too_large:
        return Failure(FailureCode.OUTPUT_TOO_LARGE, f"the generated reply for {what} was unusably large", detail=detail)
    if log.parse_failures == non_provider:
        return Failure(FailureCode.UNPARSEABLE_OUTPUT, f"the generated reply for {what} could not be read", detail=detail)
    return Failure(
        FailureCode.VALIDATION_FAILED,
        f"{what} did not pass the automatic checks after {log.attempts} attempt(s)",
        detail=detail,
    )
