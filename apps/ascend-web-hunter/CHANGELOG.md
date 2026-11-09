# Changelog: ascend-web-hunter

All notable changes to the ascend-web-hunter project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/). Newest entry on top; the topmost
`## [x.y.z]` version is the current one. The release workflow reads it for the image tag
and to guard against re-publishing an already-released version, so keep it at the top and
bump it before every release. The `version` in `pyproject.toml` is a cosmetic label the
release workflow does not read; if the two ever disagree, this file wins for release
purposes.

## [0.0.15] - <release date>

### Added
- Polling crawl jobs (`POST /api/v1/crawl/jobs`, status, list, cancel, plus the `crawl_submit`,
  `crawl_job_status`, `crawl_list_jobs` and `crawl_cancel_job` MCP tools) over a shared Redis
  frontier, recorded as ADR-019 (design D14): several instances share one crawl through Lua claim
  scripts with per-domain politeness, results land in Floci under `tenant/<tenantId>/`, recrawls
  copy unchanged pages forward server-side.
- `DELETE /api/v2/session/interventions/{flow_id}` and the MCP tool `session_cancel_intervention`
  close one NoVNC window (`204`, or `404 flow_not_found`).
- `last_window` in the session status answer, on REST and MCP.
- Ctrl+V (Cmd+V on a Mac), or a paste on a phone, on the NoVNC page types the viewer's clipboard text into the remote browser as key presses through `novnc/paste-clipboard.js`, which the image adds to noVNC at build time. A newline is a real Return key, so multi-line text pasted into a one-line field can submit the form, and a browser tab opened before an update needs a reload.
- A paste above 10000 characters on the NoVNC page is refused with a status message before any key is sent, because up to four windows share one display and the remaining keys could land in another window.
- The startup banner shows one External services row each for docling-serve, ascend-ocr and ascend-audio-scribe, saying whether its `/health` answers or that the route is off, and none of them is a `/ready` probe.
- `OCR_DELETE_DRAIN_SECONDS` (default `5`). Shutdown now waits up to that many seconds for the background ascend-ocr job deletes, cancels the rest and closes the shared HTTP client of the document routes.
- `READ_RESPONSE_MAX_BYTES` (default `52428800`) limits one page answer of the fast read tiers, on the wire bytes and on the inflated bytes alike. A value below `1` is refused at startup.

### Changed
- Unit tests run on fakeredis, an in-memory Redis, so they need no running Redis and parallel runs
  no longer delete each other's keys.
- Spans carry the package version as `service.version`, and compose no longer writes it.
- The development compose file reads `EXTRACTION_LLM_API_KEY` from `.env` first, where it used to pass `MINIMAX_API_KEY` alone.
- The standalone deployment no longer requires `VNC_PASSWORD`. Unset means the NoVNC desktop accepts any client and the container logs a warning at boot, as in the development stack.
- The development compose file gives the object store the local Floci keys.
- The `redis` and `ngrok` image digests are updated.
- Browser requests reuse pinned connections.
- The read cache purge tests that need a real Redis moved to tests/integration and run against the
  local Redis, database 15.
- The three browser tiers share one module, `src/reader/strategies/browser_read.py`, for the navigation, the poll, the render and the verdict, and keep only their own browser launch, context and protections.
- A selector recipe is written with `SET` and an expiry instead of the `SETEX` command redis-py 8 deprecates.
- Crawl jobs ignore the rules of robots.txt unless the caller sends `respect_robots` true, by owner decision. `respect_robots` now defaults to false on `POST /api/v1/crawl/jobs` and on the MCP tool `crawl_submit`, and false is accepted for every site, so the setting `CRAWL_ROBOTS_OPT_OUT_DOMAINS` is removed. A job that ignores the rules skips no page for them and applies no `Crawl-delay`, and it still fetches robots.txt once per origin to use the sitemaps it names. A robots.txt or sitemap that cannot be loaded is logged and does not stop the job reading its pages. `CRAWL_DEFAULT_DELAY_SECONDS` applies to every job. A caller who sends true gets the robots.txt behaviour as before.
- `brotli==1.2.1` and `zstandard==0.25.0` are declared dependencies, so a page or file sent with the `br` or `zstd` coding is inflated in Python. `brotli` was not installed before, and `zstandard` came only through `fpgen`.

### Removed
- The unused `requirements.txt`.

