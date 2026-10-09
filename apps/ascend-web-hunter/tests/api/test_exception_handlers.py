import httpx

from src.api.exception_handlers import (
    BLOCKLIST_REFRESH_INVALID,
    BLOCKLIST_REFRESH_THROTTLED,
    EXTERNAL_SERVICE_UNAVAILABLE,
    HUMAN_INTERVENTION_REQUIRED,
    NOVNC_BUSY,
    build_error_registry,
    error_registry,
)
from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.config.blocklist_loader import BlocklistRefreshThrottledError, BlocklistValidationError


def test_value_error_maps_to_validation() -> None:
    # given
    exc = ValueError("query must not be empty")
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is not None
    assert entry.code.code == "validation"
    assert entry.code.status == 400


def test_httpx_error_maps_to_external_service_unavailable() -> None:
    # given
    exc = httpx.HTTPError("upstream blew up")
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is not None
    assert entry.code == EXTERNAL_SERVICE_UNAVAILABLE
    assert entry.code.status == 503


def test_blocklist_validation_error_maps_to_502() -> None:
    # given
    exc = BlocklistValidationError("no usable rules")
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is not None
    assert entry.code == BLOCKLIST_REFRESH_INVALID
    assert entry.code.status == 502


def test_blocklist_throttled_error_maps_to_429_with_retry_after() -> None:
    # given
    exc = BlocklistRefreshThrottledError(12.0)
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is not None
    assert entry.code == BLOCKLIST_REFRESH_THROTTLED
    assert entry.code.status == 429
    assert callable(entry.headers)


def test_human_intervention_maps_to_428_with_extensions() -> None:
    # given
    exc = HumanInterventionRequiredException(vnc_url="http://vnc:7900", intervention_type="captcha")
    # when
    entry = error_registry.lookup(exc)
    # then
    assert entry is not None
    assert entry.code == HUMAN_INTERVENTION_REQUIRED
    assert entry.code.status == 428
    assert callable(entry.extensions)


def test_novnc_busy_maps_to_409_with_retry_after_and_extensions() -> None:
    # given
    exc = NoVNCFlowBusyException("http://in-flight.example", "default")
    # when
    entry = build_error_registry().lookup(exc)
    # then
    assert entry is not None
    assert entry.code == NOVNC_BUSY
    assert entry.code.status == 409
    assert entry.headers == {"Retry-After": "30"}
    assert callable(entry.extensions)


def test_internal_code_is_the_registry_default() -> None:
    # given
    registry = build_error_registry()
    # when
    internal = registry.internal_code
    # then
    assert internal.code == "internal"
    assert internal.status == 500
