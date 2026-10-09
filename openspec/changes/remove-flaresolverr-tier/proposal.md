## Why

`enhance-web-search-tier-ladder` keeps FlareSolverr for one release behind `FLARESOLVERR_ENABLED`, default `false`,
and adds the patched-browser tiers `4a-patchright` and `4b-camoufox` that do its job and render the page too. The
owner decided on 2026-10-01 that FlareSolverr is then removed with every reference. This is that follow-up, written
out in full. It is not started and must not start until the tier-ladder change has shipped for one release.

## What Changes

- The `3-flaresolverr` tier, its strategy, its settings, its container, its readiness probe, its banner line, its
  circuit breaker, its proxy branch, its cookie producer constant and its tests are deleted.
- `3-flaresolverr` is removed from the accepted tier values: a caller that passes it gets the normal HTTP 400
  validation refusal for a value outside the allowed set, never a silent start at another tier (owner answer 93 of
  2026-10-08). The value is never reused.
- Session records that the FlareSolverr tier stored before this change get no special handling and no migration.
  The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep. This holds only until the first real
  customer deployment.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `web-search-authenticated-sessions`: the FlareSolverr persistence requirement is removed, the capture
  requirement no longer names a FlareSolverr tier, "Stored session is replayed into every fetch tier" is modified
  without FlareSolverr from the text `enhance-web-search-tier-ladder` gives it, and "A stored session is replayed by
  the tier that earned it" is removed and replaced by "A stored session is replayed by the browser family that earned
  it", which keeps only its browser rule. A MODIFIED block cannot drop the FlareSolverr scenarios of that requirement,
  so it is removed and added under the new name (review fix of 2026-10-08).
- `web-search-antibot-evasion`: the proxy requirement no longer lists FlareSolverr among the tiers that route
  through the proxy, because its proxy branch is deleted.
- `web-search-tier-ladder`: the requirement "FlareSolverr is disabled by default for one release" is removed, the
  requirement "Ladder order with two patched-browser tiers" no longer lists `3-flaresolverr`, and a new requirement
  says the removed value `3-flaresolverr` is refused on both surfaces as a value outside the allowed set and that no
  FlareSolverr component remains.

## Dependencies and Build Order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 2 (web-hunter),
position 7. It needs `enhance-web-search-tier-ladder` (position 5), which lands before it, archived and released for
one release with `FLARESOLVERR_ENABLED=false`, and the e2e files that task 6.4 of that change updated. It does not need
`enhance-web-search-extraction-and-tiers` (position 6), which lands between the two, and
`enhance-web-search-crawl-at-scale` (position 9) and `add-file-download` (position 10) land after it on a service with
no FlareSolverr tier.

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
  ADR-001, ADR-002, ADR-005, ADR-006, ADR-010, ADR-011 and ADR-012, each amended rather than rewritten, and the new
  ADR-018 that records the removal. The version moves from 0.0.12 to 0.0.13, and
  `docs/architecture/arc42/02-constraints.md` names it.
- Root `.env.example` and `deploy-standalone/.env.example` if either names `FLARESOLVERR_URL`.
- e2e: the tier-ladder spec needs no update, because it no longer holds a FlareSolverr step (owner answer 91.3 of 2026-10-08), FlareSolverr removed from every e2e
  file outside past run records, from the Bruno collection and from `docs/E2E_RUN_SCENARIOS.md` (three fixed
  container names instead of four).

## Relevant Skills

- `/python-patterns`
- `/tdd-workflow`
- `/docker-patterns`
- `/architecture-decision-records`
- `/markdown-writer`
