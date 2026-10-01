# Add Usage Metering and Quotas

## Why

AscendAI has no per-tenant or per-user accounting of what anything costs, and nothing stops one caller from burning the operator's entire provider budget. Token usage exists only as aggregate Prometheus counters with **no user or tenant dimension**: `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/cache/GenAiTokenUsageRecorder.java` emits `gen_ai.client.token.usage` tagged by `gen_ai_system` / `gen_ai_request_model` / `gen_ai_token_type` only, and `ingestion.upload.bytes` (`controller/IngestionController.java`) is equally anonymous. Prometheus data also ages out (72h retention), so it can never back an invoice. There is no rate limiting anywhere in ascend-ai-agent, AscendMemory, or ascend-web-hunter (`apps/ascend-agent/build.gradle.kts` has no Bucket4j or Resilience4j-ratelimiter dependency), and provider API keys are global per deployment (`application.yaml` - `OPENAI_API_KEY` line 195, `GEMINI_API_KEY` lines 205/255, `ASCEND_ANTHROPIC_API_KEY` line 218, `MINIMAX_API_KEY` line 229; mirrored in `compose.yaml` lines 118-121). Once `add-auth-and-identity` gives us a trustworthy identity and `add-tenant-isolation` gives us a tenant model, metering and quotas become the piece that makes multi-tenant operation financially safe and billable.

## What Changes

- **Usage ledger (Postgres).** Every LLM-touching request persists a usage row - tenant, user, conversation, provider, model, prompt / completion / cached-token counts, timestamp, and request type (`chat`, `compaction`, `memory-extraction`, `embedding`) - via a new Liquibase changelog. Recording hooks into the existing token-usage interception point: `PromptCacheStrategy.recordOutcome(...)` invoked from `ChatExecutor.execute(...)` (line 97 of `service/chat/ChatExecutor.java`) and `SemanticMemoryExtractor` (line 100), extended to cover the compaction (`memory/ChatHistoryCompactionService.java`) and embedding paths which today bypass it.
- **Metering of every service, not only model calls (owner decision, 2026-10-01).** The same ledger also records OCR jobs (pages and processing time, read from the ascend-ocr job record the agent already polls), document ingestion (files, bytes and chunks per ingested file, with the embedding tokens in the existing `embedding` rows), audio transcription (audio seconds per provider of ascend-audio-scribe), web search and page reads of ascend-web-hunter (one row per request, with the tier that produced a page), and semantic memory operations of AscendMemory (one row per search, insert and delete). New request types: `ocr`, `ingestion`, `transcription`, `web-search`, `web-read`, `memory-search`, `memory-insert`, `memory-delete`. The agent records every row itself, because it makes every one of these calls with the tenant and user in hand. No service keeps a ledger of its own. Two services gain one reported number in a tool result: ascend-audio-scribe returns the audio length in seconds, and ascend-web-hunter returns the tier that produced a page, where it does not already. Calls that reach a service without passing through the agent carry no tenant and are not metered (design D12 lists them).
- **Usage query API.** `GET /api/v1/usage` returns summaries grouped by day or month - tenant-wide for `ADMIN`, own usage for `USER` - with CSV and JSON export suitable for invoicing. Payment processing is an explicit **non-goal**.
- **Quotas.** Per-tenant monthly token budget and per-user daily token budget, plus per-tenant monthly budgets for OCR pages and audio transcription seconds (the two non-model costs that grow with input size, unlimited unless set), with configurable platform defaults and per-tenant overrides. Enforced **before** the provider call; an exhausted budget returns `429` with `Retry-After` and a structured error body. Crossing a soft-warning threshold (default 80%) emits a log event and a metric so operators can alert before hard cut-off.
- **Rate limiting.** Per-user and per-tenant request-rate limits on the chat endpoint, ingestion upload, and web-search-tool-invoking paths. Redis-backed token buckets (Bucket4j vs. Redis Lua decided in design) so limits hold across ascend-ai-agent replicas. Over-limit requests get `429` + `Retry-After`.
- **BYOK provider credentials.** Per-tenant provider API keys stored encrypted at rest and resolved at request time, falling back to the global deployment keys when a tenant has none. Keys are write-only through the API (only `last4` and metadata are ever returned); management endpoints are `ADMIN`-only. This requires per-tenant provider clients - today `ChatModelResolver` builds one client per provider at startup (`@PostConstruct initializeProviders()`), so resolution gains a tenant-keyed client cache.
- **Observability feed.** The existing `gen_ai.client.token.usage` counter gains `tenant` and `request_type` tags (bounded cardinality - tenant count is small and operator-controlled), and a Usage & Quotas Grafana dashboard joins the existing `infra/observability/grafana/dashboards/` set.

