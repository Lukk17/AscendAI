# 8. Crosscutting Concepts

---

### Logging

Logging comes from `ascend-python-common` (`configure_logging`): `LOG_LEVEL` is honoured, `LOG_FORMAT` selects
`json` or `color`, and every line starts with `[ascend-web-hunter]`. There is no service `logging_config.py` and
no `log_config` argument on `uvicorn.run`. All strategy modules log at `INFO` when a strategy
starts (`--- Strategy N STARTED ---`) and at `WARNING` when a strategy fails or detects a challenge. The startup
banner frame lives in the library; the service passes its art text, its content lines, and its readiness probe
results, so operators can verify the runtime configuration from container logs without inspecting env vars separately.
Its External services section also probes the `/health` of the three document routing targets, docling-serve,
ascend-ocr and ascend-audio-scribe, or shows a route as off when its URL is empty. These rows are warnings only,
and the routing targets stay out of `/ready` because each route is optional, see
[running.md](../../running.md#startup-readiness-banner).

---

### SSRF guard

Two distinct SSRF surfaces exist and both are guarded by the shared `check_fetch_uri`
(`ascend_python_common.uri_guard`), with a policy of the `ALLOWED_PRIVATE_HOSTS` hosts, no file root, and
`MAX_REDIRECT_HOPS` (10) hops. The three URL checks of the REST endpoints (`src/api/rest/rest_endpoints.py`) call
it directly, and the four URL-checking MCP tools share the `_check_url` helper (`src/api/mcp/mcp_server.py`) that
calls it. A refused URL answers `400` with code `unsafe_uri` on REST and a tool error starting with `unsafe_uri: `
on MCP. A URI with user info is refused the same way. `URLValidator` and the `url_validator` singleton stay in
`src/validator/url_validator.py` for the ad blocklist only; the address rule and the pinning left that module.

The boundary check and the fetch are separated by the whole strategy chain, so the fetch path guards itself as
well. The `curl_cffi` tiers do not follow redirects automatically: the redirect loop is the library's
`follow_guarded_redirects` with a curl_cffi `send_hop` that builds its `CURLOPT_RESOLVE` entries from the checked
target, so each hop is checked before it is followed, up to ten hops, and no hop is ever fetched before it has
been validated. A relative `Location` is resolved against the URL
of the hop that returned it first, as RFC 9110 section 10.2.2 requires, and the resolved absolute URL then faces
that same check, so an ordinary relative redirect is followed and one that resolves onto an internal address is
still refused. Those tiers also pin what they
connect to: the socket opens against an address the guard authorised rather than
against a second, possibly different, answer to a second lookup. The browser tiers (`4-playwright_stealth`,
`4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive`, the browser of `6-novnc`) and the screenshot capture are
pinned too: the route handler of `src/reader/browser_guard.py` checks each request and continues it, and the browser
makes its own connection through one local tunnel per process (`src/reader/pinned_tunnel.py`), the only way out it has.
The tunnel resolves each host once, refuses what the guard refuses, connects only to the checked address and copies
bytes, so the browser keeps its own TLS. Playwright does not route redirect hops, so the tunnel checks them when the
browser connects, and a refused hop of the read's own main frame ends the read with `UnsafeUriError`. Page WebSockets
are closed. Both halves are recorded in [ADR-012](../decisions/ADR-012-connect-time-address-pinning.md), the browser
half in its 2026-11-09 amendment.

The SearXNG client issues its own outbound requests, but the query is operator-configured text from the caller.
SearXNG runs inside the trusted docker-compose network; its responses are parsed, not fetched by the service.

---

### Content validation

`ContentValidator` (`src/validator/content_validator.py`) applies four checks in order:

1. Empty-string guard.
2. Error-keyword scan (list in `settings.ERROR_KEYWORDS`: "Access Denied", "403 Forbidden", "Captcha", etc.).
3. Minimum word count (`VALIDATION_MIN_WORDS`, default 10).
4. Quality metrics: Flesch reading ease (`MIN_FLESCH_SCORE`, default 20.0) and type-token ratio
   (`MIN_TTR`, default 0.1) via `textstat`. Errors in `textstat` are caught and logged, and the content is
   rejected when the metrics calculation fails.

A strategy result is only accepted by `WebReader` if `ContentValidator.validate` returns `True`.

---

### Adblock blocklist filtering

`BlocklistLoader` loads the Fanboy Annoyance list from the vendored `src/assets/fanboy-annoyance.txt` and returns
an `AdblockRules` instance; nothing is downloaded automatically. The result backs the single process-wide
`url_validator` singleton (`src/validator/url_validator.py`), which `PlaywrightStrategy` and `CrawleeStrategy` use
as a route filter whose `route_handler` aborts any request matching the blocklist rules - reducing noise in
extracted content by blocking ads, trackers, and annoyance scripts before they execute in the browser. An operator
can refresh the list from `BLOCKLIST_URL` via `POST /api/v1/blocklist/refresh`, which only takes effect if the
download parses to at least one rule. See [ADR-008](../decisions/ADR-008-blocklist-vendored-not-fetched.md).

---

### Challenge detection

One function decides whether a page is a challenge wall: `assess` in
`src/reader/cloudflare/challenge_signals.py`. It returns one `ChallengeVerdict` with a score, the threshold,
every fired signal, the vendor, `wall`, `has_content` and the `intervention_type` (`captcha` or `login`). The
signals come from five families (vendor, HTTP status, page structure, page shape and catalogue phrases) and
work in any language. A page is a wall when its score reaches `CHALLENGE_SCORE_THRESHOLD` (100), and a page is
accepted only when it is no wall and carries real content. Every tier, the orchestrator and the NoVNC monitor
use the same function, so no two of them can disagree about the same page.
`ChallengeDetector.login_wall_verdict` (`src/reader/cloudflare/challenge_detector.py`) adds the login wall
decision on top of the verdict, and `ChallengeDetector.is_login_redirect_url` sends a URL that is itself a
login redirect straight to the NoVNC tier.

A tier that finds a wall raises `ChallengeDetectedException` with the verdict, and the orchestrator moves on to
the next tier, toward the NoVNC window. The signals, their weights, the tuning settings and the fixture rules
are in [Challenge detection](../../challenge-detection.md), and the decision is
[ADR-014](../decisions/ADR-014-scored-challenge-detection.md).

---

### Browser tier reads and their verdicts

The three browser tiers (`4-playwright_stealth`, `4a-patchright`, `4b-camoufox`) differ only in how they launch
a browser, build a context and protect it. The navigation, the poll while a challenge clears, the render, the
scroll and the judgement live once in `src/reader/strategies/browser_read.py`, so the tiers cannot drift apart.

Every browser tier judges a page by the status and headers of the latest main-frame document response
(`MainFrameResponses` in `src/reader/strategies/main_frame_response.py`), never by the first one. A challenge
that clears navigates the main frame again, and from then on the challenge response no longer describes the
page. Subresource responses and child-frame navigations are never recorded, because they do not describe the
page either. The NoVNC monitor judges every check of its window the same way, with the latest main-frame response
of the window's page, so a wall known only by its header (`cf-mitigated: challenge`) ends the window as a wall.

A read polls its page on every `NETWORKIDLE_POLL_MS` while a challenge may still clear, and logs each check, but
records exactly one verdict, one score and one set of signals, as the challenge detection observability
specification asks of every read tier. The recorded verdict is the one the read ends on: the wall or login
verdict it escalates with, or the verdict of the rendered page. When the read fails after it checked its page,
for example in the wait, the scroll or the last `page.content()`, the verdict of its last check is recorded once,
so a failed read is still counted. A read that fails before it checked any page records nothing. The
orchestrator then judges the page a tier returned once more (`_second_look` in `src/reader/web_reader.py`) and
records that verdict under the tier `reader`, accepted or not, so every verdict it requests is counted and the
score count always equals the verdict count.

The `screenshot` format navigates once per read and takes the HTML and the PNG from that one navigation, so a
screenshot read costs the target site exactly one page load. The captured page is judged with the same function
and recorded under the tier's own name, so a screenshot read through a browser tier counts like any other read
through it, and a login wall or a wall escalates to the next tier before a PNG is taken.

---

### Browser identity of the patchright tier

`4a-patchright` keeps the user agent of its own browser and sets only a stored one. A fixed Windows Chrome text on the
Linux Chromium of the image keeps a Cloudflare challenge up that the same browser clears by itself without it. See the
2026-11-09 amendment of ADR-006.

---

### Browser identity of the camoufox tier

Camoufox draws a complete Firefox identity per context, so `4b-camoufox` never injects a stored user agent. A
Chromium user agent would contradict the drawn fingerprint, and even a Firefox one would disagree with the
generated version and client hints. Only the stored `storage_state`, the cookies and localStorage, is replayed.

---

### The crawlee tier's process-wide configuration and wall-clock bound

Crawlee's service locator builds and caches its `Configuration` singleton the first time any crawler is
constructed in the process, and never reads the environment again. `CRAWLEE_MEMORY_MBYTES` and
`CRAWLEE_STORAGE_DIR` are therefore written to the environment before the first crawler is constructed, or they
have no effect.

Building a crawler also configures the process logging unless the crawler is told not to: `BasicCrawler` in
Crawlee 1.3.1 removes every handler of the root logger, adds its own colored handler, sets the root level, and
sets the `httpx` logger level. The adaptive crawler passes its options on to its two sub-crawlers, so all three
would do it. After one read through `5-crawlee_adaptive` every log line of the process, `uvicorn.access`
included, was Crawlee's colored text with no `correlation_id` or `trace_id`. The tier therefore builds its
crawler with `configure_logging=False`. Crawlee's own loggers keep `propagate` on, so their records reach the
service's one handler set up by `ascend-python-common` and are written in `LOG_FORMAT` like every other line.

Crawlee's autoscaler blocks all work for as long as it considers the system memory-overloaded, so no request is
ever dequeued. `BasicCrawler.run()` also catches `CancelledError` for its graceful shutdown, which swallows the
cancellation `asyncio.wait_for` issues on timeout. The asyncio documentation says that "if the task suppresses
the cancellation and returns a value instead, that value is returned". The elapsed time is therefore checked
again after the call returns, so an autoscaler that stays overloaded fails the tier instead of returning empty
content after it used the whole read budget.

Crawlee's own block handling is off (`retry_on_blocked=False`), and 403, 429 and 503, the statuses the scored
verdict treats as block statuses (`BLOCK_STATUSES` in `src/reader/cloudflare/challenge_signals.py`), are ignored
error status codes. Without this Crawlee raises a session error on 401, 403 or 429, or on a challenge iframe it
knows, before the request handler runs, and fetches the page again on a new session up to ten times, and it
retries a 503 as a server error. The tier then counts no verdict for the page. Now the answer reaches the request
handler once and the tier's scored verdict decides, with the status and headers of the latest main-frame
response, as on every other tier. Other 4xx answers fail the request without a retry, and other 5xx answers keep
Crawlee's retries.

---

### The recrawl conditional probe

A recrawl first sends `If-None-Match` and `If-Modified-Since` (`src/crawl/fetcher.py`) through the same guard and
connect-time pinning as a single read, so a 304 answer costs one light request and the stored page file is copied
forward without any page bytes passing through the service. Every hop is streamed and stopped once its status
and headers arrive, so no body is read. The probe sends the stored cookies and user agent of the job's profile,
the ones the static read tiers send, so a profile crawl probes the same page a read sees. Like every crawl fetch
it runs inside the crawl proxy context of the worker.

---

### Crawl page reads and robots.txt

A crawl page read neither reads from nor writes to the in-process read cache of single reads
(`use_read_cache=False` on `WebReader.read_page` and `WebReader.read_linked_page`), so a page a job reports as
`fetched` was fetched by that job, never served from a read another tenant made.

A crawl job ignores the rules of robots.txt unless the request sends `respect_robots` true. A job that ignores them
skips no page for them and applies no `Crawl-delay`, and it still fetches robots.txt once per origin to read its
sitemap addresses, which seed the crawl. For such a job a robots.txt that cannot be loaded disallows nothing and
only leaves the job without sitemap addresses, and every failure while seeding from sitemaps is logged and ends the
seeding, so the page is still read. `CRAWL_DEFAULT_DELAY_SECONDS` applies to every job. The rest of this section
describes a job that sends `respect_robots` true.

robots.txt is fetched by `fetch_robots_txt` (`src/crawl/fetcher.py`) through the same guard, connect-time pinning
and redirect hops as every crawl fetch, and `load_rules` (`src/crawl/robots.py`) reads the final answer as RFC 9309
says, with 429 read as a server error the way Google reads it:

| Final answer | Verdict for the origin |
| :--- | :--- |
| 2xx with a body | The parsed rules, their `Crawl-delay` and their sitemaps |
| 2xx with an empty body, any 4xx except 429, a redirect left at the hop limit, a hop the guard refuses | Every page allowed |
| 5xx, 429, or a connection or transport error | Every page disallowed |

The robots.txt and sitemap fetches carry the cookies and user agent of the job's `profile` and run inside the
crawl proxy context, the first robots ask before a claim included. Each instance keeps one verdict per job, profile
and origin, the disallow-all of an unreachable file included, and concurrent asks share one fetch. Every instance
that sees the job ended, gone or no longer claimable drops that memory, and a fetch still running when its job is
dropped keeps nothing. A fetch that raises or is cancelled is not kept, and the page that asked is skipped. A disallowed page is never fetched: it counts as `failed` and its line in `pages.ndjson` reads
`status` `skipped` with `reason` `robots_disallowed`. Reading a robots.txt stops at `CRAWL_ROBOTS_MAX_BYTES`
(512000, the 500 KiB RFC 9309 section 2.5 requires), the whole lines before it are parsed and the rest is ignored.

---

### User-agent rotation

`WebReader._load_user_agents` reads a JSON array from `src/assets/user_agents.json` at construction time.
`_get_random_user_agent` selects a random entry per request. Strategies that use direct HTTP clients
(`BeautifulSoupStrategy`, `TrafilaturaStrategy`) inject this random User-Agent unless a saved session for the
domain already specifies which User-Agent was used to acquire the clearance cookie (mixing User-Agents with a
`cf_clearance` cookie causes Cloudflare challenges to replay).

---

### Compat patches

Earlier revisions carried a runtime patch, `src/config/compat.py:apply_compatibility_patches()`, called at the
very top of `src/main.py` before any heavy imports. It injected a `DATA_FILES` attribute onto
`browserforge.download` when the attribute was missing, guarding against a version mismatch: `crawlee` (1.3.1)
expects `browserforge` to expose `DATA_FILES`, and `browserforge` releases from 1.2.4 onward removed it.

The pinned dependency in `pyproject.toml`, `browserforge==1.2.3`, already carries `DATA_FILES`, so the patch's
guard condition was always false and the shim never ran. The patch and its test were removed.

The incompatibility itself has not gone away. It is now handled entirely by the version pin. `browserforge`
must stay at 1.2.3 until `crawlee` is upgraded to a version that no longer expects `DATA_FILES`. Bumping
`browserforge` past 1.2.3 on its own breaks the crawler.
