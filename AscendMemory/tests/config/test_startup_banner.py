from email.message import Message
from types import TracebackType
from unittest.mock import patch

import pytest

from src.config import startup_banner


class _FakeUrlOpenResponse:
    """Stand-in for the urllib.request.urlopen context manager.

    Mirrors only the surface area `_probe_http_sync` touches: a `status`
    attribute and the context-manager protocol. Subclassed per-test to vary
    the status code.
    """

    status: int = 200

    def __enter__(self) -> "_FakeUrlOpenResponse":
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        return


class _Resp200(_FakeUrlOpenResponse):
    status = 200


class _Resp301(_FakeUrlOpenResponse):
    status = 301


def test_resolve_host_returns_string() -> None:
    host = startup_banner._resolve_host()
    assert isinstance(host, str)
    assert host


def test_resolve_host_falls_back_on_oserror() -> None:
    with patch.object(startup_banner.socket, "gethostname", side_effect=OSError):
        assert startup_banner._resolve_host() == "localhost"


def test_probe_http_sync_rejects_disallowed_scheme() -> None:
    # file:// URL is the exact case the scheme guard exists to block.
    result = startup_banner._probe_http_sync("file:///tmp/example")
    assert "unsupported scheme" in result


def test_probe_http_sync_connected_on_2xx() -> None:
    with patch.object(startup_banner.urllib.request, "urlopen", return_value=_Resp200()):
        assert "[Connected]" in startup_banner._probe_http_sync("http://x.test/")


def test_probe_http_sync_warning_on_3xx_etc() -> None:
    with patch.object(startup_banner.urllib.request, "urlopen", return_value=_Resp301()):
        assert "[Warning" in startup_banner._probe_http_sync("http://x.test/")


def test_probe_http_sync_http_error_returns_warning() -> None:
    # HTTPError.hdrs is typed email.message.Message; pass a real (empty)
    # instance instead of a bare dict to satisfy the typeshed signature.
    err = startup_banner.urllib.error.HTTPError(
        "http://x.test/", 404, "Not Found", Message(), None
    )
    with patch.object(startup_banner.urllib.request, "urlopen", side_effect=err):
        assert "status=404" in startup_banner._probe_http_sync("http://x.test/")


def test_probe_http_sync_unknown_failure_returns_failed() -> None:
    with patch.object(
        startup_banner.urllib.request,
        "urlopen",
        side_effect=OSError("connection refused"),
    ):
        assert "[FAILED]" in startup_banner._probe_http_sync("http://x.test/")


def test_describe_default_embedding_handles_known_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(startup_banner.settings, "MEM0_DEFAULT_PROVIDER", "lmstudio")
    out = startup_banner._describe_default_embedding()
    assert "lmstudio" in out


def test_describe_default_embedding_handles_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(startup_banner.settings, "MEM0_DEFAULT_PROVIDER", "unknown-xyz")
    out = startup_banner._describe_default_embedding()
    assert "Warning" in out


def test_describe_default_embedding_marks_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(startup_banner.settings, "MEM0_DEFAULT_PROVIDER", "openai")
    monkeypatch.setattr(startup_banner.settings, "OPENAI_API_KEY", "")
    out = startup_banner._describe_default_embedding()
    assert "Not configured" in out


@pytest.mark.asyncio
async def test_log_startup_banner_runs_without_raising() -> None:
    with patch.object(startup_banner.urllib.request, "urlopen", return_value=_Resp200()):
        await startup_banner.log_startup_banner()