## Capabilities

### New Capabilities

- `usage-metering`: per-request usage ledger rows in Postgres for model calls and for every metered service operation (OCR, ingestion, transcription, web search and reads, memory operations), and the `GET /api/v1/usage` summary/export API.
- `quota-enforcement`: per-tenant monthly and per-user daily token budgets, per-tenant monthly OCR page and transcription second budgets, pre-request enforcement with `429` + `Retry-After`, soft-warning threshold events.
- `rate-limiting`: Redis-backed per-user and per-tenant request-rate limits on chat, ingestion upload, and web-search-tool-invoking paths.
- `byok-provider-keys`: per-tenant provider API keys - encrypted at rest, write-only API with `last4` display, request-time resolution with global-key fallback, `ADMIN`-only management.

### Modified Capabilities

(none - `openspec/specs/prompt-caching/spec.md` was reviewed for the cached-token overlap: its requirements about cache strategy resolution, structured hit/miss logging, and fallback behavior do not change. The ledger reads the same response usage metadata additively from the same `recordOutcome` hook.)

## Impact

- **ascend-ai-agent code**: new `service/usage/` package (ledger recorder, quota gate, usage query service), new `repository/` Spring Data JDBC aggregates and repositories, new `controller/UsageController.java` and `controller/admin/ProviderKeyController.java`, recorder calls in `service/ingestion/client/AscendOcrClient.java` (its `JobRecord` gains `pages_done`, `started_at`, `finished_at`), the ingestion pipeline, `service/memory/SemanticMemoryClient.java` and an MCP tool-callback wrapper for the ascend-audio-scribe and ascend-web-hunter tools, rate-limit filter/interceptor wiring, `ChatModelResolver` + `config/properties/AiProviderProperties.java` extended for tenant-key resolution, the three `service/cache/` strategy classes (`AnthropicPromptCacheStrategy`, `OpenAiPromptCacheStrategy`, `NoopPromptCacheStrategy`) and `GenAiTokenUsageRecorder` feed the ledger.
- **Dependencies**: `apps/ascend-agent/build.gradle.kts` gains `com.bucket4j:bucket4j_jdk17-lettuce` 8.20.0 (the current Bucket4j release, Lettuce matches the Spring Data Redis driver) and Caffeine for the tenant client cache, both declared in `apps/ascend-agent/gradle/libs.versions.toml`.
- **Python services**: ascend-audio-scribe adds `audio_seconds` to the success result of its three transcription tools, and ascend-web-hunter makes its page-read result name the tier that produced the content if it does not already. Both are additive fields with tests in each module, and neither service stores usage.
- **Database**: new Liquibase changelog `<NN>-usage-metering.xml` in `src/main/resources/db/changelog/`, numbered at implementation time, (usage ledger table, quota config table, tenant provider-key table) referenced from `db.changelog-master.yaml`.
- **Configuration**: `application.yaml` gains default quota/rate-limit values and the master encryption key env var; `compose.yaml` mirrors the env vars.
- **Observability**: extra tags on `gen_ai.client.token.usage`, new quota/rate-limit counters, one new provisioned Grafana dashboard under `infra/observability/grafana/dashboards/`.
- **API surface**: new `GET /api/v1/usage`, new `ADMIN` endpoints under `/api/v1/admin/tenants/{tenantId}/provider-keys` (the one administration prefix `/api/v1/admin/`, owner decision 2026-10-01); chat/ingestion/web-search paths can now return `429`.
- Depends on: `add-auth-and-identity` (authenticated principal, `USER`/`ADMIN` roles) and `add-tenant-isolation` (tenant model and `tenant` claim). Neither is re-specified here. Build order (owner, 2026-10-01): groups A, B, D, then `harden-cloud-deployment`, `add-auth-and-identity`, `add-tenant-isolation`, this change, `add-audit-and-gdpr-compliance`, `add-tenant-administration`, `add-tenant-policy`. `add-tenant-policy` depends on the tenant-aware `ChatModelResolver.resolve(provider, tenantId)` this change adds. `add-chat-streaming-and-conversations` interaction: streamed responses must still record a ledger row at stream completion (design consideration).
- **Docs**: `docs/` usage-and-billing page, module `AGENTS.md` touch-ups, Bruno collection additions for the new endpoints.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/postgres-patterns`
- `/database-migrations`
- `/api-design`
- `/tdd-workflow`
