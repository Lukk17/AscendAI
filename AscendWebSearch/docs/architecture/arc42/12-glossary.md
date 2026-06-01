# 12. Glossary

| Term | Definition |
| :--- | :--- |
| **MCP** | Model Context Protocol. An open standard for LLM tool integration. AscendWebSearch exposes `web_search` and `web_read` tools via FastMCP at `POST /mcp` (Streamable HTTP). |
| **FastMCP** | Python library for building MCP servers on top of FastAPI / Starlette. AscendWebSearch uses version 2.14.5 (`pyproject.toml`). |
| **web_search** | MCP tool that accepts a query string and limit, calls SearXNG, and returns a list of `{title, url, content}` dicts. |
| **web_read** | MCP tool that accepts a URL and optional `heavy_mode` / `include_links` flags, runs `WebReader`, and returns extracted content or a 428 human-intervention result. |
| **WebReader** | Orchestrator class (`src/reader/web_reader.py`) that iterates six strategies in order and returns the first result that passes content validation. |
| **BaseStrategy** | Abstract base class (`src/reader/strategies/base_strategy.py`) that all six strategies implement. Defines `extract(url)` and `get_html(url)`. |
| **BeautifulSoupStrategy** | Lightweight HTTP extraction using `curl_cffi` with Chrome120 TLS impersonation and BeautifulSoup HTML parsing. Strategy 1 in the chain. |
| **TrafilaturaStrategy** | Same `curl_cffi` transport as BeautifulSoupStrategy; uses the Trafilatura extraction pipeline instead of BeautifulSoup for better boilerplate removal. Strategy 2. |
| **FlareSolverrStrategy** | Delegates the HTTP request to a running FlareSolverr instance, which uses undetected-chromedriver to solve Cloudflare challenges. Saves `cf_clearance` cookies to `CookieManager`. Strategy 3. |
| **PlaywrightStrategy** | Launches a real Chromium browser (headless=False) with `playwright-stealth` to mask automation fingerprints. Polls for network idle and checks for challenges at each iteration. Strategy 4. |
| **CrawleeStrategy** | Uses Crawlee's `AdaptivePlaywrightCrawler` with geolocation context. More resilient to sites that detect standard Playwright. Strategy 5. |
| **NoVNCStrategy** | Raises `HumanInterventionRequiredException` and spawns a background task that monitors the browser session for completed challenges. Strategy 6 (human-in-the-loop). |
| **HumanInterventionRequiredException** | Python exception (`src/api/exceptions.py`) raised by `NoVNCStrategy`. Carries `vnc_url` and `intervention_type`. Converted to HTTP 428 by `human_intervention_exception_handler`. |
| **ChallengeDetectedException** | Python exception raised by a strategy when it conclusively detects a WAF block or login wall. Causes `WebReader` to short-circuit to `NoVNCStrategy`. |
| **ChallengeDetector** | Static-method class (`src/reader/cloudflare/challenge_detector.py`) that inspects response status codes, HTML content, and URL patterns to detect Cloudflare challenges and login walls. Uses `challenge_dictionary.json`. |
| **CookieManager** | Singleton (`src/reader/cloudflare/cookie_manager.py`) that persists per-domain session data (cookies + User-Agent) in Redis with a 2-hour TTL. Falls back to an in-process dict when Redis is unavailable. See [ADR-002](../decisions/ADR-002-cloudflare-cookie-persistence-redis.md). |
| **cf_clearance** | Cloudflare session cookie issued after a successful challenge solve. Valid for approximately 2 hours. Stored by `CookieManager` so subsequent requests to the same domain skip the challenge. |
| **SSRF** | Server-Side Request Forgery. An attack where a server is tricked into fetching a URI that reaches internal infrastructure. AscendWebSearch's guard is `is_safe_external_url` in `src/validator/url_validator.py`. |
| **SearxngClient** | Async HTTPX client (`src/search/search_client.py`) that sends `GET /search?format=html` to SearXNG and parses results from `article.result` DOM elements. |
| **ContentValidator** | Validates extracted text using word count, error-keyword detection, Flesch reading ease, and type-token ratio checks (`src/validator/content_validator.py`). |
| **URLValidator** | Wraps `AdblockRules` for Playwright/Crawlee route filtering; provides `is_safe_external_url` standalone SSRF check (`src/validator/url_validator.py`). |
| **BlocklistLoader** | Fetches the Fanboy Annoyance adblock list at startup and returns `AdblockRules` (`src/config/blocklist_loader.py`). Failure halts the service. |
| **NoVNC** | Web-based VNC client that exposes a browser window over WebSocket. Used to let a human operator interact with the Chromium session inside the container. |
| **Ngrok** | Tunnelling service that exposes the NoVNC WebSocket port to the public internet when the container is behind NAT. The public URL is discovered dynamically from `api/tunnels`. See [ADR-003](../decisions/ADR-003-novnc-ngrok-captcha-intervention.md). |
| **heavy_mode** | Request flag that skips strategies 1 and 2 and starts the extraction chain from `PlaywrightStrategy`. Used when the caller knows the target site requires JavaScript rendering. |
| **Settings** | Pydantic-settings class (`src/config/config.py`). Reads from env vars and `.env` file. Single `settings` singleton imported across the codebase. |
| **FlareSolverr** | Open-source proxy service that uses undetected-chromedriver to solve Cloudflare WAF challenges and return the solved HTML plus cookies. Runs as a separate container at port 8191 in the scrapper compose stack. |
| **SearXNG** | Self-hosted meta-search engine that aggregates results from multiple search providers without exposing queries to those providers. Runs at port 9020 in the scrapper compose stack. See [ADR-004](../decisions/ADR-004-searxng-meta-search-backend.md). |
| **curl_cffi** | Python library that provides an async HTTP client with TLS fingerprint impersonation. Used by strategies 1, 2, and 3 (`impersonate="chrome120"`) to avoid TLS-based bot detection. |
| **trafilatura** | Python library for main-content extraction from HTML. Strips boilerplate (navigation, ads, footers). Used by `TrafilaturaStrategy` and `FlareSolverrStrategy`. |
| **playwright-stealth** | Playwright plugin (`playwright_stealth`) that applies browser fingerprint masking patches to reduce Playwright detection by anti-bot systems. Used by `PlaywrightStrategy`. |
