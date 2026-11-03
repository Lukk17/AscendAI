# Spec Delta

## Purpose

Defines the behaviour that all four Python services (ascend-audio-scribe, ascend-web-hunter, ascend-memory, ascend-ocr) share through the one shared Python library: error bodies, refusal logging, settings, logging, request ids, tracing, health, readiness, metrics, rate limiting, the URI fetch guard, the startup banner, the MCP endpoint and the quality gates of every build.

## ADDED Requirements

### Requirement: Every Python service takes its shared behaviour from one library

Each of the four Python services SHALL declare the shared library `ascend-python-common` as a normal dependency in its `pyproject.toml`, pinned to one exact version, and SHALL take the behaviour of every other requirement of this capability from that library rather than from its own copy. A service SHALL keep only its business code, its own error codes, its own settings fields and its own readiness probes. The library SHALL have its own test suite that passes with 100 percent branch coverage.

#### Scenario: A service builds against the pinned library version

- **WHEN** a service is installed for development, in CI or in its container image
- **THEN** the installed library version equals the exact version the service's `pyproject.toml` pins
- **AND** the install fails when the library folder carries a different version

#### Scenario: No service keeps a copy of shared code

- **WHEN** the source of any of the four services is searched for its own logging setup, request id middleware, tracing setup, problem body builder, rate limiter, startup banner frame or URI fetch guard
- **THEN** none is found outside the library

### Requirement: Every REST error is an RFC 7807 problem body

Every Python 4xx/5xx SHALL use `application/problem+json` with `type`, `title`, `status`, `detail`, `instance`, `code`, `traceId`. `type` SHALL be `https://ascend.ai/errors/` plus lower-case code with `-` for `_`. `title` SHALL be the reason phrase and `instance` the path. `traceId` SHALL be the 32 hex trace id, omitted only with no trace, never empty or invented. Only the internal code SHALL use a fixed detail; other 5xx (502, 503, 504, named upstream like `DOWNLOAD_FAILED`) SHALL keep their detail. No `detail` SHALL name hosts, paths, classes, tracebacks, or URI user info. Extra fields SHALL stay top-level. Platform codes SHALL be `validation`, `bad_request`, `unauthorized` (401), `not_found`, `method_not_allowed`, `not_acceptable`, `content_too_large`, `unsupported_media_type`, `rate_limited`, `http_error`, `internal`.

#### Scenario: A service's own refusal

- **WHEN** ascend-ocr refuses a status read for an unknown job identifier over REST
- **THEN** the answer is HTTP 404 with `Content-Type: application/problem+json`, `code` `JOB_NOT_FOUND`, `type` `https://ascend.ai/errors/job-not-found`, `instance` equal to the request path and a `traceId` equal to the trace id of that request

#### Scenario: An unknown path

- **WHEN** any Python service receives a request for a path no route maps
- **THEN** the answer is HTTP 404 with `Content-Type: application/problem+json` and `code` `not_found`

#### Scenario: A method the path does not support

- **WHEN** any Python service receives `DELETE /health`
- **THEN** the answer is HTTP 405 with `Content-Type: application/problem+json`, `code` `method_not_allowed` and an `Allow` header

#### Scenario: An unexpected exception

- **WHEN** a REST handler raises an exception no code is registered for
- **THEN** the answer is HTTP 500 with the service's internal code and a fixed detail
- **AND** the body names neither the exception class nor its message

#### Scenario: An upstream failure keeps its detail

- **WHEN** ascend-ocr cannot download the file a caller named and refuses with `DOWNLOAD_FAILED`
- **THEN** the answer is HTTP 502 with `code` `DOWNLOAD_FAILED` and the detail its registered code gives, not the fixed detail of the internal code
- **AND** the detail names no internal host, exception class or user info of the URI

#### Scenario: Human help needed on ascend-web-hunter

- **WHEN** an ascend-web-hunter REST read meets a captcha that needs a human
- **THEN** the answer is HTTP 428 with `Content-Type: application/problem+json`, `code` `human_intervention_required`, `type` `https://ascend.ai/errors/human-intervention-required`, a `traceId`, and the extension members `intervention_type` and `vnc_url`
- **AND** the body has no `message` member and its `status` is the number 428

#### Scenario: The remote browser is busy on ascend-web-hunter

- **WHEN** an ascend-web-hunter REST read needs human help while every intervention window is in use
- **THEN** the answer is HTTP 409 with `Content-Type: application/problem+json`, `code` `novnc_busy`, the extension members `holder_url` and `holder_profile`, and a `Retry-After` header

