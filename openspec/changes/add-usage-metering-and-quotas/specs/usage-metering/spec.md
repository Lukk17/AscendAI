# usage-metering - Delta Specification

## ADDED Requirements

### Requirement: Every LLM-touching request and metered operation persists a usage ledger row

ascend-ai-agent SHALL persist one usage ledger row in PostgreSQL for every completed LLM-touching request, through one path only: the caller of every metered call (chat, memory extraction, compaction, embedding and every service operation below) SHALL send one `UsageEvent` through `UsageEventPort` of `add-deployment-modules`, and the registered `LedgerUsageEventPort` SHALL be the only writer of ledger rows. The prompt cache strategies SHALL NOT write or build ledger rows (owner answer 89.9 of 2026-10-08). Each row SHALL contain: tenant id, user id, conversation id (nullable for non-chat request types), provider name, model name, prompt-token count, completion-token count, cached-token count, request type (one of `chat`, `compaction`, `memory-extraction`, `embedding`, `ocr`, `ingestion`, `transcription`, `web-search`, `web-read`, `memory-search`, `memory-insert`, `memory-delete`, `subagent`, `sandbox`, `mcp-tool`, `web-download`, `coding-agent`, `scheduled`, `self-review`, `self-check`), the operation quantities `pages`, `processing_ms`, `files`, `bytes`, `chunks`, `audio_seconds` and `tier` (each empty when the request type does not measure it), the nullable `run_id` and `parent_run_id` (UUID) of the run the row was written in, the nullable `tool` holding the prefixed tool name of an `mcp-tool` row, and an occurred-at timestamp in UTC. Token counts SHALL be 0 on rows that call no model. The table SHALL be created by a Flyway versioned SQL migration under `apps/ascend-agent/src/main/resources/db/migration/`, with an index on `run_id` so a run tree's usage can be summed and an index on `(tenant_id, occurred_at)` for the quota sums, and the `tool` column SHALL be part of that same first migration.

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

#### Scenario: Cache strategies write no ledger row

- **WHEN** a chat turn completes on a provider whose prompt cache strategy records a cache outcome
- **THEN** the one `chat` ledger row comes from the `UsageEvent` the chat caller sent through `UsageEventPort`
- **AND** the cache strategy sent no event and wrote no row

#### Scenario: A model call of a run carries the run ids

- **WHEN** a run of kind `subagent` with parent run `P` makes one model call
- **THEN** one ledger row with `request_type = 'subagent'` is written, carrying the run's `run_id` and `parent_run_id = P`

### Requirement: Every service operation the agent calls is metered by the agent

ascend-ai-agent SHALL record one ledger row, attributed to the caller's tenant and user, for every successful operation it makes on another service: an `ocr` row per succeeded ascend-ocr job with `pages` and `processing_ms` taken from the job record, an `ingestion` row per ingested file with `files`, `bytes` and `chunks`, a `transcription` row per ascend-audio-scribe tool call with `audio_seconds` reported by the service and the backend as `provider`, a `web-search` row per ascend-web-hunter search call, a `web-read` row per page read with the `tier` that produced the content, a `memory-search`, `memory-insert` or `memory-delete` row per AscendMemory call, a `web-download` row per `web_download_file` call that stored or deduplicated a file with `provider = ascend-web-hunter`, `bytes` the size and `tier` the `fetch_path`, an `mcp-tool` row per successful call of a tool of a server with `metered: true` with `provider` the server id or its metric tag and `tool` the prefixed tool name, and a `sandbox` row per destroyed workspace with `processing_ms` the time from the workspace's `created_at` to its `destroyed_at`. A failed operation SHALL write no row, and a workspace whose create failed SHALL write no `sandbox` row. The erasure wipe of AscendMemory SHALL write no row. No service other than ascend-ai-agent SHALL keep a usage ledger. A call made directly to a service without passing through ascend-ai-agent carries no tenant and is not metered.

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

#### Scenario: File download is metered

- **WHEN** a chat turn calls `web_download_file` three times, the first call stores a file of 4096 bytes fetched through `fetch_path` `direct` and the second deduplicates the same file, and a third call is refused
- **THEN** two `web-download` rows exist with `provider = 'ascend-web-hunter'`, the first with `bytes = 4096` and `tier = 'direct'`
- **AND** the refused call writes no row

#### Scenario: Metered MCP tool call writes a row with the tool name

- **WHEN** a chat turn calls a tool of an outside MCP server with `metered: true` once successfully and once with an error
- **THEN** exactly one `mcp-tool` row exists, with `provider` set to the server id or its metric tag and `tool` set to the prefixed tool name

