## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 2 (web-hunter), position 2. It needs `add-ascend-python-common` (group 2, position 1), because the framework versions it moves live in one place only after that change (its D4). It needs no later change: it is checked against today's agent (Spring Boot 3.5.14, Spring AI 1.1.5, whose MCP Java SDK 0.17.0 speaks the session-based handshake that the MCP Python SDK 2 still serves), owner answer 70.1 of 2026-10-04. `upgrade-spring-boot-4` (build group 3, position 2) lands later and carries the task that checks the agent's MCP client against these servers again after its upgrade. The later changes that write Python service code build on this one: the rest of the web-hunter chain (`open-several-novnc-windows-at-once`, `detect-challenge-walls-in-any-language`, `enhance-web-search-tier-ladder`, `enhance-web-search-extraction-and-tiers`, `remove-flaresolverr-tier`, `add-web-session-import`, `enhance-web-search-crawl-at-scale`, `add-file-download`) and the Python parts of `add-keycloak-login` (group 3, position 3). This change edits no other change itself. The places that `design.md`, "Required edits to other changes", lists were edited in their target changes on 2026-10-03 by the owner's choice of one pass. The 18-number order those edits used is superseded by the owner build order of 2026-10-04.

## Why

The four Python services (ascend-audio-scribe, ascend-web-hunter, ascend-memory, ascend-ocr) run FastAPI 0.136.3, uvicorn 0.48.0, FastMCP 3.3.1 and the MCP Python SDK 1.30.0. The current releases are FastAPI 0.142.2, uvicorn 0.54.0, FastMCP 4.0.10 and MCP SDK 2.3.0 (PyPI, read on 2026-10-03). FastMCP 4 and MCP SDK 2 are major releases that change the protocol layer, and the MCP SDK 1 line now gets only critical fixes. `add-ascend-python-common` kept the old versions on purpose so the library move and the framework move stay apart, and the owner decided on 2026-10-03 (answer 60.6) that the upgrade is this separate change, right after the library.

## What Changes

- The library's single version set moves to `fastapi==0.142.2`, `uvicorn==0.54.0`, `fastmcp==4.0.10` and `mcp==2.3.0`. `starlette==1.7.0` and `httpx2==2.13.1` are pinned in the same set, because FastMCP 4 and MCP SDK 2 need them and the services already resolve exactly these versions. `pydantic` (2.13.4) and `pydantic-settings` stay, they already meet every new floor. No service pins any of these itself. The library gets a new major version.
- The library code follows the new APIs once: the FastMCP middlewares (request log context, rate limit, refusal mapping) act only on tool calls and ignore the extra notifications and unroutable messages FastMCP 4 now passes to middleware, the MCP session digest is taken only from a real `mcp-session-id` header, the MCP server reports the service version, and FastAPI's new built-in telemetry is configured so it neither adds a second exporter nor writes exception text to OpenTelemetry logs.
- FastMCP 4's Host and Origin header check is switched on for `/mcp` in all four services (owner answer 61.2 of 2026-10-03), with an allow list of host names set in the library through the new setting `MCP_ALLOWED_HOST_HEADERS` of its `ServiceSettings` base (name approved by owner answer 62 of 2026-10-04). It is inbound and is documented side by side with the outbound `ALLOWED_PRIVATE_HOSTS` of the URI fetch guard (renamed from `MCP_ALLOWED_HOSTS` by `add-ascend-python-common`, owner answer 68.2 of 2026-10-04), so no reader mixes the two up. Its default per service is the compose service name plus `localhost` and `127.0.0.1`, so the agent in its container, the agent on the host, Bruno and the health checks keep working. A request with any `Origin` header is refused, because no browser uses these endpoints. FastAPI's built-in telemetry is not adopted (owner answer 61.1): the library keeps its own tracing setup.
- Each service follows once the library is green: test code that uses the FastMCP in-memory client names the protocol era it tests, camelCase reads of MCP model fields are removed, and the compatibility bridge for them is switched off in tests so a leftover read fails the gate.
- The MCP endpoint keeps serving clients that use the session-based handshake (protocol 2025-06-18 and 2025-11-25), which is what the agent's MCP client speaks: today's agent (Spring AI 1.1.5, MCP Java SDK 0.17.0) negotiates 2025-06-18, and after `upgrade-spring-boot-4` (Spring AI 2.0.1, MCP Java SDK 2.0.0) it negotiates 2025-11-25. The endpoint also serves sessionless 2026-07-28 clients.
- **BREAKING** (MCP wire, small): a missing resource answers JSON-RPC `-32602` instead of `-32002`, an unknown method answers `-32601`, and a Streamable HTTP request body above 4 MiB is refused with 413 before it is parsed. No service exposes MCP resources today, and no MCP argument of the four services comes near 4 MiB, because files travel as URIs.
- **BREAKING** (MCP wire): a request to `/mcp` whose `Host` header is not on the service's allow list, or that carries an `Origin` header, is refused before a session is created. Every caller in the repository uses a host name the default holds. A deployment that reaches a service by another name, such as the standalone ascend-web-hunter, sets `MCP_ALLOWED_HOST_HEADERS`.
- **BREAKING** (process): uvicorn exits with code 3 on any start-up failure (app import, port bind, lifespan). Compose `restart: unless-stopped` and web-hunter's supervisord `autorestart=true` restart on any exit code, so behaviour stays the same, but docs that name an exit code change.
- Agent side: no code change is planned. The MCP integration tests of today's agent (Spring Boot 3.5.14, Spring AI 1.1.5) and a live tool listing against the four upgraded servers prove the Java client and the Python servers agree on the protocol version. The same check after the agent's upgrade is a task of `upgrade-spring-boot-4`.
- Docs: library README and changelog, each service `AGENTS.md` (Tech Stack versions) and changelog, the root `AGENTS.md` module table, and a monorepo decision record.