### Fixed
- The `vnc_url` of an intervention window carries the service version and `vnc.html` loads the paste script by a hash of its content, so a browser cannot keep running a saved page after an update.
- Ctrl+V on the NoVNC page now types the viewer's text as key events through `novnc/paste-clipboard.js`, so Polish letters and other text above Latin-1 arrive unchanged. The clipboard path it replaced corrupted those letters, served the previous value on every second paste into Chromium and lost a paste made before x11vnc created its selection window.
- Right Ctrl+V on the NoVNC page releases and restores the right Control key, so the text no longer arrives as Ctrl+letter and no Control key stays held down.
- A Chromium page load is forwarded with explicit headers, which changes the header order on the wire, and that made Reddit serve its page to the browser tiers instead of a reCAPTCHA. Chromium still sends `pragma` and `cache-control`, because any route makes the driver turn the cache off and a route cannot change those two headers.
- The `discarding data: None` warning of `trafilatura.core` no longer fills the log.
- A browser tier that clears a Cloudflare challenge now saves the clearance, so the next read of the site reaches the page without solving it again.
- `4a-patchright` keeps the user agent of its own browser unless a stored session names one, so a Cloudflare challenge that clears by itself no longer ends in a 428 and a NoVNC link.
- A refused navigation of a sub-frame no longer fails the read with `unsafe_uri`. It is aborted, the frame loads nothing and the page is still returned, on every browser tier and on the screenshot path. A third-party frame on a blocked host, such as `li.protechts.net` resolving to `0.0.0.0`, used to end the whole read of a public page. A refused navigation of the main frame, by address, by redirect or by script, still answers `unsafe_uri`.
- Closing a NoVNC window no longer logs `Future exception was never retrieved` or leaves work running. The browser calls of a window run in a task of their own that has ended before the browser closes, so Playwright drops a call still in flight instead of failing it after nobody waits for it. The browser now closes before the Playwright driver stops, which fires the context close that ends the pinned curl sessions, and a window closed while the driver is still starting waits for the start and stops that driver.
- A browser request whose page or browser went away first no longer leaves its Playwright route dispatch pending, which logged `Task was destroyed but it is pending`, and is logged at debug level instead of as a failed fetch. The route is handed back with `route.fallback`, only when the abort itself reports the target gone.
- A NoVNC captcha window no longer ends as solved on a clearance cookie it opened with. The stored session of an earlier window carried `cf_clearance` into the new window, so its first poll declared the wall solved.
- A NoVNC captcha window counts as solved only on an accepted page verdict. A `cf_clearance` cookie alone no longer ends the window or saves the session, because Cloudflare set one about 125 seconds in with nobody clicking, the page stayed its 403 challenge, and the cookie opened nothing when it was reused.
- A refused navigation of a popup the page opened no longer fails the read with `unsafe_uri`. It is aborted and the page is still returned. A refused navigation of the main frame of the page being read still answers `unsafe_uri`.
- A popup opened straight to an address loads again, through the same address check and pinned tunnel as every other request. Its first navigation has no frame yet, and reading the frame used to abort it, so a login popup never opened.
- The redirect hop budget no longer restarts when the browser asks for the next hop under a rewritten address, such as a default port, encoded dot segments or a non-ASCII host name.
- The debug line for a failed redirect hop navigation no longer carries the query of the address.
- A crawl job no longer lets a robots.txt build millions of rule objects. A file whose user-agent lines times its other lines exceeds the new `CRAWL_ROBOTS_MAX_RULES` (default `1000000`) is not parsed and disallows every page of its origin. A byte-order mark at the start of a robots.txt no longer hides its first group.
- A `Crawl-delay` too large for an integer no longer aborts the worker sweep. The new `CRAWL_MAX_DELAY_SECONDS` (default `60`) cuts the delay, and one failing job no longer stops the jobs after it.
- robots.txt rules and `Crawl-delay` are read for the agent `ascend-web-hunter-crawl`, so a group naming the crawler applies.
- A robots.txt whose host does not resolve, or that answers later than the new `CRAWL_ROBOTS_TIMEOUT_SECONDS` (default `30`), counts as unreachable. It disallows every page of its origin.
- An instance that did not end a job drops the parsed rules and sitemap state of that job on its next sweep. The parsed files are limited by the new `CRAWL_ROBOTS_CACHE_MAX_ORIGINS` (default `256`) with least recently used eviction.
- A page skipped for robots.txt no longer spends page budget. The job status answer holds the new count `robots_skipped`, apart from `failed`.
- Sitemaps are parsed as a stream with expat. A sitemap with a DOCTYPE yields no addresses, an address longer than the longest allowed URL is dropped, parsing stops at the address limit, nested sitemaps waiting never outnumber the documents left, and the event loop gets a turn during large files. Gzip inflation no longer copies the remaining input at every step.
- `CRAWL_SITEMAP_MAX_DOCUMENTS` and the addresses a sitemap queues are counted per job in each instance, not per origin, so many subdomains do not multiply them.
- With `same_domain_only` true a sitemap on another registrable domain is dropped, and a sitemap on another registrable domain than the robots.txt that named it is fetched with no stored session.
- Sitemap work of one page stops at the new `CRAWL_SITEMAP_TIMEOUT_SECONDS` (default `60`), is logged and the page is still read. Startup refuses a value at or above `CRAWL_CLAIM_LEASE_SECONDS`.
- Crawl warnings no longer log a page address with its query or an exception text with a query.
- A file that declares more than `DOCUMENT_MAX_BYTES` is now refused for its size when the server closes without sending a body. curl failed that transfer with error 18 before the declared length was read, so the file counted as a failed download.
- A direct read of a document refused for its size now ends at once with HTTP 200, `reason` `routing_error` and `routing_error` `file_too_large`. It used to fall through the HTML tiers, each fetching the file again, and ended in the human tier with a 428. A page whose main link is such a file still keeps its own text with a `routing_error`, and every other routing failure still falls back to the HTML tiers.
- A NoVNC window whose page never loaded no longer resolves and saves nothing. The monitor judged the browser's error page after a failed navigation, took it for a solved captcha and stored a session for about 14 days. The window now stays open until the human reloads a page, which is judged as usual, or until it times out with the outcome `timeout`.
- The image route reads the OCR result from `OBJECT_STORE_S3_ENDPOINT`. It still accepts only an address on
  `OBJECT_STORE_S3_PUBLIC_ENDPOINT`, then sends the same path and query to the container-side address with the signed
  host and port in the `Host` header and follows no redirect. Inside the container `localhost` was the container itself,
  so the route answered `result_failed` in the default stack.
- A stored crawl job with an old bad profile now reads as not found, is skipped by the tenant list and is removed by the
  worker, where it used to answer `400` and be logged on every sweep.
- A bad profile on MCP no longer writes an ERROR line with a traceback. The tool error and the REST body are unchanged.
- The `5-crawlee_adaptive` tier judges a 403, 429 or 503 answer itself. Crawlee took a 403 or 429 for a blocked
  session and a 503 for a server error before the request handler ran, then fetched the page again (16 fetches of
  one 403 wall page in place of one), and the read counted no crawlee verdict and failed with
  `502 extraction_failed`. Crawlee's own block handling is now off and these statuses reach the handler once, so
  the read records one verdict under `crawlee` and a wall raises the challenge exception and escalates.
- A NoVNC window judges each check with the status and headers of the latest main-frame response of its page. The
  checks used status 200 and no headers, so a wall known only by its `cf-mitigated: challenge` header ended the
  window with the verdict `no_content` instead of `wall`.
- The crawl workers of one instance share one robots.txt fetch per job and origin, so the first job no longer fetches `/robots.txt` once per worker task (`CRAWL_WORKER_CONCURRENCY`). A fetch that is cancelled or raises is not kept, and the next waiting worker fetches again.
- The development compose file falls back to `MINIMAX_API_KEY` when `EXTRACTION_LLM_API_KEY` is unset, so a `.env` that holds only `MINIMAX_API_KEY` keeps schema extraction working.
- The `5-crawlee_adaptive` tier reads a URL again on every call. Each read now opens its own
  in-memory Crawlee request queue and drops it when the crawl ends, because the shared default
  queue on disk came back with the URL already handled, so the crawl processed zero requests and
  answered an empty page. The reader treats an empty page as "escalate", so a navigation the guard
  refused (the 302 to a non-allowlisted host) could open a NoVNC window instead of answering
  `400 unsafe_uri`. A crawl that handles no request now raises `ExtractionFailedError`
  (`502 extraction_failed`) on both the read and the read-with-links path, and the tier always
  takes the browser path, where the navigation guard is installed, never the unguarded static
  sub-crawler.
- The startup banner's REST endpoints section lists the routes the service serves. It named
  `GET /v1/search`, `GET /v1/read` and `POST /v2/search`, which do not exist, and now prints one
  line per route of the REST routers the app mounts, built from the same router tuple, so the list
  cannot drift from the OpenAPI document again.
- The `text` output format and the `content` field of the `structured` format are plain text on
  every tier when readability-lxml wins the ensemble. Both returned readability's HTML markup
  (`<html><body><div><body id="readabilityBody">...`), and both now return the same text, one line
  per block element with tags removed, entities decoded and script and style text left out, the
  same shape trafilatura returns. The ensemble still scores readability's HTML, so the winner is
  unchanged, and the content validator now counts the visible words instead of tokens with markup
  attached.
- A read of a URL whose redirect the fetch guard refuses sends the first request to the site once.
  The `1-beautifulsoup` and `2-trafilatura` tiers answered the refusal with an empty page, so the
  ladder moved to the next tier and fetched the same URL again (three requests from a read starting
  at `1-beautifulsoup`, two from `2-trafilatura`). Both tiers now end the read with
  `400 unsafe_uri` at once. Crawl jobs still read a refused robots.txt or sitemap redirect as an
  absent file. The `5-crawlee_adaptive` tier retried a refused navigation three times, and now stops
  the crawl after the first refusal. Each crawl runs one task at a time (it reads one URL), so no
  second worker picks up the retry before the stop is seen. Other navigation failures keep
  Crawlee's retries.
