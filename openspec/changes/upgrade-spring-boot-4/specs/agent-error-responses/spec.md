## Purpose

Every REST error the ascend-agent answers is an RFC 7807 problem detail (`application/problem+json`) built by one global exception handler and naming the trace of its request, so one client-side handler covers every endpoint of the agent and of its sibling services, which already use the same type base. Each error the agent raises itself keeps the HTTP status it had before the move, and Spring MVC's own client errors answer their correct 4xx status instead of 500.

## ADDED Requirements

### Requirement: Every agent REST error body is an RFC 7807 problem detail

Every response of ascend-agent with a 4xx or 5xx status SHALL carry `Content-Type: application/problem+json` and a JSON body with the fields `type`, `title`, `status`, `detail`, `instance` and `code`, plus the `traceId` of the requirement "Every agent problem body names its trace". `type` SHALL be `https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`. `title` SHALL be the HTTP reason phrase of the status. `status` SHALL equal the HTTP status. `instance` SHALL be the request path. `code` SHALL be a stable snake case value and SHALL appear at the top level of the body, not inside a nested object. The body SHALL NOT carry the fields `error`, `message` or `timestamp`, and SHALL NOT carry a stack trace, an exception class name or a provider's JSON error body. One exception handler class SHALL build every body the controllers' errors produce.

#### Scenario: A handled exception answers a problem body

- **WHEN** a document routing failure ends a request to `POST /api/v1/ai/prompt`
- **THEN** the response status is 422 with `Content-Type: application/problem+json`
- **AND** the body has `type` `https://ascend.ai/errors/document-routing-failed`, `title` `Unprocessable Entity`, `status` 422, `code` `document_routing_failed`, `instance` `/api/v1/ai/prompt` and a `detail` that names the document
- **AND** the body has no `error`, `message` or `timestamp` field

#### Scenario: A controller refusal answers a problem body

- **WHEN** a prompt with an image is sent to a provider and model without vision support
- **THEN** the response status is 415 with `Content-Type: application/problem+json`
- **AND** the body has `code` `vision_unsupported`, `type` `https://ascend.ai/errors/vision-unsupported` and a `detail` that contains `does not support image input`

#### Scenario: An upload with only refused file types answers a problem body

- **WHEN** `POST /api/v1/ingestion/upload` receives only files whose detected type is outside the allowlist
- **THEN** the response status is 415 with `Content-Type: application/problem+json`
- **AND** the body has `code` `unsupported_media_type` and a `detail` that names each refused file

#### Scenario: An unexpected exception hides its text

- **WHEN** a request fails with an exception no handler names
- **THEN** the response status is 500 with `Content-Type: application/problem+json`
- **AND** the body has `code` `internal`, `type` `https://ascend.ai/errors/internal` and the `detail` `An unexpected error occurred. Check server logs for details.`
- **AND** the body contains neither the exception's message, nor its class name, nor a package name of the agent

#### Scenario: The code field is at the top level

- **WHEN** any error body of the agent is read as JSON
- **THEN** `code` is a property of the root object
- **AND** the root object has no `properties` field

### Requirement: Every agent problem body names its trace

Every problem body of ascend-agent SHALL carry the extension field `traceId` at the top level of the body, next to `code`. Its value SHALL be the 32 character lower case hex id of the trace that is current while the body is built, read from Micrometer's `Tracer`, which is the id the trace is exported under. This SHALL hold for the bodies of the global exception handler, the 401 body of the security entry point and the body rendered for Spring Boot's `/error` path. When no span is current, the field SHALL be left out, and it SHALL never hold an empty or invented value.

#### Scenario: A failed request names its trace in Tempo

- **WHEN** a client sends `POST http://localhost:9917/api/v1/ai/prompt` with a body the agent refuses with a 400 problem detail
- **THEN** the response body holds a `traceId` field of 32 lower case hex characters
- **AND** Tempo returns a trace for that id with `service.name=ascend-agent`

#### Scenario: An error body carries the caller's trace id

- **WHEN** `GET /api/v1/ai/prompt` is called with the header `traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`
- **THEN** the response status is 405 with `Content-Type: application/problem+json`
- **AND** the body has the top-level field `traceId` with the value `4bf92f3577b34da6a3ce929d0e0e4736`

#### Scenario: An error body without a caller trace still names a trace

- **WHEN** a path under `/api/v1` that no controller maps is called without a `traceparent` header
- **THEN** the 404 problem body has a top-level `traceId` of 32 lower case hex characters
- **AND** the root object has no `properties` field

#### Scenario: The 401 body names its trace

- **WHEN** `app.security.enabled` is true and `POST /api/v1/ai/prompt` is called without credentials
- **THEN** the 401 problem body has a top-level `traceId` of 32 lower case hex characters

#### Scenario: No current span leaves the field out

- **WHEN** the problem body factory builds a body while no span is current
- **THEN** the body has no `traceId` field
- **AND** every other field of the body is present

#### Scenario: An unauthenticated call with security enabled answers a problem body

- **WHEN** `app.security.enabled` is true and `POST /api/v1/ai/prompt` is called without credentials
- **THEN** the response status is 401 with `Content-Type: application/problem+json` and the `WWW-Authenticate` header for Basic authentication
- **AND** the body has `code` `unauthorized`

#### Scenario: An error rendered outside the controllers answers a problem body

- **WHEN** an error is raised outside every controller and Spring Boot renders it through its `/error` path
- **THEN** the response carries `Content-Type: application/problem+json` with `code` `http_error` and the status the container set
- **AND** the `detail` is the HTTP reason phrase and contains no exception text

### Requirement: Errors the agent raises keep their status

