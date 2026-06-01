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
    assert isinstance(startup_banner._resolve_host(), str)


def test_resolve_host_falls_back() -> None:
    with patch.object(startup_banner.socket, "gethostname", side_effect=OSError):
        assert startup_banner._resolve_host() == "localhost"


def test_key_state_configured_vs_unconfigured() -> None:
    assert "Configured" in startup_banner._key_state("x")
    assert "Not configured" in startup_banner._key_state(None)


def test_probe_unsupported_scheme() -> None:
    assert "unsupported scheme" in startup_banner._probe_http_sync("file:///tmp/x")


def test_probe_connected_on_2xx() -> None:
    with patch.object(startup_banner.urllib.request, "urlopen", return_value=_Resp200()):
        assert "[Connected]" in startup_banner._probe_http_sync("http://x.test/")


def test_probe_warning_on_3xx() -> None:
    with patch.object(startup_banner.urllib.request, "urlopen", return_value=_Resp301()):
        assert "[Warning" in startup_banner._probe_http_sync("http://x.test/")


def test_probe_http_error() -> None:
    err = startup_banner.urllib.error.HTTPError("http://x/", 404, "NF", {}, None)
    with patch.object(startup_banner.urllib.request, "urlopen", side_effect=err):
        assert "status=404" in startup_banner._probe_http_sync("http://x.test/")


def test_probe_failed_on_oserror() -> None:
    with patch.object(startup_banner.urllib.request, "urlopen", side_effect=OSError("nope")):
        assert "[FAILED]" in startup_banner._probe_http_sync("http://x.test/")


@pytest.mark.asyncio
async def test_log_startup_banner_runs() -> None:
    with patch.object(startup_banner.urllib.request, "urlopen", return_value=_Resp200()):
        await startup_banner.log_startup_banner()
