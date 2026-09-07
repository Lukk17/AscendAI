# ADR-002: Cloudflare cookie persistence in Redis

## Status

Accepted — 2026-05-31

## Context

Cloudflare clearance cookies (`cf_clearance`) are short-lived session tokens that prove a client has passed a
Cloudflare challenge. Once acquired through FlareSolverr or NoVNC, they are valid for a window of several hours
on the issuing domain. Without persistence, every new request to a Cloudflare-protected domain must either
re-invoke FlareSolverr or interrupt the user again for a manual CAPTCHA solve.

The service runs as a single container today but is designed for multi-instance deployment. A purely in-process
dict cannot be shared across replicas. Cookies also need to survive a container restart without forcing a fresh
CAPTCHA solve on every startup.

The cookie is tied to both a domain and the User-Agent that was used when it was issued. Using the wrong
User-Agent with a valid `cf_clearance` still results in a challenge failure. The persistence store must therefore
carry both cookie values and the originating User-Agent together.

## Decision

`CookieManager` (`src/reader/cloudflare/cookie_manager.py`) is a module-level singleton that persists session
data to Redis under the key `session_cookies:{apex_domain}` with a default TTL of 7200 seconds (2 hours).

Domain normalisation strips subdomains to the apex (`www.linkedin.com` becomes `linkedin.com`) so that cookies
acquired on the login subdomain are reused when the same crawl later visits a content subdomain of the same
site. The normalisation is in `_get_domain` (`src/reader/cloudflare/cookie_manager.py:40-62`) and uses
`tldextract` against the Public Suffix List, so ccTLDs like `co.uk`, `com.au`, `gov.pl` resolve to the correct
registrable domain (`example.co.uk` stays as `example.co.uk`, not `co.uk`). The previous naive
last-two-labels heuristic let one tenant's NoVNC-set cookies overwrite another's under a shared ccTLD; that
defect was fixed in the same commit that introduced this ADR.

The payload stored per domain is:

```json
{"cookies": {"cf_clearance": "...", ...}, "user_agent": "Mozilla/5.0 ..."}
```

If Redis is unavailable (connection failure at init or per-call), `CookieManager` falls back to an in-process
`_memory_store` dict. This means a single-instance deployment continues to function without Redis, at the cost
of losing cookie state across restarts and across instances.

Strategies that acquire cookies (`FlareSolverrStrategy`, `NoVNCStrategy`) call `cookie_manager.save_session_data`.
Strategies that consume cookies (`BeautifulSoupStrategy`, `TrafilaturaStrategy`) call `get_session_data` at the
start of every request and inject the stored cookies and User-Agent into the outbound request headers.

## Alternatives Considered

### Alternative 1: No persistence; re-solve per request
- **Pros**: Stateless; no Redis dependency.
- **Cons**: Every request to a Cloudflare-protected domain re-invokes FlareSolverr or blocks for a human solve.
  NoVNC CAPTCHA solves take minutes; re-triggering on every request makes the service unusable for repeated crawls
  of the same domain.
- **Why not**: Unacceptable user experience for any repeated crawl scenario.

### Alternative 2: Persistent database (PostgreSQL)
- **Pros**: Durable; survives container replacement indefinitely.
- **Cons**: Clearance cookies are short-lived by design (Cloudflare rotates them after 2 hours). Permanent
  persistence provides no benefit and introduces schema migration complexity. Redis TTL handles expiry natively.
- **Why not**: Overkill for data that should expire. Redis already exists in the stack as a shared dependency.

### Alternative 3: Shared file on a mounted volume
- **Pros**: No extra service dependency.
- **Cons**: Cannot be shared across replicas without a distributed filesystem. File locking under concurrent async
  writes requires extra code. Not cloud-native.
- **Why not**: Redis is already required by other platform services; adding a file-based store adds a pattern
  inconsistent with the rest of the stack.

## Consequences

### Positive
- Cloudflare clearance cookies survive container restarts (Redis TTL permitting).
- Multi-instance deployments share cookie state without coordination code.
- 2-hour TTL matches the actual Cloudflare clearance window; expired cookies are evicted automatically.

### Negative
- Redis is now a soft runtime dependency. A Redis outage silently degrades to in-process storage with no
  cross-instance sharing and no restart persistence.
- PSL handling adds a small import-time cost (a few hundred ms) and bundles the public-suffix snapshot from
  `tldextract`. The PSL itself changes rarely; refresh by bumping the `tldextract` pin.

### Risks
- **Non-PSL hostnames**: Internal addresses (`localhost`, `intranet-host`) have no recognised PSL suffix.
  `_get_domain` falls back to using the raw host as the key, which is safe but cannot collapse subdomain
  variants on internal networks.
- **TTL mismatch**: Cloudflare may shorten or lengthen its clearance window without notice. A 2-hour TTL that
  outlives the actual clearance lifespan sends expired cookies. The downstream effect is a Cloudflare challenge
  failure and re-escalation, not a security issue.

## Related

- `src/reader/cloudflare/cookie_manager.py` — `CookieManager`, `_get_domain`, `get_session_data`,
  `save_session_data`.
- `src/reader/strategies/beautifulsoup_strategy.py:29-37` — reads and injects cached session data.
- `src/reader/strategies/trafilatura_strategy.py:27-36` — reads and injects cached session data.
- `src/reader/strategies/flaresolverr_strategy.py:53-56` — saves `cf_clearance` after a successful solve.
- `src/config/config.py` — `REDIS_URL` (default `redis://localhost:6379/0`).