#### Scenario: A request that started a trace elsewhere

- **WHEN** a request arrives with a valid `traceparent` header and is refused
- **THEN** the `traceId` of the problem body is the trace id that header carries

### Requirement: A request validation failure answers 400 with the rejected fields

A request whose parameters, form fields or body fail validation SHALL answer HTTP 400 with code `validation` and an extension field `errors`: a JSON array with one object per rejected field, each with `field` (the field name, without the location prefix such as `body` or `query`) and `message`, sorted by `field`. The `errors` field SHALL appear only on a validation failure.

#### Scenario: A missing upload part

- **WHEN** `POST /v1/ocr/jobs` is sent without the `file` part
- **THEN** the answer is HTTP 400 with `code` `validation` and `errors` holding one entry with `field` `file`

### Requirement: Refusals are logged once and counted per code

An expected refusal SHALL log exactly one WARNING line naming its code, with no traceback, on both surfaces. An unexpected exception SHALL log at ERROR with its traceback. Every refusal and exception SHALL increment `ascend_service_errors_total` with `code`, `surface` (`rest` or `mcp`) and `operation` (route template, tool name, or `unmatched`). `operation` SHALL never hold a raw path.

#### Scenario: A refusal over REST

- **WHEN** a REST request is refused with a registered code
- **THEN** the log holds one WARNING line naming that code and no traceback
- **AND** `ascend_service_errors_total{code="<code>",surface="rest",operation="<route template>"}` grows by one

#### Scenario: The same refusal over MCP

- **WHEN** the same refusal happens in an MCP tool call
- **THEN** the log holds one WARNING line naming that code and no ERROR line
- **AND** `ascend_service_errors_total{code="<code>",surface="mcp",operation="<tool name>"}` grows by one

#### Scenario: Two tools refused with the same code

- **WHEN** one caller goes over the rate limit on `ocr_submit` and on `ocr_job_status`, so one call of each tool is refused with `rate_limited`
- **THEN** `ascend_service_errors_total{code="rate_limited",surface="mcp",operation="ocr_submit"}` and `ascend_service_errors_total{code="rate_limited",surface="mcp",operation="ocr_job_status"}` each grow by one

### Requirement: MCP refusals are tool errors that start with the code

A refused MCP tool call SHALL fail as a tool error whose text is `<code>: <detail>`, using the same code and an equivalent detail as the REST surface for the same refusal. A tool error SHALL never carry an exception class, a traceback or an internal address. A status object that a service defines as a successful tool result, such as ascend-web-hunter's MCP `human_intervention_required`, `novnc_busy` and `session_expired`, is not a refusal and SHALL stay a successful result.

#### Scenario: An empty memory text over MCP

- **WHEN** ascend-memory's insert tool is called with an empty text
- **THEN** the tool fails with a text that starts with `validation: `

#### Scenario: An unexpected failure over MCP

- **WHEN** a tool raises an exception no code is registered for
- **THEN** the tool fails with a text that starts with the service's internal code and carries a fixed detail

### Requirement: Every service reads the same base settings

Every service SHALL read `API_HOST`, `API_PORT` (1 to 65535), `LOG_LEVEL` (one of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, any case), `LOG_FORMAT` (`json` or `color`, default `json`), `OTEL_EXPORTER_OTLP_ENDPOINT` (unset default, set must be absolute http or https URL) and `RATE_LIMIT_DEFAULT` (like `60/minute`) alike, with no custom trace switch. It SHALL also read `READINESS_PROBE_TIMEOUT_SECONDS` (over 0, default `3`), `STARTUP_PROBE_TIMEOUT_SECONDS` (over 0, default `2`) and `SECURITY_HSTS_MAX_AGE_SECONDS` (0 or more, default `63072000`), passed as `${VAR:-default}`. Fetchers SHALL read `ALLOWED_PRIVATE_HOSTS`, `MCP_FILE_URI_ROOT`, `MCP_DOWNLOAD_TIMEOUT_SECONDS`, followers `FETCH_MAX_REDIRECT_HOPS` (0 or more). No service SHALL read `MCP_ALLOWED_HOSTS` and SHALL refuse start with it present, naming it and `ALLOWED_PRIVATE_HOSTS`, exiting non-zero. Bad values SHALL stop start-up naming the setting.

#### Scenario: A leftover old allow list name stops start-up