- The read cache purge subscriber keeps its subscription while the channel is quiet. redis-py's
  5-second socket timeout ended every quiet listen as a lost connection, so each container
  reconnected about every 10 seconds and dropped its whole read cache each time. The subscriber now
  waits for messages with its own timeout, which answers "no message" instead of an error. A real
  connection loss still reconnects and drops the cache once, and its warning now carries the
  exception.
- The `6-novnc` captcha monitor counts a flow as solved by a `cf_clearance` cookie only when the
  cookie's domain matches the host being read. A leading dot covers the domain and its subdomains,
  a domain without one covers that host alone. A clearance cookie of another site no longer ends
  the flow and saves the session.
- A browser request whose fetch fails inside the guarded route handler is aborted. An unreachable
  address (`ENETUNREACH`, `EHOSTUNREACH`) aborts with `addressunreachable`, any other Playwright or
  Patchright error (a closed page, a certificate error) with `failed`, and the failure is logged as
  one warning naming the URL and the error. The handler raised instead, which left the route
  unanswered and logged an "Error occurred in event listener" traceback. An abort on a page that is
  already closed no longer raises.
- Gzip sitemaps are recognised by their `1f 8b` bytes.
- A login stored only in localStorage counts as a saved login, is restored by the browser tiers,
  and is accepted by session import.
- `challenge_verdicts_total`, `challenge_score` and `challenge_signals_fired_total` record a NoVNC
  window once, from its last check.
- Browser tiers show a redirected page at its final address, with the right cookie domains and
  form-post methods.
- `link_filter` is part of the read cache key.
- Search result titles and snippets, and annotated link text, keep the spaces around inline markup
  such as SearXNG highlight spans, with no double spaces.
