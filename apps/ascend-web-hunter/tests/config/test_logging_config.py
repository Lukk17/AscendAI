import logging

from _pytest.logging import LogCaptureFixture
from ascend_python_common.log_config import configure_logging
from ascend_python_common.settings import ServiceSettings


def test_debug_line_visible_at_debug_level(caplog: LogCaptureFixture) -> None:
    # given
    configure_logging(
        "ascend-web-hunter",
        ServiceSettings(
            API_PORT=7021, LOG_LEVEL="DEBUG", LOG_FORMAT="json", RATE_LIMIT_DEFAULT="1200/minute"
        ),
    )
    logging.getLogger().addHandler(caplog.handler)
    probe = logging.getLogger("ascend-web-hunter.debug-probe")
    # when
    with caplog.at_level(logging.DEBUG, logger="ascend-web-hunter.debug-probe"):
        probe.debug("debug-marker-4-3")
    # then
    assert any(record.message == "debug-marker-4-3" for record in caplog.records)


def test_no_info_or_access_line_at_warning_level(caplog: LogCaptureFixture) -> None:
    # given
    configure_logging(
        "ascend-web-hunter",
        ServiceSettings(
            API_PORT=7021, LOG_LEVEL="WARNING", LOG_FORMAT="json", RATE_LIMIT_DEFAULT="1200/minute"
        ),
    )
    logging.getLogger().addHandler(caplog.handler)
    probe = logging.getLogger("ascend-web-hunter.quiet-probe")
    access = logging.getLogger("uvicorn.access")
    # when
    probe.debug("suppressed-debug-4-3")
    probe.info("suppressed-info-4-3")
    access.info("suppressed-access-4-3")
    # then
    assert [record for record in caplog.records if record.name == "ascend-web-hunter.quiet-probe"] == []
    assert [record for record in caplog.records if record.name == "uvicorn.access"] == []


def test_uvicorn_loggers_route_through_root() -> None:
    # given
    configure_logging(
        "ascend-web-hunter",
        ServiceSettings(
            API_PORT=7021, LOG_LEVEL="WARNING", LOG_FORMAT="json", RATE_LIMIT_DEFAULT="1200/minute"
        ),
    )
    # when
    access = logging.getLogger("uvicorn.access")
    error = logging.getLogger("uvicorn.error")
    # then
    assert access.handlers == []
    assert access.propagate is True
    assert error.propagate is True
