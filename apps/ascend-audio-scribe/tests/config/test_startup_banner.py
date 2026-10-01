import socket
import urllib.error
import urllib.request
from email.message import Message
from types import TracebackType
from unittest.mock import patch

import pytest

from src.config import startup_banner


class _Resp200:
    status = 200

    def __enter__(self) -> "_Resp200":
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        return


class _Resp301(_Resp200):
    status = 301


def test_resolve_host_returns_string() -> None:
    # when / then
    assert isinstance(startup_banner._resolve_host(), str)


def test_resolve_host_falls_back() -> None:
    # given
    with patch.object(socket, "gethostname", side_effect=OSError):
        # when / then
        assert startup_banner._resolve_host() == "localhost"


def test_key_state_configured_vs_unconfigured() -> None:
    # when / then
    assert "Configured" in startup_banner._key_state("x")
    assert "Not configured" in startup_banner._key_state(None)


def test_probe_unsupported_scheme() -> None:
    # when / then
    assert "unsupported scheme" in startup_banner._probe_http_sync("file:///tmp/x")


def test_probe_connected_on_2xx() -> None:
    # given
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        # when / then
        assert "[Connected]" in startup_banner._probe_http_sync("http://x.test/")


def test_probe_warning_on_3xx() -> None:
    # given
    with patch.object(urllib.request, "urlopen", return_value=_Resp301()):
        # when / then
        assert "[Warning" in startup_banner._probe_http_sync("http://x.test/")


def test_probe_http_error() -> None:
    # given
    err = urllib.error.HTTPError("http://x/", 404, "NF", Message(), None)
    with patch.object(urllib.request, "urlopen", side_effect=err):
        # when / then
        assert "status=404" in startup_banner._probe_http_sync("http://x.test/")


def test_probe_failed_on_oserror() -> None:
    # given
    with patch.object(urllib.request, "urlopen", side_effect=OSError("nope")):
        # when / then
        assert "[FAILED]" in startup_banner._probe_http_sync("http://x.test/")


@pytest.mark.asyncio
async def test_log_startup_banner_runs() -> None:
    # when / then
    with patch.object(urllib.request, "urlopen", return_value=_Resp200()):
        await startup_banner.log_startup_banner()