- Every read tier now applies one login title rule: a page whose title matches a login title pattern is a login wall only when it has no rich content (the `rich_content` signal, `CHALLENGE_RICH_CONTENT_WORDS` extracted words). The browser tiers `4-playwright_stealth`, `4a-patchright` and `4b-camoufox` returned a "Sign in" page with an email-first form as content and now escalate it with the intervention type `login`. The static tiers `1-beautifulsoup`, `2-trafilatura` and `5-crawlee_adaptive` no longer treat an article such as "Login - Wikipedia" as a login wall.
- A crawl job no longer sends a HEAD request after it writes a new page. When no conditional request supplied them, the recrawl state keeps the `ETag` and `Last-Modified` of the GET answer the page was read from, on every tier, so they match the stored content, and a redirected page keeps the validators of its final answer.
- A crawl job with an `output_format` other than `text` reads each page once. It read the page for its links and then a second time for the formatted content, so the site got two requests for one page and the stored content came from the second request while the stored `ETag` and `Last-Modified` came from the first. One tier read now gives the links, the formatted content and the validators, and a `screenshot` crawl takes all three from its one browser capture.
- The 4-playwright_stealth, 4a-patchright and 4b-camoufox tiers count one verdict, one score and one set of signals per read in `challenge_verdicts_total`, `challenge_score` and `challenge_signals_fired_total`, the check that decided the read, instead of one for every check while they waited for a wall to clear and a second one for a content page. A read refused before navigation because its address is a login address now counts its verdict too.
- The orchestrator's second look at a tier's page counts one verdict, one score and one set of signals under the tier `reader` for every page it judges. It counted the score and the signals of a rejected page twice and the verdict of an accepted page never.
- A screenshot read through `4-playwright_stealth`, `4a-patchright` or `4b-camoufox` is now judged by the tier and counts one verdict under the tier's name. A login wall or a wall escalates to the next tier before a PNG is taken.
- A page larger than `CHALLENGE_SHAPE_MAX_BYTES` is no longer a login wall only because its title holds a login word. The shape signals, `rich_content` among them, never run on such a page, so every large article with a title such as "Log in to read more" was a login wall. A scored wall of type `login` is still a login wall at any size.
- A browser read that checked its page and then failed, in the wait, the scroll, the last `page.content()` or the judgement of the rendered page, now counts the verdict of its last check once. It counted no verdict.
- Schema extraction stores a selector recipe only when its selectors, replayed on the page they came from, give exactly the values the model returned. The model is now given the cleaned markup of the page (the title and the body, without scripts, styles, comments and the attributes a selector does not need, cut to `EXTRACTION_LLM_MAX_INPUT_CHARS`) instead of its main text, so it can name selectors that exist. It used to guess selectors that matched nothing, so every later read failed the replay, deleted the recipe and called the model again.
- Crawl recrawls now store the ETag and Last-Modified of the same response as the stored content: a new or unchanged page takes the validators of its own read, and a 304 updates each validator it carries and keeps the other. The conditional probe streams every hop and stops it without reading a body, sends the stored cookies and user agent of the job's profile, and logs a failed probe without the URL's userinfo.
- A crawl job reads every page from the site itself. It used to read through the in-process read cache, so a job could report a page as `fetched` that another tenant's read had put in the cache up to `READ_CACHE_TTL_SECONDS` earlier. Crawl reads now neither read from nor write to that cache.
- A crawl job reads robots.txt as RFC 9309 says. A 4xx answer other than 429 allows every page of the origin. A 5xx answer, a 429, or a network or connection error disallows every page of the origin for the rest of the job, where it used to allow every page. A page that robots.txt disallows is listed in `pages.ndjson` with `status` `skipped` and `reason` `robots_disallowed`.
- A crawl job reads at most `CRAWL_ROBOTS_MAX_BYTES` (default `512000`, the 500 KiB RFC 9309 requires) of one robots.txt and stops the download there. It used to read the whole file into memory, so a site could send a huge robots.txt. The whole lines before the cap are parsed and the rest is ignored.
- The robots.txt and sitemap fetches of a crawl job carry the cookies and user agent of the job's `profile`, where they used the default profile, and the first robots.txt fetch of an origin goes through `CRAWL_PROXY_URL` like every other crawl fetch, where it left from the instance's own address.
- Every instance that sees a crawl job ended or gone forgets its robots.txt verdicts, where only the instance that finished the job did, and a robots.txt fetch still running when its job ends keeps nothing. A robots.txt address with userinfo is logged without it.
- A read that a site redirects to its login page is now a login wall in every read tier and the NoVNC monitor, and answers 428 with the intervention type `login`. Reading `https://old.reddit.com/r/programming/` ended on `https://old.reddit.com/login/`, a page titled "Welcome to Reddit" that scored below the threshold, and was returned as content. A read whose final address has a login path segment (`login`, `log-in`, `signin`, `sign-in` or `logon`, from the new `login_path_segments` list in `challenge_dictionary.json`) that the requested address does not have is now a login wall at any size and whatever its title or score, when a second login sign holds: a return address in the query (`next`, `dest`, `return_to`, `returnTo`, `redirect`, `redirect_uri`, `continue` or `from`, from the new `login_return_parameters` list) or a password input on the page. A redirect to a help page such as `/en/login/reset-password` stays content.
- A read that lands on a login page this way no longer runs every remaining tier into the same login page. It goes straight to `6-novnc` and answers 428 with the intervention type `login`, and a crawl read, which may not ask a human, ends at once with `reason` `login_required`. The NoVNC monitor counts such a page, and an address that matches a login redirect pattern, as a login page until the window has seen a login wall, and after that only on a login address the window already saw as a wall, so a finished login that ends on a callback such as `/login/callback?next=...` or `/signin/callback` is saved.
- Reddit's 403 page "You've been blocked by network security" is now a wall and escalates. The challenge corpus held it as a 403 with real content. The new body phrase `generic_blocked_by_network_security` catches it, and the phrase and structure checks now read the page after emptying inline style bodies and cutting inline `data:` images, which pushed the page's text beyond the first `CHALLENGE_DETECTION_MAX_BYTES`.
- An image read deletes its ascend-ocr job (`DELETE /v1/ocr/jobs/{job_id}`) in the background once it has its answer: the OCR text, a failed or cancelled job, a poll that runs out of `OCR_ROUTE_TIMEOUT_SECONDS`, or a cancelled read. It never deleted the job, so the record and the stored page text stayed in ascend-ocr for `OCR_JOB_RETENTION_SECONDS` (default `3600`). The read answers as soon as the OCR text is in hand, so a caller never waits up to `OCR_ROUTE_TIMEOUT_SECONDS` for the delete. A delete answered 404 is accepted, any other failed delete is logged as a warning naming the job identifier and never fails the read.
- A NoVNC login window no longer marks itself resolved while the login page still shows. On `https://old.reddit.com/login/?reason=lor2&dest=...` the window saved `session:reddit.com:default` about 8 seconds after it opened, with nobody logged in, because a cookie Reddit set by itself counted as a new login. After the first login wall, an address with the origin and path of a login address the window already saw as a wall is still a login page, and a password input inside an open shadow root, as in Reddit's web component login form, now makes a login page too.
- A read through the `5-crawlee_adaptive` tier no longer changes the service logging. Crawlee replaced the root logger's handler with its own colored one when the tier built its crawler, so every later log line of the process, access lines included, lost the JSON format, `correlation_id` and `trace_id`. The tier now turns Crawlee's logging setup off, and Crawlee's own records go through the service's handler.
- The session status answers `last_window` null once the Redis record `novnc_window_result:<domain>:<profile>` is deleted. The container answered from its own copy whenever Redis had no record, and now reads its own copy only when Redis is not configured or the Redis read fails.
- The NoVNC desktop no longer leaves a dead `sh` process under fluxbox at boot. The fluxbox style called `fbsetbg` to set its wallpaper, found no wallpaper tool, tried to start the missing `xmessage`, and supervisord logged `reaped unknown pid ... (exit status 127)`. The image now sets `background: unset` in `/etc/X11/fluxbox/overlay`, so styles no longer set a background, and the build fails if that line is missing. The value is `unset` and not `none`, because on first load fluxbox 1.3.7 still runs `fbsetbg -z` for `none`, which calls the missing `xmessage` and leaves the dead `sh`.
- A read cancelled while the image is being sent to ascend-ocr now lets the send finish and deletes the job it created. The spool file is removed only after the upload ends, which avoids a `PermissionError` on Windows.
- A crawl page whose read failed with a reason, for example `login_required`, now has a line in `pages.ndjson` with `status` `failed` and that reason.
- `SESSION_DEFAULT_PROFILE` is checked at startup and must be 1 to 64 letters, digits, `_` or `-`.
- A read that ended on a login page after the page already scored as a login wall is now marked as a login landing. The ladder stops at the login page, and a crawl read ends as `login_required`.
- The NoVNC window now counts only visible password inputs. A finished login whose page keeps a hidden password field now resolves.
- The `5-crawlee_adaptive` tier reads the status and all headers, `set-cookie` included, of the last main frame response, and no longer hides a failed header read as a 200.
- A window result whose Redis write failed is still shown by the session status in the same container, until a later write succeeds.
- The human NoVNC window launches Patchright instead of stock Playwright, the same way as the `4a-patchright` tier.
- The human NoVNC window leaves through `PROXY_URL` like a read, and both compose files now pass `PROXY_URL` to the container.
- A later navigation refused on a page judged a wall or without content now answers `unsafe_uri` on every browser tier and on screenshots.
- A NoVNC window whose main frame is sent to a refused address closes at once with the outcome `unsafe_uri` in `last_window`.
- A rendered page whose markup is above `BROWSER_RESPONSE_MAX_BYTES` fails that tier without being copied out of the browser.
- A temporary lookup failure no longer turns later good reads of that host into `unsafe_uri`.
- New `BROWSER_TUNNEL_MAX_CONNECTIONS` (default `256`). A browser connection above it answers 503.
- `FETCH_MAX_REDIRECT_HOPS` no longer limits browser tiers. A browser follows redirects up to its own limit and each hop is still checked.
- A page answered 200 whose only challenge evidence is a vendor's script or presence is no longer judged a wall, through the new `served_page` guard signal and `CHALLENGE_WEIGHT_SERVED_PAGE` (default `-30`). The cleared Cloudflare page is in the corpus.
- The standalone deployment turns the PDF, image and audio routes off by default, because it runs none of those services. `DOCLING_SERVE_URL`, `ASCEND_OCR_URL` and `AUDIO_SCRIBE_URL` are empty there unless set in `.env`.
- The normal page read of the fast tiers no longer inflates in libcurl. It streams with libcurl decoding off, keeps the impersonated request headers, inflates gzip, deflate, brotli and zstd in Python and stops at `READ_RESPONSE_MAX_BYTES`, so a compression bomb ends that tier as a failure with a warning.
- A routed PDF, image or audio download no longer inflates in libcurl. A compressed body is inflated in Python and a body that inflates past `DOCUMENT_MAX_BYTES` raises `DocumentTooLargeError`.
- A robots.txt success that arrives compressed although `identity` was asked for is inflated within `CRAWL_ROBOTS_MAX_BYTES`, where it counted as unreachable. A success that cannot be decoded still counts as unreachable.
- A `.xml.gz` sitemap also sent with `Content-Encoding: gzip` is unpacked twice, the Content-Encoding layer and then the file layer, both within `CRAWL_SITEMAP_MAX_BYTES`, where it was unpacked once and failed as broken.
- Stored login cookies no longer cross between two sites under one private suffix such as `foo.github.io` and `bar.github.io`, because the redirect cookie check now uses the private suffix list. The Redis session keys are unchanged.
- The parse of a robots.txt that passes `CRAWL_ROBOTS_MAX_RULES` runs in a worker thread, where it held the event loop for up to 1.62 s.
- The crawl warning about a failed recrawl write carries no query string, in the page address or in the exception text.
- A server-declared charset can no longer select a slow or unsafe text codec. Page reads use an allowlist of web charsets and sitemap reads are always UTF-8.
- Capped sitemap and robots.txt fetches no longer inflate in libcurl, where a 64 KiB capped read reached 269 MB of memory on a compression bomb.
- Stored login cookies go only to redirect hops on the registrable domain of the first URL, and only over https when the first URL was https.
- A redirect answer is stopped before the next hop is sent, so its body is not read.
- A robots.txt whose lines end only in carriage returns is no longer emptied at the size cap.
- robots.txt log lines carry no query string.
- A streamed read now has a total deadline of `EXTRACT_TIMEOUT` on the curl tiers, the browser guard delivery and the recrawl probe, so a body sent one byte at a time cannot hold a reader.
- A crawl request that lists a seed twice queues it once, so two claims of the same page no longer overlap.
- Page reads accept the Korean labels `ks_c_5601-1987`, `euc_kr`, `cp949`, `windows-949`, plus `iso-8859-11` and the `iso_8859-1`, `iso_8859-2` and `iso8859-N` spellings of the charsets already allowed.
- An unreadable `Content-Length` counts as absent, and a request the browser guard cannot serve is aborted and logged and no longer raises inside the route handler.
- The file download and the browser guard stop a redirect answer before they send the next hop.
- A body labelled gzip that holds a zlib stream is now inflated.
- Stopping a streamed answer waits at most one second, so a stuck close cannot hold the reader.
- The rule count of a robots.txt is now an exact upper bound, with starred agent names, `$` rules and allowed index pages counted as the parser expands them.
- `CRAWL_ROBOTS_CACHE_MAX_RULES` (default `2000000`) limits the rule objects the kept robots.txt files of one instance hold together.
- The password field check of the challenge detector reads only the first `CHALLENGE_SHAPE_MAX_BYTES` of a page.
- A sitemap with a start tag so long that one parse step delivers no `<` while inside it yields nothing and spends nothing, and addresses completed by the last parse step are no longer lost.
- `CRAWL_ROBOTS_SKIP_FACTOR` (default `10`) ends a job once its pages skipped for robots.txt reach `page_budget` times that number.
- A cancelled file download removes its partial file.
- A compressed file that stops before its content coding ends is a failed download. Page reads still accept a truncated body.
- The challenge verdict runs in a worker thread, because `trafilatura.extract` took up to 3.7 s on a 500 KB hostile page.
- A NoVNC poll no longer calls `context.storage_state()` on every pass, which opened a helper tab for each cross-origin frame every 5 seconds and made the windows flicker and lose focus. A poll reads cookies and live site frames, a login window reads the whole state once per address, and a save still reads the whole state.
- `DOCUMENT_FETCH_TIMEOUT_SECONDS` (default `300`) limits one routed PDF, image or audio download, so a server that sends its body one byte at a time ends in `download_failed`, and a written file the caller does not receive is deleted.

