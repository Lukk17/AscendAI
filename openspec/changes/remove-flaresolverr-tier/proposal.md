## Why

`enhance-web-search-tier-ladder` keeps FlareSolverr for one release behind `FLARESOLVERR_ENABLED`, default `false`,
and adds the patched-browser tiers `4a-patchright` and `4b-camoufox` that do its job and render the page too. The
owner decided on 2026-10-01 that FlareSolverr is then removed with every reference. This is that follow-up, written
out in full. It is not started and must not start until the tier-ladder change has shipped for one release.

## What Changes

- The `3-flaresolverr` tier, its strategy, its settings, its container, its readiness probe, its banner line, its
  circuit breaker, its proxy branch, its cookie producer constant and its tests are deleted.
- `3-flaresolverr` stays a reserved public value from ADR-011: a caller that passes it gets HTTP 400 naming a removed
  tier, never a silent start at another tier. The value is never reused.
- A stored session with `produced_by` `3-flaresolverr` is replayed by the browser tiers.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `web-search-authenticated-sessions`: the FlareSolverr persistence requirement is removed, and the capture
  requirement no longer names a FlareSolverr tier. The replay requirements modified by
  `enhance-web-search-tier-ladder` are rewritten without FlareSolverr in task 1.1, after that change is archived, so
  this change's deltas apply to the archived text.

## Dependencies and Build Order

Depends on `enhance-web-search-tier-ladder` being archived and released for one release. Independent of
`enhance-web-search-extraction-and-tiers` and `enhance-web-search-crawl-at-scale`.

## Impact

Code, compose and docs that name FlareSolverr today, measured on 2026-10-01 with a recursive search:

- `compose.ascend-web-hunter.yaml` (the `flaresolverr` service, its port 8191 on 127.0.0.1, the `depends_on` and the
  `FLARESOLVERR_URL` variable) and `apps/ascend-web-hunter/deploy-standalone/compose.yaml` plus its `README.md`.
- `apps/ascend-web-hunter/src/`: `reader/strategies/flaresolverr_strategy.py`, `reader/web_reader.py`,
  `reader/cloudflare/cookie_manager.py` (`PRODUCED_BY_FLARESOLVERR`), `api/readiness.py`, `api/mcp/mcp_server.py`,
  `config/config.py` (`FLARESOLVERR_URL`, `FLARESOLVERR_ENABLED`), `config/startup_banner.py`,
  `circuit_breaker/breaker.py`, `proxy/proxy_provider.py`.
- `apps/ascend-web-hunter/tests/`: `reader/strategies/test_flaresolverr_strategy.py`,
  `test_flaresolverr_circuit_breaker.py`, `test_flaresolverr_unconditional_save.py`, and the FlareSolverr cases in
  `conftest.py`, `api/test_readiness.py`, `api/mcp/test_mcp_read_controls.py`, `api/rest/test_rest_read_controls.py`,
  `reader/cloudflare/test_cookie_manager_auth_presence.py`, `reader/cloudflare/test_cookie_manager_session.py`,
  `reader/test_web_reader.py`, `reader/test_web_reader_428_propagation.py`, `reader/test_web_reader_tier_override.py`
  and `test_proxy_provider.py`.
- `apps/ascend-web-hunter/Dockerfile`: no FlareSolverr reference today. The Camoufox and Patchright build steps added
  by the tier-ladder change stay.
- Docs: root `AGENTS.md` (the scrapper service table and the four fixed container names, which become three),
  `apps/ascend-web-hunter/AGENTS.md`, `README.md`, `CHANGELOG.md`, `docs/configuration.md`, `docs/running.md`,
  `docs/api-examples.md`, `docs/README.md`, the arc42 sections 01 to 12 that name it, the container diagram, and
  ADR-001, ADR-002, ADR-005, ADR-006, ADR-010, ADR-011 and ADR-012, each amended rather than rewritten.
- Root `.env.example` and `deploy-standalone/.env.example` if either names `FLARESOLVERR_URL`.

## Relevant Skills

- `/python-patterns`
- `/tdd-workflow`
- `/docker-patterns`
- `/architecture-decision-records`
- `/markdown-writer`
