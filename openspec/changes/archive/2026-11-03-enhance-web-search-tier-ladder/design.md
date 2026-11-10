## Context

The ladder lives in `apps/ascend-web-hunter/src/reader/web_reader.py`. `TierName` is a `Literal` of six public values
(ADR-011), and the strategies sit in `src/reader/strategies/`. Session replay, producer-aware replay (ADR-010),
coherent fingerprints (`src/reader/fingerprint.py`), the proxy seam (`src/proxy/proxy_provider.py`), connect-time
address pinning (ADR-012, which `add-ascend-python-common` D21 moves into the library guard: `check_fetch_uri`, its
`FetchTarget` and `follow_guarded_redirects`, owner answer 63.2), session validation (`session_manager.validate`) and the caller-selected
`tier` and `output_format` are all built and shipped. This change adds to them and rebuilds none of them.

## Goals and Non-Goals

Goals: two stronger free browser tiers, FlareSolverr off by default for one release, and a ladder that remembers what
worked per domain.

Non-Goals: removing FlareSolverr (follow-up `remove-flaresolverr-tier`), any CAPTCHA solver (dropped by the owner on
2026-10-01), any paid proxy or solving service, a headed browser as an automated tier (recorded as a possible
follow-up in `open-several-novnc-windows-at-once`), and anything about extraction.

## Decisions

### D1: New tiers get new public names, old names stay

ADR-011 made the tier values public. Renaming `4-playwright_stealth` would break every caller that passes it. The new
tiers are `4a-patchright` and `4b-camoufox`, placed after `4-playwright_stealth` and before `5-crawlee_adaptive`. The
order of the ladder is the order of the `TIER_ORDER` tuple in `web_reader.py`, never a sort on the name.

Rejected: replacing the Playwright engine inside `4-playwright_stealth` with Patchright. It changes what a public
value means without a new name, and a regression could not be isolated by selecting the old tier.

### D2: FlareSolverr behind a disabled-by-default flag for one release

`FLARESOLVERR_ENABLED` (default `false`). When false: the ladder skips `3-flaresolverr`, a request naming it answers
HTTP 409 (HTTP 400 until owner answer 94.6 of 2026-10-08, see D7, confirmed for this tier by owner answer 95.3 of 2026-10-08) with a problem body whose `code` is `tier_disabled` and whose `detail` names the disabled tier on REST, and a
`ToolError` whose text starts with `tier_disabled: ` on MCP (owner answer 67.7 of 2026-10-04: every disabled scraping
tier answers this code, and `remove-flaresolverr-tier` keeps it for the removed value), `readiness.py` does not probe
`FLARESOLVERR_URL`, `startup_banner.py` prints the tier as disabled, and a stored session whose `produced_by` is
`3-flaresolverr` is sent to the browser tiers (its clearance was bound to FlareSolverr's fingerprint and is likely
useless, but its auth cookies may not be). The container stays in both compose files for this release so an operator
can turn the flag on without a new image.

### D3: Per-domain tier memory in Redis

Key `tier_memory:{registrable_domain}` where the domain is `CookieManager.registrable_domain(url)`, value the tier name
that last returned accepted content, TTL `TIER_MEMORY_TTL_SECONDS` (default 86400). The TTL is the decay: when the key
expires the next read starts at the beginning of the ladder again. A success at a cheaper tier than the remembered one
overwrites it. A caller `tier` overrides the memory. A stored session's producer (ADR-010) overrides the memory too,
because a session must be replayed by the tier that earned it. A Redis failure is logged and the read climbs the full
ladder, it never fails the read.

### D4: Camoufox has its own fingerprint family

Camoufox generates a Firefox fingerprint. Injecting the Chromium fingerprint from `fingerprint.py` into it would be the
exact incoherence the antibot spec forbids. The fingerprint group is therefore chosen per browser family, and a stored
session's recorded user agent is replayed only into a tier of the same family.

### D5: Browsers are fetched at build time

The Dockerfile runs the Patchright and Camoufox fetch steps during the image build, pinned to the versions in
`pyproject.toml`. A missing browser binary is a startup error, never a download at request time.

### D6: Every browser request passes the shared URI guard before the browser connects (owner decision 66 of 2026-10-04)

Every browser tier, `4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive` and the browser of
`6-novnc`, installs one guarded route handler, `src/reader/browser_guard.py`, on its browser context with
`context.route("**/*", ...)` before the first navigation, and sets `service_workers="block"` on the context, because
Playwright's routing does not see requests a service worker makes. The Crawlee tier installs it in its pre-navigation
hook, in place of the ad blocklist handler it installs today, and its static HTTP path passes each URL through
`check_fetch_uri` too. The handler:

