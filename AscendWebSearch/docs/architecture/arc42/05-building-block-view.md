# 5. Building Block View

---

### Level 1: module map

```mermaid
graph TB
    subgraph "AscendWebSearch service"
        main["src/main.py<br/>App factory, lifespan, health probe"]

        subgraph "api"
            rest["api/rest/rest_endpoints.py<br/>GET /api/v1/web/search<br/>POST /api/v2/web/read"]
            mcp["api/mcp/mcp_server.py<br/>web_search, web_read tools"]
            exc["api/exception_handlers.py<br/>428, 503, 500 handlers"]
            exceptions["api/exceptions.py<br/>HumanInterventionRequiredException<br/>ChallengeDetectedException"]
        end

        subgraph "reader"
            webreader["reader/web_reader.py<br/>WebReader — strategy orchestrator"]
            subgraph "strategies"
                bs["strategies/beautifulsoup_strategy.py"]
                traf["strategies/trafilatura_strategy.py"]
                flare["strategies/flaresolverr_strategy.py"]
                pw["strategies/playwright_strategy.py"]
                crawlee["strategies/crawlee_strategy.py"]
                novnc["strategies/novnc_strategy.py"]
            end
            subgraph "cloudflare"
                detector["cloudflare/challenge_detector.py"]
                cookies["cloudflare/cookie_manager.py"]
            end
            annotator["reader/link_annotator.py"]
        end

        subgraph "search"
            searxng["search/search_client.py<br/>SearxngClient"]
        end

        subgraph "validator"
            content["validator/content_validator.py"]
            url["validator/url_validator.py"]
        end

        subgraph "config"
            cfg["config/config.py<br/>Settings singleton"]
            blocklist["config/blocklist_loader.py"]
            banner["config/startup_banner.py"]
        end
    end

    main --> rest
    main --> mcp
    main --> exc
    main --> blocklist
    rest --> webreader
    rest --> searxng
    rest --> url
    mcp --> webreader
    mcp --> searxng
    mcp --> url
    webreader --> bs
    webreader --> traf
    webreader --> flare
    webreader --> pw
    webreader --> crawlee
    webreader --> novnc
    webreader --> content
    webreader --> detector
    bs --> cookies
    traf --> cookies
    flare --> cookies
    novnc --> cookies
    pw --> url
    crawlee --> url
```

---

### Component responsibilities

| Component | File | Responsibility |
| :--- | :--- | :--- |
| App factory | `src/main.py` | Creates FastAPI app, runs lifespan blocklist load, mounts MCP sub-app, registers `/health`. |
| `rest_endpoints.py` | `src/api/rest/rest_endpoints.py` | Two routers (`/api/v1`, `/api/v2`). Validates URL safety, delegates to `WebReader` or `SearxngClient`. |
| `mcp_server.py` | `src/api/mcp/mcp_server.py` | FastMCP instance. `web_search` and `web_read` tools. Same SSRF guard as REST. |
| `exception_handlers.py` | `src/api/exception_handlers.py` | 428 for `HumanInterventionRequiredException`, 503 for `httpx.HTTPError`, 500 fallback. |
| `WebReader` | `src/reader/web_reader.py` | Ordered dict of six strategies. Iterates until `ContentValidator` passes or all strategies exhausted. |
| `BeautifulSoupStrategy` | `src/reader/strategies/beautifulsoup_strategy.py` | `curl_cffi` Chrome120 impersonation + BeautifulSoup parse. Reads cached session from `CookieManager`. |
| `TrafilaturaStrategy` | `src/reader/strategies/trafilatura_strategy.py` | Same `curl_cffi` transport; Trafilatura extraction pipeline instead of BeautifulSoup. |
| `FlareSolverrStrategy` | `src/reader/strategies/flaresolverr_strategy.py` | Posts URL to FlareSolverr, parses solved HTML with Trafilatura, saves `cf_clearance` to `CookieManager`. |
| `PlaywrightStrategy` | `src/reader/strategies/playwright_strategy.py` | Headless=False Chromium with `playwright-stealth`. Polls for network idle; runs adblock route filter. |
| `CrawleeStrategy` | `src/reader/strategies/crawlee_strategy.py` | Crawlee `AdaptivePlaywrightCrawler`; geolocation context; adblock route filter. |
| `NoVNCStrategy` | `src/reader/strategies/novnc_strategy.py` | Spawns background cookie monitor; raises `HumanInterventionRequiredException` with resolved VNC URL. |
| `ChallengeDetector` | `src/reader/cloudflare/challenge_detector.py` | Inspects response status, HTML snippets, and URL patterns to detect WAF blocks and login walls. |
| `CookieManager` | `src/reader/cloudflare/cookie_manager.py` | Singleton. Redis-backed session store with in-process fallback. Apex domain normalisation. |
| `SearxngClient` | `src/search/search_client.py` | Async `httpx` client for SearXNG HTML search. BeautifulSoup `article.result` parser. |
| `ContentValidator` | `src/validator/content_validator.py` | Word count, error-keyword check, Flesch reading ease, type-token ratio. |
| `URLValidator` | `src/validator/url_validator.py` | Wraps adblock `AdblockRules` for route filtering; `is_safe_external_url` standalone SSRF guard. |
| `Settings` | `src/config/config.py` | Pydantic-settings class. Single `settings` singleton. Reads `.env` file or environment. |