### Security
- A read URL is limited to the 2083 characters REST reads already have (pydantic `HttpUrl`) on every MCP tool that takes an
  address and on crawl seeds. A longer one is refused with `validation`.
- A pydantic validation error no longer puts the refused input in its detail, in the tool error or in the log. The detail
  is built from the field and the message only.
- Read addresses in logs show scheme, host, port and path only: never the query, the fragment, user info or path
  parameters after `;`. This covers the document routes, the NoVNC lines, the verdict line, the byte fetch, the read
  tiers, the session lines and the browser guard. The verdict line keeps the same address at each tier.
- The byte fetch failure line prints the exception type only. The strategy failure lines, the curl_cffi failure line, the
  screenshot failure line and the crawl conditional probe line keep the reason, with every address in the text cut to
  scheme, host, port and path and the text capped at 1000 characters.
- The startup banner shows the Redis address without its query, and the crawl result expiry status prints the exception
  type only.
- `is_login_required` reads title elements in one forward pass, so a page of many unclosed `<title>` tags can no longer
  block the service.
- Browser tiers reach the network only through a local pinned tunnel (`src/reader/pinned_tunnel.py`), which resolves a
  host once, refuses what the SSRF guard refuses and connects only to the checked address, which closes DNS rebinding
  and leaves the browser its own TLS. A Patchright read in a visible window now passes a Cloudflare challenge that the
  earlier pinned fetch kept it on. WebSockets are closed. New settings `BROWSER_RESPONSE_MAX_BYTES` (per connection, on the bytes a site
  sends), `BROWSER_TUNNEL_CONNECT_TIMEOUT_SECONDS` and `BROWSER_TUNNEL_IDLE_TIMEOUT_SECONDS`.
- Document route warnings no longer print the error text. They name the error type and, for an HTTP
  error, the status code, so a password in a service address and the signature of a presigned result
  address never reach the log. The document address is logged without its user part.
- The OCR result is read as a stream capped at `DOCUMENT_MAX_BYTES`. A larger result is the routing
  error `result_failed`.
- A job id from ascend-ocr must be 22 letters, digits, `_` or `-` before it is put into a request
  path. Any other answer is the routing error `submit_failed`.
- The startup banner debug lines no longer print a password or the error text. A document route
  address with a user part is now checked without that part, so its row no longer always shows
  `FAILED`.
- x11vnc now listens on the loopback address only. Other containers on the network can no longer
  reach port 5900. The desktop is reached through websockify on port 7900.
- The challenge detector now reads style bodies and password inputs in one linear pass. Very large
  or broken pages can no longer block the service for minutes.
- The NoVNC log line for a finished login shows the scheme, host and path only. One-time codes and
  tokens in the query or fragment are never logged.
- Read logs, verdict logs, session logs and the `5-crawlee_adaptive` tier error text no longer show
  user info from the read address.
- The 409 busy answer and the open window list show another caller's address as scheme, host and
  path only.
- Sessions are keyed by the real host of the address, and every session REST call and MCP tool
  refuses an address with user info.
- The read cache key is now built from separate fields, so two different reads can no longer share
  one cache entry.
- Every REST field and MCP tool parameter that takes a profile checks it against the limit
  `[A-Za-z0-9_-]{1,64}`, and a bad profile answers `invalid_profile`. An empty profile means the default.
- The OCR result is fetched only from the address in OBJECT_STORE_S3_PUBLIC_ENDPOINT. Any other address is the routing error result_failed.
- The httpx, httpx2 and httpcore loggers stay at WARNING, so request addresses with a password or a signature never reach the log.

## [0.0.14] - <release date>

### Added
- `POST /api/v2/web/session/import` stores a captured Playwright storage state for the URL's
  registrable domain under `session:{domain}:{profile}` with provenance value `import`, dropping
  cookies of other domains and purging the domain read cache on every instance, so the next read
  uses the new session. Refusals are problem bodies with codes `invalid_profile` and
  `no_cookies_for_domain`. The e2e harness `seed_authenticated_session.py` now seeds over HTTP
  through this endpoint and no longer imports service code (design D5).

## [0.0.13] - <release date>

