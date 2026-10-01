## 1. Constants

- [ ] 1.1 Add `PRODUCED_BY_IMPORT = "import"` beside the other `PRODUCED_BY_*` constants in `apps/ascend-web-hunter/src/reader/cloudflare/cookie_manager.py`, and make sure the provenance check that decides whether a tier may replay a clearance treats it like `PRODUCED_BY_LOGIN_SEED`. Check: a unit test asserts the replay decision for an imported record equals the one for a login-seed record

## 2. Request model and route

- [ ] 2.1 Write the failing tests first in `apps/ascend-web-hunter/tests/api/rest/test_session_import.py` for every row of the design's D2 table and for the success answer of D3, using the FastAPI test client and a mocked `cookie_manager` and `web_reader`. Include a test that a storage state of 1000 cookies for the URL's domain is accepted and stored, so no hidden limit creeps back
- [ ] 2.2 Add `PlaywrightCookie`, `PlaywrightOrigin`, `PlaywrightStorageState` and `SessionImportRequest` Pydantic models to `apps/ascend-web-hunter/src/api/rest/rest_endpoints.py`, with `extra="forbid"` on the storage state and request, and the profile pattern `^[A-Za-z0-9_-]{1,64}$`
- [ ] 2.3 Add `@rest_router_v2.post("/session/import")` that checks `is_safe_external_url`, the profile pattern and the registrable domain match, in that order, with no body size or cookie count limit, and answers `400 UNSAFE_URL`, `400 INVALID_PROFILE` or `400 NO_COOKIES_FOR_DOMAIN`
- [ ] 2.4 On success drop the cookies of other domains, call `cookie_manager.save_storage_state(..., produced_by=PRODUCED_BY_IMPORT)`, call `web_reader.clear_cache_for_domain(domain)`, and answer `200` with `status`, `domain`, `profile`, `auth_cookies`, `waf_cookies` and `dropped_cookies`
- [ ] 2.5 Run `.venv/Scripts/python.exe -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` from `apps/ascend-web-hunter`, then `.venv/Scripts/python.exe -m ruff check .` and `.venv/Scripts/python.exe -m mypy src`. Pass: all green, 100 percent branch coverage

## 3. Harness and e2e

- [ ] 3.1 Change `apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py` to send the captured storage state and user agent to `POST {WEB_HUNTER_BASE_URL}/api/v2/web/session/import` with `profile=e2e` (default base URL `http://localhost:7021`), exit non-zero on any answer other than `200`, and remove every `from src...` import. Check: `grep -n "from src" apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py` prints nothing
- [ ] 3.2 Update the seeding steps in `apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md`, its template under `apps/ascend-web-hunter/e2e/testing/templates/`, and `apps/ascend-web-hunter/e2e/README.md` so they describe the HTTP import instead of a direct Redis write
- [ ] 3.3 Add a Bruno request `docs/api/request/AscendAI/web-hunter/session-import.yml` with a small sample body for manual use
- [ ] 3.4 Ask the owner which run scenario from `docs/E2E_RUN_SCENARIOS.md` to use, then run e2e spec 7 Part 2 against the rebuilt `ascend-web-hunter` container. Pass: the harness exits `0`, the anonymous read of `https://www.saucedemo.com/inventory.html` shows the login wall, and the read with `profile=e2e` shows an auth-only marker. Record the run file path from `apps/ascend-web-hunter/e2e/testing/runs/` here
- [ ] 3.5 Tick task 6.1 in `openspec/changes/add-web-search-scraping-e2e/tasks.md` with a pointer to this change once 3.4 passes
