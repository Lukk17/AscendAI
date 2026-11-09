"""The curl_cffi tier never logs a URI's user info (secret never reaches logs)."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.reader.strategies import curl_cffi_fetcher as fetcher


class _NoCookies:
    async def get_flat_cookies(self, _url: str, _profile: str | None) -> dict[str, str]:
        return {}

    async def get_user_agent(self, _url: str, _profile: str | None) -> None:
        return None


@pytest.mark.asyncio
async def test_refused_userinfo_url_logs_no_secret(caplog: pytest.LogCaptureFixture) -> None:
    # given
    url = "https://user:topsecret123@example.com/page"
    # when
    with caplog.at_level(logging.WARNING):
        result = await fetcher.fetch_with_curl_cffi(url, lambda: "probe-ua", "probe")
    # then
    assert result == ""
    assert "topsecret123" not in caplog.text
    refused = [record for record in caplog.records if "SSRF guard refused" in record.getMessage()]
    assert len(refused) == 1
    assert "user@" not in refused[0].getMessage()
    assert "https://example.com/page" in refused[0].getMessage()


@pytest.mark.asyncio
async def test_a_failed_fetch_logs_the_reason_without_a_signature(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    url = "https://example.com/page?X-Amz-Signature=secret"

    monkeypatch.setattr(fetcher, "check_fetch_uri", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(
        "src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession",
        MagicMock(side_effect=OSError(f"lost {url}")),
    )
    monkeypatch.setattr(fetcher, "cookie_manager", _NoCookies())

    # when
    with caplog.at_level(logging.WARNING):
        result = await fetcher.fetch_with_curl_cffi(url, lambda: "probe-ua", "probe")

    # then
    assert result == ""
    assert "X-Amz-Signature" not in caplog.text
    assert "probe failed to fetch URL https://example.com/page: lost https://example.com/page" in caplog.text