### Removed
- The `3-flaresolverr` tier, its strategy, its `FLARESOLVERR_URL` and `FLARESOLVERR_ENABLED`
  settings, its `flaresolverr` container in both compose files, and its readiness probes, banner
  entry, circuit breaker, proxy branch and cookie producer constant. Passing `3-flaresolverr`
  is refused like any value outside the allowed set, and no future tier reuses the name or the
  number 3 (ADR-018).

## [0.0.12] - <release date>

### Added
- Structured extraction on `output_format` `structured`: JSON-LD, OpenGraph and microdata parsed by
  `extruct` into a `metadata` object; a parse error leaves it empty and never fails the read.
- Scored ensemble: trafilatura and readability-lxml both run on every extraction and the higher scoring
  result wins, ties to trafilatura (ADR-016, superseding the ADR-009 recall pass).
- Schema-guided extraction on `output_format` `schema` with `extraction_schema`, produced by a
  configurable OpenAI-compatible endpoint (`EXTRACTION_LLM_*`), with per-domain self-healing CSS
  selector recipes in Redis (ADR-017).
- Non-HTML routing: PDFs convert through docling-serve, images read through the ascend-ocr job API and
  audio transcribes through ascend-audio-scribe, every file fetched by the shared `stream_to_file`
  capped at `DOCUMENT_MAX_BYTES`. A routing failure returns the HTML extraction with a `routing_error`.
- Two more output formats: `tables` (HTML tables as rows) and `screenshot` (base64 PNG from the
  browser tier that served the read). Four new problem codes: `extraction_not_configured`,
  `screenshot_unavailable`, `bad_request` (for `include_links` with any format but `text`) and the
  expected upstream `extraction_failed`.
- Cross-container read-cache purge: clearing a session publishes the domain on the `read_cache_purge`
  Redis channel and every container's subscriber drops that domain's cached reads.

## [0.0.11] - <release date>

### Added
- Two automated browser tiers in the ladder, both free and self-hosted: `4a-patchright` drives a
  patched Chromium through the Patchright drop-in for the Playwright API, and `4b-camoufox` drives a
  hardened Firefox, tried when `4a-patchright` is detected or fails and only while `CAMOUFOX_ENABLED`
  is true (default `true`). The ladder is `1-beautifulsoup`, `2-trafilatura`, `3-flaresolverr` (only
  while enabled), `4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive` and
  `6-novnc`, and both new values are accepted by the REST `tier` field and the MCP `web_read` `tier`
  argument.
- Per-domain tier memory: the tier that last succeeded for a registrable domain is kept in Redis and
  the next read starts there, decaying back to the start of the ladder after `TIER_MEMORY_TTL_SECONDS`
  (default `86400`). A caller-selected `tier` always wins over the memory.
- The guarded route handler every browser tier installs: each page load, redirect hop and subresource
  request is checked against the shared URI guard before the browser connects, and a request that
  fails is blocked (ADR-015, with a dated amendment to ADR-011 listing the two new public values).

### Changed
- FlareSolverr stays for one release behind `FLARESOLVERR_ENABLED` (default `false`). While it is off
  the `3-flaresolverr` tier is skipped by the ladder, a caller that names it gets `409`
  `tier_disabled`, readiness does not probe it, and a session it produced earlier is replayed by the
  browser tiers.
- The two waits `playwright_strategy.py` held as code are settings now, `NETWORKIDLE_POLL_MS`
  (default `1000`) and `SCROLL_PAUSE_MS` (default `200`), read by every browser tier.
- Image size grew from 5.6 GB to 10.4 GB with the two patched browser tiers, measured on
  linux/amd64 on 2026-11-02 by building the commit before this change and the current tree.

## [0.0.10] - <release date>

### Added
- One scored challenge verdict in place of four booleans: `ChallengeDetector.assess(status_code,
  headers, html)` returns a `ChallengeVerdict` carrying the score, every signal that fired with its
  weight, the vendor the signals point at when they point at one, and the intervention type, while
  `is_blocked`, `has_real_content` and `is_content_accepted` keep their names as thin readers of it.
- Wall detection that does not depend on language. The evidence is what a wall cannot translate: a
  definitive vendor response header, vendor script, cookie and header signatures, the HTTP status,
  the shape of the page, and the ratio of extracted words to bytes, links and article structure. A
  page is a wall at `CHALLENGE_SCORE_THRESHOLD` (default `100`) or on a definitive signal, which
  carries twice the threshold so no guard can cancel it, and a page carrying
  `CHALLENGE_RICH_CONTENT_WORDS` of extracted article text is pulled back below the threshold unless
  a definitive signal says otherwise.
- `challenge_dictionary.json` as the one maintained catalogue file, holding each vendor marker and
  each phrase translation with the source it was taken from, so a marker with no source or a
  translation with no provenance fails a test. Phrases are normalised before matching and stay a
  supplement only, sixteen canonical phrases over thirty BCP 47 languages.
- A counter per signal and per verdict, a histogram of scores, and one log line per verdict at or
  above half the threshold carrying the score, the signals, the vendor, the tier and the URL. The
  exception carries the verdict, so the line a tier writes when it escalates says why (ADR-014, with
  a dated amendment to ADR-001).

## [0.0.9] - <release date>

### Added
- Concurrent NoVNC intervention windows. Each flow owns its own Chromium process, browser context,
  page and monitor task, nothing is shared except the X display and the Redis the session store lives
  in, and every launch uses `--remote-debugging-port=0` with `--remote-debugging-address=127.0.0.1`,
  so the operating system assigns a free port and two launches never contend for one.
- `NOVNC_MAX_CONCURRENT_FLOWS` (default `4`) replaces the global single-flow lock. Each window sits at
  its own deterministic cascade position on the shared display, a second request for a site and
  profile that already has a live window joins that window and receives the same `vnc_url` and flow
  identifier, and a flow's lease runs from its own start for `NOVNC_TIMEOUT_SECONDS` plus
  `NOVNC_FLOW_LEASE_GRACE_SECONDS` (default `30.0`), with a sweep every
  `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS` (default `30.0`) that cancels a dead flow and takes its window
  off the display.
- `GET /api/v2/session/interventions` on REST and `session_interventions` on MCP list the live flows
  of every container with their windows and remaining lease. The 428 answer gains `flow_id`, `joined`
  and `window` (slot index and pixel rectangle), and the 409 answer gains `active_flows`,
  `max_concurrent_flows` and a `flows` array, with `holder_url` and `holder_profile` now describing
  the oldest live flow (ADR-013, with a dated amendment to ADR-003).

### Changed
- A 409 is answered only when the cap is reached. A flow that raises, times out, is cancelled or loses
  its browser closes its own browser, frees its own slot and records its own outcome without touching
  a sibling, shutdown cancels every live monitor and waits bounded for each to close, and setting
  `NOVNC_MAX_CONCURRENT_FLOWS` to `1` restores one window at a time without a code change.

## [0.0.8] - <release date>

### Changed
- The service follows the shared library version set through `ascend-python-common==2.0.0`
  (FastAPI 0.147.0, Starlette 1.9.0, uvicorn 0.54.0, FastMCP 4.1.1, MCP SDK 2.3.0,
  httpx2 2.14.0).
