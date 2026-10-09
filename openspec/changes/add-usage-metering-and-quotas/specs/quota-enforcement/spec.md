# quota-enforcement - Delta Specification

## ADDED Requirements

### Requirement: Token budgets are enforced before the provider call

ascend-ai-agent SHALL enforce a per-tenant monthly token budget and a per-user daily token budget on every LLM-touching request, evaluated **before** the provider call. Budget windows are calendar month and calendar day in UTC. Platform-wide default budgets SHALL be configurable in `application.yaml` (`app.usage.quotas.*`), with per-tenant overrides stored in a Flyway-managed quota configuration table. A request whose tenant or user budget is already met or exceeded SHALL be rejected with HTTP `429`.

#### Scenario: Exhausted user budget rejects the request pre-call

- **WHEN** a user's recorded token usage for the current UTC day has reached their daily budget and the user sends a chat request
- **THEN** the response is `429` and no call is made to any AI provider

#### Scenario: Exhausted tenant budget rejects all tenant users

- **WHEN** a tenant's recorded token usage for the current UTC month has reached the tenant's monthly budget
- **THEN** chat requests from every user of that tenant are rejected with `429`, while users of other tenants are unaffected

#### Scenario: Budget window rollover restores service

- **WHEN** a user was quota-rejected and the UTC day boundary passes
- **THEN** the user's next chat request is served normally

#### Scenario: Per-tenant override beats the platform default

- **WHEN** the platform default tenant budget is X tokens and a tenant has a configured override of 2X
- **THEN** that tenant is only rejected after consuming 2X tokens in the window

### Requirement: The quota gate runs before each model call of a run

The quota gate SHALL be registered as the implementation of the shared `QuotaGate` port of `add-deployment-modules`, replacing its default `AllowAllQuotaGate`, so every earlier change that asks that port gets this decision with no edit of its own.

ascend-ai-agent SHALL run the tenant and user quota check before each model call of a run (kinds `subagent`, `scheduled` and `self_review`) and before each guard call of `add-self-improvement`, not only at the HTTP entry. A refusal inside a run SHALL NOT be an HTTP `429`: the run SHALL end `failed` with the reason `QUOTA_EXCEEDED`. The accepted overshoot of one request SHALL be the overshoot of one model call. A coding run of `add-coding-agent-delegation`, whose model calls happen inside its workspace, SHALL be checked before it starts and at every poll, and a used up quota SHALL end it `QUOTA_EXCEEDED`. A model call inside a run SHALL count in the calendar window in which the call happened, not in the window in which its run started.

#### Scenario: Quota used up during a run ends the run

- **WHEN** a run has made two model calls and the user's daily budget is used up before its third call
- **THEN** no third call is made to any provider and the run ends `failed` with the reason `QUOTA_EXCEEDED`
- **AND** no HTTP `429` is sent for it

#### Scenario: Quota used up during a coding run

- **WHEN** the tenant's monthly token quota is used up while a coding run works
- **THEN** the run ends `failed` with reason `QUOTA_EXCEEDED` at the next poll

#### Scenario: A run crossing midnight counts each call in its own day

- **WHEN** a run started at 23:59 UTC makes one model call before midnight and one after
- **THEN** the first call counts in the user's budget of the day the run started and the second in the budget of the next day

### Requirement: A quota refusal of a channel turn is answered as refused

A quota refusal of a turn that reaches ascend-ai-agent through the channel message endpoint of `add-openclaw-plugin-host` SHALL be answered to the platform as `refused` with reason `quota_exceeded` and the retry time in the text, not as an HTTP `429` to the host.

#### Scenario: Channel turn over quota

- **WHEN** a linked user whose daily budget is used up sends a message through a chat platform
- **THEN** the platform receives `refused` with reason `quota_exceeded` and a text that names the retry time
- **AND** no call is made to any AI provider

### Requirement: OCR page and transcription second budgets are enforced before the call

ascend-ai-agent SHALL support an optional per-tenant monthly budget of OCR pages and an optional per-tenant monthly budget of transcription audio seconds, with platform defaults in `app.usage.quotas.*` (unset means unlimited) and per-tenant overrides in the quota configuration table. Both are read as sums of the ledger rows of the window, with no Redis counter. A tenant at its OCR page budget SHALL be refused with HTTP `429` before any job is submitted to ascend-ocr. A tenant at its transcription budget SHALL get a tool result naming the retry time instead of the transcription, before ascend-audio-scribe is called, and the enclosing chat request SHALL still complete.

#### Scenario: Exhausted OCR page budget refuses the upload before submission

- **WHEN** tenant `acme` has used its whole monthly OCR page budget and one of its users uploads a scanned PDF
- **THEN** the response is `429` with a problem detail body with `code = "quota_exceeded"` and `scope = "tenant"`
- **AND** no job is submitted to ascend-ocr

#### Scenario: Exhausted transcription budget skips the tool call

- **WHEN** tenant `acme` has used its whole monthly transcription budget and a chat turn calls a transcription tool
- **THEN** ascend-audio-scribe receives no call and the tool result names the retry time
- **AND** the chat request completes with `200`

#### Scenario: No budget set means unlimited

