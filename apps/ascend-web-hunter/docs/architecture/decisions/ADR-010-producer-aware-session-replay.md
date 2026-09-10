# ADR-010: Route a stored session by who produced it, not merely that one exists

## Status

Accepted, 2026-09-10

## Context

`WebReader._prefer_browser` treated "a stored session exists for this URL" as a single boolean, regardless of
which tier had captured it. Once that boolean was true, `_select_strategies` skipped straight to the browser
tiers (`4-playwright_stealth`, `5-crawlee_adaptive`, `6-novnc`), unconditionally, for every stored session alike.

That is correct for a session a browser earned (NoVNC or a login-seeded account): the cookies are the browser's
own, so a browser tier is the right one to replay them with. It is wrong for a WAF clearance FlareSolverr earned.
A Cloudflare `cf_clearance` cookie is bound to the browser fingerprint that solved the challenge, and FlareSolverr's
own fingerprint is not Playwright's, so handing a FlareSolverr-earned clearance to Playwright does not skip the
challenge, it re-triggers it.

Measured on 2026-09-10 with the scraping stack alone, three plain `curl` calls against the reader, no Bruno. Read 1,
`https://www.scrapingcourse.com/cloudflare-challenge` with no stored session: HTTP 200, `status="success"`, answered
through the FlareSolverr tier in 25.2 s, and a session for `scrapingcourse.com` was stored with `cf_clearance` under
`waf` and six site cookies under `auth`. Read 2, the same address again: HTTP 200 in 0.21 s, served from the reader's
in-memory read cache (`READ_CACHE_TTL_SECONDS`, 300 s), which is not cookie reuse and proves nothing about the stored
session. Read 3, the same page with a query string appended, so a different cache key on the same site, with the
stored session present: the reader skipped the cheap tiers and FlareSolverr and went straight to the Playwright
tier, the `ascend-web-hunter` container logged `PlaywrightStrategy: WAF/Cloudflare challenge did not auto-clear
within 12.0s`, fell through to `5-crawlee_adaptive` (failed) and to NoVNC, and answered HTTP 428
`status="human_intervention_required"` after 24.9 s. Holding a stored session made the second read of the same site
slower and worse than the cold first read, which is exactly backwards for what session persistence exists to buy
(registered as defect A61).

A related check confirmed the other half was already correct and did not need a fix: `FlareSolverrStrategy.get_html`
already injects whatever cookies `cookie_manager.get_flat_cookies` returns into the FlareSolverr request payload
before every call (`src/reader/strategies/flaresolverr_strategy.py`), so a FlareSolverr-produced clearance really is
replayed on the wire once the reader routes to that tier at all (this closed defect A52's open question about the
same code path).

## Decision

### D1, every session-record write names its producer

`CookieManager.save_storage_state` and `save_flat_cookies` take a `produced_by: str | None` parameter, stored
alongside `saved_at` and `user_agent` on the `auth` and `waf` sub-entries of the record (`src/reader/cloudflare/
cookie_manager.py`). Three named values cover every writer in this codebase: `PRODUCED_BY_FLARESOLVERR`
(`FlareSolverrStrategy`, the tier that solves a Cloudflare challenge and earns `cf_clearance`), `PRODUCED_BY_NOVNC`
(the NoVNC monitor's captcha and login branches, which is also what `session/establish` drives), and
`PRODUCED_BY_LOGIN_SEED`, reserved for a scripted browser login outside the reader's own tiers (the e2e seed
harness). `PlaywrightStrategy` does not currently save a session at all, so it has no producer to name yet; if it
gains one, it writes its own value the same way.

A caller that omits `produced_by` writes `None` into the entry. `CookieManager.get_stored_session_producer` reports
that as `PRODUCED_BY_UNKNOWN`, a value distinct from returning `None` outright: `None` means no valid stored session
exists, `PRODUCED_BY_UNKNOWN` means one exists but nothing on record says who earned it. A record written before
this change carries no `produced_by` key at all, which reads back the same way, `.get("produced_by")` returning
`None` and thus `PRODUCED_BY_UNKNOWN`, without a migration.

### D2, the WAF entry's producer governs routing, falling back to the auth entry's

`get_stored_session_producer` prefers the currently-valid `waf` entry's producer, since that is the entry a
challenge-solving tier would need to replay, and falls back to the `auth` entry's producer when no valid `waf`
entry exists (an auth-only session, e.g. a login-seeded account that never touched a WAF challenge). The two
sub-entries can carry different producers, because each is fully overwritten independently by whichever call
touches it: a `waf` entry FlareSolverr just refreshed and an `auth` entry a login-seed wrote earlier both stay
individually accurate this way, rather than one record-level field going stale the moment either sub-entry is
rewritten by a different tier.