1. applies the ad blocklist, as the current `URLValidator.route_handler` does;
2. runs `check_fetch_uri` of `add-ascend-python-common` D21 on the request URL with the web-hunter policy (the hosts
   of `ALLOWED_PRIVATE_HOSTS`, empty by default and set only during an e2e sweep, and no file root, `add-ascend-python-common` D21
   and D22). This covers every page load, every frame and popup navigation and every subresource.
   `data:` and `blob:` URLs make no network request and pass. Any other scheme is refused;
3. on a refusal, aborts the request with `route.abort("blockedbyclient")`, so the browser opens no connection to the
   address. A refused main navigation ends the tier with `UnsafeUriError`, which the service answers as `unsafe_uri`
   (400 on REST, a tool error on MCP). A refused subresource is only blocked, and the page goes on without it;
4. on a pass, fetches the request through `route.fetch(max_redirects=0)` and hands the answer to the browser with
   `route.fulfill(response=...)`. A redirect therefore reaches the browser as a 3xx answer, the browser asks for the
   `Location` as a new request, and that request passes this handler again, so every redirect hop is checked before
   anything connects to it. `route.continue_()` is not used, because Playwright follows the redirects of a continued
   request inside the browser without calling the handler again.

WebSocket connections opened by a page are checked the same way with `context.route_web_socket`, when the pinned
Playwright version offers it, and refused otherwise. The connection made by `route.fetch` resolves the host again, so
the address pinning of the library is not applied inside the browser path. That residual DNS rebinding window is the
one ADR-012 already accepts for browsers, and ADR-015 records it. FlareSolverr needs nothing, because
`remove-flaresolverr-tier` removes it and it is off by default here.

Rejected: checking only the first URL and the final URL. A redirect chain through a private address would already have
sent a request to it, which is what the guard must prevent.

### D7: A caller who selects a switched-off tier gets 409 `tier_disabled` (owner answer 94.6 of 2026-10-08)

`CAMOUFOX_ENABLED` (default `true`) is the Camoufox switch of this change. While it is false, the ladder skips
`4b-camoufox`, and a request that names `4b-camoufox` as its `tier` answers HTTP 409 on REST with a problem body whose
`code` is `tier_disabled` and whose `detail` names the tier `4b-camoufox`, and the MCP `web_read` call answers a tool
error whose text starts with `tier_disabled: ` and names the same tier. No tier runs. 409 says that the request is
valid but conflicts with the current state of the service, which an operator can change, unlike the 400 of a value
outside the accepted tier values.

A problem code has one status in the error registry of `add-ascend-python-common` (D5 there: `ProblemCode` is a code
and a status), so the registry entry `tier_disabled` is 409 for every tier that raises it. The disabled FlareSolverr of
D2 therefore answers 409 too during its one release, which the owner confirmed (answer 95.3 of 2026-10-08).
`remove-flaresolverr-tier` later drops `3-flaresolverr` from the accepted values (its D1) and keeps the
`tier_disabled` registry entry, because `4b-camoufox` still raises it.

## Risks

- Image size grows by two browser builds. Measured in task 6.3 and recorded in the CHANGELOG.
- Camoufox is heavier than Chromium. It runs only after `4a-patchright` fails, and `CAMOUFOX_ENABLED=false` removes it.
- Tier memory can pin a domain to a slow tier for one TTL after a single bad day. The TTL bounds it, and a cheaper
  success overwrites it at once.
- Fetching every browser request through `route.fetch` adds a hop per request and can change timing a wall checks.
  Task 2.6 measures the read time of the e2e pages with and without the guard, and the guard stays on either way.

## Owner decisions of 2026-10-08

- Item 19 of the review of 2026-10-07, approved by the owner on 2026-10-08: the gate of task 6.1 runs mypy over `src tests`, the same gate as `add-ascend-python-common` D14.
- Owner decision of 2026-10-08, "one named version per change, in build order": this change ships as ascend-web-hunter 0.0.11, one patch step after 0.0.10 of `detect-challenge-walls-in-any-language` (build group 2, position 4), with one CHANGELOG entry (task 5.3).

Answer 87: confirmed, nothing to change. The tier memory of D3 already lives in Redis with a TTL, so every
ascend-web-hunter container reads and writes the same memory and no container keeps a copy of its own. The patched
browsers and the FlareSolverr and Camoufox switches are per container, which is correct because each container runs its
own browsers and reads the same settings from the same compose service. This change adds no lock, cache, counter or
queue that a second container would need to see.

Answer 92: not applied, because each would cut a capability. Review item C17 (drop the `CAMOUFOX_ENABLED` kill switch)
is skipped: the switch lets an operator take the heaviest browser off a host with little memory without a new image,
which the Risks section names, and removing it removes that. Review item B1 (remove FlareSolverr inside this change and
drop `remove-flaresolverr-tier`) is skipped by the owner's own list of things not to apply: the one release with the
flag off stays, and `remove-flaresolverr-tier` stays a change of its own.

