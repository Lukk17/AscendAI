"""The curl_cffi tier never logs a URI's user info (secret never reaches logs)."""

import logging

import pytest

from src.reader.strategies import curl_cffi_fetcher as fetcher


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