#### Scenario: Destroyed workspaces are metered as sandbox time

- **WHEN** a workspace of a run is destroyed after it existed for 90 seconds, and a chat workspace of a conversation is destroyed
- **THEN** one `sandbox` row exists for the run's tenant and user with `processing_ms` within one second of 90000 and the run's `run_id` and `parent_run_id`
- **AND** one `sandbox` row exists for the conversation's tenant and user with no run id
- **AND** a workspace whose create failed writes no row

### Requirement: The ledger backs the company usage port and joins erasure and export

This change SHALL register an implementation of `UsageEventPort` of `add-deployment-modules` that replaces the default `NoOpUsageEventPort` and writes one ledger row per recorded usage event, so every usage event an earlier change records through the port becomes a ledger row with no edit of that change. It SHALL register a store step for `usage_ledger` and `usage_quota_warning` in the shared store inventory of `add-audit-and-gdpr-compliance`, so per user and per tenant erasure delete the rows and per user and per tenant export hold them, and per tenant erasure SHALL also delete the tenant's `tenant_quota_config` and `tenant_provider_key` rows. An export SHALL never hold a provider key.

#### Scenario: A usage event becomes a ledger row

- **WHEN** `add-mcp-tool-servers` records one usage event for a successful call of a metered tool through `UsageEventPort`
- **THEN** one `usage_ledger` row of type `mcp-tool` with the server, the prefixed tool name and the tenant exists

#### Scenario: Erasure removes the ledger rows of the subject

- **WHEN** an erasure job of `add-audit-and-gdpr-compliance` for user `frosty` of tenant `acme` completes
- **THEN** no `usage_ledger` row of `frosty` in `acme` remains
- **AND** the rows of every other user and tenant are unchanged

### Requirement: Runs and the agent changes are metered with their own request types

Every ledger row written while a run of `add-agent-subagents` works, of any request type, SHALL carry that run's `run_id` and `parent_run_id`, read from the run context the agent binds on the run's thread. A model call of a run SHALL use the request type of the run's kind: `subagent` for kind `subagent`, `scheduled` for kind `scheduled` and `self-review` for kind `self_review`. A guard call of `add-self-improvement` SHALL write a `self-check` row. A coding run of `add-coding-agent-delegation` SHALL write, when it ends in any state, one `coding-agent` row per model it used, carrying its `run_id`. A reminder of `add-scheduled-tasks` makes no model call and SHALL write no row. A voice note of `add-openclaw-plugin-host` that is transcribed SHALL write a `transcription` row with `audio_seconds`, attributed to the linked user.

#### Scenario: Tool-side row inside a run carries the run ids

- **WHEN** a run calls the web search tool once
- **THEN** the `web-search` row carries the run's `run_id` and `parent_run_id`

#### Scenario: Scheduled run is shown apart from subagent work

- **WHEN** a run of kind `scheduled` makes two model calls and a reminder of a scheduled job fires
- **THEN** two ledger rows with `request_type = 'scheduled'` and the run's ids exist
- **AND** the reminder writes no row

#### Scenario: Finished coding run writes one row per model

- **WHEN** a coding run that used two models ends
- **THEN** two `coding-agent` rows exist, one per model, each carrying the run's `run_id`

#### Scenario: Ledger rows of a coding run

- **WHEN** a coding run that used one model ends `done`
- **THEN** the ledger holds one `coding-agent` row and one `sandbox` row for that run id, with the run's tenant and user

#### Scenario: Self-improvement review and guard calls are metered

- **WHEN** a review run makes three model calls and the guard is called once
- **THEN** three `self-review` rows with the review run's `run_id` and one `self-check` row exist

#### Scenario: Voice note transcription is metered for the linked user

- **WHEN** a linked user sends a voice note of 12.5 seconds through a chat platform and it is transcribed
- **THEN** one `transcription` row with `audio_seconds = 12.5` exists for that user

### Requirement: Streamed responses record usage at stream completion

When chat responses are streamed (per the `add-chat-streaming-and-conversations` change), ascend-ai-agent SHALL record the usage ledger row in the stream-completion callback using the usage metadata available at stream end, carrying the usage context captured at request start.

#### Scenario: Streamed chat turn still produces a ledger row

- **WHEN** a chat response is delivered as a stream and the stream completes normally
- **THEN** exactly one ledger row is written for the request after stream completion, with token counts from the final response metadata

### Requirement: Usage summaries are queryable via the usage API

