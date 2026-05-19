## ADDED Requirements

### Requirement: Every AscendAI service exposes a Prometheus-format metrics endpoint

Every long-running AscendAI service (AscendAgent, WeatherMCP, AscendMemory, AudioScribe, AscendWebSearch, PaddleOCR) SHALL expose an HTTP endpoint that returns metrics in OpenMetrics / Prometheus exposition format on a documented path. JVM services use `/actuator/prometheus`; Python services use `/metrics`.

#### Scenario: AscendAgent metrics endpoint

- **WHEN** `GET http://localhost:9917/actuator/prometheus` is invoked
- **THEN** the response status is 200
- **AND** the body contains text in OpenMetrics format
- **AND** the body contains at least one line beginning with `jvm_memory_used_bytes`

#### Scenario: AscendMemory metrics endpoint

- **WHEN** `GET http://localhost:7020/metrics` is invoked
- **THEN** the response status is 200
- **AND** the body contains a line beginning with `python_info{`

### Requirement: Every AscendAI service emits OpenTelemetry spans

Every long-running AscendAI service SHALL be configured to emit OpenTelemetry spans via OTLP to `http://otel-collector:4317`. JVM services rely on Spring AI 1.1's bundled OTel auto-instrumentation; Python services rely on `opentelemetry-distro` auto-instrumentation activated at startup.

#### Scenario: AscendAgent emits a trace per chat turn

