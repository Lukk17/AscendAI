## Context

Three follow-ups from
[2026-09-18-enhance-web-search-scraping](../archive/2026-09-18-enhance-web-search-scraping/design.md) are built
here. Nothing else in the fetch path changes.

The pieces of the existing implementation this change stands on:

- `is_safe_external_url(url)` in `src/validator/url_validator.py` resolves a host with `socket.getaddrinfo` and
  rejects the run of non-public address classes. It is called at the REST and MCP boundary, before every dispatch
  to FlareSolverr and Crawlee, and per redirect hop inside `fetch_with_curl_cffi`.
- `fetch_with_curl_cffi` in `src/reader/strategies/curl_cffi_fetcher.py` is the only place this process opens an
  HTTP connection to a caller-supplied URL. It serves tiers `1-beautifulsoup` and `2-trafilatura`, follows
  redirects manually up to ten hops, and validates each hop before following it.
- `SessionManager.validate(url, profile)` in `src/session/session_manager.py` returns False when the auth TTL has
  lapsed or the stored record carries no cookies, and slides the auth TTL when it returns True.
- `CookieManager` splits every record into an `auth` entry and a `waf` entry with independent TTLs. A record whose
  `auth` entry holds cookies is a record that once authenticated.
- `WebReader._select_strategies` builds the six-tier dict, short-circuits to `6-novnc` for a login-redirect URL,
  and otherwise routes on `heavy_mode` plus the producer recorded on the stored session (ADR-010).

## Goals / Non-Goals

**Goals**

- The address the guard validated is the address the in-process fetch connects to, for the initial URL and for
  every redirect hop.
- A read whose stored session has expired says so, instead of quietly reading anonymously.
- A caller can ask for structured output and can choose where the escalation chain starts, over REST and over MCP.

**Non-Goals**

- Pinning inside Playwright, Crawlee, NoVNC or FlareSolverr. Reasoning in D1.
- A network-probe validate with a per-site logged-in marker. That is the other half of D4 in the archived design
  and it stays open.
- Structured output on the `include_links` path.
- Any new configuration setting. Every knob this change needs already exists.

## Decisions

### D1 Pin the validated addresses through `CURLOPT_RESOLVE`

`pin_safe_host(url) -> PinnedHost | None` performs one `getaddrinfo` for the host and the port implied by the
scheme, validates every address it returns with the same predicate `is_safe_external_url` uses, and returns a
frozen `PinnedHost` carrying the host, the port and the validated addresses. `None` means unresolvable, non-public,
or a scheme that is not http or https, and a `None` is a refusal to fetch.

`PinnedHost.curl_resolve_entries()` renders libcurl's `HOST:PORT:ADDRESS[,ADDRESS]` form as a single-entry list,
bracketing IPv6 literals as libcurl requires. It renders an empty list for a host that is already an IP literal,
because there is no name there for a second lookup to answer differently and so nothing to pin.
`fetch_with_curl_cffi` writes those entries into the session's `curl_options` under `CurlOpt.RESOLVE` before each
request it issues. libcurl consults its resolve list before the system resolver, so the socket goes to an address
this process already validated. Each request replaces the whole resolve list rather than adding to it, so one hop
cannot leave a pin behind for the next.

Two consequences worth stating plainly. First, the hop check inside the fetcher now resolves once instead of twice:
`pin_safe_host` both validates and pins, so the check and the connect can no longer disagree. Second, the initial
URL is now validated inside the fetcher too, not only at the API boundary, which matters because the boundary check
and the fetch are separated by the whole strategy chain.

Rejected alternative: rewriting the URL to the validated IP and setting a `Host` header. That is the classic pinning
trick for plain HTTP and it breaks TLS, because SNI and certificate verification both key on the name. `RESOLVE`
keeps the name for the handshake and changes only the address.

Rejected alternative: pinning the browser tiers. Chromium takes `--host-resolver-rules` on its command line, and
`browser_pool` launches one browser for the whole process, so a per-request pin would mean a browser launch per
request. That trade is not worth it for a local service whose Playwright launch already dominates its own tier's
latency. FlareSolverr and Crawlee resolve in their own processes and expose no equivalent. All four keep
pre-dispatch validation, which is what they have today, and the residual risk moves from an implied gap to ADR-012.

### D2 The read path validates a stored session before it uses one

`CookieManager.has_auth_cookies(url, profile)` answers one question: does a stored record for this domain and
profile carry auth cookies, valid or not. It is the gate, and it is deliberately not a validity check.

The outcome names the domain through `CookieManager.registrable_domain(url)`, which is the former private
`_get_domain` promoted to the public surface. `SessionManager` already reached past the underscore for it behind a
`noqa: SLF001`, twice, so the accessor the gate needs also removes two suppressions rather than adding any.