### D3, only a FlareSolverr-produced clearance changes the escalation order

`WebReader._select_strategies` still runs the full six-tier ladder when no stored session exists, and still
routes straight to the browser tiers under `heavy_mode`, an explicit caller preference that outranks producer
routing and is checked first. Otherwise, when a stored session exists: if `get_stored_session_producer` returns
`PRODUCED_BY_FLARESOLVERR`, the reader runs `3-flaresolverr` first (with its stored cookies injected exactly as
D1's related check confirmed), then the browser tiers exactly as before if it fails. Any other producer,
including `PRODUCED_BY_NOVNC`, `PRODUCED_BY_LOGIN_SEED`, and `PRODUCED_BY_UNKNOWN`, keeps today's behaviour:
straight to the browser tiers, cheap tiers and FlareSolverr both skipped. The read-result cache (`READ_CACHE_TTL_
SECONDS`) is unchanged by any of this; Read 2 above already proved it answers independently of tier routing.

## Alternatives Considered

### Alternative 1: always try every tier, ignore the stored session for routing
- Pros: no new field, no routing branch, the escalation order is always the same six-tier ladder.
- Cons: throws away the entire reason `_prefer_browser` exists. A stored auth cookie (a logged-in account) is
  useless to the cheap curl-based tiers, which cannot execute the JavaScript a login wall usually gates on, so a
  real login session would be re-solved on every read instead of being replayed by the tier that can use it.
- Why not: it trades one defect (a FlareSolverr clearance handed to the wrong tier) for a worse one (no session
  ever gets replayed by the tier equipped to use it, browser or otherwise).

### Alternative 2: skip FlareSolverr's stored-cookie injection and always re-solve
- Pros: no cookie ever goes stale against a fingerprint mismatch, since none is replayed.
- Cons: throws away the entire benefit of persisting a WAF clearance at all: every read of a Cloudflare-protected
  site pays FlareSolverr's solve cost again, measured at 25.2 s on the cold read above, instead of a fast cached
  replay on a domain FlareSolverr already cleared.
- Why not: the injection already works (D1's related check), and the actual defect was the reader routing away
  from the tier that could use it, not the tier itself.

### Alternative 3: one record-level `produced_by` instead of one per sub-entry
- Pros: simpler record shape, one field to read instead of two.
- Cons: `auth` and `waf` sub-entries are already written and expire independently (different TTLs, different
  writers). A record-level field would go stale the moment a later write to one sub-entry (say, NoVNC solving a
  login after FlareSolverr already cleared the WAF) overwrote the field, making the still-valid WAF entry's real
  producer unrecoverable.
- Why not: the two sub-entries can genuinely have different producers at the same time, and routing needs the WAF
  entry's own producer specifically, not whichever save happened most recently.

## Consequences

### Positive
- A second read of a Cloudflare-protected site, after the read cache expires, replays the same FlareSolverr-earned
  clearance through FlareSolverr instead of failing through Playwright to NoVNC. The measured Read 3 case
  (428 after 24.9 s) is now expected to answer through `3-flaresolverr` the way the cold Read 1 did.
- A record from before this change, or written by a caller that has not adopted `produced_by` yet, keeps its
  current routing exactly (browser tiers first), so nothing regresses for an un-migrated writer.

### Negative
- One more field to keep in sync: any future writer of a session record needs to pass its own `produced_by` or its
  writes silently fall back to `PRODUCED_BY_UNKNOWN` routing, which is safe but not optimal for that writer's
  own tier.

### Risks
- If a future tier other than FlareSolverr starts earning a fingerprint-bound WAF cookie, `_select_strategies`
  needs its own branch for that producer too; the current code only special-cases `PRODUCED_BY_FLARESOLVERR`.

## Related

- `src/reader/cloudflare/cookie_manager.py` — `PRODUCED_BY_FLARESOLVERR`, `PRODUCED_BY_NOVNC`,
  `PRODUCED_BY_LOGIN_SEED`, `PRODUCED_BY_UNKNOWN`, `save_storage_state`, `save_flat_cookies`,
  `get_stored_session_producer`.
- `src/reader/web_reader.py` — `_select_strategies`, `_browser_tiers`.
- `src/reader/strategies/flaresolverr_strategy.py` — the stored-cookie injection this ADR's D1 related check
  confirmed already worked, and the `produced_by` tag it now writes.
- `src/reader/strategies/novnc_strategy.py` — `_poll_captcha`, `_poll_login`, both now tagging `PRODUCED_BY_NOVNC`.
- [ADR-002](ADR-002-cloudflare-cookie-persistence-redis.md), the session store this ADR extends.
- [ADR-003](ADR-003-novnc-ngrok-captcha-intervention.md), the NoVNC tier whose captures this ADR tags.