- **WHEN** AscendAgent serves a single `POST /api/v1/ai/prompt` request
- **AND** Tempo is queried for traces with `service.name=ascend-agent` within 5 seconds
- **THEN** at least one trace exists for that request
- **AND** the trace contains at least one span tagged `gen_ai.operation.name=chat` (Spring AI's auto-emitted LLM-call span)

#### Scenario: Python service emits a trace per HTTP request

- **WHEN** any Python service serves an HTTP request
- **AND** Tempo is queried for traces with the matching `service.name`
- **THEN** at least one trace exists with a root server-span for the request

### Requirement: Common identification tags on every metric, log label, and span attribute

Every metric emitted by any AscendAI service SHALL carry the tags `service` and `version`. The `service` tag value SHALL match the service's logical name (`ascend-agent`, `audio-scribe`, etc.). The `version` tag SHALL be derived from build metadata. The same `service` and `version` SHALL appear as Loki log labels and OTel span resource attributes (`service.name`, `service.version`).

#### Scenario: Tag presence on a custom counter

- **WHEN** a custom counter (e.g., `memory_extraction_parse_failed_total`) is scraped from AscendAgent
- **THEN** every emitted sample carries `service="ascend-agent"` and a non-empty `version="..."` tag

#### Scenario: Log labels match metric tags

- **WHEN** a log line written by AscendAgent is queried in Loki
- **THEN** the line carries the label `service="ascend-agent"`

### Requirement: Domain custom metrics — semantic memory

AscendAgent SHALL emit the following metrics related to semantic memory operations.

| Metric | Type | Required tags |
|---|---|---|
| `memory.extraction.parse_failed` | counter | `provider`, `model` |
| `memory.insert.failed` | counter | `embedding_provider`, `reason` |
| `memory.search.duration` | timer | `embedding_provider`, `outcome` |

#### Scenario: Parse-failed counter increments on extractor parse failure

- **WHEN** `SemanticMemoryExtractor` receives an LLM response from which it cannot extract a valid JSON array of facts
- **THEN** `memory_extraction_parse_failed_total{provider="<p>",model="<m>"}` increments by exactly 1

#### Scenario: Insert-failed counter increments on insert error

- **WHEN** `SemanticMemoryClient.insertMemory` invocation results in an HTTP error
- **THEN** `memory_insert_failed_total{embedding_provider="<p>",reason="<r>"}` increments by exactly 1
- **AND** `reason` is one of a closed set: `4xx`, `5xx`, `timeout`, `connect_error`

#### Scenario: Search timer records duration and outcome

- **WHEN** `SemanticMemoryClient.search` completes (success or failure)
- **THEN** `memory_search_duration_seconds_count{outcome="<o>"}` increments by 1
- **AND** `outcome` is one of `ok`, `error`, `timeout`, `not_found`

### Requirement: Domain custom metrics — RAG retrieval

AscendAgent SHALL emit the following metrics related to RAG retrieval.

| Metric | Type | Required tags |
|---|---|---|
| `rag.retrieval.hits` | counter | `provider`, `embedding_provider`, `above_threshold` |
| `rag.retrieval.duration` | timer | `provider`, `outcome` |
| `rag.last_top_score` | gauge | `provider` |
| `rag.top_score` | histogram | `provider` |

#### Scenario: Retrieval hits counter splits above/below threshold

- **WHEN** `RagRetrievalService` returns N hits from Qdrant of which K are above the configured similarity threshold
- **THEN** `rag_retrieval_hits_total{above_threshold="true"}` is incremented by K
- **AND** `rag_retrieval_hits_total{above_threshold="false"}` is incremented by `N - K`

#### Scenario: Top-score histogram observes every hit

- **WHEN** `RagRetrievalService` returns N hits with scores `[s1, ..., sN]`
- **THEN** `rag_top_score_bucket{provider="<p>"}` records N observations, one per hit score

### Requirement: Domain custom metrics — MCP tool calls

AscendAgent SHALL record a timer for every MCP tool invocation.

| Metric | Type | Required tags |
|---|---|---|
| `mcp.tool.duration` | timer | `tool`, `outcome` |

#### Scenario: Tool timer fires per call

- **WHEN** AscendAgent invokes any MCP tool (e.g., `web_search`, `transcribe_audio`)
- **THEN** `mcp_tool_duration_seconds_count{tool="<name>",outcome="<o>"}` increments by exactly 1

### Requirement: Domain custom metrics — prompt cache (powers L3 dashboard)

AscendAgent SHALL emit prompt-cache token counters from each provider strategy's `recordOutcome(...)` so the L3 Cache Hit Rate dashboard can chart cache effectiveness over time.

| Metric | Type | Required tags |
|---|---|---|
| `prompt_cache.tokens.read` | counter | `provider` |
| `prompt_cache.tokens.creation` | counter | `provider` (Anthropic only; OpenAI/Gemini implicit) |
| `prompt_cache.tokens.total` | counter | `provider` |

#### Scenario: Anthropic cache hit increments all three counters

- **WHEN** an Anthropic chat response carries `cacheReadInputTokens=487`, `cacheCreationInputTokens=0`, `inputTokens=612`
- **AND** `AnthropicPromptCacheStrategy.recordOutcome(...)` runs
- **THEN** `prompt_cache_tokens_read_total{provider="anthropic"}` increments by 487
- **AND** `prompt_cache_tokens_creation_total{provider="anthropic"}` increments by 0
- **AND** `prompt_cache_tokens_total_total{provider="anthropic"}` increments by 612

#### Scenario: OpenAI cache hit increments read + total

- **WHEN** an OpenAI chat response carries `promptTokensDetails.cachedTokens=512`, `promptTokens=1024`
- **AND** `OpenAiPromptCacheStrategy("openai").recordOutcome(...)` runs
- **THEN** `prompt_cache_tokens_read_total{provider="openai"}` increments by 512
- **AND** `prompt_cache_tokens_total_total{provider="openai"}` increments by 1024
- **AND** `prompt_cache_tokens_creation_total` is NOT incremented for `provider="openai"` (cache writes are implicit on OpenAI)

### Requirement: Spring AI generative AI metrics auto-collection

AscendAgent SHALL retain Spring AI's automatically-collected `gen_ai.*` metrics (notably `gen_ai_client_token_usage_total` with tags `model`, `type`, `provider`) once Actuator is on the classpath; no custom code is required, but the metrics MUST appear at `/actuator/prometheus`. The `provider` tag is required so the L1 Token Cost dashboard can multiply by per-provider pricing.

#### Scenario: Token usage metric is exposed with provider tag

- **WHEN** AscendAgent processes a prompt that invokes any chat provider
- **AND** `/actuator/prometheus` is then scraped
- **THEN** the body contains a line matching `gen_ai_client_token_usage_total{...,provider="...",type="(input|output)",...}`

### Requirement: Cardinality discipline on tag values

No metric tag value SHALL be a free-form unbounded string (URL, prompt content, error message). The `outcome` tag SHALL be one of: `ok`, `error`, `timeout`, `rate_limited`, `not_found`. Per-user gauges SHALL be capped at the top-10 active users by default; the cap SHALL be configurable via `app.metrics.user-gauge.max-tracked`.

#### Scenario: Outcome tag uses closed set

- **WHEN** any metric with an `outcome` tag is emitted
- **THEN** the tag value is one of `ok`, `error`, `timeout`, `rate_limited`, `not_found`

### Requirement: Actuator endpoint exposure scope

JVM services SHALL expose only `health`, `info`, and `prometheus` endpoints from Actuator by default. `env`, `heapdump`, `threaddump`, `loggers`, `caches`, `mappings`, `beans` SHALL NOT be exposed unless explicitly enabled via configuration override.

#### Scenario: Sensitive endpoint is not exposed by default

- **WHEN** `GET http://localhost:9917/actuator/env` is invoked with no override config
- **THEN** the response status is 404

### Requirement: Domain custom metrics — Python services

Each Python service SHALL emit at least the following custom metrics in addition to framework defaults.

| Service | Metric | Type | Required tags |
|---|---|---|---|
| AudioScribe | `transcription.duration_seconds` | histogram | `provider`, `outcome` |
| AudioScribe | `transcription.audio_duration_seconds` | histogram | `provider` |
| AscendWebSearch | `search.results_returned` | histogram | `engine`, `outcome` |
| AscendWebSearch | `extraction.tier_used_total` | counter | `tier` |
| AscendMemory | `memory.operations_total` | counter | `operation`, `outcome` |
| AscendMemory | `memory.search.duration_seconds` | histogram | `embedding_provider` |
| PaddleOCR | `ocr.pages_processed_total` | counter | `language`, `outcome` |
| PaddleOCR | `ocr.duration_seconds` | histogram | `language` |

#### Scenario: AudioScribe transcription metric records duration

- **WHEN** any `/api/v1/transcribe/*` request completes successfully
- **THEN** `transcription_duration_seconds_count{provider="<p>",outcome="ok"}` increments by 1