- **WHEN** any Python service starts with `MCP_ALLOWED_HOSTS=internal.example` in its environment
- **THEN** start-up stops with an error that names `MCP_ALLOWED_HOSTS` and `ALLOWED_PRIVATE_HOSTS`
- **AND** the process exits non-zero before its port accepts a connection

#### Scenario: An invalid log level

- **WHEN** any Python service starts with `LOG_LEVEL=VERBOSE`
- **THEN** start-up stops with an error that names `LOG_LEVEL`

#### Scenario: A lower case log level

- **WHEN** a service starts with `LOG_LEVEL=debug`
- **THEN** it starts and logs at DEBUG

#### Scenario: ascend-audio-scribe reads API_PORT

- **WHEN** ascend-audio-scribe starts with `API_PORT=7117`
- **THEN** it listens on port 7117

#### Scenario: The HSTS lifetime is a setting

- **WHEN** any Python service starts with `SECURITY_HSTS_MAX_AGE_SECONDS=60`
- **THEN** every response carries `strict-transport-security: max-age=60; includeSubDomains; preload`

### Requirement: Logging honours the configured level and format

Every service SHALL log at `LOG_LEVEL` and in `LOG_FORMAT`, for its own, web server (access included) and MCP loggers, through one handler. In `json` every line SHALL carry `timestamp`, `level`, `name`, `module`, `message`, `service`, `correlation_id`, `mcp_session_id`, `trace_id`, `span_id`. In `color` every line SHALL start with `[<service name>]`.

#### Scenario: DEBUG lines appear only at DEBUG

- **WHEN** a service runs with `LOG_LEVEL=WARNING`
- **THEN** no INFO line and no access line is written

#### Scenario: JSON lines name the service

- **WHEN** a service runs with `LOG_FORMAT=json`
- **THEN** every line is one JSON object whose `service` is the service name

### Requirement: Every request carries a correlation id and an MCP session digest

Every HTTP request SHALL bind a correlation id: inbound `x-request-id` when 1 to 128 chars of letters, digits, `.`, `_`, `:` and `-`, else a new random id. The id SHALL be echoed in the `x-request-id` response header, errors included, and SHALL be the `correlation_id` of its log lines. MCP session lines SHALL carry `mcp_session_id`, the first 16 hex of the SHA-256 digest. The raw session id SHALL never appear in logs or spans.

#### Scenario: An unsafe request id

- **WHEN** a request carries `x-request-id` with a line break in it
- **THEN** the response carries a new id in `x-request-id` and the log lines carry that new id

#### Scenario: A safe request id is echoed

- **WHEN** a request carries `x-request-id: e2e-canary-req-0001`
- **THEN** the response carries `x-request-id: e2e-canary-req-0001`

#### Scenario: An over-long request id

- **WHEN** a request carries an `x-request-id` of 129 allowed characters
- **THEN** the response carries a different `x-request-id` of 1 to 128 allowed characters

#### Scenario: The MCP transport logs a session id

- **WHEN** the MCP framework writes a log line that contains a session id
- **THEN** the line carries the digest in place of the id

### Requirement: Every request has a trace, and export is optional

Every service SHALL start a trace per HTTP request, continuing a valid `traceparent`, with or without export. Spans SHALL export over OTLP to `OTEL_EXPORTER_OTLP_ENDPOINT` when set, and SHALL NOT export when unset or empty. `OTEL_SDK_DISABLED=true` SHALL switch tracing off entirely with no span recorded or exported, leaving `traceId` out. No exported span SHALL carry an MCP session id, raw or digest.

#### Scenario: Export disabled

- **WHEN** a service runs with `OTEL_EXPORTER_OTLP_ENDPOINT` unset and refuses a request
- **THEN** the problem body still carries a `traceId`
- **AND** no span is sent anywhere

#### Scenario: Export enabled by the endpoint

- **WHEN** a service runs with `OTEL_EXPORTER_OTLP_ENDPOINT` set to a collector address and answers a request
- **THEN** the server span of that request is exported to that address

#### Scenario: The SDK is switched off

- **WHEN** a service runs with `OTEL_SDK_DISABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` set, and refuses a request
- **THEN** nothing is sent to that endpoint
- **AND** the problem body has no `traceId` member

#### Scenario: No session id on an exported span

- **WHEN** export is on and a client calls an MCP tool on a session
- **THEN** no exported span of that request has an attribute that holds the client's `mcp-session-id` or its digest

### Requirement: Health, readiness and metrics have one shape