## Capabilities

### New Capabilities

- `python-mcp-runtime`: what every Python service's MCP endpoint and HTTP runtime must keep doing across the framework upgrade: which protocol versions it accepts, how the session digest behaves for session-based and sessionless clients, one trace per request with no second exporter, the request body limit and the Host and Origin header check on the MCP endpoint, and route-based behaviour (stricter rate limits and the metrics route label) that must survive FastAPI's new router structure.

### Modified Capabilities

None. `python-service-platform`, which `add-ascend-python-common` (build group 2, position 1) creates and which is archived before this change, keeps every requirement word for word: its rules hold unchanged on the new framework versions, and the settings list of its requirement "Every service reads the same base settings" stays true with one more setting beside it. What this change adds is new behaviour of the MCP endpoint and the HTTP runtime (the protocol versions, the sessionless client, the request body limit, the Host and Origin header check, the route label), so it goes into the new capability `python-mcp-runtime` as ADDED requirements, and no requirement of `python-service-platform` is modified.

## Impact

- Library: `libs/ascend-python-common/pyproject.toml` (version set, major version), `src/ascend_python_common/app.py`, `settings.py` (`MCP_ALLOWED_HOST_HEADERS`), `request_context.py`, `rate_limit.py`, `errors/mcp.py`, `tracing.py`, their tests, `README.md`, `CHANGELOG.md`.
- Services: each `apps/<service>/pyproject.toml` (library pin and version), the tests that use the FastMCP client or read MCP model fields, `AGENTS.md`, `CHANGELOG.md`, and for ascend-web-hunter and ascend-ocr `docs/architecture/arc42/02-constraints.md`. Each service takes one named version (design D15): ascend-memory 0.1.5, ascend-audio-scribe 0.9.5, ascend-web-hunter 0.0.8, ascend-ocr 0.3.2. ascend-ocr also `tests/api/mcp/test_request_log_context.py` (moved into the library by `add-ascend-python-common`, wherever it lives then) and the Pact provider verification run. No business code change is expected. Any that the tests find is fixed in the service group that finds it.
- Agent: no code change. Its MCP integration tests run as a gate.
- Containers: the four images are rebuilt. Dockerfiles and CI workflows need no edit, because they install the library and the service from their `pyproject.toml` files. By owner rule 98 of 2026-10-08 each compose service passes the new setting with its code default, `MCP_ALLOWED_HOST_HEADERS=${<SERVICE>_MCP_ALLOWED_HOST_HEADERS:-<default>}`, in `compose.yaml`, `compose.ascend-web-hunter.yaml` and, under the sync rule, `apps/ascend-web-hunter/deploy-standalone/compose.yaml` (design D10). The root `.env.example`, `apps/ascend-web-hunter/deploy-standalone/.env.example` and the configuration table of `deploy-standalone/README.md` document the ascend-web-hunter variable (the sync rule), and the configuration reference gets one row per service (task 6.14).
- APIs: every REST body and every MCP tool result stays as `add-ascend-python-common` leaves it. The MCP wire changes listed as BREAKING above.
- Docs: `docs/architecture/decisions/ADR-M013-python-runtime-upgrade.md` (the next free number when it is written, after the M012 of `add-ascend-python-common`, checked free before writing, because `upgrade-spring-boot-4` and its M011 now land later) and its index line.
- No data migration. The project is under development and no Python service stores state these versions read. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

## Relevant Skills

Load these from `.agents/skills/` before implementing this change:

- `python-patterns` for the library and service tests, typing under mypy strict and the coverage gate
- `build-dependency-management` for the single version set, the major library version and the install order
- `tdd-workflow` for the tests that pin today's MCP and REST behaviour before the versions move
- `observability-and-logging` for the one trace per request rule, the OpenTelemetry exporter set-up and the session digest in log lines, with no session id on spans
- `security-review` for the MCP request body limit, the host and origin checks FastMCP 4 offers, and the OpenTelemetry exception logs that can carry sensitive text
- `api-design` for the MCP and REST error codes that change on the wire
- `docker-patterns` for the image rebuilds and the container checks
- `springboot-patterns` for reading the agent's MCP client configuration and running its MCP integration tests
- `architecture-decision-records` for ADR-M013
- `markdown-writer` for the library README, the changelogs and the `AGENTS.md` updates
- `e2e-runbooks` for the end-to-end verification step
- `git-workflow` for the commit split, once the owner says to commit
