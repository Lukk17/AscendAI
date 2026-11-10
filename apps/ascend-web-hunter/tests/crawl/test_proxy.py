import pytest

from src.config.config import settings
from src.proxy.proxy_provider import ProxyProvider, crawl_proxy, proxy_provider


def _provider(monkeypatch: pytest.MonkeyPatch, proxy_url: str, crawl_url: str) -> ProxyProvider:
    monkeypatch.setattr(settings, "PROXY_URL", proxy_url)
    monkeypatch.setattr(settings, "CRAWL_PROXY_URL", crawl_url)
    return ProxyProvider()


def test_single_read_never_uses_crawl_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # given both proxies configured
    provider = _provider(monkeypatch, "http://proxy:8080", "http://crawl-proxy:8080")

    # when a single read asks outside any crawl
    # then it uses PROXY_URL only
    assert provider.for_curl_cffi() == {"http": "http://proxy:8080", "https": "http://proxy:8080"}
    assert provider.for_playwright() == {"server": "http://proxy:8080"}


def test_crawl_uses_crawl_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # given both proxies configured
    provider = _provider(monkeypatch, "http://proxy:8080", "http://crawl-proxy:8080")

    # when a crawl fetch asks inside the crawl context
    with crawl_proxy():
        # then it uses CRAWL_PROXY_URL only
        assert provider.for_curl_cffi() == {
            "http": "http://crawl-proxy:8080",
            "https": "http://crawl-proxy:8080",
        }
        assert provider.for_playwright() == {"server": "http://crawl-proxy:8080"}

    # and the context does not leak into later single reads
    assert provider.for_curl_cffi() == {"http": "http://proxy:8080", "https": "http://proxy:8080"}


def test_crawl_without_crawl_proxy_keeps_direct_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    # given no proxy at all
    provider = _provider(monkeypatch, "", "")

    # when / then both surfaces fetch direct
    assert provider.for_curl_cffi() is None
    with crawl_proxy():
        assert provider.for_curl_cffi() is None
        assert provider.for_playwright() is None


def test_crawl_proxy_credentials_split_for_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    # given a crawl proxy URL with credentials
    provider = _provider(monkeypatch, "", "http://user:pass@crawl-proxy:8080")

    # when / then curl keeps the whole URL and playwright splits the credentials
    with crawl_proxy():
        assert provider.for_curl_cffi() == {
            "http": "http://user:pass@crawl-proxy:8080",
            "https": "http://user:pass@crawl-proxy:8080",
        }
        assert provider.for_playwright() == {
            "server": "http://user:pass@crawl-proxy:8080",
            "username": "user",
            "password": "pass",
        }


def test_global_provider_serves_crawl_context(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    monkeypatch.setattr(settings, "CRAWL_PROXY_URL", "http://crawl-proxy:8080")

    # when / then the shared provider answers the crawl proxy in context
    with crawl_proxy():
        assert proxy_provider.for_curl_cffi() == {
            "http": "http://crawl-proxy:8080",
            "https": "http://crawl-proxy:8080",
        }
    assert proxy_provider.for_curl_cffi() != {
        "http": "http://crawl-proxy:8080",
        "https": "http://crawl-proxy:8080",
    }
