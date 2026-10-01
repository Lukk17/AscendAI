# usage-metering - Delta Specification

## ADDED Requirements

### Requirement: Every LLM-touching request and metered operation persists a usage ledger row

ascend-ai-agent SHALL persist one usage ledger row in PostgreSQL for every completed LLM-touching request, recorded from the token-usage interception point (`PromptCacheStrategy.recordOutcome` for chat and memory-extraction, plus explicit recorder calls on the compaction and embedding paths). Each row SHALL contain: tenant id, user id, conversation id (nullable for non-chat request types), provider name, model name, prompt-token count, completion-token count, cached-token count, request type (one of `chat`, `compaction`, `memory-extraction`, `embedding`, `ocr`, `ingestion`, `transcription`, `web-search`, `web-read`, `memory-search`, `memory-insert`, `memory-delete`), the operation quantities `pages`, `processing_ms`, `files`, `bytes`, `chunks`, `audio_seconds` and `tier` (each empty when the request type does not measure it), and an occurred-at timestamp in UTC. Token counts SHALL be 0 on rows that call no model. The table SHALL be created by a Liquibase changelog referenced from `db.changelog-master.yaml`.

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

### Requirement: Every service operation the agent calls is metered by the agent

ascend-ai-agent SHALL record one ledger row, attributed to the caller's tenant and user, for every successful operation it makes on another service: an `ocr` row per succeeded ascend-ocr job with `pages` and `processing_ms` taken from the job record, an `ingestion` row per ingested file with `files`, `bytes` and `chunks`, a `transcription` row per ascend-audio-scribe tool call with `audio_seconds` reported by the service and the backend as `provider`, a `web-search` row per ascend-web-hunter search call, a `web-read` row per page read with the `tier` that produced the content, and a `memory-search`, `memory-insert` or `memory-delete` row per AscendMemory call. A failed operation SHALL write no row. The erasure wipe of AscendMemory SHALL write no row. No service other than ascend-ai-agent SHALL keep a usage ledger. A call made directly to a service without passing through ascend-ai-agent carries no tenant and is not metered.

#### Scenario: OCR job is metered from the job record

- **WHEN** a user of tenant `acme` uploads a scanned PDF and the ascend-ocr job succeeds with `pages_done = 3`, `started_at = 100.0` and `finished_at = 112.5`
- **THEN** one `ocr` ledger row exists for that user and tenant with `pages = 3` and `processing_ms = 12500`

#### Scenario: Ingested file is metered

- **WHEN** a user ingests a 2048-byte file that is split into 4 chunks
- **THEN** one `ingestion` row exists with `files = 1`, `bytes = 2048` and `chunks = 4`
- **AND** the embedding calls of that file are recorded as `embedding` rows

#### Scenario: Transcription is metered in audio seconds per provider

- **WHEN** a chat turn calls the `transcribe_openai` tool and the result reports `audio_seconds = 61.2`
- **THEN** one `transcription` row exists with `provider = 'openai'` and `audio_seconds = 61.2`

#### Scenario: Web search and page read are metered with the tier

- **WHEN** a chat turn calls the web search tool once and reads one page that the second tier served
- **THEN** one `web-search` row and one `web-read` row exist, and the `web-read` row names the tier that served the page

#### Scenario: Memory operations are metered and erasure is not

- **WHEN** a chat turn searches semantic memory once and stores one memory, and later an erasure job wipes the same user's memories
- **THEN** exactly one `memory-search` row and one `memory-insert` row exist for the user, and the wipe writes no row

#### Scenario: Failed operation writes no row

- **WHEN** an ascend-ocr job ends failed
- **THEN** no `ocr` row is written for it

### Requirement: Streamed responses record usage at stream completion

When chat responses are streamed (per the `add-chat-streaming-and-conversations` change), ascend-ai-agent SHALL record the usage ledger row in the stream-completion callback using the usage metadata available at stream end, carrying the usage context captured at request start.

#### Scenario: Streamed chat turn still produces a ledger row

- **WHEN** a chat response is delivered as a stream and the stream completes normally
- **THEN** exactly one ledger row is written for the request after stream completion, with token counts from the final response metadata

### Requirement: Usage summaries are queryable via the usage API

ascend-ai-agent SHALL expose `GET /api/v1/usage` accepting `from`, `to`, `groupBy` (`day` or `month`), and `format` (`json` or `csv`). Results SHALL aggregate ledger rows into rows of: period, provider, model, request type, prompt tokens, completion tokens, cached tokens, pages, processing milliseconds, files, bytes, chunks, audio seconds, and request count. A caller with role `USER` SHALL receive only their own usage; a caller with role `ADMIN` SHALL receive tenant-wide usage and MAY filter by `userId`.

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
