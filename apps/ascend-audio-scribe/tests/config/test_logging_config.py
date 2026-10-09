import logging
import re

import pytest
from _pytest.logging import LogCaptureFixture
from ascend_python_common.log_config import configure_logging
from ascend_python_common.settings import ServiceSettings

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _service_settings(log_level: str, log_format: str) -> ServiceSettings:
    return ServiceSettings(
        API_PORT=7017,
        LOG_LEVEL=log_level,  # type: ignore[arg-type]
        LOG_FORMAT=log_format,  # type: ignore[arg-type]
        RATE_LIMIT_DEFAULT="600/minute",
    )


def test_debug_line_visible_at_debug_level(caplog: LogCaptureFixture) -> None:
    # given
    configure_logging("ascend-audio-scribe", _service_settings("DEBUG", "json"))
    logging.getLogger().addHandler(caplog.handler)
    probe = logging.getLogger("ascend-audio-scribe.debug-probe")
    # when
    with caplog.at_level(logging.DEBUG, logger="ascend-audio-scribe.debug-probe"):
        probe.debug("debug-marker-3-4")
    # then
    assert any(record.message == "debug-marker-3-4" for record in caplog.records)


def test_no_info_or_access_line_at_warning_level(caplog: LogCaptureFixture) -> None:
    # given
    configure_logging("ascend-audio-scribe", _service_settings("WARNING", "json"))
    logging.getLogger().addHandler(caplog.handler)
    probe = logging.getLogger("ascend-audio-scribe.quiet-probe")
    access = logging.getLogger("uvicorn.access")
    # when
    probe.debug("suppressed-debug-3-4")
    probe.info("suppressed-info-3-4")
    access.info("suppressed-access-3-4")
    # then
    assert [record for record in caplog.records if record.name == "ascend-audio-scribe.quiet-probe"] == []
    assert [record for record in caplog.records if record.name == "uvicorn.access"] == []


def test_color_line_starts_with_service_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # given
    configure_logging("ascend-audio-scribe", _service_settings("INFO", "color"))
    # when
    logging.getLogger("ascend-audio-scribe.color-probe").info("hello-color-3-4")
    captured = capsys.readouterr()
    # then
    [line] = [line for line in ANSI_ESCAPE.sub("", captured.err).splitlines() if "hello-color-3-4" in line]
    assert line.startswith("[ascend-audio-scribe]")
