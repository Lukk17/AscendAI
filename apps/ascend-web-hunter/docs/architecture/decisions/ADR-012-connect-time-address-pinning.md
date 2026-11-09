# ADR-012: Pin the validated address through to connect time, for the tiers that connect in-process

## Status

Accepted, 2026-09-18

## Amendment, 2026-10-04 (owner answer 63.2)

The rule is unchanged and now lives in the library: `check_fetch_uri`,
`follow_guarded_redirects` and the `CURLOPT_RESOLVE` send hop of
`ascend-python-common` (`openspec/changes/add-ascend-python-common/design.md`
D21). `is_safe_external_url`, `pin_safe_host` and their helpers left
`src/validator/url_validator.py`, keeping `URLValidator` and the
`url_validator` singleton, which apply the ad blocklist. A host on
`ALLOWED_PRIVATE_HOSTS` skips the address check, a setting no production
file sets (owner answer 67.3). The rest of this record is unchanged.

## Amendment, 2026-10-19 (enhance-web-search-tier-ladder)

The browser and out-of-process tiers no longer keep only pre-dispatch validation: `src/reader/browser_guard.py`
installs one guarded route handler on every browser context (`4-playwright_stealth`, `4a-patchright`,
`4b-camoufox`, `5-crawlee_adaptive`, the browser of `6-novnc`), with `service_workers="block"`, before the
first navigation. The handler applies the ad blocklist, then `check_fetch_uri` with the web-hunter policy,
aborts refusals with `route.abort("blockedbyclient")`, and fetches passes through
`route.fetch(max_redirects=0)` handed to the browser with `route.fulfill(response=...)`, so every redirect
hop re-enters the handler. The residual window below is unchanged in kind: `route.fetch` resolves the host
again, so the connect-time address pinning of D1 and D2 is still not applied inside the browser path. That
residual DNS rebinding window is accepted for the same reason D4 accepted it. See
[ADR-015](ADR-015-patched-browser-tiers-and-tier-memory.md) D4.

## Amendment, 2026-10-20 (remove-flaresolverr-tier)

FlareSolverr leaves the out-of-process tier list: the tier that fetched
through it is deleted, so only Crawlee still fetches out of process. The
pinning rule and the residual window are unchanged. The rest of this record
is unchanged. See [ADR-018](ADR-018-flaresolverr-tier-removed.md).

## Amendment, 2026-11-07 (security fix 19, owner approved): the browser tiers are pinned too

The residual window of D4 and of the 2026-10-19 amendment is closed for every browser tier
(`4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive`, the browser of `6-novnc`, and the
screenshot capture). `route.fetch` resolved the host again in the Playwright driver, so a name that answered a
public address to `check_fetch_uri` could answer a private one to the fetch. That second lookup is gone.

Measured on 2026-11-07 with Playwright 1.60.0 and Chromium 148, Patchright 1.60.0, and Camoufox 0.5.8 on Firefox
156, each against local test servers:

- A response handed over with `route.fulfill` that is a 3xx is followed by the browser itself and the next hop
  does not enter routing again, in all three engines. The handler therefore never fulfills a redirect.
- `route.request.all_headers()` carries the browser's own `Cookie` header in all three engines, and the
  `Set-Cookie` lines of a fulfilled answer, joined with a newline, land in the browser context in all three.
- Requests Playwright routing never sees: a speculation rules prefetch in Chromium, the requests of a shared
  worker in all three engines, the requests of a dedicated worker in Camoufox, page WebSockets in Camoufox,
  `<link rel=preconnect>` in Camoufox, and WebRTC STUN over UDP and TURN over TCP in Chromium. Each of them
  reached a local listener. A dedicated worker's requests in Chromium are routed. Patchright's
  `route_web_socket` makes the page's `WebSocket` constructor throw.

Decision:

- Pinned fetch for every routed request. On a pass, `src/reader/browser_guard.py` sends the request itself
  with `send_pinned_request` from `src/fetch/pinned_fetch.py`: the method, the browser's own headers in the
  browser's order (no curl_cffi default headers), and the body, pinned through `CURLOPT_RESOLVE` to the addresses
  the guard checked, through the configured proxy when one is set. The answer goes back with `route.fulfill`
  (status, headers without the transfer framing, decoded body). `route.fetch` and `route.continue_` are no longer
  used for a network URL, and `continue_` remains only for `data:` and `blob:`.