- The MCP server reports the service name and version in `initialize`.
- The `/mcp` endpoint accepts only allowed `Host` headers (`ascend-web-hunter,localhost,127.0.0.1`)
  and no `Origin` header; a refused `Host` answers 421, a refused `Origin` answers 403.

## [0.0.7]

### Changed
- The service is built on `ascend-python-common==1.0.0` via `create_service_app`: shared problem bodies, settings
  base, logging, request correlation, tracing, readiness aggregation, rate limiting, security headers, and the
  startup banner frame. `Settings` subclasses `ServiceSettings`; the error registry maps `ValueError` to
  `validation`, `UnsafeUriError` to `unsafe_uri`, and everything unexpected to `internal`.
- REST errors are problem bodies (`application/problem+json`) with `code` and `traceId`. Request validation
  failures answer `400` with code `validation` and an `errors` array sorted by `field`. A refused URL answers
  `400` with code `unsafe_uri`, including URIs with user info. The 428 and 409 answers are problem bodies too:
  code `human_intervention_required` with `intervention_type` and `vnc_url`, and code `novnc_busy` with
  `holder_url`, `holder_profile` and the `Retry-After` header. Unknown paths answer a problem `404` and wrong
  methods a problem `405` with `Allow`. Unexpected failures answer `500` with code `internal` and a fixed generic
  detail.
- MCP refusals are tool errors whose text starts with `<code>: ` (`validation: `, `unsafe_uri: `, `internal: `).
  The MCP status objects (`human_intervention_required`, `novnc_busy`, `session_expired`) are successful tool
  results, not errors, and keep their `status`-keyed shape.
- `/health` answers `{"status": "ok", "service": "ascend-web-hunter", "version": ...}`. `/ready` aggregates the
  `redis`, `searxng`, `flaresolverr`, `searxng_breaker` and `flaresolverr_breaker` probes and answers `200`
  `{"status": "ready", ...}` or `503` `{"status": "not-ready", ...}`.
- Logging comes from the library: `LOG_LEVEL` is honoured, `LOG_FORMAT` selects `json` or `color`, lines start
  with `[ascend-web-hunter]`. `src/config/logging_config.py` and `src/observability/request_context.py` are
  deleted.
- `RATE_LIMIT_DEFAULT` defaults to `1200/minute` on REST routes and MCP tools, with no stricter limit;
  `/health`, `/ready`, `/metrics` and `tools/list` are never limited.
- OpenTelemetry comes from the library (1.45.0 and 0.66b0); the service's own 1.42.1 and 0.63b1 pins are gone.
- The URL guard lives in the library: the REST endpoints and MCP tools call `check_fetch_uri` with the
  `ALLOWED_PRIVATE_HOSTS` policy (empty by default, only an e2e sweep sets it), and the curl_cffi tier follows
  redirects through `follow_guarded_redirects` with address pinning. `is_safe_external_url`, `pin_safe_host`
  and their helpers left `src/validator/url_validator.py`, which keeps `URLValidator` and the `url_validator`
  singleton for the ad blocklist.
- `Dockerfile` installs the library from the `ascend-python-common` named build context before the service; the
   compose service declares `additional_contexts` and sets `LOG_FORMAT=json` and `OTEL_EXPORTER_OTLP_ENDPOINT` with no rate
   limit line, so the code default applies.
- Docs updated: `AGENTS.md`, `README.md`, `docs/configuration.md`, `docs/api-examples.md`, `docs/running.md`,
  arc42 pages 04, 05, 06, 08, 10 and 12, the container diagram, the ADR-003 amendment (428 and 409 body shape
  superseded), and e2e specs 7, 11 and 12 with their Bruno requests and the spec 11 template now asserting `code`.
- The shared library is cut at `1.0.0` now that all four services are migrated. The service pin moves to
  `ascend-python-common==1.0.0`; this entry stays the one version of this change.

### Fixed
- The standalone `docker run` in `docs/running.md` joins the stack network and calls SearXNG by name, with the host gateway mapping for the host's Redis. `fix-linux-docker-host-access`.
- The IDE Docker run configuration sets `SEARXNG_BASE_URL` and `REDIS_URL` and joins the stack network with the host gateway mapping. `fix-linux-docker-host-access`.
- The configuration reference names `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`, `BREAKER_FAILURE_THRESHOLD`, `BREAKER_RECOVERY_TIMEOUT_SECONDS`, `CHALLENGE_CLEAR_WAIT_SECONDS`, `CHALLENGE_DETECTION_MAX_BYTES`, `CHALLENGE_WALL_MAX_BYTES`, `CRAWLEE_MEMORY_MBYTES`, `CRAWLEE_STORAGE_DIR`, `DOMAIN_METRIC_CARDINALITY_CAP`, `NOVNC_COOKIE_SYNC_POLL_SECONDS`, `PROXY_URL`, `READ_CACHE_TTL_SECONDS`, `SESSION_AUTH_TTL_SECONDS`, `SESSION_DEFAULT_PROFILE` and `SESSION_WAF_TTL_SECONDS`. `fix-linux-docker-host-access`.

## [0.0.6] - 2026-10-01

### Fixed
- Dashes in comments, docstrings, test assertion messages, documentation, the architecture decisions, the
  agent skill file, the end-to-end specs, templates and harness, the pyproject.toml lint comments and the
  standalone deployment's .env.example are plain hyphens or commas now. No service code, configuration
  value or log message changed.
- The end-to-end README points at this module's own entry under the service suites of
  docs/E2E_RUN_SCENARIOS.md.

## [0.0.5]

### Changed
- End-to-end spec 11 keeps only the human captcha solve and its capture, and the new automated spec 12
  proves a stored Cloudflare clearance is reused on a second read of the same site.
- End-to-end spec 7 mixed two automated parts with a human captcha part that asserted only that a
  session was saved. The human part is spec 11 now: it reads the democaptcha hCaptcha demo form to
  get the NoVNC intervention, has the human solve it, checks the captured hmt_id cookie, then reads
  the same page again and requires HTTP 200 with status success, so the saved session is proven
  reused and a second 428 is a product defect. Spec 7 keeps the real-world matrix and the saucedemo
  login reuse and is fully automated.

### Fixed
- A stored WAF clearance forced every later read straight to the browser tiers, so a clearance
  FlareSolverr earned was handed to Playwright instead, which a Cloudflare challenge does not
  recognise, and the read ended at the human window. Every session record now names the tier that
  produced it (`produced_by`, written by the FlareSolverr strategy and the NoVNC monitor), and the
  reader replays a FlareSolverr-produced clearance through FlareSolverr first before falling back to
  the browser tiers as before. A record with no producer (written before this change, or by a caller
  that has not adopted the field yet) keeps today's behaviour: browser tiers first. See
  [ADR-010](docs/architecture/decisions/ADR-010-producer-aware-session-replay.md).
