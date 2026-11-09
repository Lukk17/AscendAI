import logging
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import FastMCP

from ascend_python_common.app import ServiceDefinition, create_service_app
from ascend_python_common.errors import ErrorRegistry
from ascend_python_common.settings import CsvTuple, RateLimit, ServiceSettings
from ascend_python_common.startup_banner import (
    CONFIGURED,
    CONNECTED,
    FAILED,
    NOT_CONFIGURED,
    BannerCheck,
    BannerLine,
    BannerSection,
    build_banner,
    format_check,
    render_section,
    render_value,
    strip_user_info,
    warning,
)


class _Settings(ServiceSettings):
    API_PORT: int = 9917
    RATE_LIMIT_DEFAULT: RateLimit = "100/minute"
    MCP_ALLOWED_HOST_HEADERS: CsvTuple = ("testserver", "localhost", "127.0.0.1")


def _server() -> FastMCP:
    server = FastMCP("banner-service")

    @server.tool
    def echo(text: str) -> str:
        return text

    return server


def _definition(lifespan: Any = None, banner: Any = None) -> ServiceDefinition:
    return ServiceDefinition(
        name="banner-service",
        distribution="ascend-python-common",
        settings=_Settings(),
        mcp=_server(),
        error_registry=ErrorRegistry(),
        probes={},
        lifespan=lifespan,
        startup_banner=banner,
    )


def _raise_os_error() -> str:
    raise OSError("hostname unavailable")


def test_check_target_prints_connected_status() -> None:
    # given
    target = "http://qdrant:6333/"
    # when
    line = format_check(target, CONNECTED)
    # then
    assert line == "http://qdrant:6333/ [Connected]"


def test_check_target_prints_failed_status() -> None:
    # given
    target = "http://searxng:8080/healthz"
    # when
    line = format_check(target, FAILED)
    # then
    assert line == "http://searxng:8080/healthz [FAILED]"


def test_check_target_prints_warning_with_reason() -> None:
    # given
    target = "http://example-dependency:8080/"
    # when
    line = format_check(target, warning("status=503"))
    # then
    assert line == "http://example-dependency:8080/ [Warning (status=503)]"


def test_section_with_different_label_lengths_aligns_values_in_one_column() -> None:
    # given
    section = BannerSection(
        "External services",
        (
            BannerLine("DB", "alpha-value"),
            BannerLine("LongerLabel", "beta-value"),
        ),
    )
    # when
    lines = render_section(section)
    # then
    assert lines[0] == "    External services:"
    assert lines[1].index("alpha-value") == lines[2].index("beta-value")


def test_secret_value_prints_mask_instead_of_the_value() -> None:
    # given
    section = BannerSection(
        "Keys",
        (BannerLine("API key", "http://user:s3cret@host/db", secret=True),),
    )
    # when
    lines = render_section(section)
    # then
    assert "****" in lines[1]
    assert "s3cret" not in lines[1]


def test_uri_value_with_user_info_prints_without_it() -> None:
    # given
    value = "http://user:s3cret@db-host:5432/app"
    # when
    rendered = render_value(value, secret=False)
    # then
    assert rendered == "http://db-host:5432/app"
    assert "s3cret" not in rendered


def test_user_info_with_an_at_sign_in_the_password_is_stripped_up_to_the_last_one() -> None:
    assert strip_user_info("http://u:p@ss@h/x") == "http://h/x"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://h/x?to=a@b", "http://h/x?to=a@b"),
        ("http://h/x#a@b", "http://h/x#a@b"),
        ("http://h?to=a@b", "http://h?to=a@b"),
        ("redis://:p@ss@redis:6379/0 and http://u:pw@h/y", "redis://redis:6379/0 and http://h/y"),
    ],
)
def test_an_at_sign_after_the_authority_is_kept(value: str, expected: str) -> None:
    assert strip_user_info(value) == expected


_ONE_MEGABYTE = 1_000_000

_SCAN_BUDGET_SECONDS = 1.0


