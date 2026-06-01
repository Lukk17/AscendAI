# ADR-001: Multi-tier extraction strategy — six strategies in fixed escalation order

## Status

Accepted — 2026-05-31

## Context

Web content extraction fails for different reasons depending on the target site. A plain HTTP client (curl_cffi /
BeautifulSoup) is fast but fails against JavaScript-heavy pages. Trafilatura parses richer HTML but has the same
HTTP-level limitations. FlareSolverr can bypass Cloudflare WAF challenges. Playwright renders full JavaScript but
is slow and resource-heavy. Complex CAPTCHAs and login walls cannot be solved programmatically at all and require
a human in the loop.

No single strategy handles all cases, and falling back silently without content is worse than surfacing a clear
signal to the caller. The service must attempt lightweight extraction first, escalate to progressively heavier
methods only when the cheaper ones fail, and terminate with an explicit 428 human-intervention response when
automation is exhausted.

## Decision

`WebReader` (`src/reader/web_reader.py:26`) defines six strategies in a fixed ordered dict:

| Key | Strategy class | Cost |
| :--- | :--- | :--- |
| `1-beautifulsoup` | `BeautifulSoupStrategy` | Low — `curl_cffi` impersonating Chrome120 + BeautifulSoup parse |
| `2-trafilatura` | `TrafilaturaStrategy` | Low — same HTTP client, Trafilatura extraction |
| `3-flaresolverr` | `FlareSolverrStrategy` | Medium — external FlareSolverr proxy call |
| `4-playwright_stealth` | `PlaywrightStrategy` | High — headless Chromium + `playwright-stealth` |
| `5-crawlee_adaptive` | `CrawleeStrategy` | High — Crawlee AdaptivePlaywrightCrawler |
| `6-novnc` | `NoVNCStrategy` | Human — raises `HumanInterventionRequiredException` |

The loop in `WebReader.read` (`src/reader/web_reader.py:81-88`) iterates the dict in insertion order, tries each
strategy, and validates the extracted content via `ContentValidator`. The first strategy that produces content
passing validation wins; all subsequent strategies are skipped.

Two override modes short-circuit the default sequence. When `ChallengeDetector.is_login_redirect_url(url)` fires
on the URL itself before any request is made, the chain is replaced with `{6-novnc}` alone. When `heavy_mode=True`
is passed by the caller, the chain is replaced with strategies 4, 5, and 6 only, skipping the cheap HTTP strategies
that would certainly fail against the target.

`ChallengeDetectedException` raised by any strategy short-circuits to `NoVNCStrategy` immediately rather than
continuing the loop.

## Alternatives Considered

### Alternative 1: Single browser-only strategy
- **Pros**: Simpler code; no escalation logic.
- **Cons**: Playwright is 10x slower than `curl_cffi` for plain HTML. Every request pays the full browser launch
  cost regardless of whether the site needs it.
- **Why not**: Response latency is unacceptable for the majority of pages that do not require JavaScript rendering.

### Alternative 2: Parallel attempt, take fastest result
- **Pros**: Lower worst-case latency.
- **Cons**: Wastes significant CPU and memory launching four strategies simultaneously for every request. Adds
  race-condition complexity in result handling. Playwright and Crawlee both open browser contexts; parallel launches
  stress container memory.
- **Why not**: The cost is borne on every request. The sequential escalation only pays the cost when cheaper
  strategies fail.

### Alternative 3: Caller-selectable strategy
- **Pros**: Caller knows the target site and can skip useless strategies.
- **Cons**: Every MCP caller (AscendAgent) would need site-specific knowledge about which strategy to request. This
  belongs in the service, not in the caller.
- **Why not**: The service is the expert on extraction; callers should only control `heavy_mode` as a coarse
  override.

## Consequences

### Positive
- Fast path (strategies 1 and 2) handles the majority of plain-HTML pages with minimal latency.
- Escalation is transparent to callers; they get content or a 428 — they do not see the strategy that ran.
- Adding a new strategy requires one new class implementing `BaseStrategy` and one dict entry; no routing changes.

### Negative
- Sequential ordering means a slow strategy 3 or 4 blocks the request for its full timeout before strategy 5 runs.
- The fixed order cannot be tuned per domain without code changes. There is no configuration for "skip FlareSolverr
  for this domain."
- `NoVNCStrategy` raises rather than returning content, making it unlike the other five in the chain.

### Risks
- If FlareSolverr is misconfigured or offline, `FLARESOLVERR_URL` is checked at call time
  (`src/reader/strategies/flaresolverr_strategy.py:26`). The strategy returns empty string and the loop continues,
  so an offline FlareSolverr does not block the chain. The cost is wasted time waiting for `EXTRACT_TIMEOUT * 2`.

## Related

- `src/reader/web_reader.py` — `WebReader.read`, `WebReader._execute_strategy`.
- `src/reader/strategies/` — all six strategy implementations.
- `src/reader/cloudflare/challenge_detector.py` — `ChallengeDetector.is_blocked`, `is_login_required`,
  `is_login_redirect_url`.
- `src/validator/content_validator.py` — `ContentValidator.validate` governs whether a strategy result is accepted.
- [ADR-003](ADR-003-novnc-ngrok-captcha-intervention.md) — covers the NoVNC end of the chain.
