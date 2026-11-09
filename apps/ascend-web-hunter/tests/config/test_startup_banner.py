import logging
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from ascend_python_common.startup_banner import (
    CONFIGURED,
    CONNECTED,
    FAILED,
    NOT_CONFIGURED,
    BannerCheck,
    warning,
)

from src.config.config import Settings, settings
from src.config.startup_banner import (
    BANNER,
    _blocklist_entry,
    _document_route_check_sync,
    _probe_url_sync,
    _redis_check_sync,
    build_service_banner,
    service_banner_sections,
)
from src.crawl import result_store as result_store_module
from src.crawl.result_store import ExpiryRuleStatus, retention_days
from src.main import REST_ROUTERS


class _Resp200:
    status = 200

    def __enter__(self) -> "_Resp200":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _Resp503:
    status = 503

    def __enter__(self) -> "_Resp503":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _stubbed_sections() -> list[Any]:
    with (
        patch.object(urllib.request, "urlopen", return_value=_Resp200()),
        patch("src.config.startup_banner.socket.create_connection") as mock_conn,
    ):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_cm
        # when
        return service_banner_sections(REST_ROUTERS)


def test_banner_art_text_is_present() -> None:
    # given
    art = BANNER
    # when
    with patch("src.config.startup_banner.socket.create_connection", side_effect=OSError("unreachable")):
        lines = build_service_banner(REST_ROUTERS)
    # then
    assert art.splitlines()[0] in "\n".join(lines)


def test_banner_finds_every_content_line() -> None:
    # given
    with (
        patch.object(urllib.request, "urlopen", return_value=_Resp200()),
        patch("src.config.startup_banner.socket.create_connection") as mock_conn,
    ):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_cm
        # when
        text = "\n".join(build_service_banner(REST_ROUTERS))
    # then
    assert "SearXNG" in text
    assert "Redis" in text
    assert "Blocklist" in text
    assert f"GET http://localhost:{settings.API_PORT}/api/v1/web/search" in text
    assert f"POST http://localhost:{settings.API_PORT}/api/v2/web/read" in text
    assert "/openapi.json" in text
    assert "/docs" in text
    assert "/redoc" in text


def test_banner_redis_line_shows_no_user_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "REDIS_URL", "redis://user:supersecret@127.0.0.1:6379/0")
    with (
        patch.object(urllib.request, "urlopen", return_value=_Resp200()),
        patch("src.config.startup_banner.socket.create_connection") as mock_conn,
    ):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_cm
        # when
        text = "\n".join(build_service_banner(REST_ROUTERS))
    # then
    assert "supersecret" not in text
    assert "user@" not in text


def test_probe_url_sync_success() -> None:
    # given
    url = "http://upstream/healthz"
    # when
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        result = _probe_url_sync("SearXNG", url)
    # then
    assert "Connected" in result.status


def test_probe_url_sync_warns_on_non_2xx() -> None:
    # given
    url = "http://upstream/healthz"
    # when
    with patch.object(urllib.request, "urlopen", return_value=_Resp503()):
        result = _probe_url_sync("SearXNG", url)
    # then
    assert "status=503" in result.status


def test_probe_url_sync_http_error() -> None:
    # given
    url = "http://upstream/healthz"
    error = urllib.error.HTTPError(url, 502, "Bad Gateway", Message(), None)

    try:
        # when
        with patch.object(urllib.request, "urlopen", side_effect=error):
            result = _probe_url_sync("SearXNG", url)
    finally:
        error.close()

    # then
    assert "status=502" in result.status


def test_probe_url_sync_other_error() -> None:
    # given
    url = "http://upstream/healthz"
    # when
    with patch.object(urllib.request, "urlopen", side_effect=RuntimeError("dns")):
        result = _probe_url_sync("SearXNG", url)
    # then
    assert result.status == FAILED


def test_probe_url_sync_refuses_disallowed_scheme() -> None:
    # given
    url = "redis://localhost:6379"
    # when
    result = _probe_url_sync("Redis", url)
    # then
    assert result.status == FAILED


def test_redis_check_sync_success() -> None:
    # given
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_cm)
    mock_cm.__exit__ = MagicMock(return_value=False)
    # when
    with patch("src.config.startup_banner.socket.create_connection", return_value=mock_cm):
        result = _redis_check_sync()
    # then
    assert "Connected" in result.status


def test_redis_check_sync_failure() -> None:
    # given
    failing = OSError("unreachable")
    # when
    with patch("src.config.startup_banner.socket.create_connection", side_effect=failing):
        result = _redis_check_sync()
    # then
    assert result.status == FAILED


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()


