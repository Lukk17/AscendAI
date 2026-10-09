Not started. Start only after `enhance-web-search-tier-ladder` is archived and has shipped for one release with
`FLARESOLVERR_ENABLED=false`. Every command runs from `apps/ascend-web-hunter/` through `.venv/Scripts/python.exe -m`
(Windows) or `.venv/bin/python -m` (Linux and macOS).

## 1. Preconditions

- [x] 1.2 Owner decision 65.12 of 2026-10-04: the owner agreed to the removal, and no owner answer is needed about
      `FLARESOLVERR_ENABLED`. The e2e files that name FlareSolverr are updated by task 6.4 of
      `enhance-web-search-tier-ladder`, starting with row 2 of `e2e/testing/6-tiered-scraping-test.md`.

Task 1.1 removed: the spec deltas against the `enhance-web-search-tier-ladder` text are written in this change now
(review fix of 2026-10-08, owner answer of 2026-10-08).

## 2. Code

- [ ] 2.1 Delete `src/reader/strategies/flaresolverr_strategy.py` and remove `3-flaresolverr` from `TierName` and
      `TIER_ORDER` in `src/reader/web_reader.py`, so it is refused like any value outside the allowed set per D1
      (owner answer 93 of 2026-10-08). Verify with tests on both surfaces that the value answers HTTP 400 with the
      problem body code `validation` on REST and an invalid argument refusal on MCP, and that no tier runs.
- [ ] 2.2 Remove FlareSolverr from `src/api/readiness.py`, `src/config/startup_banner.py`,
      `src/circuit_breaker/breaker.py`, `src/proxy/proxy_provider.py` and `src/api/mcp/mcp_server.py`, and remove
      `FLARESOLVERR_URL` and `FLARESOLVERR_ENABLED` from `src/config/config.py`. Remove the `tier_disabled` handling
      the FlareSolverr flag needed. Keep the `tier_disabled` registry entry (status 409), because `4b-camoufox` still
      raises it while `CAMOUFOX_ENABLED` is false (owner answer 94.6 of 2026-10-08, `enhance-web-search-tier-ladder`
      D7 and task 2.8), and keep its test. In the same commit (owner rule 98 of 2026-10-08), remove the two settings
      everywhere they are listed: their rows in `docs/configuration.md` (task 4.1), the `FLARESOLVERR_URL` and
      `FLARESOLVERR_ENABLED` lines of the `ascend-web-hunter` service in both compose files, and the
      `FLARESOLVERR_ENABLED` lines and rows that `enhance-web-search-tier-ladder` task 1.4 added to both `.env.example`
      files and the bundle README (task 3.1). Verify a recursive search of `src/` for `flaresolverr`, ignoring case,
      finds nothing, and a search of both compose files, both `.env.example` files, the bundle README and
      `docs/configuration.md` finds neither setting name.
- [ ] 2.3 Delete the `PRODUCED_BY_FLARESOLVERR` constant and its handling in `src/reader/cloudflare/cookie_manager.py`
      with no special case for old records, per D2. Verify a recursive search of `src/` and `tests/` finds no
      `PRODUCED_BY_FLARESOLVERR`.
- [ ] 2.4 Delete `tests/reader/strategies/test_flaresolverr_strategy.py`, `test_flaresolverr_circuit_breaker.py` and
      `test_flaresolverr_unconditional_save.py`, and remove the FlareSolverr cases from every other test file listed
      in `proposal.md`. Verify the gate
      `python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` passes.

## 3. Compose and deployment

- [ ] 3.1 Remove the `flaresolverr` service and every reference to it from `compose.ascend-web-hunter.yaml` and
      `apps/ascend-web-hunter/deploy-standalone/compose.yaml` in the same commit, and from both `.env.example` files and
      the configuration table of `deploy-standalone/README.md` (the `FLARESOLVERR_ENABLED` row and lines of
      `enhance-web-search-tier-ladder` task 1.4 included, sync rule). The host port setting `FLARESOLVERR_HOST_PORT`
      of `fix-linux-docker-host-access` task 10.2 (owner answer 100.6 of 2026-10-09) goes in the same commit: its
      published port line, its commented line in the root `.env.example`, the "FlareSolverr port 8191" row of the
      differences table of `deploy-standalone/README.md` and its row in `docs/CONFIGURATION.md`.
      Verify `docker compose config` from the repository root succeeds and lists no `flaresolverr` service, and a
      search of the root `.env.example`, `deploy-standalone/README.md` and `docs/CONFIGURATION.md` finds no
      `FLARESOLVERR_HOST_PORT`.

