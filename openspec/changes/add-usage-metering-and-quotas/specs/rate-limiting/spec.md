# rate-limiting - Delta Specification

## ADDED Requirements

### Requirement: Chat and ingestion-upload endpoints are rate limited per user and per tenant

ascend-ai-agent SHALL enforce request-rate limits on `POST /api/v1/ai/prompt` and `POST /api/v1/ingestion/upload` using Redis-backed token buckets so that limits hold across multiple ascend-ai-agent replicas. Each endpoint group SHALL consume from both a per-user bucket and a per-tenant bucket; the request is rejected when either bucket is empty. Bucket capacities and refill rates SHALL be configurable in `application.yaml` (`app.usage.rate-limit.*`). The channel message endpoint `POST /api/v1/channel-host/messages` of `add-openclaw-plugin-host` SHALL consume the chat buckets of the linked user and tenant, and its rejection SHALL be answered to the platform as `refused` with reason `rate_limited`, not as an HTTP `429` to the host.

#### Scenario: Burst beyond the user limit returns 429

- **WHEN** a user sends chat requests faster than their configured per-user rate allows
- **THEN** requests beyond the bucket capacity are rejected with `429` before any controller logic runs, and requests from other users are unaffected

#### Scenario: Tenant bucket caps aggregate traffic

- **WHEN** many users of one tenant collectively exceed the per-tenant rate while each stays under their per-user rate
- **THEN** excess requests are rejected with `429` with `scope = "tenant"` in the error body

#### Scenario: Limits hold across replicas

- **WHEN** two ascend-ai-agent replicas share the same Redis and a user splits requests across both
- **THEN** the combined admitted rate does not exceed the configured per-user rate

#### Scenario: Channel message over the chat limit is refused, not 429

- **WHEN** a linked user sends chat platform messages faster than their per-user chat rate allows
- **THEN** the messages beyond the bucket capacity are answered to the platform as `refused` with reason `rate_limited`
- **AND** the host receives no HTTP `429`

### Requirement: Web-search tool invocations are rate limited inside the chat turn

Because web-search tool calls happen inside a chat turn (MCP tool callback) rather than on their own HTTP endpoint, ascend-ai-agent SHALL consume from a dedicated `web-search` bucket (per user and per tenant) around each ascend-web-hunter MCP tool invocation, the `web_download_file` calls of `add-file-download` included. When the bucket is empty, the tool invocation SHALL NOT reach the ascend-web-hunter service; instead the tool result returned to the model SHALL state that the tool is rate limited and after how many seconds it may be retried.

#### Scenario: Rate-limited tool call is short-circuited

- **WHEN** the model requests a web-search tool call and the caller's `web-search` bucket is empty
- **THEN** no request is sent to ascend-web-hunter and the model receives a tool result describing the rate limit and the retry delay, while the enclosing chat request still completes with `200`

### Requirement: Rate-limit rejection carries a structured error and Retry-After

A rate-limited HTTP request SHALL return `429` with a `Retry-After` header derived from the bucket's estimated refill time and an RFC 7807 problem detail body (`Content-Type: application/problem+json`), the same one error body as every other ascend-ai-agent error response (`upgrade-spring-boot-4` and its `agent-error-responses` spec), with `type` `https://ascend.ai/errors/rate-limited`, the snake case `code = rate_limited` at the top level, a `traceId` field, and the extension fields `scope` (`tenant` or `user`) and `retryAfterSeconds`. The body SHALL NOT carry the fields `error`, `message` or `timestamp`.

#### Scenario: 429 body and header are consistent

- **WHEN** a request is rejected by the per-user chat bucket
- **THEN** the response carries a `Retry-After` header and `Content-Type: application/problem+json`, and the body has `type = "https://ascend.ai/errors/rate-limited"`, `status = 429`, `code = "rate_limited"`, a `traceId`, `scope = "user"`, and a `retryAfterSeconds` value consistent with the header

### Requirement: Rate limiting fails open when Redis is unavailable

When the Redis backing the buckets is unreachable, ascend-ai-agent SHALL admit requests (fail-open), log a WARN, and increment `rate_limit.redis_unavailable`. Each bucket's capacity and refill rate SHALL be configuration values, and an endpoint group whose capacity is not set SHALL get no bucket and SHALL never be rejected, with no separate on and off flag (answer 93 of 2026-10-08).

#### Scenario: Redis outage does not block chat

- **WHEN** Redis is down and a user sends a chat request
- **THEN** the request is served normally and `rate_limit.redis_unavailable` increments

#### Scenario: No capacity set never rejects

- **WHEN** no bucket capacity is configured for any endpoint group
- **THEN** no request on any path is rejected with `rate_limited`