GET /health SHALL be 200 ok with service/version always. GET /ready SHALL be 200 ready if all probes ok/skipped else 503 not-ready, with status,service,version,checks each at least status ok/skipped/degraded/error. Past READINESS_PROBE_TIMEOUT_SECONDS SHALL be error, never leaking credentials, strings, or exception text. GET /metrics SHALL be Prometheus. The three SHALL skip limiting and metrics.

#### Scenario: A dependency is down

- **WHEN** ascend-memory's Qdrant probe fails
- **THEN** `/ready` answers HTTP 503 with `status` `not-ready` and `checks.qdrant.status` `error`
- **AND** `/health` still answers HTTP 200

#### Scenario: A healthy service

- **WHEN** every probe of a service reports `ok` or `skipped`
- **THEN** `/ready` answers HTTP 200 with `status` `ready`, the service name, its version and its `checks`
- **AND** `/health` answers HTTP 200 with `status` `ok`, the service name and its version

#### Scenario: A probe slower than the readiness budget

- **WHEN** a service runs with `READINESS_PROBE_TIMEOUT_SECONDS=0.1` and one of its probes takes longer than that
- **THEN** `/ready` answers HTTP 503 with `status` `not-ready` and that probe's `status` `error`

### Requirement: Every service limits the request rate of each caller

SHALL limit per address on REST/MCP as flood protection via RATE_LIMIT_DEFAULT plus stricter named settings. Over-limit REST SHALL be 429 rate_limited with Retry-After, MCP SHALL fail rate_limited:. Listing SHALL NOT limit. REST/MCP SHALL share one budget. Sharing Redis SHALL share one budget, each of the four SHALL use its REDIS_URL own prefix. Without Redis SHALL limit alone and SHALL NOT refuse for Redis failure.

#### Scenario: Too many submissions

- **WHEN** one caller sends more OCR submissions than `RATE_LIMIT_OCR` allows in its window
- **THEN** the next submission answers HTTP 429 with `code` `rate_limited` and a `Retry-After` header

#### Scenario: Too many tool calls

- **WHEN** one caller calls an MCP tool more often than its limit allows
- **THEN** the next call fails with a text that starts with `rate_limited: `

#### Scenario: Two containers share one budget

- **WHEN** one caller sends calls to two containers of ascend-web-hunter that use the same Redis, and the calls together go over the limit
- **THEN** the call that goes over the limit is refused with `rate_limited`, whichever container receives it

#### Scenario: Two services keep separate budgets in one Redis

- **WHEN** ascend-memory and ascend-ocr use the same Redis and one caller uses up its `RATE_LIMIT_DEFAULT` window of ascend-ocr
- **THEN** the caller's next request to ascend-memory is not refused because of it
- **AND** every rate limit key ascend-ocr writes starts with its own prefix

#### Scenario: Health is never limited

- **WHEN** one caller calls `/health` more often than `RATE_LIMIT_DEFAULT` allows in its window
- **THEN** every call answers HTTP 200

### Requirement: Caller-supplied URIs pass one fetch guard

Fetchers of caller URIs SHALL check each URI with the one guard before any fetch. The guard SHALL accept only `http`, `https`, `file`. It SHALL refuse unparsable URIs, bad ports, HTTP user info or missing host, and hosts off `ALLOWED_PRIVATE_HOSTS` whose lookup fails, answers none, or answers private, loopback, link-local, multicast, reserved, or unspecified. Connections SHALL use only checked addresses. Redirects SHALL resolve against the hop URL, pass the same guard, never target `file://`, and stop after `FETCH_MAX_REDIRECT_HOPS` (default 10 in ascend-audio-scribe and ascend-web-hunter, 0 in ascend-ocr). `file://` SHALL need `MCP_FILE_URI_ROOT` set and a real path inside it. Refusal details SHALL name neither root nor user info. ascend-web-hunter SHALL keep `ALLOWED_PRIVATE_HOSTS` empty by default with no file root.

#### Scenario: A host that resolves to a private address

- **WHEN** an MCP caller asks ascend-ocr to read `http://internal.example/file.pdf` and that host resolves to `10.0.0.5` and is not on `ALLOWED_PRIVATE_HOSTS`
- **THEN** the tool fails with a text that starts with `UNSAFE_URI: ` and nothing is fetched

#### Scenario: A link that leaves the file root

- **WHEN** `MCP_FILE_URI_ROOT` is set and an MCP caller asks ascend-audio-scribe to read a `file://` path inside the root that is a symbolic link to a file outside it
- **THEN** the tool fails with a text that starts with `validation: ` and the file is not read

