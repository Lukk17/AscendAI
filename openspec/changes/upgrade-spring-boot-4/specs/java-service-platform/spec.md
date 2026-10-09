## Purpose

ascend-agent and ascend-weather-mcp run on one supported Spring Boot and Spring AI version line, and moving that line keeps everything a caller, an operator or the model can observe: provider defaults and error statuses, tool-call reporting, the database schema, embedding collections, metrics and trace export, and how the weather server answers bad tool arguments.

## ADDED Requirements

### Requirement: Both Java services share one supported framework line

ascend-agent and ascend-weather-mcp SHALL declare the same Spring Boot version and the same Spring AI version in their version catalogs. The Spring AI version SHALL be a GA release, and its reference documentation SHALL list the declared Spring Boot minor line as supported. Neither service SHALL depend on a milestone or snapshot of either framework.

#### Scenario: Catalogs agree

- **WHEN** a reviewer compares `apps/ascend-agent/gradle/libs.versions.toml` with `apps/ascend-weather-mcp/gradle/libs.versions.toml`
- **THEN** the `spring-boot` entries are equal and the `spring-ai` entries are equal

#### Scenario: The pair is a supported combination

- **WHEN** the declared Spring AI version's reference documentation is read
- **THEN** it lists the declared Spring Boot minor line as supported
- **AND** neither declared version carries a `-M`, `-RC` or `-SNAPSHOT` suffix

#### Scenario: Only release repositories are declared

- **WHEN** a reviewer reads the `repositories` block of both `build.gradle.kts` files
- **THEN** each block lists Maven Central and no milestone or snapshot repository

### Requirement: The agent database schema is created by versioned SQL migrations

ascend-agent SHALL create and change its PostgreSQL schema only through versioned SQL migration files that run at start-up. The first migration SHALL create `user_instructions` (`user_id` VARCHAR(255) primary key, `instruction_text` TEXT, `updated_at` TIMESTAMP, all not null), `chat_history` (`id` taking its value from a sequence, primary key, `user_id` VARCHAR(255), `role` VARCHAR(50), `content` TEXT, `created_at` TIMESTAMP, all not null) and the index `idx_chat_history_user_id` on `chat_history(user_id)`, the schema the Liquibase changelog `01-initial-schema` of the earlier release declared. The same migration SHALL create Spring Integration's JDBC tables from Spring Integration's own PostgreSQL script, and Spring Integration SHALL NOT create tables itself (`spring.integration.jdbc.initialize-schema` is `never`), so the migrations are the one owner of the schema (owner answer 89.11 of 2026-10-08). Data written by an earlier release is not carried over while no real customer deployment exists.

#### Scenario: Fresh database

- **WHEN** the agent starts against an empty `ascend_ai` database
- **THEN** the migration history holds exactly one entry, version 1, marked successful
- **AND** `user_instructions`, `chat_history` and `idx_chat_history_user_id` exist with the columns, types, lengths, nullability and primary keys listed above
- **AND** the Spring Integration tables exist next to them, created by the same migration

### Requirement: Every chat provider keeps its shipped defaults

ascend-agent SHALL keep serving the `lmstudio`, `openai`, `gemini`, `anthropic` and `minimax` providers with the defaults `application.yaml` ships: the model, a temperature of 0.7, a maximum of 16384 output tokens for `lmstudio`, `anthropic` and `minimax`, and a 120-second request timeout. `openai` and `gemini` SHALL be called over the OpenAI chat completions protocol. `anthropic`, `minimax` and `lmstudio` SHALL be called over the Anthropic messages protocol, and `minimax` SHALL reach `https://api.minimax.io/anthropic`. An `anthropic`-type provider with no configured maximum SHALL send 4096.

#### Scenario: OpenAI-protocol provider request

- **WHEN** a prompt is sent with `provider=openai` against a local server standing in for the configured base URL
- **THEN** the server receives one `POST` on the OpenAI chat completions path under that base URL
- **AND** the request body names model `gpt-4o` and temperature 0.7

#### Scenario: Anthropic-protocol provider request

- **WHEN** a prompt is sent with `provider=minimax` against a local server standing in for the configured base URL
- **THEN** the server receives one `POST` on the Anthropic messages path under that base URL
- **AND** the request body names model `MiniMax-M2.7`, temperature 0.7 and `max_tokens` 16384

#### Scenario: Missing maximum falls back to 4096

- **WHEN** an `anthropic`-type provider is configured without `max-tokens` and a prompt is sent to it
- **THEN** the request body carries `max_tokens` 4096

#### Scenario: A slow provider times out

- **WHEN** a provider is configured with a timeout of 1 second and no retry count of its own, and its server waits 3 seconds before answering every request
- **THEN** the prompt fails with a timeout in its cause chain
- **AND** the client closed every request before the server's 3 second answer
- **AND** at most three requests reached the server, the provider client's default retry count

#### Scenario: Plain HTTP provider is called over HTTP/1.1

- **WHEN** a prompt is sent to a provider whose base URL uses `http://`
- **THEN** the server records the request protocol as `HTTP/1.1`

### Requirement: Provider errors keep their HTTP statuses