`WebReader.read` and `WebReader.read_with_links` call it first. When it says no, nothing changes: a domain with no
session, or one whose record only ever held WAF clearance from FlareSolverr, reads exactly as it does today. When
it says yes, the read calls `session_manager.validate(url, profile)`. True slides the auth TTL and the chain runs.
False returns the `session_expired` outcome without running a tier.

The gate runs before the cache lookup, not after, so the outcome does not depend on whether a previous read of the
same URL is still cached. A caller that fixes its session by re-establishing it gets a fresh read, because
`session/clear` and a new login both purge or replace the record the gate reads.

Why gate on auth cookies rather than on "a record exists": a FlareSolverr clearance writes an `auth` entry with an
empty cookie list and a `waf` entry with the clearance. Thirty minutes later the WAF entry has expired and
`validate()` returns False for a domain the user never logged into. Gating on "a record exists" would turn that
into a `session_expired` refusal on a perfectly ordinary anonymous read, which is a regression. Gating on auth
cookies fires only where a login was actually captured.

The outcome shape is a 200 body, matching how `human_intervention_required` and `novnc_busy` are already returned
over both surfaces:

```json
{
  "url": "https://example.com/feed",
  "content": "",
  "status": "session_expired",
  "profile": "work",
  "message": "Stored session for example.com (profile=work) is no longer valid. Re-establish it with the session establish operation, then read again."
}
```

The `url` field is the one the REST layer already adds to every read response, so the orchestrator itself returns
the body without it and the MCP tool returns exactly what the orchestrator built. That is how the existing
outcomes behave on both surfaces, and this one is not made a special case.

### D3 One starting tier, one output format, both on both surfaces

`TierName` is a `Literal` of the six existing strategy keys, exported from `src/reader/web_reader.py` so the REST
model, the MCP tool signature and the orchestrator all name the same set and the type checker enforces it. The
values are the same strings a successful read already returns in `mode`, so a caller can feed a response back as a
request without a translation table.

`_select_strategies` applies, in this order:

1. A login-redirect URL short-circuits to `{6-novnc}`. This outranks `tier`, because
   `web-search-authenticated-sessions` requires that a known login-redirect URL is not fetched by the cheap tiers
   first. An override of a safety rule is not an override, it is a hole.
2. An explicit `tier` selects that tier and every tier after it, in the existing order. Escalation still works, it
   simply starts later or earlier. `tier` outranks `heavy_mode` and the producer-aware routing, because it is the
   most specific instruction the caller can give.
3. Otherwise the existing `heavy_mode` and producer routing decide, unchanged.

`output_format` is a `Literal["text", "structured"]`. `structured` with `include_links=true` is rejected at the
boundary with a 400 over REST and a `ValueError` over MCP, rather than accepted and ignored. A parameter that is
accepted and silently dropped is the failure mode this change exists to fix, so it is not reintroduced.

Both fields join `_cache_key`, because both change the result. `tier` is appended last with a default of `None`, so
the existing positional calls in the test suite keep working.

ADR-001 rejected a caller-selectable strategy on the grounds that the service, not the caller, is the expert on
extraction. That reasoning still holds for the default, which is why `tier` stays unset unless asked for and the
routing underneath it is untouched. What changed is the evidence: the e2e suite needs to exercise one tier
deliberately, and an operator debugging a site needs to ask for the tier they are debugging. ADR-011 records the
reversal and its scope rather than leaving ADR-001 quietly contradicted.

## Risks / Trade-offs

- **`CURLOPT_RESOLVE` is a libcurl behaviour, not a curl_cffi API.** curl_cffi exposes it through the session's
  `curl_options`, and the version is pinned in the manifest. The tests assert the pin reaches the transport and
  that the transport honours it, so an upgrade that changes the mechanism fails the suite instead of silently
  unpinning the connection.
- **Pinning covers one tier of six.** A read that escalates past `2-trafilatura` is back to pre-dispatch validation.
  This is an improvement over the current state rather than a closure, and ADR-012 says so in those words.
- **The session gate adds a store read to every read of a domain with auth cookies.** In-memory it is a dict
  lookup. On Redis it is one GET, plus one SET when the TTL slides. Both are small next to a fetch.
- **A false `session_expired` costs one re-login.** The gate inherits the conservative expiry model documented on
  `_auth_ttl_remaining_from_entry`, which prefers reporting a live session dead over reporting a dead session live.
- **`tier` lets a caller pick a worse tier.** That is the point of an override, and the default is unchanged.

## Open Questions

None. The two items deliberately left open, a network-probe validate and pinning inside the browser tiers, are
recorded as non-goals above with their reasons.
