## Why

The authenticated part of ascend-web-hunter e2e spec 7 (Part 2) logs in to `saucedemo.com` with a Playwright script and then stores the captured session. Today the harness `apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py` imports `cookie_manager` from `src/reader/cloudflare/cookie_manager.py` and calls `save_storage_state` directly, so it writes the Redis record `session:{domain}:{profile}` from outside the service. The test is coupled to the store's key format and to the service's Python internals, it must run with the service's own virtual environment and Redis address, and it cannot seed a service that runs in a container or on another host. A public endpoint that imports a Playwright `storage_state` removes that coupling and gives an operator a supported way to move a login captured on one machine into the service. This was task 6.1 of `add-web-search-scraping-e2e` and the owner moved it into its own change on 2026-10-01.

## What Changes

- Add `POST /api/v2/web/session/import` to the ascend-web-hunter REST API (`rest_router_v2` in `apps/ascend-web-hunter/src/api/rest/rest_endpoints.py`). The body carries `url`, an optional `profile`, a Playwright `storage_state` object and an optional `user_agent`.
- Validate the request before anything is stored: the URL's host must have a registrable domain, checked with no address lookup because the import fetches nothing (owner decision 93 of 2026-10-08), and a refusal raises the library's `UnsafeUriError` and answers `400` with the code `unsafe_uri`, the `profile` must match a bounded pattern, the `storage_state` must have the Playwright shape, and at least one cookie must belong to the URL's registrable domain.
- Store the session through the existing `cookie_manager.save_storage_state(...)` with a new provenance value `PRODUCED_BY_IMPORT = "import"`, so the stored record is the same shape a NoVNC capture or the login seed produces and every fetch tier replays it.
- Clear the read cache of the domain on every ascend-web-hunter instance, not only on the one that served the import, by calling the domain purge that a session clear runs, built by `enhance-web-search-extraction-and-tiers` (build group 2, position 6) in its task 5.5 and design D7, the same purge `session/clear` already runs (owner decisions 87 and 89 of 2026-10-08: several instances run at once, one mechanism per job).
- Answer `200` with the domain, the effective profile and the number of auth and WAF cookies stored. Refuse otherwise with `400` and an RFC 7807 problem body built by the `ascend-python-common` library, whose `code` is a lower case snake case value (`validation`, `unsafe_uri`, `invalid_profile`, `no_cookies_for_domain`) and which carries a `traceId`. There is no size or cookie count limit (owner decision, 2026-10-01: no made-up limits).
- Change the e2e harness to log in with Playwright as today and then call the new endpoint over HTTP instead of importing `cookie_manager`.
- No MCP tool is added. Importing a login is an operator action, not something an LLM should call.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `web-search-authenticated-sessions`: adds a requirement for importing a Playwright storage state through the REST API, with its validation and error codes.

## Impact

- Code: `apps/ascend-web-hunter/src/api/rest/rest_endpoints.py` (request model and route), `apps/ascend-web-hunter/src/reader/cloudflare/cookie_manager.py` (new provenance constant, cookie domain helper if needed). The read cache purge across instances is reused from `enhance-web-search-extraction-and-tiers` task 5.5, so this change adds no channel and no subscriber (design D6).
- Tests: new unit tests under `apps/ascend-web-hunter/tests/api/rest/`, inside the module's 100 percent branch coverage gate.
- Harness: `apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py` stops importing service internals.
- Docs: the e2e spec 7 text and README where they describe seeding, a Bruno request under `docs/api/request/AscendAI/web-hunter/`, and a `## [0.0.14]` CHANGELOG entry with the version bump from 0.0.13 to 0.0.14 in `pyproject.toml`, `AGENTS.md` and `docs/architecture/arc42/02-constraints.md`.
- e2e: a new deterministic spec, `<N>-session-import` (next free number at implementation time), with its one fixture, its Bruno folder `docs/api/request/AscendAI/web-hunter/testing/session-import/` and its place in `docs/E2E_RUN_SCENARIOS.md`, beside the spec 7 Part 2 rerun.
- Deployment: no new setting or environment variable, so the `.env.example` files and the standalone configuration table do not change.
- Security: the endpoint writes credentials into the session store. It has the same trust level as `session/establish`, which also lets any caller of the REST API create a session. No authentication is added here. The service is meant to be reached only from the local stack.

## Dependencies and Build Order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 2 (web-hunter), position 8. It needs `add-ascend-python-common` (position 1), whose `UnsafeUriError`, problem builder and error registry it uses, and `add-python-runtime-upgrades` (position 2), whose framework versions the service runs on. Its e2e spec needs no fake site and no refusal check since owner decision 91.3 of 2026-10-08 (the refusals are proven by the unit tests of task 2.1). It changes the e2e spec 7 seeding of that suite, which was task 6.1 of `add-web-search-scraping-e2e`. It needs no later change.

## Relevant Skills

- `ascend-web-hunter` for the service's session store and tiers
- `python-patterns` for the FastAPI route, Pydantic models and pytest tests
- `api-design` for the request shape, status codes and error bodies
- `security-review` for the URL check, the domain check and storing credentials
- `tdd-workflow` for writing the failing tests first
- `e2e-runbooks` for the harness change and the spec 7 rerun