ascend-agent SHALL answer each error class it raises itself with the HTTP status it answered before the move to problem details, and with the code listed here:

| Error | Status | `code` |
|---|---|---|
| Incompatible embedding configuration | 400 | `incompatible_embedding` |
| Unsupported file type in the ingestion pipeline | 400 | `unsupported_file_type` |
| `IllegalArgumentException`, for example an unknown or disabled provider | 400 | `validation` |
| Upload with no file | 400 | `no_file` |
| Unknown `compactionProvider` | 400 | `unknown_compaction_provider` |
| Unauthenticated call with security enabled | 401 | `unauthorized` |
| Upload where every file is refused | 415 | `unsupported_media_type` |
| Image for a model without vision | 415 | `vision_unsupported` |
| Document routing failure | 422 | `document_routing_failed` |
| Provider answered 429 | 429 | `provider_rate_limited` |
| Provider answered any other error status | 502 | `provider_error` |
| Ingestion failure | 502 | `ingestion_failed` |
| AI generation failure | 500 | `ai_generation_failed` |
| Any other exception | 500 | `internal` |

#### Scenario: Statuses before and after are equal

- **WHEN** the error tests that pinned the status of each error class above on the earlier release are run against the problem detail release
- **THEN** every status they assert for those classes is unchanged

#### Scenario: Upload with no file

- **WHEN** `POST /api/v1/ingestion/upload` is called with an empty `file` part
- **THEN** the response status is 400 with `code` `no_file` and the `detail` `No file provided`

#### Scenario: Unknown compaction provider

- **WHEN** a prompt names a `compactionProvider` that is not configured
- **THEN** the response status is 400 with `code` `unknown_compaction_provider` and a `detail` that names the value and lists the known providers

### Requirement: Spring MVC's own errors answer their correct client status

When Spring MVC itself refuses a request before or around a controller method, ascend-agent SHALL answer the 4xx status that names the caller's mistake, never 500, as a problem body with the code listed here. The `detail` SHALL be Spring's own description of the refusal. Any other status Spring MVC answers SHALL carry the code `http_error`, and a 5xx among them SHALL carry the fixed `detail` of `internal`.

| Refusal | Status | `code` |
|---|---|---|
| Missing request part or parameter, unreadable body, value of the wrong type | 400 | `bad_request` |
| Bean validation failure | 400 | `validation` |
| Path no controller maps | 404 | `not_found` |
| Method the path does not support | 405 | `method_not_allowed` |
| `Accept` header the endpoint cannot produce | 406 | `not_acceptable` |
| Upload over the multipart size limit | 413 | `content_too_large` |
| Request body type the endpoint does not consume | 415 | `unsupported_media_type` |

#### Scenario: Missing request part

- **WHEN** `POST /api/v1/ai/prompt` is called without the `prompt` part
- **THEN** the response status is 400 with `Content-Type: application/problem+json` and `code` `bad_request`
- **AND** the `detail` names `prompt`

#### Scenario: Unknown path

- **WHEN** a path under `/api/v1` that no controller maps is called
- **THEN** the response status is 404 with `Content-Type: application/problem+json` and `code` `not_found`

#### Scenario: Wrong method

- **WHEN** `GET /api/v1/ai/prompt` is called
- **THEN** the response status is 405 with `Content-Type: application/problem+json` and `code` `method_not_allowed`
- **AND** the `Allow` header lists `POST`

#### Scenario: Accept header the endpoint cannot produce

- **WHEN** `POST /api/v1/ai/prompt` is called with a valid multipart body and `Accept: text/html`
- **THEN** the response status is 406 with `Content-Type: application/problem+json` and `code` `not_acceptable`
- **AND** no provider is called

#### Scenario: Upload over the size limit

- **WHEN** a file larger than `spring.servlet.multipart.max-file-size` is uploaded to `POST /api/v1/ingestion/upload` through the running server
- **THEN** the response status is 413 with `Content-Type: application/problem+json` and `code` `content_too_large`

#### Scenario: Body type the endpoint does not consume

- **WHEN** `POST /api/v1/ai/prompt` is called with `Content-Type: application/json`
- **THEN** the response status is 415 with `Content-Type: application/problem+json` and `code` `unsupported_media_type`

### Requirement: A validation failure lists every rejected field

When a request fails bean validation, ascend-agent SHALL answer 400 with `code` `validation` and an extension field `errors` at the top level of the body. `errors` SHALL be an array with one object per rejected constraint, each with the string fields `field` and `message`, sorted by `field`, and SHALL keep every message when one field breaks more than one constraint. A body with any other code SHALL NOT carry `errors`.

#### Scenario: Two fields fail validation

- **WHEN** a request fails bean validation on the fields `name` and `description`, with two broken constraints on `name`
- **THEN** the response status is 400 with `code` `validation`
- **AND** `errors` holds three objects, the one for `description` first, each with its `field` and its `message`

#### Scenario: An illegal argument carries no field list

- **WHEN** a request fails with an `IllegalArgumentException`
- **THEN** the response status is 400 with `code` `validation`
- **AND** the body has no `errors` field

### Requirement: The API description names the problem body

The OpenAPI description the agent serves at `/v3/api-docs` SHALL describe every documented error response of `/api/v1/**` with media type `application/problem+json` and the problem detail schema.

#### Scenario: Error responses in the API description

- **WHEN** `/v3/api-docs` is read
- **THEN** every 4xx and 5xx response of `/api/v1/ai/prompt`, `/api/v1/ingestion/upload` and `/api/v1/ingestion/run` lists `application/problem+json` as its content type
- **AND** none of them lists `application/json`
