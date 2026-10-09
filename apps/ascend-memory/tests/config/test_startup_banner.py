import urllib.error
import urllib.request
from email.message import Message
from unittest.mock import patch

import pytest
from ascend_python_common.startup_banner import FAILED, BannerCheck

from src.config.config import settings
from src.config.startup_banner import (
    BANNER,
    build_service_banner,
    service_banner_sections,
)


class _Resp200:
    status = 200

    def __enter__(self) -> "_Resp200":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_banner_art_text_is_present() -> None:
    # given
    art = BANNER
    # when
    lines = build_service_banner()
    # then
    assert art.splitlines()[0] in "\n".join(lines)


def test_banner_finds_every_content_line() -> None:
    # given
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        # when
        text = "\n".join(build_service_banner())
    # then
    assert "Qdrant" in text
    assert "Embedding" in text
    assert "POST http://localhost" in text
    assert "/api/v1/memory/insert" in text
    assert "/api/v1/memory/search" in text
    assert "/api/v1/memory" in text
    assert "DELETE" in text
    assert "/api/v1/memory/wipe" in text
    assert "/openapi.json" in text
    assert "/docs" in text
    assert "/redoc" in text


def test_banner_key_lines_show_configured_state_without_key_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "MEM0_DEFAULT_PROVIDER", "lmstudio")
    monkeypatch.setattr(settings, "LMSTUDIO_API_KEY", "super-secret-key-xyz")
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        # when
        text = "\n".join(build_service_banner())
    # then
    assert "[Configured]" in text
    assert "super-secret-key-xyz" not in text


def test_banner_key_lines_show_not_configured_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "MEM0_DEFAULT_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        # when
        text = "\n".join(build_service_banner())
    # then
    assert "[Not configured]" in text


def test_banner_sections_have_expected_titles() -> None:
    # given
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        # when
        sections = service_banner_sections()
    # then
    titles = [section.title for section in sections]
    assert titles == ["External services", "REST endpoints", "API documentation"]


def test_service_banner_function_is_used_by_definition() -> None:
    # given
    from src.main import definition

    banner = definition.startup_banner
    assert banner is not None
    # when
    lines = banner()
    # then
    assert isinstance(lines, list)
    assert any("ascend-memory" in line for line in lines)


class _Resp503:
    status = 503

    def __enter__(self) -> "_Resp503":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_probe_returns_failed_for_disallowed_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr("src.config.startup_banner._ALLOWED_PROBE_SCHEMES", ("https://",))
    # when
    sections = service_banner_sections()
    # then
    check = sections[0].entries[0]
    assert isinstance(check, BannerCheck)
    assert check.status == FAILED


def test_probe_returns_warning_on_non_2xx_status() -> None:
    # given
    with patch.object(urllib.request, "urlopen", return_value=_Resp503()):
        # when
        sections = service_banner_sections()
    # then
    check = sections[0].entries[0]
    assert isinstance(check, BannerCheck)
    assert "status=503" in check.status


def test_probe_returns_warning_on_http_error() -> None:
    # given
    error = urllib.error.HTTPError("http://localhost:6333/", 500, "Internal Error", Message(), None)
    with patch.object(urllib.request, "urlopen", side_effect=error):
        # when
        sections = service_banner_sections()
    # then
    check = sections[0].entries[0]
    assert isinstance(check, BannerCheck)
    assert "status=500" in check.status


def test_banner_probe_uses_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "STARTUP_PROBE_TIMEOUT_SECONDS", 0.1)
    seen: dict[str, object] = {}

    def fake_urlopen(url: str, timeout: float = 0.0) -> _Resp200:
        seen["timeout"] = timeout
        return _Resp200()

    with patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
        # when
        service_banner_sections()
    # then
    assert seen["timeout"] == 0.1


def test_embedding_returns_warning_for_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "MEM0_DEFAULT_PROVIDER", "unknown-provider-xyz")
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        # when
        sections = service_banner_sections()
    # then
    entry = sections[0].entries[1]
    assert isinstance(entry, BannerCheck)
    assert "unknown provider" in entry.status
