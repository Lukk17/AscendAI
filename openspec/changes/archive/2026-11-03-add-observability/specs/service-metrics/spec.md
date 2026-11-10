## ADDED Requirements

### Requirement: Every AscendAI service exposes a Prometheus-format metrics endpoint

Every long-running AscendAI service (ascend-agent, ascend-weather-mcp, ascend-memory, ascend-audio-scribe, ascend-web-hunter, ascend-ocr) SHALL expose an HTTP endpoint that returns metrics in OpenMetrics / Prometheus exposition format on a documented path. JVM services use `/actuator/prometheus`; Python services use `/metrics`.

#### Scenario: ascend-agent metrics endpoint

- **WHEN** `GET http://ascend-agent:9918/actuator/prometheus` is invoked from the compose network
- **THEN** the response status is 200
- **AND** the body contains text in OpenMetrics format
- **AND** the body contains at least one line beginning with `jvm_memory_used_bytes`

#### Scenario: ascend-memory metrics endpoint

- **WHEN** `GET http://localhost:7020/metrics` is invoked
- **THEN** the response status is 200
- **AND** the body contains a line beginning with `python_info{`

### Requirement: Every AscendAI service emits OpenTelemetry spans

Every long-running AscendAI service SHALL be configured to emit OpenTelemetry spans via OTLP to the OTel collector. A service SHALL export its spans whenever its OTLP endpoint is configured (`management.otlp.tracing.endpoint` for the JVM services, `OTEL_EXPORTER_OTLP_ENDPOINT` for the Python services), and `compose.yaml` SHALL configure it for every service. A Python service SHALL be switched off only by OpenTelemetry's standard `OTEL_SDK_DISABLED=true`, which tests use. No service SHALL read a custom `OTEL_ENABLED` setting or a deployment module setting to decide whether to export (owner answer 89.14 of 2026-10-08). JVM services rely on Spring AI's bundled OTel auto-instrumentation and export over OTLP HTTP to `http://otel-collector:4318/v1/traces` through `management.otlp.tracing.endpoint` (the Spring Boot 3.5.14 name, which `upgrade-spring-boot-4` later renames in its D12). Python services rely on the OpenTelemetry FastAPI instrumentation each service wires at startup and export OTLP gRPC to `http://otel-collector:4317` from `OTEL_EXPORTER_OTLP_ENDPOINT`.

#### Scenario: ascend-agent emits a trace per chat turn

