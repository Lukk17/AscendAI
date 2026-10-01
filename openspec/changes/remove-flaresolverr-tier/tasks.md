Not started. Start only after `enhance-web-search-tier-ladder` is archived and has shipped for one release with
`FLARESOLVERR_ENABLED=false`. Every command runs from `apps/ascend-web-hunter/` through `.venv/Scripts/python.exe -m`
(Windows) or `.venv/bin/python -m` (Linux and macOS).

## 1. Preconditions

- [ ] 1.1 Rewrite this change's spec deltas against the archived `openspec/specs/web-search-authenticated-sessions`
      and `web-search-antibot-evasion` text, removing FlareSolverr from every requirement that names it. Verify
      `openspec validate remove-flaresolverr-tier --strict` passes.
- [ ] 1.2 Confirm no deployment turned `FLARESOLVERR_ENABLED` on during the release. Verify by asking the owner and
      recording the answer in `design.md`.

## 2. Code

- [ ] 2.1 Delete `src/reader/strategies/flaresolverr_strategy.py` and remove `3-flaresolverr` from `TIER_ORDER` in
      `src/reader/web_reader.py`, keeping it as a reserved value that answers HTTP 400 and a tool error per D1. Verify
      with tests on both surfaces.
- [ ] 2.2 Remove FlareSolverr from `src/api/readiness.py`, `src/config/startup_banner.py`,
      `src/circuit_breaker/breaker.py`, `src/proxy/proxy_provider.py` and `src/api/mcp/mcp_server.py`, and remove
      `FLARESOLVERR_URL` and `FLARESOLVERR_ENABLED` from `src/config/config.py`. Verify a recursive search of `src/`
      for `flaresolverr`, ignoring case, finds only the reserved value and its 400 message.
- [ ] 2.3 Replace `PRODUCED_BY_FLARESOLVERR` handling in `src/reader/cloudflare/cookie_manager.py` with D2. Verify with
      a test that an old record is replayed by the browser tiers.
- [ ] 2.4 Delete `tests/reader/strategies/test_flaresolverr_strategy.py`, `test_flaresolverr_circuit_breaker.py` and
      `test_flaresolverr_unconditional_save.py`, and remove the FlareSolverr cases from every other test file listed
      in `proposal.md`. Verify the gate
      `python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` passes.

## 3. Compose and deployment

- [ ] 3.1 Remove the `flaresolverr` service and every reference to it from `compose.ascend-web-hunter.yaml` and
      `apps/ascend-web-hunter/deploy-standalone/compose.yaml` in the same commit, and from both `.env.example` files.
      Verify `docker compose config` from the repository root succeeds and lists no `flaresolverr` service.

## 4. Documentation

- [ ] 4.1 Update the root `AGENTS.md`, `apps/ascend-web-hunter/AGENTS.md`, `README.md`, `docs/configuration.md`,
      `docs/running.md`, `docs/api-examples.md`, `docs/README.md`, `deploy-standalone/README.md`, the arc42 sections
      and the container diagram. Verify a recursive search of the module docs finds FlareSolverr only in history
      sections, ADR amendments and the CHANGELOG.
- [ ] 4.2 Amend ADR-001, ADR-002, ADR-005, ADR-006, ADR-010, ADR-011 and ADR-012 with a dated note, and write the
      next free ADR number recording the removal. Verify each amended ADR keeps its status line.
- [ ] 4.3 Bump the version and add one CHANGELOG entry. Verify `pyproject.toml` and the CHANGELOG agree.
