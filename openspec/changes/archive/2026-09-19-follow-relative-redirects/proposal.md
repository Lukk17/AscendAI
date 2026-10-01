## Why

Two related things are wrong on the same few lines of the in-process fetch path: the code refuses an ordinary
redirect, and the published specification describes a mechanism that no longer exists.

1. **An ordinary relative redirect ends the read.** `fetch_with_curl_cffi`
   ([curl_cffi_fetcher.py](../../../apps/ascend-web-hunter/src/reader/strategies/curl_cffi_fetcher.py)) follows
   redirects with a manual loop and hands each hop's raw `Location` value to `pin_safe_host`. A relative
   `Location`, `/article` or `../index.html` or `//other.example/page`, carries no host, so `urlparse` finds none,
   `pin_safe_host` returns `None`, and the fetcher treats it as an SSRF refusal: it logs that the guard blocked the
   redirect and returns an empty string. RFC 9110 section 10.2.2, formerly RFC 7231 section 7.1.2, requires a
   client to resolve a relative reference against the effective request URI, and relative `Location` headers are
   ordinary HTTP that a large share of real sites emit. Measured against the live service on 2026-09-18,
   `https://www.python.org/doc` redirects to `/doc/` and both curl_cffi tiers refuse it, so the read is served by
   `3-flaresolverr` after two tiers have failed for a reason that is not a security event at all. On a stack with
   no FlareSolverr the read would simply fail, and in the logs it looks like a blocked attack rather than a bug.
2. **A published requirement is backed by nothing.**
   [openspec/specs/web-search-fetch-correctness/spec.md](../../specs/web-search-fetch-correctness/spec.md) line 11
   states that "A response history SHALL likewise be re-checked hop by hop". The helper that clause described,
   `validate_redirect_chain`, was removed after being measured as both uncalled and vacuous: on curl_cffi 0.15.0
   the `Response.history` list is empty whether redirects are followed automatically or not, so the check could
   never have returned `False`. Per-hop re-validation is genuinely performed, but by the manual loop in the fetcher
   that re-validates and re-pins before each hop is fetched, never by inspecting a history afterwards. The clause
   promises a mechanism no code can satisfy and hides the one that actually holds the property.

## What Changes

- **A relative `Location` is resolved before it is validated.** The redirect loop tracks the URL of the hop that
  produced the current response and resolves each `Location` against it with `urllib.parse.urljoin`, which handles
  the path-relative, root-relative and protocol-relative forms in one call and leaves an absolute `Location`
  untouched. The resolved absolute URL then goes through exactly the same `pin_safe_host` validation and pinning an
  absolute one goes through, with no shortcut: a relative redirect that resolves onto a private, loopback,
  link-local, multicast or reserved address is still refused and never fetched, and a protocol-relative `Location`
  that moves the read to a second host is validated as that second host. The existing hop bound, the existing
  refusal behaviour and the existing pin-per-hop behaviour are unchanged. The refusal log now names the resolved
  URL and the hop it came from, because the raw value alone does not say where the fetch was actually headed.
- **The published requirement describes the mechanism that exists.** The `SSRF guard re-validated on every redirect
  hop` requirement drops the response-history sentence, states that re-validation happens before each hop is
  fetched because the tier follows the chain itself and has no history to inspect, and folds in relative
  resolution, which is part of how a hop is validated rather than a separate rule.

Out of scope: the out-of-process and browser tiers, which never see a `Location` header in this process and keep
pre-dispatch validation as the only check available for them. The hop bound, which is unchanged at ten. Any change
to what counts as a safe address.

## Capabilities

### New Capabilities

<!-- None: the behaviour belongs to a requirement that already exists under openspec/specs/. -->

### Modified Capabilities

- `web-search-fetch-correctness`: the redirect-hop requirement gains relative-reference resolution before
  validation, and loses the response-history clause that no code can satisfy.

## Impact

- **Code:** `src/reader/strategies/curl_cffi_fetcher.py` only. One import, one tracked variable for the current
  hop, one `urljoin`, and a log line that names the resolved target.
- **API:** none. No request field, no response field and no status changes. A read that fails today because of a
  relative redirect now succeeds on the cheap tier, which is the bug fix, and a read that succeeds today still
  succeeds the same way.
- **Config:** none. No new setting and no threshold moves.
- **Dependencies:** none. `urllib.parse.urljoin` is standard library.
- **Docs/ADRs:** no new ADR, because no decision is reversed. The arc42 crosscutting SSRF section gains the
  relative-resolution sentence, and ADR-012's context paragraph loses its one sentence about
  `validate_redirect_chain`, which names a helper the repository no longer contains.
- **Tests:** the module's 100 percent branch-coverage gate holds. The new tests fail before the fix, assert the
  resolved URL that was requested rather than only the returned content, and keep the refusal cases proving that a
  relative hop onto an internal address is still refused.

## Relevant Skills

Load these before implementing:

- `/python-patterns` for typing, pytest discipline and the async conventions this module follows.
- `/tdd-workflow` for the red-green loop and the coverage gate.
- `/security-review` for the SSRF surface this change touches, since the fix must not widen it.
- `/coding-standards` for the cross-cutting floor.
- `/ai-regression-testing` for writing the regression test that names the defect it prevents.
- `/api-design` for the redirect semantics the fetch path has to honour.