- Redirects. No redirect is followed by curl, and every hop is checked and pinned before anything connects to
  it, up to `FETCH_MAX_REDIRECT_HOPS`. A 303, and a 301 or 302 answering a `POST`, become a `GET` without the
  body, a 307 or 308 keeps both, and a hop to another origin drops `Authorization`. A refused hop still aborts
  with `blockedbyclient` after exactly one request to the site, which spec 18 checks.
  - A navigation (a page load, a form post, a link, a frame) that answers with a redirect is aborted with
    `aborted`, and its frame navigates to the next hop, so the browser itself shows the final address: the
    page's URL, `document.location`, the base for relative links and subresources, the history entry, and the
    latest main-frame response all belong to the last hop. `guarded_goto` follows the hops of a navigation it
    awaits within the caller's one timeout, and every tier navigates through it. Crawlee calls `page.goto`
    itself, so its pre-navigation hook makes `page.goto` follow the hops with `guard_page_goto`. Any other
    navigation is sent on by the handler with a `frame.goto` of its own. The hop arrives at the handler as an
    ordinary routed request and is sent with the rewritten method and body, the first request's headers and the
    context's cookies for its URL.
  - A subresource follows its hops inside the handler through the library's `follow_guarded_redirects` and is
    fulfilled at its first address, so a redirected script, style sheet or `fetch()` keeps its first address as
    its own URL.
- Cookies. A request sends the browser's own `Cookie` header, and a hop the handler sends sends the context's
  cookies for its URL. The `Set-Cookie` lines of every hop the browser never sees, and those of a subresource's
  last hop when it had a redirect, are written into the context for that hop's URL by
  `src/reader/route_cookies.py`, and an already expired one is cleared. Every other answer's `Set-Cookie` lines go
  through `route.fulfill`, which the browser applies to the address it requested. Logins, Cloudflare clearance
  cookies and the NoVNC capture read the context as before.
- Connection reuse. Each context keeps one curl_cffi session per pinned address set, keyed by the
  `CURLOPT_RESOLVE` entries of the checked target, and closes them when the context closes. A session only sends
  targets with its own key, so its connections are reused across requests to that host and can only reach the
  addresses that key was checked with. A host whose check answers other addresses gets a session of its own.
- Fingerprint. The pinned fetch impersonates the tier's browser family: `chrome146` for the Chromium tiers and
  `firefox147` for `4b-camoufox`, the newest targets curl_cffi 0.15.0 offers. `install_browser_guard` and
  `capture_page` take the family as a required argument.
- Everything routing does not see goes nowhere. Every Chromium launch adds `CHROMIUM_GUARD_ARGS` and the
  Camoufox launch adds `FIREFOX_GUARD_PREFS`: the browser's own network path points at a proxy on
  `127.0.0.1:1` that refuses every connection, loopback included, and WebRTC may use only proxied connections. A
  routed request never reaches that path, because it is answered with `route.fulfill`. With the final settings
  none of the requests listed above reached a listener in any engine. A context proxy from
  `proxy_provider.for_playwright()` takes the place of the refusing proxy for that context, so the browser's own
  connections then resolve at the customer proxy, the same as the static tiers. Service workers stay blocked with
  `service_workers="block"` on every context.
- WebSockets. Every page WebSocket is closed in `route_web_socket` before the browser connects, one warning
  each. No engine hands a WebSocket to the handler in a form the pinned fetch can carry.
- Body cap. An answer whose declared length or read bytes pass `BROWSER_RESPONSE_MAX_BYTES` (default
  `52428800`) is aborted with `failed`, because `route.fulfill` needs the whole body in memory.
- Failure codes. A pinned fetch that cannot connect aborts with `addressunreachable`, any other transport
  failure with `failed`, each with one warning. An abort on a closed page is skipped.

What a browser tier can no longer do: a page cannot keep a WebSocket open, a worker in `4b-camoufox` and a shared
worker in any tier cannot reach the network, speculation rules prefetch and preconnect do nothing, WebRTC finds no
route, and no single answer above `BROWSER_RESPONSE_MAX_BYTES` reaches the page. A caller that waits with
`wait_for_url` or `expect_navigation` sees an aborted redirect hop as a failed navigation, so the tiers wait with
`guarded_goto` and load states only.

Measured on 2026-11-07, a local page with fifty images on one host in Chromium 148, median of seven loads: with
one session per request it took 334 ms over HTTP and 2150 ms over HTTPS with 51 connections per load, with one
session per pinned address set 393 ms and 482 ms with 10 connections per load.

