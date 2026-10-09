import urllib.error
import urllib.request
from email.message import Message
from unittest.mock import patch

import pytest

from src.config import startup_banner
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
    assert "OpenAI" in text
    assert "HF API" in text
    assert "POST http://localhost" in text
    assert "/api/v1/transcribe/local" in text
    assert "/api/v1/transcribe/openai" in text
    assert "/api/v1/transcribe/hf" in text
    assert "/api/v1/transcribe/audacity" in text
    assert "/openapi.json" in text
    assert "/docs" in text
    assert "/redoc" in text
    assert "/health" in text
    assert "/ready" in text
    assert "/metrics" in text
    assert "/mcp" in text
    assert "[ascend-audio-scribe]" in text


def test_banner_key_lines_show_configured_state_without_key_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "super-secret-key-xyz")
    monkeypatch.setattr(settings, "HF_TOKEN", "hf-secret-xyz")
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        # when
        text = "\n".join(build_service_banner())
    # then
    assert "[Configured]" in text
    assert "super-secret-key-xyz" not in text
    assert "hf-secret-xyz" not in text


def test_banner_key_lines_show_not_configured_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.setattr(settings, "HF_TOKEN", None)
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        # when
        text = "\n".join(build_service_banner())
    # then
    assert "[Not configured]" in text


def test_service_banner_function_is_used_by_definition() -> None:
    # given
    from src.main import definition

    banner = definition.startup_banner
    assert banner is not None
    # when
    lines = banner()
    # then
    assert isinstance(lines, list)
    assert any("ascend-audio-scribe" in line for line in lines)


def test_banner_sections_have_expected_titles() -> None:
    # given
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        # when
        sections = service_banner_sections()
    # then
    titles = [section.title for section in sections]
    assert titles == ["External services", "REST endpoints", "API documentation", "Observability"]


def test_probe_returns_failed_for_disallowed_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr("src.config.startup_banner._ALLOWED_PROBE_SCHEMES", ("https://",))
    # when
    sections = service_banner_sections()
    # then
    assert startup_banner is not None
    assert len(sections) > 0


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


def test_probe_url_sync_warns_on_non_2xx() -> None:
    # given
    class _Resp503:
        status = 503

        def __enter__(self) -> "_Resp503":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    with patch.object(urllib.request, "urlopen", return_value=_Resp503()):
        # when
        check = startup_banner._probe_url_sync("OpenAI", "http://x.test/")
    # then
    assert "status=503" in check.status


def test_probe_url_sync_warns_on_http_error() -> None:
    # given
    err = urllib.error.HTTPError("http://x/", 404, "NF", Message(), None)
    with patch.object(urllib.request, "urlopen", side_effect=err):
        # when
        check = startup_banner._probe_url_sync("OpenAI", "http://x.test/")
    # then
    assert "status=404" in check.status


def test_probe_url_sync_fails_on_oserror() -> None:
    # given
    with patch.object(urllib.request, "urlopen", side_effect=OSError("nope")):
        # when
        check = startup_banner._probe_url_sync("OpenAI", "http://x.test/")
    # then
    assert check.status == "FAILED"


def test_probe_url_sync_rejects_disallowed_scheme() -> None:
    # when
    check = startup_banner._probe_url_sync("OpenAI", "file:///tmp/x")
    # then
    assert check.status == "FAILED"