- **WHEN** ascend-agent serves a single `POST /api/v1/ai/prompt` request
- **AND** Tempo is queried for traces with `service.name=ascend-agent` within 5 seconds
- **THEN** at least one trace exists for that request
- **AND** the trace contains at least one span tagged `gen_ai.operation.name=chat` (Spring AI's auto-emitted LLM-call span)

#### Scenario: The standard switch turns a Python service's export off

- **WHEN** a Python service starts with `OTEL_EXPORTER_OTLP_ENDPOINT` set and `OTEL_SDK_DISABLED=true`
- **THEN** it exports no span
- **AND** it reads no `OTEL_ENABLED` setting

#### Scenario: Python service emits a trace per HTTP request

- **WHEN** any Python service serves an HTTP request
- **AND** Tempo is queried for traces with the matching `service.name`
- **THEN** at least one trace exists with a root server-span for the request

### Requirement: Common identification tags on every metric, log label, and span attribute

Every metric emitted by any AscendAI service SHALL carry the tags `service` and `version`. In ascend-agent they SHALL be set once, by `management.metrics.tags` in `application.yaml`, and by no Java bean. The `service` tag value SHALL match the service's logical name (`ascend-agent`, `ascend-audio-scribe`, etc.). The `version` tag SHALL be derived from build metadata. The same `service` and `version` SHALL appear as Loki log labels and OTel span resource attributes (`service.name`, `service.version`).

#### Scenario: Tag presence on a custom counter

- **WHEN** a custom counter (e.g., `memory_extraction_parse_failed_total`) is scraped from ascend-agent
- **THEN** every emitted sample carries `service="ascend-agent"` and a non-empty `version="..."` tag

#### Scenario: Log labels match metric tags

- **WHEN** a log line written by ascend-agent is queried in Loki
- **THEN** the line carries the label `service="ascend-agent"`

### Requirement: Domain custom metrics - semantic memory

ascend-agent SHALL emit the following metrics related to semantic memory operations.

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

### Requirement: Domain custom metrics - RAG retrieval

ascend-agent SHALL emit the following metrics related to RAG retrieval.

| Metric | Type | Required tags |
|---|---|---|
| `rag.retrieval.hits` | counter | `provider`, `embedding_provider`, `above_threshold` |
| `rag.retrieval.duration` | timer | `provider`, `outcome` |
| `rag.top_score` | histogram | `provider` |

#### Scenario: Retrieval hits counter splits above/below threshold

- **WHEN** `RagRetrievalService` returns N hits from Qdrant of which K are above the configured similarity threshold
- **THEN** `rag_retrieval_hits_total{above_threshold="true"}` is incremented by K
- **AND** `rag_retrieval_hits_total{above_threshold="false"}` is incremented by `N - K`

#### Scenario: Top-score histogram observes every hit

- **WHEN** `RagRetrievalService` returns N hits with scores `[s1, ..., sN]`
- **THEN** `rag_top_score_bucket{provider="<p>"}` records N observations, one per hit score

### Requirement: Domain custom metrics - MCP tool calls

ascend-agent SHALL record a timer for every MCP tool invocation.

| Metric | Type | Required tags |
|---|---|---|
| `mcp.tool.duration` | timer | `tool`, `outcome` |

#### Scenario: Tool timer fires per call

- **WHEN** ascend-agent invokes any MCP tool (e.g., `web_search`, `transcribe_audio`)
- **THEN** `mcp_tool_duration_seconds_count{tool="<name>",outcome="<o>"}` increments by exactly 1

### Requirement: Domain custom metrics - prompt cache (powers L3 dashboard)

ascend-agent SHALL emit prompt-cache token counters from each provider strategy's `recordOutcome(...)` so the L3 Cache Hit Rate dashboard can chart cache effectiveness over time. The denominator of the hit rate SHALL be the `input` series of `gen_ai.client.token.usage`, which counts the same prompt tokens in the same call, so no separate total counter SHALL exist (owner answer 93 of 2026-10-08).

| Metric | Type | Required tags |
|---|---|---|
| `prompt_cache.tokens.read` | counter | `provider` |
| `prompt_cache.tokens.creation` | counter | `provider` (Anthropic only; OpenAI/Gemini implicit) |

#### Scenario: Anthropic cache hit increments the cache counters and the input tokens

- **WHEN** an Anthropic chat response carries `cacheReadInputTokens=487`, `cacheCreationInputTokens=0`, `inputTokens=612`
- **AND** `AnthropicPromptCacheStrategy.recordOutcome(...)` runs
- **THEN** `prompt_cache_tokens_read_total{provider="anthropic"}` increments by 487
- **AND** `prompt_cache_tokens_creation_total{provider="anthropic"}` increments by 0
- **AND** `gen_ai_client_token_usage_total{gen_ai_system="anthropic",gen_ai_token_type="input"}` increments by 612
- **AND** no `prompt_cache_tokens_total` series exists

#### Scenario: OpenAI cache hit increments read and the input tokens

- **WHEN** an OpenAI chat response carries `promptTokensDetails.cachedTokens=512`, `promptTokens=1024`
- **AND** `OpenAiPromptCacheStrategy("openai").recordOutcome(...)` runs
- **THEN** `prompt_cache_tokens_read_total{provider="openai"}` increments by 512
- **AND** `gen_ai_client_token_usage_total{gen_ai_system="openai",gen_ai_token_type="input"}` increments by 1024
- **AND** `prompt_cache_tokens_creation_total` is NOT incremented for `provider="openai"` (cache writes are implicit on OpenAI)

### Requirement: Spring AI generative AI metrics auto-collection

ascend-agent SHALL expose `gen_ai_client_token_usage_total` at `/actuator/prometheus` with the tags `gen_ai_system` (the provider), `gen_ai_request_model` and `gen_ai_token_type` (`input`, `output`, `total`). `GenAiTokenUsageRecorder` records it from the `recordOutcome(...)` of every prompt cache strategy, so every provider is counted whether or not prompt caching is active. The `gen_ai_system` tag is required so the L1 Token Cost dashboard can multiply by the per-provider price series.

#### Scenario: Token usage metric is exposed with provider tag

- **WHEN** ascend-agent processes a prompt that invokes any chat provider
- **AND** `/actuator/prometheus` is then scraped
- **THEN** the body contains a line matching `gen_ai_client_token_usage_total{...,gen_ai_system="...",...,gen_ai_token_type="(input|output|total)",...}`

### Requirement: Cardinality discipline on tag values

No metric tag value SHALL be a free-form unbounded string (URL, prompt content, error message). The `outcome` tag SHALL be one of: `ok`, `error`, `timeout`, `rate_limited`, `not_found`. No metric SHALL carry a `user_id` tag, with no exception, and no metric SHALL carry a tenant id tag. Tenant level detail SHALL go to log lines instead.

A new metric of a JVM service SHALL be named in lowercase, dot separated, with the singular name of its domain as the first segment (as `memory.`, `rag.`, `mcp.` and `chat.` are), and that first segment SHALL be one word without an underscore. The existing `prompt_cache.` names and Spring AI's `gen_ai.` names keep their names.

#### Scenario: Outcome tag uses closed set

- **WHEN** any metric with an `outcome` tag is emitted
- **THEN** the tag value is one of `ok`, `error`, `timeout`, `rate_limited`, `not_found`

#### Scenario: No user tag

- **WHEN** `/actuator/prometheus` of ascend-agent is scraped after requests of two users
- **THEN** no sample carries a `user_id` tag
- **AND** no `chat_history_size` series exists

#### Scenario: No tenant tag

- **WHEN** `/actuator/prometheus` of ascend-agent is scraped after requests of two tenants
- **THEN** no sample carries a tag whose value is a tenant id

#### Scenario: New metric names start with one domain word

- **WHEN** a new agent metric is added
- **THEN** its name starts with one lowercase domain word and a dot, such as `skill.` or `improvement.`, never with a segment that holds an underscore

### Requirement: Actuator endpoint exposure scope

JVM services SHALL expose only `health`, `info`, and `prometheus` endpoints from Actuator by default. `env`, `heapdump`, `threaddump`, `loggers`, `caches`, `mappings`, `beans` SHALL NOT be exposed unless explicitly enabled via configuration override.

#### Scenario: Sensitive endpoint is not exposed by default

- **WHEN** `GET http://ascend-agent:9918/actuator/env` is invoked with no override config
- **THEN** the response status is 404

### Requirement: The agent serves actuator only on the internal management port

ascend-agent SHALL serve every actuator endpoint on the management port `9918` (`management.server.port: 9918`) and none on the application port `9917` (owner decision 65.6 of 2026-10-04). `compose.yaml` SHALL NOT publish `9918` on the host. Prometheus SHALL scrape `/actuator/prometheus` on port `9918` of every ascend-agent container over the compose network, found through DNS service discovery on the compose service name so several instances are each scraped (owner answer 87 of 2026-10-08), and the agent's container healthcheck SHALL call `http://localhost:9918/actuator/health`. The gateway SHALL NOT route to `9918`.

#### Scenario: Metrics are not on the application port

- **WHEN** `GET http://localhost:9917/actuator/prometheus` is invoked on the host
- **THEN** the response status is 404

#### Scenario: Metrics are not reachable from the host

- **WHEN** a host process opens a TCP connection to `localhost:9918`
- **THEN** the connection fails, because the port is not published

#### Scenario: Prometheus scrapes the management port

- **WHEN** the Prometheus targets page is read
- **THEN** every `ascend-agent` target scrapes port `9918` and its state is `up`

### Requirement: Domain custom metrics - Python services

ascend-web-hunter and ascend-ocr SHALL emit at least the following custom metrics in addition to framework defaults. The domain metrics of ascend-audio-scribe, ascend-memory and the ascend-web-hunter search results are defined by `add-ascend-python-common`, which adds them on top of its library.

| Service | Metric | Type | Required tags |
|---|---|---|---|
| ascend-web-hunter | `strategy_attempts_total` | counter | `strategy`, `outcome`, `domain`, as defined by the main spec `web-search-caching-observability` |
| ascend-ocr | `ascendocr_jobs_total` | counter | `outcome` (the job's terminal state) |
| ascend-ocr | `ascendocr_job_duration_seconds` | histogram | none |
| ascend-ocr | `ascendocr_job_queue_wait_seconds` | histogram | none |
| ascend-ocr | `ascendocr_job_queue_documents` | gauge | none |
| ascend-ocr | `ascendocr_job_queue_pages` | gauge | none |

Where a main spec under `openspec/specs/` already defines a metric of the same service, that spec is the source of truth and this table only points to it. The ascend-ocr rows follow the job model of `openspec/specs/ocr-job-admission/spec.md`.

#### Scenario: ascend-ocr job metric counts a finished job

- **WHEN** an OCR job submitted through `POST /v1/ocr/jobs` reaches a terminal state
- **AND** `GET http://localhost:7022/metrics` is then invoked
- **THEN** `ascendocr_jobs_total{outcome="<terminal state>"}` has increased by 1

