from unittest.mock import patch

import httpx
from ascend_python_common.errors.registry import resolve_extensions

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


def test_human_intervention_extensions_carry_flow_fields() -> None:
    # given
    window = {"slot": 2, "x": 96, "y": 96, "width": 1280, "height": 800}
    exc = HumanInterventionRequiredException(
        vnc_url="http://vnc/x",
        intervention_type="captcha",
        flow_id="9f2c41ab77de",
        joined=True,
        window=window,
    )

    # when
    entry = error_registry.lookup(exc)
    assert entry is not None
    assert entry.extensions is not None
    extensions = resolve_extensions(entry, exc)

    # then
    assert extensions == {
        "intervention_type": "captcha",
        "vnc_url": "http://vnc/x",
        "flow_id": "9f2c41ab77de",
        "joined": True,
        "window": window,
    }


def test_human_intervention_extensions_keep_old_members_for_plain_raise() -> None:
    # given
    exc = HumanInterventionRequiredException(vnc_url="http://vnc/x", intervention_type="captcha")

    # when
    entry = error_registry.lookup(exc)
    assert entry is not None
    assert entry.extensions is not None
    extensions = resolve_extensions(entry, exc)

    # then
    assert extensions == {
        "intervention_type": "captcha",
        "vnc_url": "http://vnc/x",
        "flow_id": None,
        "joined": False,
        "window": None,
    }


def test_novnc_busy_extensions_carry_cap_fields() -> None:
    # given
    flows = [
        {
            "flow_id": "9f2c41ab77de",
            "url": "https://nowsecure.nl",
            "domain": "nowsecure.nl",
            "profile": "default",
            "intervention_type": "captcha",
            "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
            "age_seconds": 207.3,
            "expires_in_seconds": 412.7,
            "vnc_url": "http://vnc/x",
        }
    ]
    exc = NoVNCFlowBusyException(
        "https://nowsecure.nl",
        "default",
        active_flows=1,
        max_concurrent_flows=4,
        flows=flows,
    )

    # when
    entry = error_registry.lookup(exc)
    assert entry is not None
    assert entry.extensions is not None
    extensions = resolve_extensions(entry, exc)

    # then
    assert extensions == {
        "holder_url": "https://nowsecure.nl",
        "holder_profile": "default",
        "active_flows": 1,
        "max_concurrent_flows": 4,
        "flows": flows,
    }


def test_novnc_busy_extensions_keep_old_members_for_plain_raise() -> None:
    # given
    exc = NoVNCFlowBusyException("http://in-flight.example", "default")

    # when
    entry = error_registry.lookup(exc)
    assert entry is not None
    assert entry.extensions is not None
    extensions = resolve_extensions(entry, exc)

    # then
    assert extensions == {
        "holder_url": "http://in-flight.example",
        "holder_profile": "default",
        "active_flows": 0,
        "max_concurrent_flows": 0,
        "flows": [],
    }


def test_internal_code_is_the_registry_default() -> None:
    # given
    registry = build_error_registry()
    # when
    internal = registry.internal_code
    # then
    assert internal.code == "internal"
    assert internal.status == 500


def test_novnc_busy_retry_after_follows_setting_override() -> None:
    # given
    exc = NoVNCFlowBusyException("http://in-flight.example", "default")
    with patch("src.api.exception_handlers.settings.NOVNC_BUSY_RETRY_AFTER_SECONDS", 45):
        # when
        entry = build_error_registry().lookup(exc)

        # then
        assert entry is not None
        assert entry.headers == {"Retry-After": "45"}


def test_challenge_detected_carries_verdict() -> None:
    # given
    from src.api.exceptions import ChallengeDetectedException
    from src.reader.cloudflare.challenge_signals import assess

    wall_html = "<html><body><div id='cf-challenge-running'></div></body></html>"

    # when
    verdict = assess(200, wall_html)
    exc = ChallengeDetectedException(verdict)

    # then
    assert exc.verdict is verdict
    assert exc.intervention_type == verdict.intervention_type == "captcha"
    assert exc.verdict.vendor == "cloudflare"


def test_challenge_detected_message_names_vendor_and_score() -> None:
    # given
    from src.api.exceptions import ChallengeDetectedException
    from src.reader.cloudflare.challenge_signals import assess

    wall_html = "<html><body><div id='cf-challenge-running'></div></body></html>"

    # when
    verdict = assess(200, wall_html)
    exc = ChallengeDetectedException(verdict)

    # then
    assert "cloudflare" in exc.message
    assert str(verdict.score) in exc.message
    assert str(exc) == exc.message


def test_challenge_detected_takes_login_type_from_verdict() -> None:
    # given
    from src.api.exceptions import ChallengeDetectedException
    from src.reader.cloudflare.challenge_signals import as_login_verdict, assess

    wall_html = "<html><body><div id='cf-challenge-running'></div></body></html>"

    # when
    verdict = as_login_verdict(assess(200, wall_html))
    exc = ChallengeDetectedException(verdict)

    # then
    assert exc.intervention_type == "login"
    assert exc.verdict.intervention_type == "login"
