# usage-metering — Delta Specification

## ADDED Requirements

### Requirement: Every LLM-touching request persists a usage ledger row

AscendAgent SHALL persist one usage ledger row in PostgreSQL for every completed LLM-touching request, recorded from the token-usage interception point (`PromptCacheStrategy.recordOutcome` for chat and memory-extraction, plus explicit recorder calls on the compaction and embedding paths). Each row SHALL contain: tenant id, user id, conversation id (nullable for non-chat request types), provider name, model name, prompt-token count, completion-token count, cached-token count, request type (one of `chat`, `compaction`, `memory-extraction`, `embedding`), and an occurred-at timestamp in UTC. The table SHALL be created by a Liquibase changelog referenced from `db.changelog-master.yaml`.

#### Scenario: Chat turn writes a ledger row

- **WHEN** an authenticated user completes one chat request via `POST /api/v1/ai/prompt` on any provider
- **THEN** exactly one ledger row exists for that request with `request_type = 'chat'`, the caller's tenant id and user id, the resolved provider and model, and prompt/completion token counts matching the provider-reported usage metadata

#### Scenario: Memory extraction and compaction write ledger rows

- **WHEN** a chat turn triggers semantic-memory extraction and a later turn triggers chat-history compaction
- **THEN** a ledger row with `request_type = 'memory-extraction'` and a ledger row with `request_type = 'compaction'` are written, each attributed to the same tenant and user as the originating conversation

#### Scenario: Cached tokens are captured per request

- **WHEN** an Anthropic chat response reports `cacheReadInputTokens = 487`
- **THEN** the ledger row for that request has `cached_tokens = 487`

#### Scenario: Ledger failure never fails the user request

- **WHEN** the ledger insert fails (for example PostgreSQL is briefly unavailable)
- **THEN** the user receives the normal chat response
- **AND** an ERROR is logged and the `usage.ledger.write_failed` counter increments

### Requirement: Streamed responses record usage at stream completion

When chat responses are streamed (per the `add-chat-streaming-and-conversations` change), AscendAgent SHALL record the usage ledger row in the stream-completion callback using the usage metadata available at stream end, carrying the usage context captured at request start.

#### Scenario: Streamed chat turn still produces a ledger row

- **WHEN** a chat response is delivered as a stream and the stream completes normally
- **THEN** exactly one ledger row is written for the request after stream completion, with token counts from the final response metadata

### Requirement: Usage summaries are queryable via the usage API

AscendAgent SHALL expose `GET /api/v1/usage` accepting `from`, `to`, `groupBy` (`day` or `month`), and `format` (`json` or `csv`). Results SHALL aggregate ledger rows into rows of: period, provider, model, request type, prompt tokens, completion tokens, cached tokens, and request count. A caller with role `USER` SHALL receive only their own usage; a caller with role `ADMIN` SHALL receive tenant-wide usage and MAY filter by `userId`.

#### Scenario: User queries own monthly usage

- **WHEN** a `USER`-role caller requests `GET /api/v1/usage?from=2026-07-01&to=2026-07-31&groupBy=day`
- **THEN** the response is `200` with JSON rows aggregated per day containing only that user's usage

#### Scenario: Admin queries tenant-wide usage

- **WHEN** an `ADMIN`-role caller requests `GET /api/v1/usage?groupBy=month`
- **THEN** the response aggregates usage across all users of the caller's tenant

#### Scenario: User cannot read another user's usage

- **WHEN** a `USER`-role caller requests `GET /api/v1/usage?userId=<someone-else>`
- **THEN** the `userId` filter is rejected or ignored such that no other user's usage is returned

#### Scenario: CSV export for invoicing

- **WHEN** an `ADMIN`-role caller requests `GET /api/v1/usage?groupBy=month&format=csv`
- **THEN** the response has content type `text/csv` and one header row plus one data row per aggregation group, with the same columns as the JSON shape

### Requirement: Token usage metrics carry tenant and request-type dimensions

The `gen_ai.client.token.usage` counter emitted by `GenAiTokenUsageRecorder` SHALL additionally be tagged with `tenant` and `request_type`, and a provisioned Grafana dashboard SHALL visualize per-tenant token consumption from these series.

#### Scenario: Metric series is tenant-dimensioned

- **WHEN** two users from different tenants each complete one chat request
- **THEN** `/actuator/prometheus` exposes `gen_ai_client_token_usage_total` series with two distinct `tenant` tag values, each also tagged `request_type="chat"`
