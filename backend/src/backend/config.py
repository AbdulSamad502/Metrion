"""Environment configuration. No secret ever has a default — a missing value fails at
startup, not at first use, so a misconfigured deployment can't silently run unauthenticated
or unscoped."""

from __future__ import annotations

import os
from functools import lru_cache


class MissingConfig(RuntimeError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is not set. See .env.example.")


class LlmEndpointNotVerified(MissingConfig):
    """A configured LLM endpoint is not attested as operator-controlled, so seller data must not be sent to it (approval prerequisite R7).
    Subclasses `MissingConfig` so every existing handler answers 503 "not configured" instead of calling the model."""

    def __init__(self, setting: str, url: str) -> None:
        RuntimeError.__init__(
            self,
            f"{setting} points at {url!r}, which is not listed in LLM_OPERATOR_CONTROLLED_HOSTS. An LLM endpoint is treated as EXTERNAL until the "
            "operator attests it (loopback alone is not evidence of control), and no seller data is sent to an external endpoint: the data-disclosure "
            "policy for third-party model endpoints is not defined yet.",
        )


def _endpoint_key(url: str) -> str | None:
    """`host:port` of an http(s) URL, lower-cased, with the scheme's default port filled in; None if it cannot be parsed."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host or port is None:
        return None
    return f"{host}:{port}"


def operator_controlled_llm_hosts() -> frozenset[str]:
    """`LLM_OPERATOR_CONTROLLED_HOSTS`: comma-separated EXACT `host:port` entries the operator attests they control. No default, and not cached
    (a change takes effect at once). An entry without a port never matches."""
    raw = os.environ.get("LLM_OPERATOR_CONTROLLED_HOSTS") or ""
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def llm_endpoint_trust(url: str) -> str:
    """`INTERNAL` only when the endpoint's exact host:port is attested by the operator; everything else (including loopback, private ranges,
    unparsable URLs) is `EXTERNAL` (Q-R9 / F5: loopback alone is insufficient evidence)."""
    key = _endpoint_key(url)
    return "INTERNAL" if key is not None and key in operator_controlled_llm_hosts() else "EXTERNAL"


def verified_llm_endpoint(url: str, *, setting: str) -> str:
    """The URL itself when it is attested operator-controlled; otherwise raises `LlmEndpointNotVerified` (fail closed, nothing is sent)."""
    if llm_endpoint_trust(url) != "INTERNAL":
        raise LlmEndpointNotVerified(setting, url)
    return url


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingConfig(name)
    return value


@lru_cache
def clerk_secret_key() -> str:
    return _required("CLERK_SECRET_KEY")


@lru_cache
def clerk_webhook_secret() -> str:
    return _required("CLERK_WEBHOOK_SECRET")


@lru_cache
def clerk_jwt_key() -> str:
    """The instance's PEM public key (Dashboard -> API Keys -> JWKS, or `clerk api /jwks`)
    for networkless JWT verification. Without this, `authenticate_request()` performs a
    live JWKS network fetch on every call with no bounded timeout — observed to hang
    indefinitely in this environment. `\\n`-escaped in .env; unescaped here."""
    return _required("CLERK_JWT_KEY").replace("\\n", "\n")


# Leeway (ms) allowed between this machine's clock and Clerk's token timestamps. The SDK's own
# default (5s) is right for production, where hosts run NTP. A developer workstation's clock can
# drift further between syncs (Windows polls ~every 17 min and may be several seconds off), which
# makes Clerk reject a perfectly valid token as "not active yet" / "expired".
_CLOCK_SKEW_PRODUCTION_MS = 5_000
_CLOCK_SKEW_DEV_INSTANCE_MS = 30_000
_CLOCK_SKEW_MAX_MS = 120_000


@lru_cache
def clerk_clock_skew_ms() -> int:
    """The `clock_skew_in_ms` passed to Clerk's token verification.

    `CLERK_CLOCK_SKEW_MS` overrides everything (bounded to 0..120000 so it can never be turned into
    "accept stale tokens"). Unset: a Clerk DEVELOPMENT instance (`sk_test_…`) gets 30s, a production
    instance (`sk_live_…`) keeps the SDK's strict 5s — production verification is never relaxed
    implicitly. Signature, key, expiry and audience checks are unchanged either way."""
    raw = os.environ.get("CLERK_CLOCK_SKEW_MS")
    if raw is not None and raw.strip() != "":
        try:
            value = int(raw)
        except ValueError:
            raise ValueError(f"CLERK_CLOCK_SKEW_MS must be an integer number of milliseconds, got {raw!r}") from None
        if not 0 <= value <= _CLOCK_SKEW_MAX_MS:
            raise ValueError(f"CLERK_CLOCK_SKEW_MS must be between 0 and {_CLOCK_SKEW_MAX_MS}, got {value}")
        return value
    return _CLOCK_SKEW_DEV_INSTANCE_MS if clerk_secret_key().startswith("sk_test_") else _CLOCK_SKEW_PRODUCTION_MS


def deployment_like() -> bool:
    """True when this process is configured as a real deployment: `METRION_ENV` is `production`, `prod` or `staging`, or the Clerk secret key is a LIVE key (`sk_live_`).
    Local development and tests are neither, and keep their defaults."""
    if (os.environ.get("METRION_ENV") or "").strip().lower() in {"production", "prod", "staging"}:
        return True
    return (os.environ.get("CLERK_SECRET_KEY") or "").startswith("sk_live_")


class InvalidConfig(ValueError):
    """A configuration value is present but unusable. The message names the setting and the rule, never the value of a secret."""


DEFAULT_FRONTEND_ORIGIN = "http://localhost:3000"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})


def validate_origin(value: str, *, setting: str = "FRONTEND_ORIGIN") -> str:
    """One browser origin: scheme + host (+ port), nothing else. No wildcard, no path, no query, no trailing slash, no credentials. Returns it normalised (lower case)."""
    from urllib.parse import urlsplit

    raw = value.strip()
    if not raw or "*" in raw:
        raise InvalidConfig(f"{setting} must be one explicit origin such as https://app.example.com (no wildcard)")
    try:
        parts = urlsplit(raw)
        port = parts.port  # raises ValueError for a non-numeric / out-of-range port
    except ValueError:
        raise InvalidConfig(f"{setting} is not a valid origin") from None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise InvalidConfig(f"{setting} must start with http:// or https:// and name a host")
    if parts.username or parts.password or parts.path not in {"", None} or parts.query or parts.fragment:
        raise InvalidConfig(f"{setting} must be an origin only: no credentials, path, query or trailing slash")
    host = parts.hostname.lower()
    host = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


@lru_cache
def frontend_origin() -> str:
    """The one browser origin allowed by CORS. Development and tests default to http://localhost:3000. A deployment-like process (`deployment_like()`) must set
    `FRONTEND_ORIGIN` explicitly, to an https origin (http only for a loopback host): it fails at start-up otherwise, instead of silently serving the development default."""
    raw = (os.environ.get("FRONTEND_ORIGIN") or "").strip()
    if not raw:
        if deployment_like():
            raise MissingConfig("FRONTEND_ORIGIN")
        return DEFAULT_FRONTEND_ORIGIN
    origin = validate_origin(raw)
    if deployment_like() and origin.startswith("http://") and origin.split("://", 1)[1].split(":")[0] not in _LOCAL_HOSTS:
        raise InvalidConfig("FRONTEND_ORIGIN must be https in a deployment")
    return origin


OPS_TOKEN_MIN_CHARS = 24


def ops_token() -> str | None:
    """`OPS_TOKEN`: the shared secret that unlocks the operations endpoints (`/api/v1/ops/*`: liveness, readiness, recovery diagnostics). Unset = those endpoints are OFF (they
    answer 401 like any unauthenticated request). Set but shorter than 24 characters is a start-up error, never a weak secret in use. The value is never logged or returned."""
    raw = (os.environ.get("OPS_TOKEN") or "").strip()
    if not raw:
        return None
    if len(raw) < OPS_TOKEN_MIN_CHARS:
        raise InvalidConfig(f"OPS_TOKEN must be at least {OPS_TOKEN_MIN_CHARS} characters")
    return raw


API_MAX_BODY_DEFAULT_BYTES = 1024 * 1024


def api_max_body_bytes() -> int | None:
    """`API_MAX_BODY_BYTES`: the largest request body any NON-upload route accepts (default 1 MiB, far above every JSON body the API defines; the upload routes keep their own
    limits). Larger bodies are refused with 413 before the body is parsed. `0` turns the default limit off (a reverse proxy then has to enforce one). Invalid values are an error at start-up."""
    raw = (os.environ.get("API_MAX_BODY_BYTES") or "").strip()
    if not raw:
        return API_MAX_BODY_DEFAULT_BYTES
    value = int(raw)
    if value < 0:
        raise ValueError("API_MAX_BODY_BYTES must be 0 (off) or a positive number of bytes")
    return value or None


RECOVERY_SWEEP_DEFAULT_SECONDS = 300


def recovery_sweep_interval_seconds() -> int | None:
    """`RECOVERY_SWEEP_INTERVAL_SECONDS`: how often a running backend looks for runs whose owner died (default 300; `0` turns the periodic pass off, start-up recovery stays).
    This is a polling interval, not a deadline: it decides how soon a dead worker's rows are noticed, never whether a live run is touched (that is decided by ownership). An
    invalid value is an error at the first use, not a silent default."""
    raw = (os.environ.get("RECOVERY_SWEEP_INTERVAL_SECONDS") or "").strip()
    if not raw:
        return RECOVERY_SWEEP_DEFAULT_SECONDS
    value = int(raw)
    if value < 0:
        raise ValueError("RECOVERY_SWEEP_INTERVAL_SECONDS must be 0 (off) or a positive number of seconds")
    return value or None


def ci_default_watchlist_limit() -> int | None:
    """`CI_DEFAULT_WATCHLIST_LIMIT`: the most competitors a tenant may track when the tenant has no limit of its own. NO default: unset means no limit. Not a subscription-plan
    value; plans are not decided, so this is only the hook a future plan resolver sets. Not cached."""
    return _optional_positive_int("CI_DEFAULT_WATCHLIST_LIMIT") or 5  # the owner's limit: five active tracked competitors per seller (a tenant's own limit overrides it)


def ci_scheduler_interval_seconds() -> int | None:
    """`CI_SCHEDULER_INTERVAL_SECONDS`: how often a running backend runs Competitor Intelligence's housekeeping over its own stored data (default 900; `0` turns it off): expire
    unanswered confirmation questions, release alerts held for quiet hours (after re-checking their evidence is still fresh), and add evidence-freshness reminders. It makes no outbound
    request. An invalid value is an error at first use, not a silent default."""
    raw = (os.environ.get("CI_SCHEDULER_INTERVAL_SECONDS") or "").strip()
    if not raw:
        return 900
    value = int(raw)
    if value < 0:
        raise ValueError("CI_SCHEDULER_INTERVAL_SECONDS must be 0 (off) or a positive number of seconds")
    return value or None


def api_docs_enabled() -> bool:
    """`API_DOCS_ENABLED=true` serves the interactive docs and the OpenAPI document (`/docs`, `/redoc`, `/openapi.json`). Default OFF: they are unauthenticated and list every route,
    so a deployment opts in on purpose (a developer machine sets it in its own .env)."""
    return (os.environ.get("API_DOCS_ENABLED") or "").strip().lower() in {"1", "true", "yes"}


@lru_cache
def cfo_report_storage_dir() -> str:
    """Local-disk storage for seller-uploaded marketplace report files (cfo-agent.md §6.16) —
    same functional-only, real-object-storage-is-later posture as `ci_evidence_storage_dir`."""
    return os.environ.get("CFO_REPORT_DIR", "./data/cfo-reports")


@lru_cache
def ci_evidence_storage_dir() -> str:
    """Local-disk storage for seller-uploaded evidence screenshots (Step 4, functional-only
    — not a secret, so a default is fine here unlike everything else in this file). Real
    object storage (S3-equivalent) is a later concern; this just needs to work for now."""
    return os.environ.get("CI_EVIDENCE_DIR", "./data/ci-evidence")


@lru_cache
def cmo_llm_model() -> str:
    """The Ollama model Slim CMO generates listing text with. REQUIRED, no default (P5): a model is
    an operator decision, and a silent fallback would hide a misconfigured deployment. Unset ->
    `MissingConfig`; the CMO routes then answer `503 CMO_NOT_CONFIGURED` before doing any work."""
    return _required("CMO_LLM_MODEL")


@lru_cache
def cmo_ollama_host() -> str:
    """The Ollama endpoint Slim CMO calls. REQUIRED, no default (P5) - deliberately separate from the
    shared `ollama_host()` (which other agents still default to localhost), so CMO never runs
    against an address nobody chose."""
    return verified_llm_endpoint(_required("CMO_OLLAMA_HOST"), setting="CMO_OLLAMA_HOST")


@lru_cache
def ceo_llm_model() -> str:
    """The model the CEO composes answers with. REQUIRED, no default: a model is an operator decision (B2's benchmark was
    deliberately not completed, so nothing here may imply a preferred model). Unset -> `MissingConfig` -> `503 CEO_NOT_CONFIGURED`."""
    return _required("CEO_LLM_MODEL")


@lru_cache
def ceo_classifier_model() -> str:
    """OPTIONAL `CEO_CLASSIFIER_MODEL`: a (typically smaller) model for the single classification pass (spec §6.26 L5). Unset = the same model."""
    return (os.environ.get("CEO_CLASSIFIER_MODEL") or "").strip() or ceo_llm_model()


@lru_cache
def ceo_ollama_host() -> str:
    """The local model server for the CEO. `CEO_OLLAMA_HOST`, else the shared `ollama_host()` (a local address by default; the model
    layer refuses a non-local host)."""
    explicit = (os.environ.get("CEO_OLLAMA_HOST") or "").strip()
    return verified_llm_endpoint(explicit, setting="CEO_OLLAMA_HOST") if explicit else ollama_host()


@lru_cache
def ceo_llm_provider() -> str:
    """OPTIONAL `CEO_LLM_PROVIDER` (default `ollama`, the development backend). Another provider is selected here once registered in `services/ceo_runtime.py`."""
    return (os.environ.get("CEO_LLM_PROVIDER") or "ollama").strip().lower()


@lru_cache
def ceo_llm_think() -> bool | None:
    """OPTIONAL `CEO_LLM_THINK=false|true`; unset = the field is not sent (the model's own default)."""
    raw = os.environ.get("CEO_LLM_THINK")
    if raw is None or not raw.strip():
        return None
    if raw.strip().lower() not in ("true", "false"):
        raise ValueError(f"CEO_LLM_THINK must be true or false, got {raw!r}")
    return raw.strip().lower() == "true"


@lru_cache
def ceo_llm_timeout_seconds() -> int:
    """Per-request timeout, whole seconds, for a CEO model call. REQUIRED, no default (a CPU host measured 15-200 s per call)."""
    return _required_positive_int("CEO_LLM_TIMEOUT_SECONDS")


def _optional_positive_int(name: str) -> int | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return int(raw)


class ConfigInvalid(ValueError):
    """A setting is present but not usable (`CONFIG_INVALID`). The caller fails CLOSED: it declines to start the work with a plain message and guesses nothing."""

    code = "CONFIG_INVALID"


def _positive_int_or_default(name: str, default: int) -> int:
    """Unset or blank -> `default`. Present -> it must be a positive whole number; anything else (0, negative, 1.5, text) raises `ConfigInvalid`."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) <= 0:
        raise ConfigInvalid(f"{name} must be a positive integer, got {raw!r}")
    return int(raw)


def cmo_delegation_max_questions() -> int:
    """`CMO_DELEGATION_MAX_QUESTIONS` (default 8): the most clarification questions the CEO asks for one CMO task, re-asks included (ceo-cmo-delegation.md CD13, 6.3-3).
    Questions 1-8 are asked; a 9th never is. Server-side only. Not cached."""
    return _positive_int_or_default("CMO_DELEGATION_MAX_QUESTIONS", 8)


def cmo_delegation_max_reasks() -> int:
    """`CMO_DELEGATION_MAX_REASKS` (default 2): the most times the SAME field is re-asked after an unusable reply; a field is asked at most 1 + this many times. Not cached."""
    return _positive_int_or_default("CMO_DELEGATION_MAX_REASKS", 2)


def cmo_delegation_idle_expiry_seconds() -> int:
    """`CMO_DELEGATION_IDLE_EXPIRY_SECONDS` (default 86400 = 24 h): a pending CMO task expires when `now - last_activity >= this` (server clock). Not cached."""
    return _positive_int_or_default("CMO_DELEGATION_IDLE_EXPIRY_SECONDS", 86400)


def ceo_leg_timeout_seconds() -> int | None:
    """`CEO_LEG_TIMEOUT_SECONDS`: the per-turn deadline for specialist legs (spec §6.12 rule 5, §6.26 L9). NO default: unset -> None -> any
    investigation with legs refuses with CONFIG_MISSING. Not cached, so a test or operator change takes effect."""
    return _optional_positive_int("CEO_LEG_TIMEOUT_SECONDS")


def ceo_pi_research_timeout_seconds() -> int | None:
    """`CEO_PI_RESEARCH_TIMEOUT_SECONDS`: how long an APPROVED product-research plan waits for the research run before answering "still running" (the run itself keeps going).
    A real run (30 candidates, local-model extraction and commentary) took about 10 minutes (live run 2026-10-14), far over a normal leg deadline, so this is separate from
    `CEO_LEG_TIMEOUT_SECONDS`. NO default: unset -> the ordinary leg deadline applies, which will cut a real research run off. Not cached."""
    return _optional_positive_int("CEO_PI_RESEARCH_TIMEOUT_SECONDS")


def ceo_leg_abandon_seconds() -> int | None:
    """`CEO_LEG_ABANDON_SECONDS`: the HARD leg deadline. A leg that is still running this long after it started, although its turn already answered without it (the soft
    deadline `CEO_LEG_TIMEOUT_SECONDS` passed), is settled as timed out (`ceo/deadlines.py`). NO default: unset -> None -> a late leg is never settled by age and keeps running
    until it finishes or its process dies. Must be longer than the soft deadline; a smaller value is raised to it. Not cached."""
    return _optional_positive_int("CEO_LEG_ABANDON_SECONDS")


def ceo_state_cache_max_entries() -> int | None:
    """`CEO_STATE_CACHE_MAX_ENTRIES`: how many Business State reads the in-process cache may hold (spec L7). NO default: unset -> None -> caching is OFF.
    Not cached, so a test or operator change takes effect."""
    return _optional_positive_int("CEO_STATE_CACHE_MAX_ENTRIES")


def ceo_turn_lock_wait_seconds() -> int | None:
    """`CEO_TURN_LOCK_WAIT_SECONDS`: how long a second turn in the SAME investigation waits for the running one (spec E24). NO default: unset ->
    None -> the second turn is refused at once (409 TURN_IN_PROGRESS) rather than waiting an unchosen time."""
    return _optional_positive_int("CEO_TURN_LOCK_WAIT_SECONDS")


def ceo_playbook_max_legs() -> int | None:
    """`CEO_PLAYBOOK_MAX_LEGS`: the most legs one playbook may fan out to (§6.12 rule 5). NO default; unset -> CONFIG_MISSING for playbooks with legs."""
    return _optional_positive_int("CEO_PLAYBOOK_MAX_LEGS")


def ceo_approval_enabled() -> bool:
    """`CEO_APPROVAL_ENABLED=true|false`: whether a CEO turn that would run an approval-required action (the CEO approval-gate module) PRODUCES A PLAN for the seller to approve
    (ceo-approval-workflow.md section 6.1). DEFAULT OFF, which keeps the existing behaviour exactly: such a turn is refused with APPROVAL_UNAVAILABLE_TEXT and nothing is run,
    asked, saved or sent. The plan/approve/decline API works either way (it acts on stored plans only); this switch controls only whether CHAT creates plans. It is the owner's
    enablement gate (VP-1/VP-2 restatement, ceo-cmo-delegation.md OQ-9): set it only after that is accepted. Not cached, so a test or operator change takes effect."""
    raw = (os.environ.get("CEO_APPROVAL_ENABLED") or "").strip().lower()
    if raw in ("", "false", "0", "no"):
        return False
    if raw in ("true", "1", "yes"):
        return True
    raise ValueError(f"CEO_APPROVAL_ENABLED must be true or false, got {raw!r}")


def ceo_needs_max_per_turn() -> int | None:
    """`CEO_NEEDS_MAX_PER_TURN`: the most add-on lookups (spec agent-needs 5.4) the CEO runs for one turn. NO default: unset -> None -> no add-on runs and the answer names the gap;
    the main request still runs. Not cached, so a test or operator change takes effect."""
    return _optional_positive_int("CEO_NEEDS_MAX_PER_TURN")


def ceo_max_candidate_prices() -> int | None:
    """`CEO_MAX_CANDIDATE_PRICES`: the most candidate prices one COMPETITOR_PRICE_IMPACT run may carry (spec 6.33, Q32). NO default: unset -> that playbook refuses
    with CONFIG_MISSING rather than running with an unchosen bound."""
    return _optional_positive_int("CEO_MAX_CANDIDATE_PRICES")


def _required_positive_int(name: str) -> int:
    raw = _required(name).strip()
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return int(raw)


@lru_cache
def cmo_accept_test_fixture_constraints() -> bool:
    """DEVELOPMENT ONLY. `CMO_ACCEPT_TEST_FIXTURE_CONSTRAINTS=true` lets generation use `TEST_FIXTURE` format-constraint rows (placeholder limits,
    never verified marketplace rules) so the workflow can be exercised before the H1 inputs exist. Unset/false (the default) = VERIFIED rows only.
    Every output made under it cites the fixture's `example.invalid/test-fixture` source."""
    return (os.environ.get("CMO_ACCEPT_TEST_FIXTURE_CONSTRAINTS") or "").strip().lower() == "true"


@lru_cache
def cmo_llm_provider() -> str:
    """OPTIONAL `CMO_LLM_PROVIDER`: which registered `LlmProvider` backs the CMO. Unset = `ollama` (the development backend);
    a hosted model is selected here at deployment once its provider is registered in `services/cmo_runtime.py`."""
    return (os.environ.get("CMO_LLM_PROVIDER") or "ollama").strip().lower()


@lru_cache
def cmo_llm_think() -> bool | None:
    """OPTIONAL `CMO_LLM_THINK=false|true`. Unset => the field is not sent (the model's own default). `false` is needed for
    reasoning models such as qwen3, whose thinking pass otherwise takes ~70 s per call and exhausts the timeout."""
    raw = os.environ.get("CMO_LLM_THINK")
    if raw is None or not raw.strip():
        return None
    if raw.strip().lower() not in ("true", "false"):
        raise ValueError(f"CMO_LLM_THINK must be true or false, got {raw!r}")
    return raw.strip().lower() == "true"


@lru_cache
def cmo_llm_timeout_seconds() -> int:
    """Per-request timeout, whole seconds, for the CMO model call. REQUIRED, no default (P5)."""
    return _required_positive_int("CMO_LLM_TIMEOUT_SECONDS")


def pi_quota_reservation_ttl_seconds() -> int:
    """How long an in-flight PI quota reservation counts against a cap before it is treated as abandoned (approval prerequisite R6). REQUIRED when a
    cap is configured, NO default, and it must be at least the action's structural worst-case duration (`product_intelligence.timing`), otherwise a
    still-running run could lose its reservation and the cap could be overshot; `services/pi_usage` refuses (503) when it is missing or too short."""
    return _required_positive_int("PI_QUOTA_RESERVATION_TTL_SECONDS")


@lru_cache
def cmo_quota_reservation_ttl_seconds() -> int:
    """How long an in-flight CMO quota reservation counts against a cap before it is treated as
    abandoned (spec §8.4 amendment, P5). REQUIRED when a cap is configured, no code default: if it
    is missing a capped request answers `503 CMO_NOT_CONFIGURED` instead of guessing."""
    return _required_positive_int("CMO_QUOTA_RESERVATION_TTL_SECONDS")


@lru_cache
def cmo_image_storage_dir() -> str:
    """Local-disk storage for seller product images (spec §5 `seller_image_asset`). REQUIRED, no default (P6): seller
    photos are tenant data and must never land in a directory nobody chose. Unset -> `MissingConfig`; the CMO image
    routes then answer `503 CMO_NOT_CONFIGURED` before reading the upload."""
    return _required("CMO_IMAGE_DIR")


@lru_cache
def cmo_image_max_pixels() -> int | None:
    """Largest decoded picture (width x height) the upload route accepts - the decompression-bomb limit. **No default**
    (P6): `None` when `CMO_IMAGE_MAX_PIXELS` is unset, and the image routes then refuse (`503`)."""
    return _optional_positive_int_env("CMO_IMAGE_MAX_PIXELS")


@lru_cache
def cmo_vision_model() -> str:
    """The Ollama VISION model used for photo analysis. REQUIRED, no default (P6). With the provider name it is part of
    the trust identity an evaluation is recorded against."""
    return _required("CMO_VISION_MODEL")


@lru_cache
def cmo_vision_ollama_host() -> str:
    """The local Ollama endpoint for photo analysis. REQUIRED, no default (P6; local only - no hosted vision provider)."""
    return verified_llm_endpoint(_required("CMO_VISION_OLLAMA_HOST"), setting="CMO_VISION_OLLAMA_HOST")


def cmo_vision_endpoint_verified() -> str:
    """The vision endpoint, checked NOW and never cached: it must be listed in `LLM_OPERATOR_CONTROLLED_HOSTS` or this raises `LlmEndpointNotVerified` (`MissingConfig` if unset).
    Used by the plan builder, the approval re-check and the image hand-off, so a seller's photo is never read, let alone sent, towards an endpoint that stopped being attested."""
    return verified_llm_endpoint(_required("CMO_VISION_OLLAMA_HOST"), setting="CMO_VISION_OLLAMA_HOST")


def cmo_vision_model_label() -> str:
    """The configured vision model name, read now (not cached), for the plan card's endpoint label."""
    return _required("CMO_VISION_MODEL")


@lru_cache
def cmo_vision_timeout_seconds() -> int:
    """Per-request timeout, whole seconds, for the vision model. REQUIRED, no default (P6): a CPU host measured 13-160 s
    per call, so this is an operator decision."""
    return _required_positive_int("CMO_VISION_TIMEOUT_SECONDS")


@lru_cache
def cmo_vision_rate_max() -> int:
    """Per-tenant cap on analyses (model calls) per rate window. REQUIRED, no default (P6): analysis is 0 units, so this
    is the only guard on an expensive endpoint."""
    return _required_positive_int("CMO_VISION_ANALYSES_PER_WINDOW")


@lru_cache
def cmo_vision_rate_window_seconds() -> int:
    """Length of the per-tenant analysis rate window, whole seconds. REQUIRED, no default (P6)."""
    return _required_positive_int("CMO_VISION_RATE_WINDOW_SECONDS")


def _optional_positive_int_env(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}")
    return value


@lru_cache
def cmo_image_max_bytes() -> int | None:
    """Largest product image the CMO upload route will accept. **No default** (spec H4/Q7): an
    upload limit is a decision (memory, vision latency, storage), not a convention, so until
    `CMO_IMAGE_MAX_BYTES` is set this returns `None` and the upload route refuses rather than
    guessing."""
    return _optional_positive_int_env("CMO_IMAGE_MAX_BYTES")


@lru_cache
def cmo_image_allowed_types() -> frozenset[str]:
    """MIME types accepted for product images, from `CMO_IMAGE_ALLOWED_TYPES` (comma-separated,
    e.g. `image/jpeg,image/png`). **No default** (spec H4): empty means "not configured", and
    the upload route refuses."""
    raw = os.environ.get("CMO_IMAGE_ALLOWED_TYPES", "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer number of bytes, got {raw!r}")
    return value


@lru_cache
def cfo_max_upload_bytes() -> int:
    """Largest marketplace-report CSV `POST /cfo/ingest` accepts. Ingestion holds the whole
    file in memory at ~31x its size (measured, 4-column Meesho orders CSV: 15 MB -> ~470 MB
    peak), so the default 20 MB bounds one concurrent ingestion at roughly 0.6 GB — a memory-
    budget judgment, not a spec requirement; `CFO_MAX_UPLOAD_BYTES` raises or lowers it."""
    return _positive_int_env("CFO_MAX_UPLOAD_BYTES", 20 * 1024 * 1024)


@lru_cache
def ci_max_evidence_bytes() -> int:
    """Largest screenshot `POST /ci/evidence` accepts. A screenshot is read whole, base64'd
    (+33%) and sent to the local vision model; the default 10 MB is far above a real listing
    screenshot yet bounds that — a judgment, not a spec requirement; `CI_MAX_EVIDENCE_BYTES`
    overrides it."""
    return _positive_int_env("CI_MAX_EVIDENCE_BYTES", 10 * 1024 * 1024)


@lru_cache
def ollama_host() -> str:
    """C15: a local, operator-controlled model server, never a hosted provider. The default is a loopback address, but loopback ALONE is not
    evidence of operator control (R7): the endpoint must also be listed in `LLM_OPERATOR_CONTROLLED_HOSTS`, else every model call refuses
    (`LlmEndpointNotVerified`). `OLLAMA_HOST` overrides the default."""
    return verified_llm_endpoint(os.environ.get("OLLAMA_HOST", "http://localhost:11434"), setting="OLLAMA_HOST")


@lru_cache
def ollama_vision_timeout_seconds() -> float:
    """Per-request timeout for the local vision model. Default 60 s (unchanged); on a CPU-only
    host a real extraction was measured at 13-160 s and the first call after the model unloads
    at ~140 s, so such a host needs `OLLAMA_VISION_TIMEOUT_SECONDS` raised or a timed-out call
    silently degrades to manual entry."""
    raw = os.environ.get("OLLAMA_VISION_TIMEOUT_SECONDS")
    if raw is None or not raw.strip():
        return 60.0
    value = float(raw)
    if value <= 0:
        raise ValueError(f"OLLAMA_VISION_TIMEOUT_SECONDS must be positive, got {raw!r}")
    return value


@lru_cache
def ollama_keep_alive() -> str | None:
    """Optional Ollama `keep_alive` (e.g. `30m`) sent with vision requests so the model stays
    loaded between extractions. Unset (the default) leaves Ollama's own default in force."""
    raw = os.environ.get("OLLAMA_KEEP_ALIVE")
    return raw.strip() if raw and raw.strip() else None


@lru_cache
def ci_vision_model() -> str:
    """The Ollama model used for listing-screenshot field extraction (`evidence/
    vision_extractor.py`). No model choice is locked by the spec (§1a item 4 / Q7 remains
    open) — this is a configurable default, not a spec decision, so an operator can swap
    models without a code change."""
    return os.environ.get("CI_VISION_MODEL", "llava")


@lru_cache
def ci_review_vision_model() -> str:
    """The Ollama model used for reviews-tab screenshot classification (`review_insight/
    ollama_extractor.py`). Defaults to the same model as listing extraction — both are
    vision-classification tasks; an operator may point them at different models via env."""
    return os.environ.get("CI_REVIEW_VISION_MODEL", ci_vision_model())


@lru_cache
def tavily_api_key() -> str:
    """`product_intelligence.sources.tavily_client.HttpTavilyClient` — not `_required()`: PI's
    unit/integration tests run entirely against fakes (Phase 1), so an empty key here must not
    block app startup; only a real `pi.discover`/`pi.supplier_lookup` call against this key
    fails, honestly, at that call site."""
    return os.environ.get("TAVILY_API_KEY", "")


def ci_search_provider() -> str:
    """Which `SearchProvider` CI discovery composes (competitor-intelligence-agent.md C34): `tavily` (the owner-approved default) or `mock` (fixtures only, for tests and
    local work). Deliberately NOT cached, so a test can switch it per case. An unrecognised value is a configuration error, never a silent fallback to the mock: a
    mock presented as a real provider would show the seller "no competitors found" for a search that never ran."""
    value = os.environ.get("CI_SEARCH_PROVIDER", "tavily").strip().lower()
    if value not in ("tavily", "mock"):
        raise ConfigInvalid(f"CI_SEARCH_PROVIDER must be 'tavily' or 'mock', got {value!r}")
    return value


def ci_tavily_daily_query_cap() -> int:
    """`CI_TAVILY_DAILY_QUERY_CAP`: the most Tavily queries one tenant's CI discovery may send in any rolling 24 hours (§6.28.1 cost cap). Tavily credits are shared
    with PI, so this is a per-tenant guard, not a budget. Provisional default; the real per-tenant ceiling is a commercial decision (V16)."""
    return _positive_int_or_default("CI_TAVILY_DAILY_QUERY_CAP", 100)


@lru_cache
def youtube_api_key() -> str:
    """`product_intelligence.sources.youtube_client.HttpYoutubeClient` — same "optional at
    startup, real calls fail honestly" posture as `tavily_api_key()`."""
    return os.environ.get("YOUTUBE_API_KEY", "")


@lru_cache
def google_places_api_key() -> str:
    """`product_intelligence.supplier.google_places_client.HttpPlacesClient` — same posture as
    `tavily_api_key()`."""
    return os.environ.get("GOOGLE_PLACES_API_KEY", "")


@lru_cache
def pi_text_insight_model() -> str:
    """The Ollama model used for PI's review-commentary text classification
    (`review_insight/text_extraction.py`'s `OllamaTextInsightExtractor`) — configurable
    default, not a spec decision, same reasoning as `ci_vision_model()`."""
    return os.environ.get("PI_TEXT_INSIGHT_MODEL", "qwen3:8b")


@lru_cache
def pi_product_extraction_model() -> str:
    """The Ollama model used for PI's discovery-time product-name extraction
    (`discovery/product_extraction.py`'s `OllamaProductExtractionClient`) — a separate
    extraction task from `pi_text_insight_model()`'s review-commentary sentiment
    classification (different prompt, different output contract), so it gets its own
    configurable default rather than silently reusing that one — same `PI_*_MODEL` env-var
    convention, same default model family."""
    return os.environ.get("PI_PRODUCT_EXTRACTION_MODEL", "qwen3:8b")


@lru_cache
def pi_embedding_model() -> str:
    """The Ollama model used for PI's derived-attribute embeddings (`embedding/embed.py`'s
    `OllamaEmbeddingClient`). Do not repoint at a different-dimension model without also
    updating `embed.py`'s `MODEL_DIM`/the `product_embedding.embedding` column type."""
    return os.environ.get("PI_EMBEDDING_MODEL", "nomic-embed-text")


@lru_cache
def cfo_narration_model() -> str:
    """The Ollama model used for CFO's Brain-3 narration (`cfo.reasoning.narrate.
    narrate_figures`, via `cfo.reasoning.ollama_provider.OllamaLlmProvider`) — text-only,
    unrelated to `ci_vision_model()`'s vision-classification models above. No model choice is
    locked by cfo-agent.md; this is a configurable default, not a spec decision, so an
    operator can swap models without a code change (mirrors `ci_vision_model()`'s own
    precedent exactly)."""
    return os.environ.get("CFO_NARRATION_MODEL", "qwen3:8b")


def ceo_attachment_max_bytes() -> int | None:
    """`CEO_ATTACHMENT_MAX_BYTES`: the largest single attachment (spec 6.34, Q34). NO default: unset -> attachments are refused with a plain message."""
    return _optional_positive_int("CEO_ATTACHMENT_MAX_BYTES")


def ceo_attachment_max_files() -> int | None:
    """`CEO_ATTACHMENT_MAX_FILES`: how many attachments one message may carry. NO default: unset -> attachments are refused."""
    return _optional_positive_int("CEO_ATTACHMENT_MAX_FILES")


def ceo_attachment_max_pages() -> int | None:
    """`CEO_ATTACHMENT_MAX_PAGES`: how many PDF pages are read. NO default: unset -> attachments are refused."""
    return _optional_positive_int("CEO_ATTACHMENT_MAX_PAGES")


# --- RAG (rag-knowledge.md). Every value is configuration, never a spec constant. ---------------------------------------------------


@lru_cache
def rag_embedding_model() -> str:
    """`RAG_EMBEDDING_MODEL`: the embedding model for the shared RAG index. Provisional (rag-knowledge.md §1, §11 P-1): it must be a model registered in
    `backend.rag.embedding.KNOWN_MODELS`; switching is a re-index, not a config-only change."""
    return (os.environ.get("RAG_EMBEDDING_MODEL") or "nomic-embed-text").strip()


@lru_cache
def rag_ollama_host() -> str:
    """`RAG_OLLAMA_HOST`, else the shared local `ollama_host()`. Self-hosted only (rag-knowledge.md §1): no hosted embedding provider without a new decision."""
    return (os.environ.get("RAG_OLLAMA_HOST") or "").strip() or ollama_host()


@lru_cache
def rag_embed_timeout_seconds() -> float:
    """`RAG_EMBED_TIMEOUT_SECONDS`: hard timeout of one embedding request (rag-knowledge.md §5.9: 3 s on the chat path; ingestion workers pass their own)."""
    raw = os.environ.get("RAG_EMBED_TIMEOUT_SECONDS")
    if raw is None or not raw.strip():
        return 3.0
    value = float(raw)
    if value <= 0:
        raise ValueError(f"RAG_EMBED_TIMEOUT_SECONDS must be positive, got {raw!r}")
    return value


@lru_cache
def rag_max_document_bytes() -> int:
    """`RAG_MAX_DOCUMENT_BYTES`: pilot per-document cap (owner decision Q7: 10 MB)."""
    return _positive_int_env("RAG_MAX_DOCUMENT_BYTES", 10 * 1024 * 1024)


@lru_cache
def rag_max_documents_per_tenant() -> int:
    """`RAG_MAX_DOCUMENTS_PER_TENANT`: pilot per-tenant document cap (owner decision Q7: 50)."""
    return _positive_int_env("RAG_MAX_DOCUMENTS_PER_TENANT", 50)