The live proof is `test_name_rebound_to_a_private_address_is_still_read_from_the_checked_address` in
`tests/integration/test_browser_ssrf.py`: the guard's lookup answers `localhost` with `127.0.0.2`, standing for a
public address, while every other resolver answers `127.0.0.1`, where a second site listens on the same port. All
four browser tiers read the page, its redirect hop and its script fetch from `127.0.0.2`, and the second site gets
no request. With `route.fetch` in place of the pinned fetch the same test reads the second site in all three
tiers it was run against. `tests/integration/test_browser_guard_fetch.py` proves the redirect behaviour in each
engine, the cookie domains, the 303 and 307 form posts, and the connection reuse.

## Amendment, 2026-11-09 (owner approved): browsers connect through a pinned tunnel

The 2026-11-07 amendment fixed DNS rebinding, but it also replaced the browser's TLS and HTTP stack with curl_cffi for
every routed request, and a protected site can see that. Measured on 2026-11-09 on
`https://www.scrapingcourse.com/cloudflare-challenge`, nobody clicking: Patchright through the pinned fetch stayed
challenged even holding a valid `cf_clearance`, Patchright with no guard passed in about 4 seconds, and Patchright
through a local tunnel that only pins the address passed in 5 seconds. Stock Playwright Chromium through the same
tunnel stayed blocked for 120 seconds.

Decision:

- Tunnel. `src/reader/pinned_tunnel.py` is a local forward proxy on `127.0.0.1` and an ephemeral port, one per process,
  started and stopped with the service. For CONNECT and for plain http absolute-URI requests it resolves the host once
  through `check_fetch_uri` with `web_hunter_fetch_policy()`, so `ALLOWED_PRIVATE_HOSTS` counts exactly as in the guard,
  connects only to the checked address and copies bytes both ways. Nothing resolves the name a second time. It replaces
  the refusing proxy on `127.0.0.1:1`: `chromium_guard_args()` and `firefox_guard_prefs()` point every launch at it,
  loopback included, keep QUIC and HTTP/3 off and keep WebRTC to proxied connections.
- Guard. `src/reader/browser_guard.py` keeps the per-request check, the ad blocklist, service worker blocking and the
  rule that only a refused main frame of the read's own page fails a read. An allowed request uses `route.continue_()`.
  The curl_cffi path, `route.fulfill` of fetched bodies, the redirect rebuilding, the impersonation targets and the
  popup hop handling are removed, with `src/reader/route_cookies.py` and `send_pinned_request`.
- Redirects. Playwright, Patchright and Camoufox do not route redirect hops, measured on 2026-11-09 in all three. The
  tunnel checks a hop when the browser connects to it and answers a refusal with 403. It remembers the refusal for 30
  seconds, and the `requestfailed` and `response` events of the read's main frame compare against that record, so the
  read still answers `unsafe_uri`.
- Limits. `BROWSER_TUNNEL_MAX_CONNECTIONS` bounds the connections carried at once, and one above it answers 503. A
  browser that closes ends its connection at once, on the plain http path as well as on the CONNECT path. A refusal is
  forgotten as soon as a later check of that host and port passes, and a `response` event counts as a refusal only with
  the tunnel's own status 403.
- Headers. Any route makes the driver turn the cache off, so Chromium still sends `pragma` and `cache-control` below
  the level a route can change. A bare `route.continue_()` on a page load made `https://www.reddit.com/` answer a
  reCAPTCHA, a real page in 0 of 22 reads. A Chromium navigation therefore continues with explicit headers, read 5 of 5
  with a real page. On the wire both headers are still there and the header order changes, measured on an HTTP/2 echo,
  so the changed order is what made Reddit serve its page. Why Reddit reacts to the order is not measured. Only
  navigations get the explicit headers, because the override
  follows redirects: a page `fetch` carried its `Authorization` to another origin. Firefox continues bare, because it
  never adds the two headers and the override carried its `Cookie` and `Host` to another origin.
- Customer proxy. A context proxy from `proxy_provider.for_playwright()` is reached through its own tunnel listener, so
  the same refusal check applies to the target before anything is sent to the proxy. Only http and https proxies can
  be chained. A socks proxy answers 502 with a warning.
- WebSockets. Chromium closes them in `route_web_socket`. In Camoufox a main-world init script makes the page's
  `WebSocket` constructor throw, because `route_web_socket` and the Firefox preferences did not stop them.