- The text reader returned prices and stock lines and no book titles from `https://books.toscrape.com/`:
  trafilatura's default precision pass yielded 319 characters of a page whose plain text is 1851. When the
  precision pass is shorter than `CONTENT_RECALL_FALLBACK_RATIO` (default 0.75) of the page's plain text, a
  second pass now runs with `favor_recall=True` and the longer result is returned, 1143 characters with every
  title on that page. Article pages, measured at 0.90 of the plain text or more, stay on the single pass. The
  derivation is in [ADR-009](docs/architecture/decisions/ADR-009-recall-pass-for-thin-precision-extractions.md).
- End-to-end spec 7 treated a `409` `novnc_busy` answer on a Part 1 row as a verdict, though it only
  means another row's NoVNC intervention still holds the shared browser. The spec, its template and
  the suite README now have the runner wait the response's `Retry-After` seconds and re-run the row,
  up to 3 attempts in total, recording each attempt and each 409 body's `holder_url`, with the row
  failing only on its third 409.
- End-to-end spec 7 ran the Part 1 matrix as a plain folder run, whose console output shows only pass or
  fail per request and never a response body or header, so a `409` `novnc_busy` row's `Retry-After` and
  `holder_url` could not be read without re-running the request by hand. The folder run now writes its
  full results with Bruno's `-o <file> -f json`, the retry rule reads both values from that file and
  re-runs only the busy row's own request file after the wait, and the template's retry line matches.
- End-to-end spec 6 stripped script blocks with a sed flag GNU sed does not have. The Unix form
  uses perl now.
- End-to-end spec 8 reset Redis only, so the in-process read cache spec 3 fills survived into the
  call under test, and its docker cp path did not resolve from the Bruno collection root. The
  reset primes the clear endpoint first, and the path is relative to the collection root.
- End-to-end spec 10 named the default-profile session key while the request sends the
  e2e-establish profile, which the service forwards, so its reset and cleanup never touched the
  key the run created. The spec, its template and the request comment now name the e2e-establish
  key.
- The MCP specs and templates described the session id as a UUID. The value is a 32 character
  hexadecimal id without hyphens, and the wording now says so.
- The PowerShell form of the MCP specs' JSON-body curl.exe blocks failed on pwsh 7.6.5 with a
  nested brace error and HTTP 400. Those blocks pass the body single-quoted now.
- End-to-end specs 8 and 10 still said both mutate the default-profile key. They name the real
  keys now, and state that spec 8's before-and-after scan of session:* is why the two must not run
  together.
- End-to-end spec 1 claimed each rejection returns in under 200 milliseconds. Bruno measured 325
  to 362 milliseconds on 2026-09-10, so the spec states that range and keeps the 2 second gate.
- The MCP tools/list, MCP web_search, read and session-clear Bruno requests asserted less than
  their specs: an envelope with any result or error, any object with a status key, and a clear
  without its cache count. They assert the tool schemas spec 4 lists, the 1 to 3 result entries
  with title, http(s) url and content spec 5 lists, the url, success status, content length and
  canary phrase spec 3 lists, and the four session-clear fields spec 8 lists.
- End-to-end spec 8's own Concurrency section said it was safe to run in parallel with everything
  else in the suite, contradicting that same section's test 10 conflict and the suite README's
  test 3 conflict. It now names both.
- The version in pyproject.toml, AGENTS.md and the constraints document lagged this changelog at
  0.0.3. All three say 0.0.5.
- The development compose file still exported service.version=0.0.3 in OTEL_RESOURCE_ATTRIBUTES.
  It says 0.0.5 now.
- The REDIS_URL default was redis://localhost:6379/0. On a Windows host localhost resolves to IPv6
  first, the asyncio Redis client timed out, and the cookie store fell back to memory without a
  word. The default and every documented example say redis://127.0.0.1:6379/0 now. Both compose
  files set REDIS_URL themselves, so containers are unaffected.
- End-to-end spec 7 Part 3 targeted Google's reCAPTCHA v2 demo, whose script stays in the DOM after
  the solve so the NoVNC monitor could never declare that address cleared, and asserted a
  _GRECAPTCHA cookie that appears on a bare load. Part 3, its template and the Bruno request target
  the democaptcha hCaptcha demo form, and the capture check asserts the hmt_id cookie, which proves
  a human acted in the window and not that the image task was solved.

## [0.0.4]

### Fixed
- Establishing a session persisted nothing. An earlier expiry fix had added a condition requiring
  a page to be seen blocked at least once before the monitor would treat it as cleared, and for a
  site that is never challenged, which is exactly the case session establishment exists for, that
  can never become true. The condition is gone, so an ordinary never-challenged page records a
  session again. A genuinely blocked page is still not treated as accepted.
- A session record with an empty cookie jar was reported as a live authenticated session with a
  fortnight of life remaining, because an empty jar carries no expiry and the remaining time fell
  back to the configured ceiling. One such record pushed every later read of that domain onto the
  heavier browser tiers for no benefit. The emptiness check now lives in the single remaining-time
  helper that the status endpoint and the tier chooser both read through.

## [0.0.3]

### Added
- Unified scraping strategies into a cohesive Orchestrator loop.
- Enforced identical `ContentValidator` rule boundaries (with default of 10 words) across `read` and `read_with_links` HTTP flows.
- Global HTTP 428 Precondition Required exception mapping natively into FastAPI.
- Re-architected NoVNC tracking to utilize an unconditional, persistent Redis-backed 5-second polling loop to prevent heuristic misfires.
- VNC authentication. `VNC_PASSWORD` is turned into an encrypted x11vnc password file by a new container entrypoint; unset falls back to the previous open desktop with a warning at boot.
- `deploy-standalone/` bundle for running this stack on a host of its own, with pinned images, its own `.env.example` and SearXNG overlay, and no build context.
- Healthchecks on SearXNG and FlareSolverr with `condition: service_healthy` gating, so the service no longer starts against a cold upstream and opens its circuit breaker.
- Resource limits and bounded container logs across the scrapper stack.

### Changed
- SearXNG `secret_key` moved out of the committed settings overlay and into the `SEARXNG_SECRET` environment variable. The previously committed value is public and compromised.
- SearXNG upgraded to `2026.8.14`, FlareSolverr to `v3.5.0`.

Note on numbering: this entry was drafted as `[0.1.0]` while the manifest carried a version that never matched any published image. It is renumbered to `0.0.3` so that the changelog, the manifest and the registry tags all agree. Images `v0.0.1` and `v0.0.2` correspond to the two entries below.

## [0.0.2]

### Added
- Complete network stack including Playwright `headless=False` browser execution rendering inside Docker via `fluxbox` and `Xvfb`.
- `NoVNC` tunnel integration allowing live human intervention for captchas and login walls directly inside the containerized browser.
- `FlareSolverr` integration proxy for bypassing Cloudflare bot protections heuristically.
- Global `ChallengeDetector` utilizing dictionary string mapping against `<title>` tags for bot-wall identification.

## [0.0.1]

### Added
- Simple HTML web scraping API wrapper built on `BeautifulSoup` and `Trafilatura`.

### Note
- Excluded the heavy network infrastructure (VNC, FlareSolverr) and fallback loops found in later system versions.
