Every command runs from `apps/ascend-web-hunter/` through the module's own virtual environment, as
`.venv/Scripts/python.exe -m <tool>` on Windows or `.venv/bin/python -m <tool>` on Linux and macOS. The test gate is
`python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`.

## 1. Configuration and dependencies

- [ ] 1.1 Add `patchright` and `camoufox` to `pyproject.toml` with exact pinned versions. Verify
      `python -m pip install -e ".[dev]"` succeeds and `python -c "import patchright, camoufox"` exits 0.
- [ ] 1.2 Add `FLARESOLVERR_ENABLED` (bool, default `false`), `CAMOUFOX_ENABLED` (bool, default `true`) and
      `TIER_MEMORY_TTL_SECONDS` (int, default `86400`, minimum `60`) to `src/config/config.py`, and turn the two waits
      `playwright_strategy.py` holds as code today into settings with today's values as defaults (owner answer 100.3 of
      2026-10-09, design Answer 100.3): `NETWORKIDLE_POLL_MS` (int, default `1000`, the page-quiet poll interval, today
      `_NETWORKIDLE_POLL_MS`) and `SCROLL_PAUSE_MS` (int, default `200`, the pause between two scroll steps, today the
      literal `200` of `_scroll_page`). `playwright_strategy.py` reads both from `settings`, and the constant
      `_NETWORKIDLE_POLL_MS` and the literal `200` are removed. Verify with cases in
      `tests/config/test_config.py` for each default, a valid override and a rejected value. The default in
      `config.py` is the same value as the compose default of task 1.4 (owner rule 98 of 2026-10-08).
- [ ] 1.3 Fetch both browser builds at image build time in `apps/ascend-web-hunter/Dockerfile`. Verify
      `docker build -t ascend-web-hunter:latest .` succeeds and a container started from it launches each browser
      once with no network fetch, by reading its logs.
- [ ] 1.4 Pass the five settings of task 1.2 through the `ascend-web-hunter` service of
      `compose.ascend-web-hunter.yaml` and of `deploy-standalone/compose.yaml` as `- <NAME>=${<NAME>:-<default>}`
      with the default of task 1.2: `- FLARESOLVERR_ENABLED=${FLARESOLVERR_ENABLED:-false}`,
      `- CAMOUFOX_ENABLED=${CAMOUFOX_ENABLED:-true}` and
      `- TIER_MEMORY_TTL_SECONDS=${TIER_MEMORY_TTL_SECONDS:-86400}`, `- NETWORKIDLE_POLL_MS=${NETWORKIDLE_POLL_MS:-1000}`
      and `- SCROLL_PAUSE_MS=${SCROLL_PAUSE_MS:-200}` (owner rule 98 of 2026-10-08, owner answer 100.3 of 2026-10-09).
      Under the sync rule,
      in the same commit as task 1.2, add each name as a commented line with its default and a one-line comment, in the
      form of `# RATE_LIMIT_DEFAULT=1200/minute`, to the root `.env.example` and `deploy-standalone/.env.example`, and a
      row (Required `No`, the default named) to the configuration table of `deploy-standalone/README.md`. Verify with
      `docker compose config` (read only) from the repository root and in `deploy-standalone/` showing each variable
      with its default on the service, the same command with `TIER_MEMORY_TTL_SECONDS=3600` set in the shell of that
      one command showing the override, and a search of both `.env.example` files and the bundle README finding each
      name once.

## 2. The two tiers

- [ ] 2.1 Create `src/reader/strategies/patchright_strategy.py` mirroring `playwright_strategy.py`: session
      `storage_state` replay, the fingerprint, the proxy seam, the browser request guard of design D6 built on the library
      guard of `add-ascend-python-common` (`check_fetch_uri` and its `FetchTarget`, owner answer 63.2), scroll
      handling and the `ChallengeDetector.assess` verdict on the initial response and after render. It reads the
      waits and scroll values the Playwright tier reads, from the same settings (`DYNAMIC_CONTENT_WAIT`,
      `SCROLL_ITERATIONS`, `SCROLL_STEP_PX`, `NETWORKIDLE_POLL_MS` and `SCROLL_PAUSE_MS`), never a copy (design, Answer
      98 and Answer 100.3). Verify with
      `tests/reader/strategies/test_patchright_strategy.py` using a mocked browser, covering replay, a wall verdict
      raising `ChallengeDetectedException`, and a clean page returning HTML.
- [ ] 2.2 Create `src/reader/strategies/camoufox_strategy.py` the same way, with the Firefox fingerprint family per
      `design.md` D4. Verify with `tests/reader/strategies/test_camoufox_strategy.py`, including a test that a stored
      Chromium user agent is not injected into Camoufox.