Answer 93: no small item of the review applies to this change beyond the ones above. `remove-flaresolverr-tier` now
drops the removed value `3-flaresolverr` from the accepted values instead of answering `tier_disabled` for it (its D1,
review item C16). The `tier_disabled` answer of D2 for a disabled FlareSolverr during the one release is unchanged.

Answer 91.3: the tier-ladder spec of task 7.2 stays, and loses the two steps that only repeated unit tests: a request
for `3-flaresolverr` with the flag off (task 3.1) and `/ready` without FlareSolverr (task 3.2). Their Bruno requests
`flaresolverr-disabled.yml` and `ready-no-flaresolverr.yml` are not written. The spec keeps the guard steps, which run
the real browsers of the image on the real network, and the two new tiers and the tier memory. The live row `ak` of
spec 7 stays.

Answer 85.1: no task of this change exports a key or a secret in a shell.

Answer 94.6: when a caller asks for `4b-camoufox` while `CAMOUFOX_ENABLED` is false, ascend-web-hunter answers HTTP 409 with code `tier_disabled` and a `detail` naming the tier, and the MCP `web_read` tool answers a tool error starting with `tier_disabled: ` (new D7, new task 2.8, a new spec requirement, and task 7.1 marked for rework). A problem code has one status in the library's error registry, so the disabled FlareSolverr of D2 and task 3.1 answers 409 too during its one release. The owner confirmed that consequence in answer 95.3.

Answer 95.3: confirmed. A request for the switched-off `3-flaresolverr` during its one release answers HTTP 409 with code `tier_disabled` on REST and a tool error starting with `tier_disabled: ` on MCP, the same as the switched-off `4b-camoufox` (D2, D7, task 3.1, the spec requirement "FlareSolverr is disabled by default for one release"). The notes that asked the owner to confirm it are removed.

Answer 98: every value of this change that has a default is a setting (owner rule 98 of 2026-10-08). Settings, each
read by `config.py` with its default, passed by `compose.ascend-web-hunter.yaml` and `deploy-standalone/compose.yaml`
as `${VAR:-default}` with the same value, put into both `.env.example` files and the bundle README by the sync rule
(new task 1.4) and listed in `docs/configuration.md` with "Added by `enhance-web-search-tier-ladder`." (task 5.1):
`FLARESOLVERR_ENABLED` false, `CAMOUFOX_ENABLED` true and `TIER_MEMORY_TTL_SECONDS` 86400. Kept as constants, because
they are not operational: the tier names and their order in `TIER_ORDER` (public values of ADR-011), the Redis key
`tier_memory:{registrable_domain}`, the problem code `tier_disabled` and its status 409, the lower bound 60 of
`TIER_MEMORY_TTL_SECONDS` (a validation rule, not a value an operator tunes), the pinned versions of `patchright` and
`camoufox` (dependency pins of `pyproject.toml`), and the test-only values of the e2e spec and the integration test.
The new tiers reuse the existing settings of the Playwright tier (`EXTRACT_TIMEOUT`, `CHALLENGE_CLEAR_WAIT_SECONDS`,
`DYNAMIC_CONTENT_WAIT`, `SCROLL_ITERATIONS`, `SCROLL_STEP_PX`), so they add no timeout of their own. The two waits
that `playwright_strategy.py` holds as code today (`_NETWORKIDLE_POLL_MS` and the 200 millisecond pause between
scroll steps) become the settings `NETWORKIDLE_POLL_MS` and `SCROLL_PAUSE_MS` by owner answer 100.3 of 2026-10-09,
and every browser tier reads them from `settings`, so each value keeps one source. Tasks changed: 1.2 and 5.1, new task 1.4. No ticked task changes: task 7.1 is about the
problem code, not a setting. The proposal text that still said HTTP 400 for a disabled tier now says 409
`tier_disabled`. No test or measurement of this change uses LM Studio, and no text of this change names the old `e2e`
profile or plans several copies elsewhere.

## Owner decisions of 2026-10-09

Answer 100.3: the page-quiet poll interval that `playwright_strategy.py` holds as `_NETWORKIDLE_POLL_MS` and the 200 millisecond pause between two scroll steps become settings with today's values as defaults: `NETWORKIDLE_POLL_MS` 1000 and `SCROLL_PAUSE_MS` 200, named in the module's existing form (`SCROLL_STEP_PX`, `DYNAMIC_CONTENT_WAIT`). The Playwright tier and the two new tiers read them from `settings`, the constant and the literal are removed. Like the other settings of this change they get a `config.py` field with the same default (task 1.2), a `${VAR:-default}` line on `ascend-web-hunter` in `compose.ascend-web-hunter.yaml` and `deploy-standalone/compose.yaml` with the sync rule (task 1.4) and a row in `apps/ascend-web-hunter/docs/configuration.md` ending "Added by `enhance-web-search-tier-ladder`." (task 5.1). The two names are new and were chosen in this round from the module's naming.