## 4. Documentation

- [ ] 4.1 Update the root `AGENTS.md`, `apps/ascend-web-hunter/AGENTS.md`, `README.md`, `docs/configuration.md`,
      `docs/running.md`, `docs/api-examples.md`, `docs/README.md`, `deploy-standalone/README.md`, the arc42 sections
      and the container diagram. The rows of `FLARESOLVERR_URL` and `FLARESOLVERR_ENABLED` leave `docs/configuration.md`
      (the per-service configuration reference of ascend-web-hunter, owner rule 98 of 2026-10-08) in the same commit as
      task 2.2 removes the settings. Verify a recursive search of the module docs finds FlareSolverr only in history
      sections, ADR amendments and the CHANGELOG.
- [ ] 4.2 Amend ADR-001, ADR-002, ADR-005, ADR-006, ADR-010, ADR-011 and ADR-012 with a dated note, and write
      `docs/architecture/decisions/ADR-018-flaresolverr-tier-removed.md` recording the removal (ADR-013 to ADR-017 are
      taken by the group 2 changes before this one, see design D4), with its line in the ADR index. Verify each
      amended ADR keeps its status line and the index links ADR-018.
- [ ] 4.3 Bump `version` in `pyproject.toml`, the version line in `AGENTS.md` and the version in
      `docs/architecture/arc42/02-constraints.md` from `0.0.12` (set by `enhance-web-search-extraction-and-tiers`) to
      `0.0.13`, and add one `## [0.0.13]` CHANGELOG entry at the top (design D4, owner decision of 2026-10-08, one named
      version per change, in build order). Verify the four agree and `## [0.0.13]` is the topmost version heading.

## 5. End-to-end coverage

Owner request of 2026-10-04: every planned change carries end-to-end tests. The problem body check and the scenario
rule are design D13 and D14 of `add-web-search-scraping-e2e`. When a feature changes, its existing numbered spec and
tasks template are updated in place, and a new spec is written only when an existing one cannot be updated to cover the
change (owner answer 67.2 of 2026-10-04). The tier-ladder spec of `enhance-web-search-tier-ladder` task 7.2 no longer
holds a FlareSolverr step (owner answer 91.3 of 2026-10-08), so it needs no update here. The refusal of the removed
value and the readiness without FlareSolverr are proven by the unit tests of tasks 2.1 and 2.2, and the missing
container by the check of task 3.1.

- [ ] 5.3 Remove FlareSolverr from every e2e file outside `e2e/testing/runs/`: the prerequisites, the flow diagram and
      the ordering notes of `apps/ascend-web-hunter/e2e/README.md`, `e2e/testing/README.md`, `e2e/fixtures/README.md`,
      every spec and template that still names it after `enhance-web-search-tier-ladder` task 6.4, and the Bruno
      requests that name it. Past run records stay as they are. Verify a search for `flaresolverr`, ignoring case, in
      `apps/ascend-web-hunter/e2e/` outside `runs/` and in `docs/api/request/AscendAI/web-hunter/` finds nothing.
- [ ] 5.4 In `docs/E2E_RUN_SCENARIOS.md`, change the four fixed container names to three, drop `flaresolverr` from every
      precondition and service list, and keep the tier-ladder spec where it is listed in every scenario and the
      ascend-web-hunter service suite (this change does not touch it, so no count changes because of it). Verify every count in the document still adds up and no scenario names
      FlareSolverr.
- [ ] 5.5 Ask the owner which run scenario to use, then run the tier-ladder spec of `enhance-web-search-tier-ladder`
      task 7.2 and the web-hunter specs that read Cloudflare pages (spec 6 and spec 12) on a stack without
      FlareSolverr. Verify each run record under `e2e/testing/runs/` reads PASS, and attach them to this change.

Task 5.1 removed by owner decision 91.3 of 2026-10-08.
Task 5.2 removed by owner decision 91.3 of 2026-10-08.