- [ ] 2.3 Add `4a-patchright` and `4b-camoufox` to `TierName` and to `TIER_ORDER` in `src/reader/web_reader.py`
      after `4-playwright_stealth`, and register both strategies. Verify with a test that a page blocking
      `4-playwright_stealth` and `4a-patchright` succeeds at `4b-camoufox`, and that `CAMOUFOX_ENABLED=false` skips it.
- [ ] 2.4 Accept the two new values on REST (`tier` field) and MCP (`web_read` `tier` argument, docstring included).
      Verify with tests in `tests/api/` that both values start the chain at that tier.
- [ ] 2.5 Create `src/reader/browser_guard.py` with the guarded route handler of design D6 (ad blocklist, then
      `check_fetch_uri` with the web-hunter policy, `route.abort("blockedbyclient")` on a refusal,
      `route.fetch(max_redirects=0)` and `route.fulfill(response=...)` on a pass, `data:` and `blob:` passed), and the
      WebSocket check with `context.route_web_socket` when the pinned Playwright version offers it. Install it on the
      context with `service_workers="block"` before the first navigation in `4-playwright_stealth`, `4a-patchright`,
      `4b-camoufox`, the browser of `6-novnc` and the pre-navigation hook of `5-crawlee_adaptive` (in place of the ad
      blocklist handler), and pass the static HTTP path of the Crawlee tier through `check_fetch_uri`. Owner decision 66
      of 2026-10-04. Verify with `tests/reader/test_browser_guard.py` using a faked route: a private URL is aborted and
      never fetched, a public URL is fetched with `max_redirects=0` and fulfilled, a blocklisted URL is aborted, `data:`
      passes, `ftp:` is refused, and a refused main navigation raises `UnsafeUriError`.
- [ ] 2.6 Integration test `tests/integration/test_browser_ssrf.py` with a real Chromium and a real Firefox on a local
      test server reached through the resolver seam of the tests: for each browser tier, a public page that redirects
      to `169.254.169.254`, a page that loads an image from `10.0.0.5`, and a page that sets `window.location` to
      `127.0.0.1:6379`. Verify that the private addresses receive no connection (a listener on each stays silent), the
      redirect and the script navigation answer `unsafe_uri` on REST and as a tool error on MCP, and the page with the
      private image is still returned. Record the read time of the e2e pages with and without the guard under this
      task.
- [ ] 2.7 Amend ADR-012 and write ADR-015 (task 5.2) with the browser request guard and the residual DNS rebinding
      window of `route.fetch`. Verify both files name `browser_guard.py`.
- [ ] 2.8 Owner answer 94.6 of 2026-10-08 (design D7): while `CAMOUFOX_ENABLED` is false, a REST read whose `tier` is
      `4b-camoufox` answers HTTP 409 with a problem body of `code` `tier_disabled` whose `detail` names `4b-camoufox`,
      and the MCP `web_read` call with that `tier` answers a tool error starting with `tier_disabled: ` that names the
      same tier. Register `tier_disabled` in the service's error registry with status 409, the one status of the code,
      so the disabled FlareSolverr of task 3.1 answers 409 too. Tests first, on both surfaces: the switched-off tier
      answers as above and no tier runs (no strategy is called), the same request with `CAMOUFOX_ENABLED` true runs at
      `4b-camoufox`, and a read without `tier` and the switch off skips `4b-camoufox` as task 2.3 says. Verify: the
      tests fail before the code and pass after, inside the gate of task 6.1.

## 3. FlareSolverr behind the flag

- [ ] 3.1 Skip `3-flaresolverr` in the ladder when `FLARESOLVERR_ENABLED` is false and answer HTTP 409 (REST, owner
      answer 94.6 of 2026-10-08, design D7: one status for the code `tier_disabled`, confirmed for this tier by owner
      answer 95.3 of 2026-10-08, the same answer as the switched-off `4b-camoufox`) with a
      problem body of `code` `tier_disabled` or a `ToolError` (MCP) starting with `tier_disabled: `, naming the disabled
      tier, when a caller selects it (owner answer 67.7 of 2026-10-04, design D2). Verify with tests for both surfaces and both
      flag values.
- [ ] 3.2 Probe FlareSolverr in `src/api/readiness.py` and show it in `src/config/startup_banner.py` only when enabled.
      Verify with tests that `/ready` ignores an unreachable `FLARESOLVERR_URL` when the flag is false.
- [ ] 3.3 Route a stored session with `produced_by` `3-flaresolverr` to the browser tiers when the flag is false, per
      the MODIFIED requirement in `specs/web-search-authenticated-sessions/spec.md`. Verify with a test in
      `tests/reader/test_web_reader.py`.

## 4. Tier memory

