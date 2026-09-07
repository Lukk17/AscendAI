# rate-limiting — Delta Specification

## ADDED Requirements

### Requirement: Chat and ingestion-upload endpoints are rate limited per user and per tenant

AscendAgent SHALL enforce request-rate limits on `POST /api/v1/ai/prompt` and `POST /api/v1/ingestion/upload` using Redis-backed token buckets so that limits hold across multiple AscendAgent replicas. Each endpoint group SHALL consume from both a per-user bucket and a per-tenant bucket; the request is rejected when either bucket is empty. Bucket capacities and refill rates SHALL be configurable in `application.yaml` (`app.usage.rate-limit.*`).

#### Scenario: Burst beyond the user limit returns 429

- **WHEN** a user sends chat requests faster than their configured per-user rate allows
- **THEN** requests beyond the bucket capacity are rejected with `429` before any controller logic runs, and requests from other users are unaffected

#### Scenario: Tenant bucket caps aggregate traffic

- **WHEN** many users of one tenant collectively exceed the per-tenant rate while each stays under their per-user rate
- **THEN** excess requests are rejected with `429` with `scope = "tenant"` in the error body

#### Scenario: Limits hold across replicas

- **WHEN** two AscendAgent replicas share the same Redis and a user splits requests across both
- **THEN** the combined admitted rate does not exceed the configured per-user rate

### Requirement: Web-search tool invocations are rate limited inside the chat turn

Because web-search tool calls happen inside a chat turn (MCP tool callback) rather than on their own HTTP endpoint, AscendAgent SHALL consume from a dedicated `web-search` bucket (per user and per tenant) around each ascend-web-hunter MCP tool invocation. When the bucket is empty, the tool invocation SHALL NOT reach the ascend-web-hunter service; instead the tool result returned to the model SHALL state that the tool is rate limited and after how many seconds it may be retried.

#### Scenario: Rate-limited tool call is short-circuited

- **WHEN** the model requests a web-search tool call and the caller's `web-search` bucket is empty
- **THEN** no request is sent to ascend-web-hunter and the model receives a tool result describing the rate limit and the retry delay, while the enclosing chat request still completes with `200`

### Requirement: Rate-limit rejection carries a structured error and Retry-After

A rate-limited HTTP request SHALL return `429` with a `Retry-After` header derived from the bucket's estimated refill time and a JSON body containing `code = RATE_LIMITED`, `scope` (`tenant` or `user`), and `retryAfterSeconds`, using the same error envelope as other AscendAgent error responses.

#### Scenario: 429 body and header are consistent

- **WHEN** a request is rejected by the per-user chat bucket
- **THEN** the response carries a `Retry-After` header, and the body has `code = "RATE_LIMITED"`, `scope = "user"`, and a `retryAfterSeconds` value consistent with the header

### Requirement: Rate limiting fails open when Redis is unavailable

When the Redis backing the buckets is unreachable, AscendAgent SHALL admit requests (fail-open), log a WARN, and increment `rate_limit.redis_unavailable`. Rate limiting SHALL be toggleable via `app.usage.rate-limit.enabled` without redeploy.

#### Scenario: Redis outage does not block chat

- **WHEN** Redis is down and a user sends a chat request
- **THEN** the request is served normally and `rate_limit.redis_unavailable` increments

#### Scenario: Disabled rate limiting never rejects

- **WHEN** `app.usage.rate-limit.enabled=false`
- **THEN** no request on any path is rejected with `RATE_LIMITED`
