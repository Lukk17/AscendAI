# Spec Delta

## Purpose

Defines what the MCP endpoint and the HTTP runtime of every Python service (ascend-audio-scribe, ascend-web-hunter, ascend-memory, ascend-ocr) must keep doing on the current web and MCP framework versions: the protocol versions it serves, the session digest, one trace per request, the MCP request body limit, the Host and Origin header check and the route-based behaviour that clients and dashboards rely on.

## ADDED Requirements

### Requirement: The four services share one framework version set

The four Python services SHALL run on one version of each web and MCP framework package (FastAPI, Starlette, uvicorn, FastMCP, the MCP Python SDK and the HTTP client the MCP SDK uses), taken from the shared library's version set. No service SHALL pin a different version of any of these packages, and the installed set SHALL have no broken requirement.

#### Scenario: A service is installed

- **WHEN** any of the four services is installed for development, in CI or in its container image
- **THEN** the installed versions of FastAPI, Starlette, uvicorn, FastMCP, the MCP SDK and its HTTP client equal the versions of the library's set
- **AND** the package installer's consistency check reports no broken requirement

### Requirement: The MCP endpoint serves session-based clients

Every Python service's MCP endpoint SHALL accept the session-based `initialize` handshake for the protocol versions 2025-06-18 and 2025-11-25, SHALL answer it with the negotiated protocol version, and SHALL serve `tools/list` and `tools/call` after it. This is the protocol the agent's MCP client speaks. The endpoint SHALL run in FastMCP's stateless HTTP mode, so it SHALL answer the handshake with no `mcp-session-id` response header and any container of the service SHALL serve any later request. No tool SHALL rely on a message the server sends to the client between requests.

#### Scenario: The agent lists the tools of a service

- **WHEN** the agent's MCP client starts and connects to a Python service with a session-based handshake of protocol 2025-06-18 or 2025-11-25
- **THEN** the handshake succeeds with no `mcp-session-id` header
- **AND** the client lists the same tool names the service listed before the upgrade

#### Scenario: A later request reaches another container

- **WHEN** a client completes the handshake with one container of a service and sends `tools/call` to another container of the same service
- **THEN** the tool result has the same content as when both requests reach one container

#### Scenario: A 2025-06-18 client calls a tool

- **WHEN** a client sends `initialize` with protocol version 2025-06-18, then `notifications/initialized`, then `tools/call`
- **THEN** the tool result has the same content and the same structured content as before the upgrade

### Requirement: The MCP endpoint serves sessionless clients

Every Python service's MCP endpoint SHALL also serve clients that negotiate the sessionless protocol 2026-07-28. Such a request SHALL be served without a session, and its log lines SHALL carry no `mcp_session_id` value, because no session exists.

#### Scenario: A sessionless client calls a tool

- **WHEN** a client that negotiates protocol 2026-07-28 calls a tool
- **THEN** the tool result has the same content as for a session-based client
- **AND** every log line of that request has `mcp_session_id` empty, never the digest of an id the server made up

### Requirement: The session digest comes only from the client's session id

The `mcp_session_id` field of a log line SHALL be the digest of the `mcp-session-id` value the client sent, or of the value the server announced in the response that created the session. A value the server or the framework generates for its own state keys SHALL NOT be logged, raw or as a digest. No exported span SHALL carry an MCP session id of any kind, raw or as a digest.

#### Scenario: Two tool calls on one session

- **WHEN** a session-based client makes two tool calls with the same `mcp-session-id`
- **THEN** the log lines of both calls carry the same `mcp_session_id`
- **AND** that value is the first 16 hex characters of the SHA-256 digest of the session id the client sent

### Requirement: One trace per request and one exporter

Every HTTP request SHALL produce exactly one HTTP server span, and every span the MCP framework records for an MCP request SHALL be a descendant of that span in the same trace. Spans SHALL be exported only by the exporter the service configures when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. No framework SHALL add an exporter of its own from environment variables, and no framework SHALL write an exception message or a stack trace to OpenTelemetry logs.

#### Scenario: An MCP tool call is traced

- **WHEN** `OTEL_EXPORTER_OTLP_ENDPOINT` is set and a client calls a tool
- **THEN** the exported spans of that request share one trace id
- **AND** exactly one of them is the HTTP server span, and every MCP span descends from it

#### Scenario: The SDK is switched off while the endpoint is set

- **WHEN** `OTEL_SDK_DISABLED` is `true` and `OTEL_EXPORTER_OTLP_ENDPOINT` is set
- **THEN** no span, metric or log record is sent to that endpoint

#### Scenario: An unexpected exception

- **WHEN** a REST handler raises an unexpected exception
- **THEN** the answer is the generic 500 problem body
- **AND** no OpenTelemetry log record carries the exception message or its stack trace

### Requirement: The MCP endpoint refuses an oversized request body

The MCP endpoint SHALL refuse a request whose body is larger than 4 MiB with HTTP 413 before it parses the body or creates a session, and the service SHALL keep serving other requests.

#### Scenario: A 5 MiB tool call

- **WHEN** a client posts a 5 MiB JSON-RPC message to `/mcp`
- **THEN** the answer has status 413 and no session is created
- **AND** the next normal tool call succeeds

### Requirement: The MCP endpoint accepts only allowed Host headers and no Origin

Every Python service's MCP endpoint SHALL check the `Host` and `Origin` headers of every request before it parses the body or creates a session. It SHALL serve a request whose `Host` names a host on the service's `MCP_ALLOWED_HOST_HEADERS` setting and that carries no `Origin` header, and SHALL refuse every other request with a 4xx status. The default of `MCP_ALLOWED_HOST_HEADERS` SHALL be the service's compose service name, `localhost` and `127.0.0.1`. The setting SHALL be read by the shared library, and an empty value SHALL stop start-up with an error that names it. The check SHALL apply to the MCP endpoint only, never to a REST route.

#### Scenario: The agent container calls a tool

- **WHEN** a client sends `initialize` and then a tool call to ascend-ocr with `Host: ascend-ocr:7022` and no `Origin` header, with the default setting
- **THEN** the handshake succeeds and the tool call is served

#### Scenario: A call on the host by localhost

- **WHEN** a client on the host sends `initialize` to `http://localhost:7022/mcp` with the default setting
- **THEN** the handshake succeeds

#### Scenario: A host name that is not allowed

- **WHEN** a client sends `initialize` to ascend-ocr with `Host: attacker.example`
- **THEN** the answer has a 4xx status and no session is created
- **AND** a request to `GET /health` with the same `Host` header is still answered 200

#### Scenario: A request from a browser page

- **WHEN** a client sends `initialize` with an allowed `Host` and `Origin: https://attacker.example`
- **THEN** the answer has a 4xx status and no session is created

#### Scenario: A deployment adds its own host name

- **WHEN** the standalone ascend-web-hunter starts with `MCP_ALLOWED_HOST_HEADERS=search-box,localhost` and a client sends `initialize` with `Host: search-box:7021`
- **THEN** the handshake succeeds

### Requirement: Route-based behaviour keeps the route template

A stricter rate limit set on one REST route SHALL apply to that route and only to it, and the route label of the HTTP request metrics SHALL be the route template, not the raw path, for routes registered directly on the app and for routes that come from an included router.

#### Scenario: A route with its own limit

- **WHEN** a caller exceeds the stricter limit of a route that comes from an included router
- **THEN** the next call to that route answers 429 `rate_limited`
- **AND** a call to another route of the same router is still served

#### Scenario: A request with a path parameter

- **WHEN** a client requests a route with a path parameter, for example a job status by id
- **THEN** the request metrics carry the route template with the parameter name, not the id
