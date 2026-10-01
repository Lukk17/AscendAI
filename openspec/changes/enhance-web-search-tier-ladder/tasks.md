Every command runs from `apps/ascend-web-hunter/` through the module's own virtual environment, as
`.venv/Scripts/python.exe -m <tool>` on Windows or `.venv/bin/python -m <tool>` on Linux and macOS. The test gate is
`python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`.

## 1. Configuration and dependencies

- [ ] 1.1 Add `patchright` and `camoufox` to `pyproject.toml` with exact pinned versions. Verify
      `python -m pip install -e ".[dev]"` succeeds and `python -c "import patchright, camoufox"` exits 0.
- [ ] 1.2 Add `FLARESOLVERR_ENABLED` (bool, default `false`), `CAMOUFOX_ENABLED` (bool, default `true`) and
      `TIER_MEMORY_TTL_SECONDS` (int, default `86400`, minimum `60`) to `src/config/config.py`. Verify with cases in
      `tests/config/test_config.py` for each default, a valid override and a rejected value.
- [ ] 1.3 Fetch both browser builds at image build time in `apps/ascend-web-hunter/Dockerfile`. Verify
      `docker build -t ascend-web-hunter:latest .` succeeds and a container started from it launches each browser
      once with no network fetch, by reading its logs.

## 2. The two tiers

- [ ] 2.1 Create `src/reader/strategies/patchright_strategy.py` mirroring `playwright_strategy.py`: session
      `storage_state` replay, the fingerprint, the proxy seam, connect-time pinning through `pin_safe_host`, scroll
      handling and the `ChallengeDetector.assess` verdict on the initial response and after render. Verify with
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
- [ ] 2.5 Confirm both tiers keep the SSRF guard on every redirect hop required by `web-search-fetch-correctness`.
      Verify with a test that a redirect to a private address is refused on each tier.

## 3. FlareSolverr behind the flag

- [ ] 3.1 Skip `3-flaresolverr` in the ladder when `FLARESOLVERR_ENABLED` is false and answer HTTP 400 (REST) or a
      `ToolError` (MCP) naming the disabled tier when a caller selects it. Verify with tests for both surfaces and both
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
      tier values and the three settings. Verify each setting name appears in all three files.
- [ ] 5.2 Write `docs/architecture/decisions/ADR-015-patched-browser-tiers-and-tier-memory.md` and add it to the
      decisions `README.md` index. Amend ADR-011 with the two new public values, dated. Verify ADR-011's existing
      values are unchanged.
- [ ] 5.3 Bump `pyproject.toml` and the `AGENTS.md` version line to `0.0.8` and add one `## [0.0.8]` CHANGELOG entry.
      Verify the two agree.

## 6. Verification

- [ ] 6.1 Run the test gate, `python -m ruff check .` and `python -m mypy src`. Verify all pass with no suppression
      added.
- [ ] 6.2 Rebuild the stack from the repository root with `docker compose up -d --build` and read
      `https://nowsecure.nl` through `POST /api/v2/web/read` with `tier` `4a-patchright`. Verify HTTP 200 or 428, never
      500, and that `/metrics` counts the tier.
- [ ] 6.3 Record the image size before and after in the CHANGELOG entry from 5.3.
