# ADR-006: Optional proxy seam, coherent browser fingerprints, and patchright evaluation

## Status

Accepted — 2026-06-15

## Context

Anti-bot systems on target sites (LinkedIn, Cloudflare-protected domains) detect automation using several signals:

1. **Inconsistent fingerprints.** The prior code used `locale="en-US"` + `timezone_id="UTC"` in the Playwright
   tier but `timezone_id="America/New_York"` + San Francisco geolocation in the Crawlee and NoVNC tiers. These
   combinations are internally inconsistent and are known detection tells: a real browser located in New York
   would never report UTC as its local timezone.

2. **IP-based blocks.** Sophisticated sites block or challenge egress IPs that match cloud-provider CIDR ranges
   or that have been previously flagged. A configurable proxy egress point lets the operator route fetches
   through a residential or rotating proxy without changes to application code.

3. **Stealth library.** `playwright-stealth` was the existing choice. `patchright` is an alternative that
   patches Chromium binaries at source rather than injecting JavaScript to hide automation artefacts, which
   gives stronger protection against CDP-based detection.

## Decision

### D1 — Coherent `Fingerprint` value object

A single `Fingerprint` dataclass (`src/reader/fingerprint.py`) carries `user_agent`, `locale`, `timezone_id`,
`geolocation`, `viewport_width`, and `viewport_height` as one internally consistent set. Every browser-based
tier (Playwright, Crawlee, NoVNC) receives the same `Fingerprint` instance.

The default built-in persona is "New York, English, Chrome on Windows":
- `locale` = `"en-US"`
- `timezone_id` = `"America/New_York"`
- Geolocation ≈ 40.71 N, 74.01 W (Manhattan)
- UA = Chrome 131 on Windows 10

This eliminates the prior mismatched combinations. All three tiers now agree on the same location identity.

### D2 — Optional proxy via `ProxyProvider`

A `ProxyProvider` singleton (`src/proxy/proxy_provider.py`) reads `PROXY_URL` from settings. When unset (the
default), every `for_*()` method returns `None` and all tiers fetch over direct egress, unchanged. When set,
each tier receives the proxy in the format it expects:

| Tier | Kwarg / field |
| :--- | :--- |
| curl_cffi | `proxies={"http": url, "https": url}` |
| Playwright | `proxy={"server": url}` |
| FlareSolverr | `payload["proxy"] = {"url": url}` |
| Crawlee | `browser_context_options["proxy"] = {"server": url}` |

No proxy authentication or per-domain routing is added. If rotation or auth is needed, a proxy manager sits
upstream and exposes a single CONNECT URL.

### D3 — Patchright evaluation outcome: keep playwright-stealth

`patchright` patches Chromium at the binary level and removes CDP-detectable automation flags that `playwright-stealth`
can only hide with JavaScript. However, it is **not a clean drop-in** for this codebase as of evaluation date
(2026-06-15):

- `patchright` does not publish Python stubs; mypy strict mode fails without a `[[tool.mypy.overrides]]` exemption.
- The `playwright-stealth` `Stealth.apply_stealth_async(page)` API surface used in `PlaywrightStrategy` has no
  equivalent single-call API in `patchright` — migration would require replacing the `browser_pool` singleton
  pattern and changing the context-creation flow in both `PlaywrightStrategy` and the NoVNC monitor.
- `patchright` is maintained by a single contributor with no published stability guarantees.

Decision: **keep `playwright-stealth`**. The Fingerprint coherence fix in D1 removes the most obvious detection
tell. `patchright` should be re-evaluated when it publishes Python stubs and a stable drop-in API.

## Alternatives Considered

### Alternative 1: Hardcode a single "best" user-agent and locale globally
- **Pros**: Simpler — no `Fingerprint` class.
- **Cons**: No seam for per-request or per-site overrides. A site-specific persona (e.g. a mobile UA for a
  mobile-only site) would require code changes.
- **Why not**: The `Fingerprint` dataclass is minimal overhead and gives the seam without adding complexity.

### Alternative 2: Rotate through multiple `Fingerprint` personas per request
- **Pros**: Harder to fingerprint across requests.
- **Cons**: Rotation is a bot-detection heuristic, not a human pattern. A human using LinkedIn always uses the
  same browser — rotation is a signal.
- **Why not**: Out of scope per the spec ("no self-throttling, no rate-limiting"). Fingerprint coherence is the
  goal; rotation is a separate concern.

## Consequences

### Positive
- Browser tiers now present a single internally consistent identity; the prior locale/timezone/geo mismatch is eliminated.
- Proxy egress is a configuration-only change; no code path diverges when the proxy is unconfigured.
- Fingerprint customisation (e.g. a mobile persona for specific sites) is a one-line change to `WebReader._build_strategies`.

### Negative
- The fixed New York persona is not geographically appropriate for every target site. Some sites tailor content
  to the visitor's location; a fixed persona can return US-localised content.
- `patchright` evaluated but not adopted; CDP-based bot detection remains possible via playwright-stealth's JS
  approach. Re-evaluate on patchright's next stable release.

### Risks
- **Proxy leaks:** if `PROXY_URL` is set, all four tiers route through it including the FlareSolverr payload
  field. FlareSolverr forwards the proxy to its internal fetch; the proxy operator can observe all fetched URLs.
  Do not set `PROXY_URL` to an untrusted proxy.

## Related

- `src/reader/fingerprint.py` — `Fingerprint`, `get_default_fingerprint`.
- `src/proxy/proxy_provider.py` — `ProxyProvider`, `proxy_provider`.
- `src/reader/strategies/playwright_strategy.py` — consumes `Fingerprint` and `ProxyProvider`.
- `src/reader/strategies/crawlee_strategy.py` — consumes `Fingerprint` and `ProxyProvider`.
- `src/reader/strategies/novnc_strategy.py` — consumes `Fingerprint`.
- `src/reader/strategies/curl_cffi_fetcher.py` — consumes `ProxyProvider`.
- `src/reader/strategies/flaresolverr_strategy.py` — consumes `ProxyProvider`.
- `src/config/config.py` — `PROXY_URL`.