#### Scenario: User info in an HTTP URI

- **WHEN** an MCP caller names `https://user:secret@files.example/a.mp3` to ascend-audio-scribe
- **THEN** the tool fails with a text that starts with `validation: `
- **AND** neither the tool error nor any log line holds `secret`

#### Scenario: A public URL that redirects to a private address

- **WHEN** `ALLOWED_PRIVATE_HOSTS` is empty and an MCP caller asks ascend-audio-scribe to transcribe `https://files.example/a.mp3`, whose host resolves to a public address and answers 302 with `Location: http://10.0.0.5/a.mp3`
- **THEN** the tool fails with a text that starts with `validation: `
- **AND** no request is sent to `10.0.0.5`

#### Scenario: A name that answers a private address to a second lookup

- **WHEN** an MCP caller asks ascend-ocr to read `https://files.example/a.pdf`, whose first lookup answers `93.184.216.34` and every later lookup answers `127.0.0.1`
- **THEN** the download connects to `93.184.216.34` only
- **AND** no connection is opened to `127.0.0.1`

#### Scenario: ascend-web-hunter allows only the hosts its setting names

- **WHEN** ascend-web-hunter runs with `ALLOWED_PRIVATE_HOSTS=e2e-fake-site` and a REST caller reads one page under `e2e-fake-site` and the same page under `e2e-fake-site-blocked`, both names resolving to the same private address
- **THEN** the read under `e2e-fake-site` is fetched
- **AND** the read under `e2e-fake-site-blocked` answers 400 with `code` `unsafe_uri` and no request reaches the page
- **AND** with the shipped settings `ALLOWED_PRIVATE_HOSTS` is empty, so no host skips the address check

#### Scenario: ascend-web-hunter refuses a private URL with the same guard

- **WHEN** a REST caller asks ascend-web-hunter to read `http://169.254.169.254/latest/meta-data`
- **THEN** the answer is a 400 problem body with code `unsafe_uri`
- **AND** nothing is fetched

### Requirement: The startup banner has one frame and hides secrets

Every service SHALL write one startup banner as one log record after start-up, with the library frame: service name, access URLs, log level, `/health`, `/ready`, `/metrics`, `/mcp` lines, then its own sections in one column. A check line SHALL end in `[Connected]`, `[FAILED]`, `[Warning (<reason>)]`, `[Configured]` or `[Not configured]`. No banner line SHALL hold a secret value or URI user info.

#### Scenario: A connection string with a password

- **WHEN** ascend-web-hunter starts with `REDIS_URL=redis://user:secret@redis:6379/0`
- **THEN** the banner's Redis line shows `redis://redis:6379` with its check status
- **AND** no banner line holds `secret`

#### Scenario: A key that is set

- **WHEN** ascend-memory starts with an API key set for a provider
- **THEN** that provider's banner line shows `[Configured]` and not the key

### Requirement: The MCP endpoint and server name are the same everywhere

Every service SHALL serve MCP at `/mcp` on `API_PORT`, with no separate MCP port, named after the service like `ascend-memory`. Only that path SHALL reach MCP, other paths SHALL reach REST. MCP SHALL run in FastMCP stateless HTTP mode so any container answers any request, `initialize` answers carry no `mcp-session-id` header, and no tool SHALL rely on server-to-client messages between requests.

#### Scenario: ascend-memory names itself

- **WHEN** an MCP client initializes a session with ascend-memory
- **THEN** the server name it reports is `ascend-memory`

#### Scenario: A tool call reaches a container that did not answer the handshake

- **WHEN** a client sends `initialize` to one container of ascend-ocr and then `tools/call` for `ocr_list_jobs` to another container of ascend-ocr
- **THEN** the second container answers the tool call
- **AND** the answer to `initialize` carried no `mcp-session-id` header

### Requirement: Every service build passes the same quality gates

Every Python service and the library SHALL pass ruff with the shared rule set, mypy in strict mode on source and tests, and pytest with strict markers, warnings treated as errors and 100 percent branch coverage. A service SHALL NOT weaken a shared rule. Adding rules, adding per-file exceptions for its tests and overriding the target Python version are the only changes a service makes to the shared configuration.

#### Scenario: A service drops the coverage gate

- **WHEN** a service's pytest configuration lowers the coverage threshold below 100 or drops strict markers
- **THEN** that service's tooling conformance test fails