- **WHEN** no OCR page budget is configured for a tenant or as a platform default
- **THEN** that tenant's uploads are never refused for OCR pages

### Requirement: Quota rejection carries a structured error and Retry-After

A quota-rejected request SHALL return `429` with a `Retry-After` header equal to the seconds remaining until the exhausted window rolls over, and an RFC 7807 problem detail body (`Content-Type: application/problem+json`), the one agent error body of `upgrade-spring-boot-4` and its `agent-error-responses` spec, with `type` `https://ascend.ai/errors/quota-exceeded`, the snake case `code = quota_exceeded` at the top level, a `traceId` field, and the extension fields `scope` (`tenant` or `user`), `limit`, `used`, `windowEnd`, and `retryAfterSeconds`. The body SHALL NOT carry the fields `error`, `message` or `timestamp`.

#### Scenario: Error body identifies the exhausted scope

- **WHEN** a request is rejected because the tenant monthly budget is exhausted
- **THEN** the `429` response has `Content-Type: application/problem+json` and a body with `type = "https://ascend.ai/errors/quota-exceeded"`, `status = 429`, `code = "quota_exceeded"`, a `traceId`, `scope = "tenant"`, the configured `limit`, the `used` amount, and a `Retry-After` header matching the seconds until the start of the next UTC month
- **AND** `retryAfterSeconds` in the body equals the `Retry-After` header

### Requirement: Quota accounting sums the PostgreSQL ledger

The quota gate SHALL decide from an indexed PostgreSQL sum of the usage ledger rows of the window, for each budget that is set, and SHALL keep no counter in Redis or in process memory, so every agent instance makes the same decision (owner answer 89.9 of 2026-10-08). Enforcement is post-paid within a single request: a request admitted with remaining budget MAY overshoot the budget by its own usage.

#### Scenario: The decision reflects the ledger on every instance

- **WHEN** a user with prior usage this window sends one request through a first agent instance and the next through a second, and Redis has been flushed in between
- **THEN** both decisions reflect the user's true recorded usage from the PostgreSQL ledger

#### Scenario: Admitted request may overshoot by one request

- **WHEN** a user has budget remaining below the size of their next request
- **THEN** the request is admitted and its full usage is recorded, and the following request is rejected

### Requirement: Soft-warning threshold emits an observable event once per window

When recorded usage crosses a configurable warning threshold (default 80%) of a tenant or user budget, ascend-ai-agent SHALL log one WARN line and increment `usage.quota.warning{scope}` exactly once per (scope, subject, window) across all agent instances, decided by a unique row in PostgreSQL.

#### Scenario: Crossing 80% fires exactly one warning

- **WHEN** a tenant's monthly usage crosses 80% of its budget across two successive requests
- **THEN** exactly one WARN log line naming the tenant and one `usage.quota.warning{scope="tenant"}` increment are emitted for that month, and later requests within the same month emit no further warning

#### Scenario: Two instances crossing at once warn once

- **WHEN** two agent instances write the two rows that move a tenant across 80% of its budget at the same moment
- **THEN** exactly one `usage_quota_warning` row exists for the tenant and month and exactly one warning is emitted

### Requirement: A budget that is not set is unlimited

Every budget SHALL be a configuration value with no separate on and off flag (answer 93 of 2026-10-08). A budget with neither a platform default in `app.usage.quotas.*` nor a tenant override SHALL never reject and SHALL cost no query, while ledger recording continues.

#### Scenario: No budget set never rejects

- **WHEN** no token budget is set for a tenant or its users, by default or by override, and a user has a large recorded usage
- **THEN** requests are served normally and ledger rows continue to be written

### Requirement: Quotas, rate limits, usage grouping and provider keys are covered by end-to-end tests

The ascend-ai-agent e2e suite SHALL check quota refusals and the provider key API with deterministic Bruno tests that call no AI model, reaching a budget by seeding ledger rows. It SHALL check the ledger rows of chat turns, tool calls and the cost in the stream with deterministic specs on the scripted model of `close-agent-test-gaps`, because those rows come from the real pipeline and the real services. The usage API grouping and the rate-limit refusals SHALL be proved by the lower MockMvc and Redis tests only, because an e2e spec of them would repeat those (owner answer 91.3 of 2026-10-08). Each spec SHALL use tenants and users of its own, and SHALL assert statuses, problem detail fields, headers, ledger rows and metrics, never a log line.

#### Scenario: A quota refusal is checked in the live stack

- **WHEN** the quota spec seeds ledger rows above a tiny user budget and sends a prompt
- **THEN** the answer is 429 `application/problem+json` with `code` `quota_exceeded`, `scope` `user` and a `Retry-After` header equal to `retryAfterSeconds`
- **AND** no ledger row is added

#### Scenario: A provider key is checked in the live stack

- **WHEN** the provider key spec stores an unissued OpenAI key for its tenant and sends a prompt with `provider=openai`
- **THEN** the answer names `openai` and the key's `last4`, with no fallback to the deployment key

#### Scenario: A live chat turn writes its ledger row

- **WHEN** the metering spec sends one scripted chat turn as `e2e-user-acme`
- **THEN** exactly one `chat` row with token counts above zero is written for that user and tenant
