# Add Usage Metering and Quotas

## Why

AscendAI has no per-tenant or per-user accounting of what anything costs, and nothing stops one caller from burning the operator's entire provider budget. Token usage exists only as aggregate Prometheus counters with **no user or tenant dimension**: `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/GenAiTokenUsageRecorder.java` emits `gen_ai.client.token.usage` tagged by `gen_ai_system` / `gen_ai_request_model` / `gen_ai_token_type` only, and `ingestion.upload.bytes` (`controller/IngestionController.java`) is equally anonymous. Prometheus data also ages out (72h retention), so it can never back an invoice. There is no rate limiting anywhere in AscendAgent, AscendMemory, or AscendWebSearch (`AscendAgent/build.gradle.kts` has no Bucket4j or Resilience4j-ratelimiter dependency), and provider API keys are global per deployment (`application.yaml` — `OPENAI_API_KEY` line 195, `GEMINI_API_KEY` lines 205/255, `ASCEND_ANTHROPIC_API_KEY` line 218, `MINIMAX_API_KEY` line 229; mirrored in `docker-compose.yaml` lines 118-121). Once `add-auth-and-identity` gives us a trustworthy identity and `add-tenant-isolation` gives us a tenant model, metering and quotas become the piece that makes multi-tenant operation financially safe and billable.

## What Changes

- **Usage ledger (Postgres).** Every LLM-touching request persists a usage row — tenant, user, conversation, provider, model, prompt / completion / cached-token counts, timestamp, and request type (`chat`, `compaction`, `memory-extraction`, `embedding`) — via a new Liquibase changelog. Recording hooks into the existing token-usage interception point: `PromptCacheStrategy.recordOutcome(...)` invoked from `ChatExecutor` (line 95) and `SemanticMemoryExtractor` (line 100), extended to cover the compaction (`memory/ChatHistoryCompactionService.java`) and embedding paths which today bypass it.
- **Usage query API.** `GET /api/v1/usage` returns summaries grouped by day or month — tenant-wide for `ADMIN`, own usage for `USER` — with CSV and JSON export suitable for invoicing. Payment processing is an explicit **non-goal**.
- **Quotas.** Per-tenant monthly token budget and per-user daily token budget, with configurable platform defaults and per-tenant overrides. Enforced **before** the provider call; an exhausted budget returns `429` with `Retry-After` and a structured error body. Crossing a soft-warning threshold (default 80%) emits a log event and a metric so operators can alert before hard cut-off.
- **Rate limiting.** Per-user and per-tenant request-rate limits on the chat endpoint, ingestion upload, and web-search-tool-invoking paths. Redis-backed token buckets (Bucket4j vs. Redis Lua decided in design) so limits hold across AscendAgent replicas. Over-limit requests get `429` + `Retry-After`.
- **BYOK provider credentials.** Per-tenant provider API keys stored encrypted at rest and resolved at request time, falling back to the global deployment keys when a tenant has none. Keys are write-only through the API (only `last4` and metadata are ever returned); management endpoints are `ADMIN`-only. This requires per-tenant provider clients — today `ChatModelResolver` builds one client per provider at startup (`@PostConstruct initializeProviders()`), so resolution gains a tenant-keyed client cache.
- **Observability feed.** The existing `gen_ai.client.token.usage` counter gains `tenant` and `request_type` tags (bounded cardinality — tenant count is small and operator-controlled), and a Usage & Quotas Grafana dashboard joins the existing `infra/observability/grafana/dashboards/` set.

## Capabilities

### New Capabilities

- `usage-metering`: per-request usage ledger rows in Postgres and the `GET /api/v1/usage` summary/export API.
- `quota-enforcement`: per-tenant monthly and per-user daily token budgets, pre-request enforcement with `429` + `Retry-After`, soft-warning threshold events.
- `rate-limiting`: Redis-backed per-user and per-tenant request-rate limits on chat, ingestion upload, and web-search-tool-invoking paths.
- `byok-provider-keys`: per-tenant provider API keys — encrypted at rest, write-only API with `last4` display, request-time resolution with global-key fallback, `ADMIN`-only management.

### Modified Capabilities

(none — `openspec/specs/prompt-caching/spec.md` was reviewed for the cached-token overlap: its requirements about cache strategy resolution, structured hit/miss logging, and fallback behavior do not change. The ledger reads the same response usage metadata additively from the same `recordOutcome` hook.)

## Impact

- **AscendAgent code**: new `service/usage/` package (ledger recorder, quota gate, usage query service), new `repository/` entities + Spring Data repositories, new `controller/UsageController.java` and `controller/ProviderKeyController.java`, rate-limit filter/interceptor wiring, `ChatModelResolver` + `config/properties/AiProviderProperties.java` extended for tenant-key resolution, the four `service/cache/*PromptCacheStrategy` call sites feed the ledger.
- **Dependencies**: `AscendAgent/build.gradle.kts` gains a Redis-backed rate-limiter dependency (Bucket4j + Lettuce integration or equivalent — design decides).
- **Database**: new Liquibase changelog in `src/main/resources/db/changelog/` (usage ledger table, quota config table, tenant provider-key table) referenced from `db.changelog-master.yaml`.
- **Configuration**: `application.yaml` gains default quota/rate-limit values and the master encryption key env var; `docker-compose.yaml` mirrors the env vars.
- **Observability**: extra tags on `gen_ai.client.token.usage`, new quota/rate-limit counters, one new provisioned Grafana dashboard under `infra/observability/grafana/dashboards/`.
- **API surface**: new `GET /api/v1/usage`, new `ADMIN` endpoints under `/api/v1/tenants/{tenantId}/provider-keys`; chat/ingestion/web-search paths can now return `429`.
- **Depends on**: `add-auth-and-identity` (authenticated principal, `USER`/`ADMIN` roles) and `add-tenant-isolation` (tenant model and `tenant` claim). Neither is re-specified here. `add-chat-streaming-and-conversations` interaction: streamed responses must still record a ledger row at stream completion (design consideration).
- **Docs**: `docs/` usage-and-billing page, module `AGENTS.md` touch-ups, Bruno collection additions for the new endpoints.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/jpa-patterns`
- `/database-migrations`
- `/api-design`
- `/springboot-security`
- `/springboot-tdd`
