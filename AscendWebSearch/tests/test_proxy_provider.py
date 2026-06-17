"""Tests for ProxyProvider seam (task 4.3)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.proxy.proxy_provider import ProxyProvider


def test_proxy_disabled_by_default() -> None:
    with patch("src.proxy.proxy_provider.settings.PROXY_URL", ""):
        p = ProxyProvider()
    assert not p.enabled
    assert p.for_curl_cffi() is None
    assert p.for_playwright() is None
    assert p.for_flaresolverr() is None


def test_proxy_enabled_when_url_set() -> None:
    with patch("src.proxy.proxy_provider.settings.PROXY_URL", "socks5://proxy:1080"):
        p = ProxyProvider()
    assert p.enabled
    assert p.for_curl_cffi() == {"http": "socks5://proxy:1080", "https": "socks5://proxy:1080"}
    assert p.for_playwright() == {"server": "socks5://proxy:1080"}
    assert p.for_flaresolverr() == {"url": "socks5://proxy:1080"}


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_injects_proxy_when_configured() -> None:
    """When proxy_provider.for_curl_cffi() returns a dict, it is passed to the HTTP session."""
    from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi

    proxy_dict = {"http": "http://proxy:8080", "https": "http://proxy:8080"}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>ok</body></html>"
    mock_response.url = "http://test.com"
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=mock_response)

    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.proxy_provider.for_curl_cffi", return_value=proxy_dict
        ),
        patch("src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_login_required", return_value=False
        ),
        patch("src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_blocked", return_value=False),
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")

    assert result == "<html><body>ok</body></html>"
    call_kwargs = session.get.call_args.kwargs
    assert call_kwargs.get("proxies") == proxy_dict


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_injects_proxy_on_redirect_hop() -> None:
    """When a redirect occurs, the proxy dict is forwarded to the hop request too."""
    from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi

    proxy_dict = {"http": "http://proxy:8080", "https": "http://proxy:8080"}

    redirect_response = MagicMock()
    redirect_response.status_code = 302
    redirect_response.headers = {"location": "http://test.com/final"}
    redirect_response.text = ""

    final_response = MagicMock()
    final_response.status_code = 200
    final_response.text = "<html>final</html>"
    final_response.url = "http://test.com/final"
    final_response.headers = {}
    final_response.raise_for_status = MagicMock()

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(side_effect=[redirect_response, final_response])

    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.proxy_provider.for_curl_cffi", return_value=proxy_dict
        ),
        patch("src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession", return_value=session),
        patch("src.reader.strategies.curl_cffi_fetcher.is_safe_external_url", return_value=True),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_login_required", return_value=False
        ),
        patch("src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_blocked", return_value=False),
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")

    assert "final" in result
    assert session.get.call_count == 2
    # Both the initial call and the hop call must carry proxies
    for call in session.get.call_args_list:
        assert call.kwargs.get("proxies") == proxy_dict


@pytest.mark.asyncio
async def test_flaresolverr_strategy_injects_proxy_into_payload() -> None:
    """When proxy_provider.for_flaresolverr() returns a dict, it is added to the POST payload."""
    from src.reader.strategies.flaresolverr_strategy import FlareSolverrStrategy

    fs_proxy = {"url": "http://proxy:8080"}
    payload_sent: dict = {}

    response = MagicMock()
    response.json = MagicMock(
        return_value={
            "status": "ok",
            "solution": {"response": "<html>ok</html>", "cookies": [], "userAgent": "UA"},
        }
    )
    response.raise_for_status = MagicMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    async def capture_post(url, *, json, **_kwargs):
        payload_sent.update(json)
        return response

    session.post = capture_post

    mock_breaker = MagicMock()
    mock_breaker.is_open = False

    with (
        patch(
            "src.reader.strategies.flaresolverr_strategy.proxy_provider.for_flaresolverr",
            return_value=fs_proxy,
        ),
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "src.reader.strategies.flaresolverr_strategy.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch("src.reader.strategies.flaresolverr_strategy.flaresolverr_breaker", mock_breaker),
        patch(
            "src.reader.strategies.flaresolverr_strategy.ChallengeDetector.is_login_required",
            return_value=False,
        ),
        patch("src.reader.strategies.flaresolverr_strategy.ChallengeDetector.is_blocked", return_value=False),
    ):
        await FlareSolverrStrategy().get_html("https://example.com")

    assert payload_sent.get("proxy") == fs_proxy


@pytest.mark.asyncio
async def test_crawlee_strategy_injects_proxy_when_configured() -> None:
    """When proxy_provider.for_playwright() returns a dict, it is added to browser_new_context_options."""
    from src.reader.strategies.crawlee_strategy import CrawleeStrategy
    from src.validator.url_validator import URLValidator

    proxy_dict = {"server": "http://proxy:8080"}
    rules = MagicMock()
    rules.should_block.return_value = False
    url_validator = URLValidator(rules)

    captured_ctx_options: dict = {}

    def fake_with_beautifulsoup(*args, **kwargs):
        playwright_kwargs = kwargs.get("playwright_crawler_specific_kwargs", {})
        captured_ctx_options.update(playwright_kwargs.get("browser_new_context_options", {}))
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock()
        mock_crawler.router.default_handler = lambda f: f
        mock_crawler.pre_navigation_hook = lambda f: f
        return mock_crawler

    with (
        patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_cls,
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.proxy_provider.for_playwright", return_value=proxy_dict
        ),
        patch("src.reader.strategies.crawlee_strategy.trafilatura.extract", return_value=None),
    ):
        mock_cls.with_beautifulsoup_static_parser.side_effect = fake_with_beautifulsoup
        strategy = CrawleeStrategy(url_validator)
        await strategy.extract("http://test.com")

    assert captured_ctx_options.get("proxy") == proxy_dict


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_follows_redirect_without_proxy() -> None:
    """When there is no proxy and a redirect occurs, the hop request is made without proxies."""
    from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi

    redirect_response = MagicMock()
    redirect_response.status_code = 302
    redirect_response.headers = {"location": "http://test.com/final"}
    redirect_response.text = ""

    final_response = MagicMock()
    final_response.status_code = 200
    final_response.text = "<html>noproxy</html>"
    final_response.url = "http://test.com/final"
    final_response.headers = {}
    final_response.raise_for_status = MagicMock()

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(side_effect=[redirect_response, final_response])

    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch("src.reader.strategies.curl_cffi_fetcher.proxy_provider.for_curl_cffi", return_value=None),
        patch("src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession", return_value=session),
        patch("src.reader.strategies.curl_cffi_fetcher.is_safe_external_url", return_value=True),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_login_required", return_value=False
        ),
        patch("src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_blocked", return_value=False),
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")

    assert "noproxy" in result
    assert session.get.call_count == 2
    # The hop call must NOT have proxies kwarg
    hop_call_kwargs = session.get.call_args_list[1].kwargs
    assert "proxies" not in hop_call_kwargs


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_breaks_on_empty_redirect_location() -> None:
    """When a redirect response has no Location header, the loop breaks immediately."""
    from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi

    redirect_response = MagicMock()
    redirect_response.status_code = 302
    redirect_response.headers = {}  # no location header
    redirect_response.text = "<html>original</html>"
    redirect_response.url = "http://test.com"
    redirect_response.raise_for_status = MagicMock()

    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=redirect_response)

    with (
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch("src.reader.strategies.curl_cffi_fetcher.proxy_provider.for_curl_cffi", return_value=None),
        patch("src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_login_required", return_value=False
        ),
        patch("src.reader.strategies.curl_cffi_fetcher.ChallengeDetector.is_blocked", return_value=False),
    ):
        result = await fetch_with_curl_cffi("http://test.com", lambda: "ua", "TestStrat")

    # Only one GET call (the initial); the empty location caused an immediate break
    assert session.get.call_count == 1
    assert result == "<html>original</html>"


@pytest.mark.asyncio
async def test_crawlee_strategy_injects_storage_state_when_present() -> None:
    """When get_storage_state() returns a state dict, it is passed as browser_new_context_options storage_state."""
    from src.reader.strategies.crawlee_strategy import CrawleeStrategy
    from src.validator.url_validator import URLValidator

    stored_state = {"cookies": [{"name": "auth", "value": "token"}], "origins": []}
    rules = MagicMock()
    rules.should_block.return_value = False
    url_validator = URLValidator(rules)

    captured_ctx_options: dict = {}

    def fake_with_beautifulsoup(*args, **kwargs):
        playwright_kwargs = kwargs.get("playwright_crawler_specific_kwargs", {})
        captured_ctx_options.update(playwright_kwargs.get("browser_new_context_options", {}))
        mock_crawler = MagicMock()
        mock_crawler.run = AsyncMock()
        mock_crawler.router.default_handler = lambda f: f
        mock_crawler.pre_navigation_hook = lambda f: f
        return mock_crawler

    with (
        patch("src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler") as mock_cls,
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=stored_state),
        ),
        patch("src.reader.strategies.crawlee_strategy.proxy_provider.for_playwright", return_value=None),
        patch("src.reader.strategies.crawlee_strategy.trafilatura.extract", return_value=None),
    ):
        mock_cls.with_beautifulsoup_static_parser.side_effect = fake_with_beautifulsoup
        strategy = CrawleeStrategy(url_validator)
        await strategy.extract("http://test.com")

    assert captured_ctx_options.get("storage_state") == stored_state