- [ ] 4.1 Create `src/reader/tier_memory.py` with `get(url)` and `record(url, tier)` over the key
      `tier_memory:{CookieManager.registrable_domain(url)}` and `TIER_MEMORY_TTL_SECONDS`. Verify with
      `tests/reader/test_tier_memory.py` using a fake Redis: set, overwrite by a cheaper tier, no overwrite by a dearer
      tier, expiry, and a Redis error returning `None` with a WARNING log.
- [ ] 4.2 Start the ladder at the remembered tier in `web_reader.py`, with caller `tier` and session producer taking
      precedence. Verify with tests for each precedence case.

## 5. Documentation

- [ ] 5.1 Update `apps/ascend-web-hunter/AGENTS.md`, `README.md` and `docs/configuration.md` with the ladder, the two
      tier values and the five settings of task 1.2. The rows of `docs/configuration.md` (the per-service configuration reference
      of ascend-web-hunter, owner rule 98 of 2026-10-08) go in the same commit as the settings of task 1.2, each with
      its default and its description ending with "Added by `enhance-web-search-tier-ladder`.". Verify each setting
      name appears in all three files and that each row this change adds to `docs/configuration.md` ends with "Added by
      `enhance-web-search-tier-ladder`.".
- [ ] 5.2 Write `docs/architecture/decisions/ADR-015-patched-browser-tiers-and-tier-memory.md` and add it to the
      decisions `README.md` index. Amend ADR-011 with the two new public values, dated. Verify ADR-011's existing
      values are unchanged.
- [ ] 5.3 Bump `pyproject.toml`, the `AGENTS.md` version line and the version in
      `docs/architecture/arc42/02-constraints.md` from `0.0.10` (set by `detect-challenge-walls-in-any-language`) to
      `0.0.11` and add one `## [0.0.11]` CHANGELOG entry at the top (owner decision of 2026-10-08, one named version per
      change, in build order). Verify the four agree and `## [0.0.11]` is the topmost version heading.

## 6. Verification

- [ ] 6.1 Run the test gate, `python -m ruff check .` and `python -m mypy src tests`. Verify all pass with no suppression
      added.
- [ ] 6.2 Rebuild the stack from the repository root with `docker compose up -d --build` and read
      `https://nowsecure.nl` through `POST /api/v2/web/read` with `tier` `4a-patchright`. Verify HTTP 200 or 428, never
      500, and that `/metrics` counts the tier.
- [ ] 6.3 Record the image size before and after in the CHANGELOG entry from 5.3.
- [ ] 6.4 Update the ascend-web-hunter e2e specs for FlareSolverr off by default (owner decision 65.12 of 2026-10-04):
      in `apps/ascend-web-hunter/e2e/testing/6-tiered-scraping-test.md` row 2 asserts that the Cloudflare page is
      passed by a browser tier (`mode` one of `4-playwright_stealth`, `4a-patchright`, `4b-camoufox`) instead of by
      FlareSolverr, and its cool-down note names the browser tier instead of the FlareSolverr log line. In the same file
      rows 4 and 5-8, now `TBD`, point to spec 11 and spec 7 (owner decision 65.26 of 2026-10-04). Update every
      other e2e file that names FlareSolverr in the same way: `e2e/README.md`, `e2e/fixtures/README.md`,
      `e2e/testing/README.md`, specs `3-read-example-com-test.md`, `7-authenticated-realworld-scraping-test.md`,
      `8-session-clear-test.md`, `10-session-establish-test.md`, `11-captcha-solve-and-capture-test.md` and
      `12-clearance-reuse-test.md`, and the templates `6-tiered-scraping-tasks.template.md`,
      `7-authenticated-realworld-scraping-tasks.template.md`, `11-captcha-solve-and-capture-tasks.template.md` and
      `12-clearance-reuse-tasks.template.md`. Past run records under `e2e/testing/runs/` stay as they are, because they
      record what ran. Verify that a search for `FlareSolverr` in `e2e/` outside `runs/` finds only text that says it
      is off by default, and that spec 6 passes on a stack with `FLARESOLVERR_ENABLED=false`, run alone as the heavy
      spec rule asks, after asking the owner which run scenario to use.

## 7. End-to-end coverage

Owner request of 2026-10-04: every behaviour this change adds has an end-to-end test. The shared fake site, the problem
body check and the scenario rule are design D10 to D14 of `add-web-search-scraping-e2e`, built by its tasks 7.1 to 7.3, 7.5 and 7.6 and by `add-ascend-python-common` (build group 2, position 1), which carries its tasks 7.4, 7.7 and 7.8 (the Bruno variables, the problem body check and the allow list) since the dependency fix of 2026-10-05.

