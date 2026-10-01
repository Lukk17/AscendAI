## Why

The authenticated part of ascend-web-hunter e2e spec 7 (Part 2) logs in to `saucedemo.com` with a Playwright script and then stores the captured session. Today the harness `apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py` imports `cookie_manager` from `src/reader/cloudflare/cookie_manager.py` and calls `save_storage_state` directly, so it writes the Redis record `session:{domain}:{profile}` from outside the service. The test is coupled to the store's key format and to the service's Python internals, it must run with the service's own virtual environment and Redis address, and it cannot seed a service that runs in a container or on another host. A public endpoint that imports a Playwright `storage_state` removes that coupling and gives an operator a supported way to move a login captured on one machine into the service. This was task 6.1 of `add-web-search-scraping-e2e` and the owner moved it into its own change on 2026-10-01.

## What Changes

- Add `POST /api/v2/web/session/import` to the ascend-web-hunter REST API (`rest_router_v2` in `apps/ascend-web-hunter/src/api/rest/rest_endpoints.py`). The body carries `url`, an optional `profile`, a Playwright `storage_state` object and an optional `user_agent`.
- Validate the request before anything is stored: the URL must be a safe external URL (the same `is_safe_external_url` check `session/establish` and `session/clear` use), the `profile` must match a bounded pattern, the `storage_state` must have the Playwright shape and stay under a size limit, and at least one cookie must belong to the URL's registrable domain.
- Store the session through the existing `cookie_manager.save_storage_state(...)` with a new provenance value `PRODUCED_BY_IMPORT = "import"`, so the stored record is the same shape a NoVNC capture or the login seed produces and every fetch tier replays it.
- Answer `200` with the domain, the effective profile and the number of auth and WAF cookies stored. Refuse with `400` or `413` and a stable error code otherwise.
- Change the e2e harness to log in with Playwright as today and then call the new endpoint over HTTP instead of importing `cookie_manager`.
- No MCP tool is added. Importing a login is an operator action, not something an LLM should call.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `web-search-authenticated-sessions`: adds a requirement for importing a Playwright storage state through the REST API, with its validation and error codes.

## Impact

- Code: `apps/ascend-web-hunter/src/api/rest/rest_endpoints.py` (request model and route), `apps/ascend-web-hunter/src/reader/cloudflare/cookie_manager.py` (new provenance constant, cookie domain helper if needed), `apps/ascend-web-hunter/src/config/config.py` (two new limits).
- Tests: new unit tests under `apps/ascend-web-hunter/tests/api/rest/`, inside the module's 100 percent branch coverage gate.
- Harness: `apps/ascend-web-hunter/e2e/harness/seed_authenticated_session.py` stops importing service internals.
- Docs: `apps/ascend-web-hunter/docs/configuration.md` for the new settings, the e2e spec 7 text and README where they describe seeding, a Bruno request under `docs/api/request/AscendAI/web-hunter/`.
- Deployment: the two new settings are optional with defaults. Per the sync rule in `apps/ascend-web-hunter/AGENTS.md`, any new environment variable also goes into the root `.env.example`, `apps/ascend-web-hunter/deploy-standalone/.env.example` and the configuration table in `apps/ascend-web-hunter/deploy-standalone/README.md`.
- Security: the endpoint writes credentials into the session store. It has the same trust level as `session/establish`, which also lets any caller of the REST API create a session. No authentication is added here. The service is meant to be reached only from the local stack.

## Relevant Skills

- `ascend-web-hunter` for the service's session store and tiers
- `python-patterns` for the FastAPI route, Pydantic models and pytest tests
- `api-design` for the request shape, status codes and error bodies
- `security-review` for the URL check, the size limit and storing credentials
- `tdd-workflow` for writing the failing tests first
- `e2e-runbooks` for the harness change and the spec 7 rerun
