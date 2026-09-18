Every command runs from `apps/ascend-web-hunter/` through that module's own virtual environment
(`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Linux and macOS), never the system Python. The gate is
`--cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`, so every branch added below needs a test
before the suite goes green. Tests are written with the code, not after it.

## 1. Connect-time address pinning

- [x] 1.1 Add `PinnedHost` (frozen dataclass: host, port, addresses) and `pin_safe_host(url)` to
      `src/validator/url_validator.py`. One `getaddrinfo` validates and pins. Share the address predicate with
      `is_safe_external_url` rather than duplicating the rules. Verify with cases for a public host, a loopback
      host, a private host, a link-local host, one public plus one private answer, an unresolvable host, a
      non-http scheme, an explicit port, and an IPv6 answer rendered in brackets.
- [x] 1.2 Render libcurl's resolve entries from `PinnedHost.curl_resolve_entries()` in `HOST:PORT:ADDR[,ADDR]` form,
      as a single-entry list. Verify the multi-address and IPv6 forms, and that a host which is already an IPv4 or
      IPv6 literal renders no entry at all, because there is no name to pin.
- [x] 1.3 Pin the initial request in `fetch_with_curl_cffi` through `CurlOpt.RESOLVE`, refusing the fetch when
      `pin_safe_host` returns None. Verify the refusal returns empty and issues no request.
- [x] 1.4 Pin every redirect hop the same way, replacing the second unpinned `is_safe_external_url` resolution.
      Verify a hop to a private address is refused and never connected to.
- [x] 1.5 Demonstrate the rebinding refusal: a resolver that answers public first and private afterwards, and a
      transport that honours a resolve pin the way libcurl does. Assert the connection went to the validated
      public address and that the private address was never connected to. Assert the unpinned control case would
      have connected to it.

## 2. Session validation on the read path

- [x] 2.1 Add `CookieManager.has_auth_cookies(url, profile)`: True when the stored record carries auth cookies,
      regardless of TTL. Verify for no record, a record with auth cookies, a record whose auth entry is empty, and
      a WAF-only record. Promote `_get_domain` to the public `registrable_domain` the gate and the outcome message
      both need, and drop the two `noqa: SLF001` suppressions `SessionManager` used to reach it.
- [x] 2.2 Gate `WebReader.read` and `WebReader.read_with_links` on `has_auth_cookies` plus
      `session_manager.validate`, before the cache lookup. Verify that a domain with no session is untouched, that
      a valid session runs the chain and slides the TTL, and that an expired one returns the outcome without
      running a tier.
- [x] 2.3 Return the `session_expired` outcome carrying the domain, the profile and the next step. Verify the
      response contract on both REST and MCP as a field list, not one field at a time.

## 3. Read controls on both API surfaces

- [x] 3.1 Add the `TierName` literal and the `tier` parameter to `WebReader.read`, `read_with_links` and
      `_select_strategies`, selecting the named tier and everything after it. Verify the chain contents for the
      first tier, a middle tier and the last tier.
- [x] 3.2 Keep the login-redirect short-circuit ahead of `tier`, and put `tier` ahead of `heavy_mode` and the
      producer routing. Verify both precedence rules.
- [x] 3.3 Add `tier` and `output_format` to `_cache_key`. Verify two different tiers and two different formats
      produce four distinct keys.
- [x] 3.4 Expose `output_format` and `tier` on `POST /api/v2/web/read` with `Field` constraints, and forward them.
      Verify forwarding, the default, and an invalid tier rejected with 422.
- [x] 3.5 Expose the same two on the MCP `web_read` tool with the same validation. Verify forwarding and rejection.
- [x] 3.6 Reject `output_format=structured` with `include_links=true` at both boundaries, 400 over REST and
      `ValueError` over MCP. Verify both.

## 4. Documentation

- [x] 4.1 Write ADR-011 for the caller-selectable starting tier, naming the ADR-001 alternative it reverses and the
      scope of the reversal.
- [x] 4.2 Write ADR-012 for connect-time pinning, the tiers it covers, and the tiers that stay residual risk.
- [x] 4.3 Add both to the ADR index and to the arc42 architecture-decisions list.
- [x] 4.4 Update the arc42 crosscutting SSRF section, the context-and-scope read row, the glossary entries for
      `web_read` and the runtime-view outcome table.
- [x] 4.5 Update `docs/api-examples.md` and `docs/running.md` for the two new fields and the new outcome.

## 5. Verification gate

- [x] 5.1 `.venv/Scripts/ruff.exe check .` clean, with no new suppression anywhere.
- [x] 5.2 `.venv/Scripts/ruff.exe format --check .` clean.
- [x] 5.3 `.venv/Scripts/mypy.exe src` clean, with no new `type: ignore`.
- [x] 5.4 `.venv/Scripts/pytest.exe --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` green.
- [x] 5.5 `openspec validate close-web-search-scraping-follow-ups` passes.