- [x] 7.1 The owner answered which `code` the 400 for a disabled tier carries: `tier_disabled` (owner answer 67.7 of
      2026-10-04). It is recorded in design D2, in task 3.1 and in the spec requirement "FlareSolverr is disabled by
      default for one release", and `remove-flaresolverr-tier` uses the same code for the removed value. Owner answer
      93 of 2026-10-08 changes the last part: `remove-flaresolverr-tier` drops the removed value from the accepted
      values, so it answers the normal 400 validation error (its design D1). The code of this change is unchanged.
      Rework by owner decision 94.6 of 2026-10-08: task 2.8.
- [ ] 7.2 Write the new automated spec `apps/ascend-web-hunter/e2e/testing/<N>-tier-ladder-and-guard-test.md` (`<N>`
      the next free number at implementation time) and its template. Reset deletes `tier_memory:<fake site domain>` in
      Redis and empties the fake site request log. Part A uses only the blocked name `e2e-fake-site-blocked`:
      1. For each of `1-beautifulsoup`, `2-trafilatura`, `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` and
         `5-crawlee_adaptive`, a REST read of a fake site path under its blocked name `e2e-fake-site-blocked` with that `tier` answers HTTP 400
         with the problem body check of design D13 of `add-web-search-scraping-e2e` and `code` `unsafe_uri`, and the
         MCP `web_read` call for `4a-patchright` answers a tool error starting with `unsafe_uri`. The fake site request
         log shows no request to any of those paths.
      Part B reads pages under the allowed name `e2e-fake-site` (design D12 of `add-web-search-scraping-e2e`, owner answer 67.3 of 2026-10-04):
      2. For each tier of step 1, a read of a fake site page under the allowed name that answers a redirect to a fake site path under the blocked name
         answers HTTP 400 `unsafe_uri`, and the request log shows no request to the private path.
      3. For each browser tier (`4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive`), a read of
         a page under the allowed name that loads an image from a fake site path under the blocked name answers HTTP 200 `status` `success` with the
         page's canary sentence, and the request log shows no request to the image path.
      4. For each browser tier, a read of a page under the allowed name whose script sets `window.location` to a fake site path under the blocked name
         answers HTTP 400 `unsafe_uri`, and the request log shows no request to that path.
      5. A read of the fake site article with `tier` `4a-patchright` answers HTTP 200 with `mode` `4a-patchright`, and
         with `tier` `4b-camoufox` answers HTTP 200 with `mode` `4b-camoufox`.
      6. A read of the JavaScript-only page with no `tier` answers HTTP 200 with its canary sentence and a browser tier
         as `mode`. Redis then holds `tier_memory:<fake site domain>` with that tier and a TTL no larger than
         `TIER_MEMORY_TTL_SECONDS`, and a second read of the same page under a new query string (so the read cache cannot
         answer) answers with the same `mode`.
      Concurrency: writes only `tier_memory:<fake site domain>`, opens no NoVNC flow, safe beside every spec that does
      not read the fake site's JavaScript-only page. Verify every assertion is an HTTP status, a response body, a Redis
      key or the fake site request log, never a log line. The former steps on a selected `3-flaresolverr` and on
      `/ready` without FlareSolverr are not in the spec: the unit tests of tasks 3.1 and 3.2 prove both (owner answer
      91.3 of 2026-10-08).
- [ ] 7.3 Add the Bruno requests of task 7.2 in the folder `docs/api/request/AscendAI/web-hunter/testing/tier-ladder/`
      (`private-target-per-tier.yml` with the tier from an env variable, `mcp-private-target.yml`,
      `redirect-to-private-per-tier.yml`,
      `private-subresource-per-tier.yml`, `script-navigation-per-tier.yml`, `patched-tier-serves.yml`,
      `tier-memory-first.yml`, `tier-memory-second.yml`), each with its assertions in the request file. Verify each runs
      with `bru run "<file>" --env ascend-local` against a live stack.
- [ ] 7.4 Move the live check of task 6.2 into spec 7 as a best-effort row `ak`: `https://nowsecure.nl` read with `tier`
      `4a-patchright` must answer HTTP 200 `success` or HTTP 428 with the human help problem body, never a 5xx, with its
      Bruno request `realworld-ak-nowsecure-patchright.yml` and the matching template row. Verify the template row set
      matches the spec row set item for item.
- [ ] 7.5 Add the new spec of task 7.2 to the spec lists, counts and run order of scenarios 1 to 6 and of the
      ascend-web-hunter service suite in `docs/E2E_RUN_SCENARIOS.md`, and to `e2e/README.md`'s capability table and
      `e2e/testing/README.md`'s ordered list. Verify every count in the document still adds up.
- [ ] 7.6 Ask the owner which run scenario to use, then run the new spec of task 7.2 and spec 7. Verify both run records
      under `e2e/testing/runs/` read PASS, and attach them to this change.
