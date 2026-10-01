# ADR-012: Pin the validated address through to connect time, for the tiers that connect in-process

## Status

Accepted, 2026-09-18

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