@pytest.mark.parametrize(
    "value",
    [
        "http://h/" + "a" * _ONE_MEGABYTE,
        "http://" + "a" * _ONE_MEGABYTE,
        "a" * _ONE_MEGABYTE,
        "a://" * (_ONE_MEGABYTE // 4),
    ],
    ids=["path", "authority-without-at-sign", "letters", "repeated-schemes"],
)
def test_strip_user_info_reads_a_long_value_in_one_pass(value: str) -> None:
    # given
    started = time.perf_counter()

    # when
    stripped = strip_user_info(value)

    # then
    assert time.perf_counter() - started < _SCAN_BUDGET_SECONDS
    assert stripped == value


def test_user_info_after_a_longest_scheme_is_stripped() -> None:
    # given
    scheme = "a" * 32

    # when
    stripped = strip_user_info(f"{scheme}://user:pw@host/x")

    # then
    assert stripped == f"{scheme}://host/x"


def test_format_check_strips_user_info_from_the_status() -> None:
    # when
    rendered = format_check("redis://host/0", "Warning (cannot reach redis://user:pw@host/0)")

    # then
    assert rendered == "redis://host/0 [Warning (cannot reach redis://host/0)]"


def test_empty_section_renders_title_only() -> None:
    # given
    section = BannerSection("Nothing here", ())
    # when
    lines = render_section(section)
    # then
    assert lines == ["    Nothing here:"]


def test_check_entries_in_section_print_target_with_status() -> None:
    # given
    section = BannerSection(
        "External services",
        (
            BannerCheck("Qdrant", "http://operator:pw@qdrant:6333/", CONNECTED),
            BannerCheck("API key", "environment", NOT_CONFIGURED),
        ),
    )
    # when
    lines = render_section(section)
    # then
    assert lines[0] == "    External services:"
    assert lines[1] == "      Qdrant:   http://qdrant:6333/ [Connected]"
    assert lines[2] == "      API key:  environment [Not configured]"


def test_service_art_and_content_lines_appear_unchanged() -> None:
    # given
    art = "MY-SERVICE-ART\nsecond art line"
    sections = (
        BannerSection(
            "REST endpoints",
            (BannerLine("Insert", "POST http://localhost:7020/api/v1/memory/insert"),),
        ),
        BannerSection(
            "Keys",
            (BannerCheck("API key", "environment", CONFIGURED),),
        ),
    )
    # when
    lines = build_banner(
        service_name="svc",
        api_port=7020,
        log_level="INFO",
        art=art,
        sections=sections,
        host="myhost",
    )
    # then
    assert lines[1:3] == ["MY-SERVICE-ART", "second art line"]
    assert "POST http://localhost:7020/api/v1/memory/insert" in "\n".join(lines)
    assert "environment [Configured]" in "\n".join(lines)


def test_banner_without_host_uses_local_machine_name() -> None:
    # given
    expected = socket.gethostname()
    # when
    lines = build_banner(service_name="svc", api_port=7020, log_level="INFO", art="ART")
    # then
    assert f"http://{expected}:7020" in "\n".join(lines)


def test_banner_uses_localhost_when_hostname_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(socket, "gethostname", _raise_os_error)
    # when
    lines = build_banner(service_name="svc", api_port=7020, log_level="INFO", art="ART")
    # then
    hostname_lines = [line for line in lines if "Hostname" in line]
    assert hostname_lines == ["      Hostname:  http://localhost:7020"]


def test_banner_is_written_as_one_info_record_after_service_start() -> None:
    # given
    order: list[str] = []
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    @asynccontextmanager
    async def _lifespan() -> AsyncIterator[None]:
        order.append("service-start")
        yield
        order.append("service-stop")

    def _banner() -> list[str]:
        order.append("banner-built")
        return build_banner(
            service_name="banner-service",
            api_port=9917,
            log_level="INFO",
            art="BANNER-ART",
            sections=(
                BannerSection(
                    "REST endpoints",
                    (BannerLine("Insert", "POST /insert"),),
                ),
            ),
            host="myhost",
        )

    app = create_service_app(_definition(lifespan=_lifespan(), banner=_banner))
    app_logger = logging.getLogger("ascend_python_common.app")
    handler = _Capture()
    app_logger.addHandler(handler)
    try:
        # when
        with TestClient(app):
            pass
    finally:
        app_logger.removeHandler(handler)
    # then
    banner_records = [record for record in records if record.levelno == logging.INFO]
    assert len(banner_records) == 1
    assert "BANNER-ART" in banner_records[0].getMessage()
    assert "POST /insert" in banner_records[0].getMessage()
    assert order == ["service-start", "banner-built", "service-stop"]