@pytest.fixture
def health_server() -> Iterator[int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_probe_of_a_url_with_user_info_reaches_the_address_without_it(health_server: int) -> None:
    # given
    url = f"http://user:supersecret@127.0.0.1:{health_server}/health"

    # when
    result = _probe_url_sync("ascend-ocr (image route)", url)

    # then
    assert result.status == CONNECTED
    assert result.target == f"http://127.0.0.1:{health_server}/health"


def test_failed_probe_logs_neither_the_password_nor_the_error_text(caplog: pytest.LogCaptureFixture) -> None:
    # given
    url = "http://user:supersecret@upstream/health"
    failing = RuntimeError("open http://user:supersecret@upstream/health failed")

    # when
    with (
        caplog.at_level(logging.DEBUG, logger="src.config.startup_banner"),
        patch.object(urllib.request, "urlopen", side_effect=failing),
    ):
        result = _probe_url_sync("SearXNG", url)

    # then
    assert result.status == FAILED
    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["Probe failed for http://upstream/health: RuntimeError"]


def test_failed_redis_probe_logs_neither_the_password_nor_the_error_text(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    monkeypatch.setattr(settings, "REDIS_URL", "redis://user:supersecret@127.0.0.1:6379/0")
    failing = OSError("connect redis://user:supersecret@127.0.0.1:6379/0 refused")

    # when
    with (
        caplog.at_level(logging.DEBUG, logger="src.config.startup_banner"),
        patch("src.config.startup_banner.socket.create_connection", side_effect=failing),
    ):
        result = _redis_check_sync()

    # then
    assert result.status == FAILED
    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["TCP probe failed for redis://127.0.0.1:6379/0: OSError"]


def test_blocklist_entry_reports_rule_count_when_loaded() -> None:
    # given
    from src.config.blocklist_loader import blocklist_loader

    # when
    result = _blocklist_entry()
    # then
    assert blocklist_loader.state is not None
    assert "rules)" in result.value


def test_blocklist_entry_reports_not_loaded_when_state_is_none() -> None:
    # given
    from src.config.blocklist_loader import blocklist_loader

    # when
    with patch.object(blocklist_loader, "_state", None):
        result = _blocklist_entry()
    # then
    assert "[not loaded]" in result.value


def test_service_banner_function_is_used_by_definition() -> None:
    # given
    from src.main import definition

    banner = definition.startup_banner
    assert banner is not None
    # when
    with (
        patch.object(urllib.request, "urlopen", return_value=_Resp200()),
        patch("src.config.startup_banner.socket.create_connection") as mock_conn,
    ):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_cm
        lines = banner()
    # then
    assert isinstance(lines, list)
    assert any("ascend-web-hunter" in line for line in lines)


def test_banner_prints_novnc_display_size_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "NOVNC_DISPLAY_SIZE", "1600x900")
    with (
        patch.object(urllib.request, "urlopen", return_value=_Resp200()),
        patch("src.config.startup_banner.socket.create_connection") as mock_conn,
    ):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_cm
        # when
        text = "\n".join(build_service_banner(REST_ROUTERS))
    # then
    assert "NoVNC display" in text
    assert "1600x900" in text


def test_banner_prints_default_novnc_display_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.delenv("NOVNC_DISPLAY_SIZE", raising=False)
    monkeypatch.setattr(settings, "NOVNC_DISPLAY_SIZE", Settings().NOVNC_DISPLAY_SIZE)
    with (
        patch.object(urllib.request, "urlopen", return_value=_Resp200()),
        patch("src.config.startup_banner.socket.create_connection") as mock_conn,
    ):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_cm
        # when
        text = "\n".join(build_service_banner(REST_ROUTERS))
    # then
    assert "NoVNC display" in text
    assert Settings().NOVNC_DISPLAY_SIZE in text


def test_banner_sections_have_expected_titles() -> None:
    # given
    sections = _stubbed_sections()
    # when
    titles = [section.title for section in sections]
    # then
    assert titles == ["External services", "REST endpoints", "API documentation"]


@pytest.mark.parametrize("reachable", [True, False], ids=["connected", "failed"])
def test_banner_redis_line_shows_no_query(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, reachable: bool
) -> None:
    # given
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:6379/0?password=x")
    connection = MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False))
    outcome: dict[str, Any] = (
        {"return_value": connection} if reachable else {"side_effect": OSError("refused")}
    )

    # when
    with (
        caplog.at_level(logging.DEBUG),
        patch("src.config.startup_banner.socket.create_connection", **outcome),
    ):
        check = _redis_check_sync()

    # then
    assert check.target == "redis://127.0.0.1:6379/0"
    assert "password=x" not in caplog.text