ascend-ai-agent SHALL expose `GET /api/v1/usage` accepting `from`, `to`, `groupBy` (`day`, `month` or `run`), and `format` (`json` or `csv`). Results SHALL aggregate ledger rows into rows of: period, provider, model, request type, prompt tokens, completion tokens, cached tokens, pages, processing milliseconds, files, bytes, chunks, audio seconds, and request count. `groupBy=run` is an extra option: it SHALL group the rows of the window by `run_id` instead of by period, each row SHALL name `runId` and `parentRunId` in place of the period, and the usage made outside any background run SHALL be one row with an empty `runId`. A caller with role `USER` SHALL receive only their own usage, a `USER` request whose `userId` names the caller SHALL answer the caller's own usage, and a `USER` request whose `userId` names another user SHALL be refused with 403 and `code` `forbidden`, never ignored. A caller with role `ADMIN` SHALL receive tenant-wide usage and MAY filter by `userId`.

#### Scenario: Usage grouped per background run

- **WHEN** a `USER`-role caller whose window holds the rows of a run `R`, of its child run `C` (`parent_run_id = R`) and of one chat turn requests `GET /api/v1/usage?groupBy=run`
- **THEN** the response is `200` with one row for `R`, one row for `C` with `parentRunId = R`, and one row with an empty `runId` for the chat turn, and each row's sums equal the sums of its ledger rows

#### Scenario: User queries own monthly usage

- **WHEN** a `USER`-role caller requests `GET /api/v1/usage?from=2026-07-01&to=2026-07-31&groupBy=day`
- **THEN** the response is `200` with JSON rows aggregated per day containing only that user's usage

#### Scenario: Admin queries tenant-wide usage

- **WHEN** an `ADMIN`-role caller requests `GET /api/v1/usage?groupBy=month`
- **THEN** the response aggregates usage across all users of the caller's tenant

#### Scenario: User cannot read another user's usage

- **WHEN** a `USER`-role caller requests `GET /api/v1/usage?userId=<someone-else>`
- **THEN** the response is 403 `application/problem+json` with `code` `forbidden`, and no usage row is returned

#### Scenario: User passes their own id

- **WHEN** a `USER`-role caller requests `GET /api/v1/usage?userId=<own id>`
- **THEN** the response is `200` with only that user's usage

#### Scenario: CSV export for invoicing

- **WHEN** an `ADMIN`-role caller requests `GET /api/v1/usage?groupBy=month&format=csv`
- **THEN** the response has content type `text/csv` and one header row plus one data row per aggregation group, with the same columns as the JSON shape

### Requirement: Token usage metrics carry tenant and request-type dimensions

The ledger port SHALL increment the counter `usage.tokens` for every usage event it records, tagged with `tenant`, `request_type` (the closed set of request types of the ledger) and `token_type` (`input`, `output` or `cached`), and a provisioned Grafana dashboard SHALL visualize per-tenant token consumption from these series. The existing `gen_ai.client.token.usage` counter of `GenAiTokenUsageRecorder` SHALL stay unchanged.

#### Scenario: Metric series is tenant-dimensioned

- **WHEN** two users from different tenants each complete one chat request
- **THEN** `/actuator/prometheus` exposes `usage_tokens_total` series with two distinct `tenant` tag values, each also tagged `request_type="chat"`

### Requirement: The chat stream reports the estimated cost of the turn

When `app.usage.cost-estimate.enabled` is `true` (the default), the terminal `done` event of the chat stream SHALL carry `metadata.estimatedCostUsd`, the estimated cost in US dollars of the turn's own model calls, priced from `infra/pricing/pricing.yaml` through the `PriceTable` cost meter of `add-agent-subagents`, with cached input tokens at the full input price. The cost of a background run started by the turn SHALL NOT be included. When the flag is `false`, or when a model of the turn has no price in the table, the field SHALL be left out, and an unpriced model SHALL increase `usage.cost_estimate.unpriced{provider,model}`. Owner decision 65.4 of 2026-10-04.

#### Scenario: Cost in the done event

- **WHEN** a streamed turn uses 1000 input and 500 output tokens of a model priced at 0.003 and 0.015 dollars per 1000 tokens
- **THEN** `done.metadata.estimatedCostUsd` is `0.0105`

#### Scenario: Estimate switched off

- **WHEN** `app.usage.cost-estimate.enabled` is `false` and a streamed turn completes
- **THEN** `done.metadata` has no `estimatedCostUsd`

#### Scenario: Unpriced model

- **WHEN** a streamed turn uses a model that `pricing.yaml` does not list
- **THEN** `done.metadata` has no `estimatedCostUsd` and `usage.cost_estimate.unpriced` names the provider and model