- NoVNC. The human window launches Patchright, with its driver lifecycle, window placement and context settings kept,
  and leaves through the configured `PROXY_URL` like a read. A refused navigation of its main frame closes it with the
  outcome `unsafe_uri`, shown in `last_window`. The 428 answer has already gone by then, because the window runs in the
  background after it.

Accepted costs:

1. The size limit is per connection. `BROWSER_RESPONSE_MAX_BYTES` counts the bytes a site sends on one connection, so
   several answers on one kept connection share it. No limit applies to one answer on its own.
2. Browser background traffic to public sites is no longer stopped. Speculation rules prefetch, shared workers, workers
   in Camoufox and `preconnect` now connect to public addresses through the tunnel, which still refuses private ones.
3. Bytes are counted on the wire. The browser inflates a compressed answer in its own process, so a small body that
   inflates very far is limited there by the browser and by the container memory, not by this setting. The copy into
   the service is bounded: every `page.content()` call goes through `bounded_page_content` in
   `src/reader/strategies/browser_read.py`, which evaluates `document.documentElement.outerHTML.length` in the page and
   fails the read above `BROWSER_RESPONSE_MAX_BYTES` or when the evaluation throws. The markup stays in the renderer.
4. A redirect hop of a navigation is not checked against the ad blocklist, because the route never sees it. The tunnel
   still checks its address.
5. WebSockets of a dedicated worker in Camoufox are not closed by the main-world script. The tunnel still checks their
   address.
6. Plain http requests are carried one per connection. Https connections are reused by the browser as usual.
7. `FETCH_MAX_REDIRECT_HOPS` no longer limits a browser tier. A browser follows redirects itself, so its own limit
   applies, and the tunnel still checks every hop.

Measured on 2026-11-09 on the same page with the guard and the tunnel installed: Patchright in a visible window passed
in 4.6 seconds with nobody clicking, and reusing that state opened the page with HTTP 200 at once. In headless mode it
stayed challenged for 90 seconds. `PLAYWRIGHT_HEADLESS` defaults to `false`, and the compose files do not change it.

## Context

`is_safe_external_url` resolves a hostname with `socket.getaddrinfo`, checks every address it gets back against the
loopback, private, link-local, multicast, reserved and unspecified classes, and then discards the result. The fetch
that follows resolves the same name again. Between those two lookups the authoritative DNS for the name can change
its answer, which is DNS rebinding: the validation sees a public address, the connection lands on
`169.254.169.254`, and the guard has proved nothing about the socket that actually opened.

The archived change `2026-09-18-enhance-web-search-scraping` closed the coarser half of this. Automatic redirect
following is off in the `curl_cffi` tier and each hop's `Location` is re-validated before it is followed. Its own
design records what was left: "Pinning the validated
IP through to connect time was designed but not built: no custom resolver or connector shipped, so the
DNS-rebinding window is narrowed by re-validation rather than closed."

The four tiers do not have the same options. `1-beautifulsoup` and `2-trafilatura` share `fetch_with_curl_cffi`,
which opens the connection inside this process through libcurl. `3-flaresolverr` and `5-crawlee_adaptive` fetch in
other processes. `4-playwright_stealth` and `6-novnc` fetch through a Chromium instance that `browser_pool` launches
once for the whole process.

## Decision

### D1, one lookup both validates and pins

`pin_safe_host(url)` in `src/validator/url_validator.py` resolves the host and the port implied by the URL once,
validates every address against the same predicate `is_safe_external_url` uses, and returns a frozen `PinnedHost`
carrying the host, the port and those addresses. `None` means unresolvable, non-public, no usable host or port, or a
scheme that is not http or https, and a `None` is a refusal to fetch rather than a fall-through. There is no second
resolution to disagree with the first, because the addresses the guard authorised are the addresses handed onward.

### D2, the pin reaches libcurl through `CURLOPT_RESOLVE`

`PinnedHost.curl_resolve_entries()` renders libcurl's `HOST:PORT:ADDRESS[,ADDRESS]` form, bracketing IPv6 literals
as libcurl requires, and `fetch_with_curl_cffi` writes it into the session's `curl_options` before each request it
issues, for the initial URL and for every redirect hop. libcurl consults that list before the system resolver, so
the socket opens against a validated address. curl_cffi frees the entry after each perform, so one hop's pin cannot
leak into the next.

The entry list is empty when the host is already an IP literal. There is no name for a second lookup to answer
differently, so there is nothing to pin, and the address itself was still validated.