def test_banner_redis_check_strips_user_info_on_render() -> None:
    # given
    from ascend_python_common.startup_banner import format_check

    check = BannerCheck(label="Redis", target="redis://user:pw@host:6379/0", status="Connected")
    # when
    rendered = format_check(check.target, check.status)
    # then
    assert "pw" not in rendered
    assert rendered == "redis://host:6379/0 [Connected]"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ExpiryRuleStatus(), "not checked yet"),
        (ExpiryRuleStatus(applied=True), CONFIGURED),
        (
            ExpiryRuleStatus(applied=False, error="AccessDenied"),
            warning("not set, results do not expire: AccessDenied"),
        ),
    ],
    ids=["pending", "applied", "refused"],
)
def test_banner_reports_the_crawl_result_expiry_rule(
    monkeypatch: pytest.MonkeyPatch, status: ExpiryRuleStatus, expected: str
) -> None:
    # given this process's lifecycle rule outcome
    monkeypatch.setattr(result_store_module, "expiry_rule_status", status)

    # when
    sections = _stubbed_sections()

    # then the external services section names the bucket, the prefix, the days and the outcome
    entries = {entry.label: entry for entry in sections[0].entries}
    check = entries["Crawl result expiry"]
    assert isinstance(check, BannerCheck)
    assert check.target == (f"{settings.CRAWL_RESULT_S3_BUCKET}/tenant/ after {retention_days()} days")
    assert check.status == expected


_ACTUATOR_PATHS = frozenset({"/health", "/ready"})


def _rest_section_lines(lines: list[str]) -> list[str]:
    start = lines.index("    REST endpoints:") + 1
    end = lines.index("", start)
    return lines[start:end]


def test_banner_rest_endpoints_are_exactly_the_routes_the_app_serves() -> None:
    # given the operations the app's own OpenAPI document publishes
    from src.main import app, definition

    local_url = f"http://localhost:{settings.API_PORT}"
    published = {
        f"{method.upper()} {local_url}{path}"
        for path, operations in app.openapi()["paths"].items()
        if path not in _ACTUATOR_PATHS
        for method in operations
    }
    banner = definition.startup_banner
    assert banner is not None
    with (
        patch.object(urllib.request, "urlopen", return_value=_Resp200()),
        patch("src.config.startup_banner.socket.create_connection") as mock_conn,
    ):
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_cm)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value = mock_cm
        # when
        rest_lines = _rest_section_lines(banner())
    # then
    listed = {line.split(":", 1)[1].strip() for line in rest_lines}
    assert len(rest_lines) == len(published)
    assert listed == published


_DOCUMENT_ROUTES = [
    ("DOCLING_SERVE_URL", "Docling Serve (PDF route)"),
    ("ASCEND_OCR_URL", "ascend-ocr (image route)"),
    ("AUDIO_SCRIBE_URL", "ascend-audio-scribe (audio route)"),
]


@pytest.mark.parametrize(("setting_name", "label"), _DOCUMENT_ROUTES, ids=["pdf", "image", "audio"])
def test_banner_lists_every_document_route_after_redis(
    monkeypatch: pytest.MonkeyPatch, setting_name: str, label: str
) -> None:
    # given a configured routing target
    monkeypatch.setattr(settings, setting_name, "http://target:9000/")

    # when
    sections = _stubbed_sections()

    # then the external services section carries its health check
    entries = {entry.label: entry for entry in sections[0].entries}
    labels = [entry.label for entry in sections[0].entries]
    check = entries[label]
    assert isinstance(check, BannerCheck)
    assert check.target == "http://target:9000/health"
    assert check.status == CONNECTED
    assert labels.index(label) > labels.index("Redis")


def test_document_route_check_probes_the_health_path_with_the_startup_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "STARTUP_PROBE_TIMEOUT_SECONDS", 1.5)

    # when
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()) as mock_open:
        result = _document_route_check_sync("ascend-ocr (image route)", "http://ascend-ocr:7022")

    # then
    mock_open.assert_called_once_with("http://ascend-ocr:7022/health", timeout=1.5)
    assert result == BannerCheck(
        label="ascend-ocr (image route)", target="http://ascend-ocr:7022/health", status=CONNECTED
    )


def test_document_route_check_reports_an_unreachable_target_as_failed() -> None:
    # given
    unreachable = urllib.error.URLError("Name or service not known")

    # when
    with patch.object(urllib.request, "urlopen", side_effect=unreachable):
        result = _document_route_check_sync("Docling Serve (PDF route)", "http://docling-serve:5001")

    # then
    assert result.status == FAILED


def test_document_route_check_warns_on_a_non_2xx_health_answer() -> None:
    # given
    url = "http://ascend-audio-scribe:7017"

    # when
    with patch.object(urllib.request, "urlopen", return_value=_Resp503()):
        result = _document_route_check_sync("ascend-audio-scribe (audio route)", url)

    # then
    assert result.status == warning("status=503")


@pytest.mark.parametrize("empty_url", ["", "   "], ids=["empty", "blank"])
def test_document_route_check_reports_an_empty_url_as_route_off_without_probing(empty_url: str) -> None:
    # given
    label = "ascend-ocr (image route)"

    # when
    with patch.object(urllib.request, "urlopen") as mock_open:
        result = _document_route_check_sync(label, empty_url)

    # then
    mock_open.assert_not_called()
    assert result == BannerCheck(label=label, target="route off", status=NOT_CONFIGURED)


def test_document_routes_are_not_readiness_probes() -> None:
    # given
    from src.main import definition

    # when
    probe_names = set(definition.probes)

    # then
    assert probe_names == {"redis", "searxng", "searxng_breaker"}