When a provider call fails with an HTTP error, `POST /api/v1/ai/prompt` SHALL answer 429 for a provider 429 and 502 for every other provider status. A provider 429 and a provider 5xx SHALL be retried a bounded number of times by the provider client, and only a 429 or a 5xx that persists after the retries SHALL reach the caller, as 429 or 502. Today's agent answers such a 5xx with 500 after about 19 minutes of retries, so the 502 for a persistent 5xx is a deliberate change of this capability. The response SHALL be an `application/problem+json` body (capability `agent-error-responses`) whose `detail` SHALL start with `AI provider error:` and SHALL NOT contain the provider's JSON error body.

#### Scenario: Provider rate limit

- **WHEN** the provider answers 429 with a JSON error body
- **THEN** the agent answers 429
- **AND** the `detail` field starts with `AI provider error:` and contains no `{`

#### Scenario: Provider rejects the key

- **WHEN** the provider answers 401
- **THEN** the agent answers 502

#### Scenario: Provider server error

- **WHEN** the provider answers 500 on every attempt
- **THEN** the agent answers 502 after its bounded retries

#### Scenario: Provider recovers after a server error

- **WHEN** the provider answers 500 once and then a normal answer
- **THEN** the agent answers 200 with that answer

### Requirement: Tools the model ran are reported

For every prompt, the response metadata field `toolsUsed` SHALL list the name of each tool the model asked for and the agent ran, once per call, in call order. A prompt with no tool call SHALL report an empty list. Each reported call SHALL also be recorded in the `mcp.tool.duration` timer with its `tool` and `outcome` tags.

#### Scenario: One tool call

- **WHEN** the model answers a prompt by calling `weather_current` once and then answering
- **THEN** `toolsUsed` equals `["weather_current"]`
- **AND** `mcp.tool.duration` has a sample tagged `tool=weather_current`

#### Scenario: No tool call

- **WHEN** the model answers a prompt without calling a tool
- **THEN** `toolsUsed` is an empty list

#### Scenario: Each tool call runs once

- **WHEN** the model asks for one tool call in a turn
- **THEN** the MCP server receives exactly one call for it

### Requirement: Embedding providers keep their models and collections

ascend-agent SHALL embed with `text-embedding-nomic-embed-text-v2-moe` at 768 dimensions for `lmstudio`, `text-embedding-3-small` at 1536 for `openai` and `gemini-embedding-001` at 768 for `gemini`, and SHALL read and write the Qdrant collections `ascendai-768` and `ascendai-1536` with no change to their names, vector size or payload keys.

#### Scenario: Embedding request

- **WHEN** a document is embedded with provider `openai` against a local server standing in for the configured base URL
- **THEN** the server receives one `POST` on the OpenAI embeddings path under that base URL naming model `text-embedding-3-small` and 1536 dimensions

#### Scenario: Existing collection is reused

- **WHEN** the agent starts against a Qdrant that already holds `ascendai-768` with points written by the earlier release
- **THEN** a retrieval for a stored chunk returns that chunk
- **AND** no collection is recreated

### Requirement: Metrics and trace export survive the upgrade

Both services SHALL keep serving `GET /actuator/prometheus` with every metric name and tag key they served before the upgrade, including `gen_ai_client_token_usage_total`, `mcp_tool_duration_seconds` and the `prompt_cache_tokens_*` counters. When the OTLP tracing endpoint is configured through `management.opentelemetry.tracing.export.otlp.endpoint` (environment variable `MANAGEMENT_OPENTELEMETRY_TRACING_EXPORT_OTLP_ENDPOINT`), both services SHALL export their spans there.

#### Scenario: Metric names unchanged

- **WHEN** the metric names and tag keys of `/actuator/prometheus` are listed after one prompt, before and after the upgrade
- **THEN** every name and tag key from the earlier list is present in the later one

#### Scenario: Spans reach the configured endpoint

- **WHEN** a service starts with `MANAGEMENT_OPENTELEMETRY_TRACING_EXPORT_OTLP_ENDPOINT` set to a local OTLP receiver and serves one request
- **THEN** the receiver gets at least one span carrying that service's `service.name`

### Requirement: The weather server answers bad tool arguments with an error result

ascend-weather-mcp SHALL answer a tool call whose arguments do not match the tool's input schema (a required argument missing, or a value of the wrong type) with a successful MCP response whose result is marked as an error and whose text names the argument at fault. It SHALL keep answering a value the schema allows but the service refuses (for example a forecast length outside 1 to 16 days) with its existing result of status `invalid_input` and an error text that names the problem. In neither case SHALL it answer with a protocol error or call Open-Meteo.

#### Scenario: Wrong type

- **WHEN** `weather_forecast` is called with `days` set to the string `"many"`
- **THEN** the call result has `isError` true and its text names `days`
- **AND** no request is sent to Open-Meteo

#### Scenario: Missing required argument

- **WHEN** `weather_forecast` is called without `city`
- **THEN** the call result has `isError` true and its text names `city`
- **AND** no request is sent to Open-Meteo

#### Scenario: Out of range but schema-valid

- **WHEN** `weather_forecast` is called with `city` set to `Warsaw` and `days` set to 30
- **THEN** the call result has status `invalid_input` and its error text says `days must be between 1 and 16`
- **AND** no request is sent to Open-Meteo