Measured against curl_cffi 0.15.0 on 2026-09-18, with a local HTTP server and no external network. A request for a
name that does not resolve at all succeeds when its host and port carry a pin and fails with `Could not resolve
host` without one, which is the pin reaching libcurl. A pin written into `curl_options` after the session was
constructed is honoured, and replacing it for the next request is honoured too: re-pinning the same host and port to
a black-holed address made the next request time out rather than reuse the earlier address, so a later pin beats the
entry the earlier one left in libcurl's per-session DNS cache. A host that carries no new pin can still be served
from that cache within the session, which is safe in the only direction that matters: an address gets into that
cache from a lookup this process validated, during this same call.

### D3, rewriting the URL to the IP was rejected

Replacing the hostname with the validated address and setting a `Host` header is the usual pinning trick for plain
HTTP, and it breaks TLS: SNI and certificate verification both key on the name. `CURLOPT_RESOLVE` keeps the name for
the handshake and changes only where the connection goes.

### D4, the other four tiers keep pre-dispatch validation, and that is residual risk

FlareSolverr and Crawlee resolve in their own processes and expose no equivalent knob. Chromium takes
`--host-resolver-rules` on its command line, so a per-request pin there would mean a browser launch per request,
which is not a trade worth making for a local service whose browser launch already dominates that tier's latency.
All four keep the pre-dispatch `is_safe_external_url` check they have today. The rebinding window stays open for
them and is accepted, for the same reason the archived change accepted it: this service runs locally, it fetches
URLs its own operator asked for, and the metadata endpoints an attacker would aim at are not reachable from the
scrapper stack's network in the deployments this repository ships.

## Alternatives Considered

### Alternative 1: a custom resolver hook in curl_cffi
- Pros: pins without rendering a string, and would cover any future in-process client.
- Cons: `CURLOPT_RESOLVER_START_FUNCTION` is not surfaced by curl_cffi in a usable form, and a hook that must be
  installed per handle in a pooled session is more machinery than the resolve list for the same result.
- Why not: `CURLOPT_RESOLVE` is the supported path and is one line at the call site.

### Alternative 2: launch a browser per request so the browser tiers can pin too
- Pros: closes the window on four more tiers.
- Cons: a Chromium launch per read, which is the cost [ADR-005](ADR-005-strategy-budget-and-singleton-chromium.md)
  exists to avoid, against a threat this deployment does not face.
- Why not: the cost is certain and paid on every read, the benefit is a narrow window in a local service.

### Alternative 3: leave it as re-validation only
- Pros: no change at all.
- Cons: keeps a known, specified, unbuilt defence permanently unbuilt in the one place it is cheap to build.
- Why not: the in-process tiers are the ones that serve the majority of reads, and the fix is a single resolution
  moved rather than added.

## Consequences

### Positive
- Tiers 1 and 2 connect only to addresses this process validated, and a rebound answer never reaches a socket.
- The initial URL is now validated inside the fetcher as well as at the API boundary, which matters because the two
  are separated by the whole strategy chain.
- The hop check costs one resolution instead of two, because validation and pinning are the same lookup.

### Negative
- Four tiers still carry the window, and the ADR now says so in those words rather than leaving it implied.
- A host whose DNS answers legitimately change mid-read, such as a very short TTL behind a load balancer, keeps the
  addresses from the start of that request. The pin lives for one request, so the next read resolves afresh.

### Risks
- `CURLOPT_RESOLVE` is a libcurl behaviour reached through curl_cffi's `curl_options`. The tests assert both that
  the pin is handed to the transport and that a transport honouring it refuses a rebind, so a dependency upgrade
  that changes the mechanism fails the suite rather than silently unpinning the connection.

## Related

- `src/validator/url_validator.py` - `PinnedHost`, `pin_safe_host`, `_resolve_public_addresses`,
  `_is_public_address`, `is_safe_external_url`.
- `src/reader/strategies/curl_cffi_fetcher.py` - `_pin_session_to`, `fetch_with_curl_cffi`.
- `tests/reader/strategies/test_curl_cffi_ip_pinning.py` - the rebinding demonstration.
- [ADR-005](ADR-005-strategy-budget-and-singleton-chromium.md), the singleton Chromium that rules out per-request
  browser pinning.
- `openspec/changes/archive/2026-09-18-enhance-web-search-scraping/design.md`, decision D6 and its open follow-up.
