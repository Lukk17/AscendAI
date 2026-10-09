import urllib.error
import urllib.request
from email.message import Message
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from ascend_python_common.startup_banner import FAILED, BannerCheck

from src.config.config import settings
from src.config.startup_banner import (
    BANNER,
    _blocklist_entry,
    _probe_url_sync,
    _redis_check_sync,
    build_service_banner,
    service_banner_sections,
)


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
        return service_banner_sections()


def test_banner_art_text_is_present() -> None:
    # given
    art = BANNER
    # when
    lines = build_service_banner()
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
        text = "\n".join(build_service_banner())
    # then
    assert "SearXNG" in text
    assert "FlareSolverr" in text
    assert "Redis" in text
    assert "Blocklist" in text
    assert "/v1/search" in text
    assert "/v1/read" in text
    assert "/v2/search" in text
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
        text = "\n".join(build_service_banner())
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
    # when
    with patch.object(urllib.request, "urlopen", side_effect=error):
        result = _probe_url_sync("SearXNG", url)
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


def test_banner_sections_have_expected_titles() -> None:
    # given
    sections = _stubbed_sections()
    # when
    titles = [section.title for section in sections]
    # then
    assert titles == ["External services", "REST endpoints", "API documentation"]


def test_banner_redis_check_strips_user_info_on_render() -> None:
    # given
    from ascend_python_common.startup_banner import format_check

    check = BannerCheck(label="Redis", target="redis://user:pw@host:6379/0", status="Connected")
    # when
    rendered = format_check(check.target, check.status)
    # then
    assert "pw" not in rendered
    assert rendered == "redis://host:6379/0 [Connected]"
