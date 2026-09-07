# Design — Add Usage Metering and Quotas

## Context

Every LLM call in AscendAgent already funnels through one observation point: `PromptCacheStrategy.recordOutcome(userId, chatResponse)` is called by `service/chat/ChatExecutor.java` (line 95) and `service/memory/SemanticMemoryExtractor.java` (line 100), and every strategy implementation delegates to `service/cache/GenAiTokenUsageRecorder.java`, which reads `ChatResponse.getMetadata().getUsage()` and increments the aggregate `gen_ai.client.token.usage` Micrometer counter. That counter has no user/tenant tags and Prometheus retention is 72h, so it cannot back billing. The compaction path (`memory/ChatHistoryCompactionService.java`) and the embedding path call providers without passing through `recordOutcome` at all.

Provider clients are built **once at startup**: `service/provider/ChatModelResolver.initializeProviders()` (`@PostConstruct`) constructs one `OpenAiChatModel` / `AnthropicChatModel` per enabled provider from `AiProviderProperties`, with the API key baked into the `OpenAiApi` / `AnthropicApi` instance. BYOK therefore cannot be a per-request option tweak; it needs per-tenant client instances.

This change **depends on** two siblings and re-specifies neither:

- `add-auth-and-identity` supplies the authenticated principal, `USER`/`ADMIN` roles, and the `tenant` claim.
- `add-tenant-isolation` supplies the tenant entity/model that quota configs and provider keys reference.

A third sibling, `add-chat-streaming-and-conversations`, will make chat responses streamable; usage metadata for a streamed call is only complete when the stream finishes, which constrains where the ledger write can happen.

Infrastructure available: Postgres (Liquibase-managed, `db/changelog/db.changelog-master.yaml`), Redis (already a hard prerequisite, used for chat history), and the `add-observability` Grafana stack with provisioned dashboards under `infra/observability/grafana/dashboards/`.

## Goals / Non-Goals

**Goals:**

- One durable, queryable usage row per LLM-touching request, attributable to tenant + user, precise enough to invoice from.
- Hard token budgets (tenant/month, user/day) enforced before money is spent, with a soft-warning event ahead of cut-off.
- Request-rate limits that hold across AscendAgent replicas.
- Per-tenant provider keys that never leave the server in plaintext once written, with clean fallback to the deployment's global keys.
- All enforcement lives in AscendAgent (the gateway); downstream Python services stay untouched.

**Non-Goals:**

- Payment processing, invoicing documents, price-to-currency conversion in the API (the Grafana token-cost dashboard already handles $ via `pricing.yaml`).
- Authentication, role model, or tenant modelling (owned by the sibling changes).
- Rate limiting inside AscendMemory / AscendWebSearch / AudioScribe themselves — they are only reachable through the gateway or trusted service calls.
- Predictive cost estimation (pre-counting prompt tokens before the provider call).

## Decisions

### D1 — Ledger written from the existing `recordOutcome` funnel, asynchronously

A new `UsageLedgerRecorder` (in `service/usage/`) is invoked from the same place `GenAiTokenUsageRecorder` is today — inside each `PromptCacheStrategy.recordOutcome` implementation — so chat and memory-extraction are covered without new interception machinery. The compaction and embedding paths are extended to call the recorder explicitly (they do not need cache strategies, just the recorder). The row insert runs on a dedicated bounded executor: a ledger failure logs ERROR + increments `usage.ledger.write_failed` but **never fails the user request**. Alternative considered: Spring AOP aspect around `ChatModel.call` — rejected because the strategy funnel already exists, is tested, and carries the response metadata we need.

### D2 — Usage context threaded explicitly, not via ThreadLocal

`recordOutcome(String userId, ChatResponse)` carries too little: the ledger needs tenant, conversation, provider, model, and request type. The signature grows to accept a `UsageContext` record (tenantId, userId, conversationId, provider, requestType) built by the caller (`ChatExecutor`, `SemanticMemoryExtractor`, `ChatHistoryCompactionService`, embedding client). Explicit parameter over `ThreadLocal`/request-scope because the compaction path runs off the request thread and the streaming sibling will complete on reactive/async threads where ThreadLocals silently vanish.

**Streaming consideration:** when `add-chat-streaming-and-conversations` lands, the final `ChatResponse` (with complete usage metadata) is only available at stream end; the recorder call must sit in the stream-completion callback, receiving the same `UsageContext` captured at request start. The `UsageContext` design makes that a one-line move.

### D3 — Cached tokens recorded, prompt-caching spec untouched

The ledger row includes `cached_tokens`, read from the same provider metadata the cache strategies already log (`cacheReadInputTokens` for Anthropic, `PromptTokensDetails.cachedTokens` for OpenAI/Gemini). This is additive observation; no requirement in `openspec/specs/prompt-caching/spec.md` changes.

### D4 — Quota accounting: Redis counters for the hot path, Postgres as source of truth

Enforcing "sum this tenant's tokens this month" with a Postgres aggregate query per chat request is an unnecessary read amplification. Instead:

- At ledger-write time, the recorder also `INCRBY`s two Redis counters: `quota:tenant:{id}:{yyyy-MM}` and `quota:user:{id}:{yyyy-MM-dd}`, each with a TTL past its window end.
- The pre-request quota gate reads the two counters (two `GET`s) and rejects when a counter has already met or exceeded its budget.
- If a counter key is missing (Redis restart, first request of window), it is rebuilt from a Postgres `SUM(...)` and `SET` with the proper TTL. Postgres is always the source of truth; Redis is a rebuildable cache.

Enforcement is **post-paid within one request**: the gate blocks when the budget is already exhausted, so a single request may overshoot the budget by its own size. Accepted — pre-counting prompt tokens per provider tokenizer is complex and still cannot predict completion length. Alternative (reserve-then-settle two-phase accounting) rejected as disproportionate for this platform's scale.

Soft warning: when a ledger write moves a counter across the warning threshold (default 80%, configurable), emit one WARN log line and increment `usage.quota.warning` (tags: `scope=tenant|user`). Idempotence per window via a Redis `SETNX` marker key.

### D5 — Quota windows are calendar-based UTC

Tenant budget window = calendar month UTC; user budget window = calendar day UTC. `Retry-After` on a quota 429 = seconds until the window rolls over. Calendar windows are trivially explainable on an invoice; sliding windows are not.

### D6 — Rate limiting: Bucket4j with Redis (Lettuce) backend

`bucket4j-redis` (Lettuce integration, matching Spring Data Redis's default driver already on the classpath) provides distributed token buckets, so limits hold across replicas. Alternatives: Resilience4j RateLimiter (in-memory only — fails the multi-replica requirement), hand-rolled Redis Lua (reinventing a maintained wheel), Spring Cloud Gateway RequestRateLimiter (would introduce a whole gateway layer).

Placement:

- Chat (`POST /api/v1/ai/prompt`) and ingestion upload (`POST /api/v1/ingestion/upload`): a `HandlerInterceptor` keyed by `{userId}` and `{tenantId}` per endpoint group, registered ahead of controller execution.
- Web-search tool invocations happen **inside** a chat turn (MCP tool callback), not on their own HTTP endpoint, so the interceptor cannot see them; the tool-callback wrapper around the AscendWebSearch MCP tools consumes from a dedicated `web-search` bucket and surfaces a tool-level "rate limited, retry after Ns" result to the model instead of a 429 (the enclosing chat request already passed its own limit).

Both a user bucket and a tenant bucket must have capacity; the stricter one wins. On rejection: `429`, `Retry-After` from Bucket4j's nanos-to-wait, and the standard error body. **Fail-open** when Redis is unreachable (WARN + `rate_limit.redis_unavailable` metric): availability of chat outranks limit precision, and the quota gate (D4, Postgres-backed rebuild) still bounds total spend.

### D7 — 429 error contract shared by quotas and rate limits

Same JSON shape as the existing `GlobalExceptionHandler` error responses, plus: `code` (`QUOTA_EXCEEDED` | `RATE_LIMITED`), `scope` (`tenant` | `user`), `retryAfterSeconds`, and for quotas `limit`, `used`, `windowEnd`. `Retry-After` header always set. Two new exceptions (`QuotaExceededException`, `RateLimitExceededException`) handled centrally.

### D8 — BYOK storage: AES-256-GCM envelope encryption in Postgres

Table `tenant_provider_key`: tenant id, provider name, wrapped data-encryption-key, ciphertext (key encrypted with the DEK), GCM nonce, `key_last4`, KEK id, timestamps, unique on (tenant, provider). Mechanics:

- Per stored key, generate a random 256-bit DEK; encrypt the provider key with AES-256-GCM under the DEK; wrap the DEK with the master key-encryption-key (KEK).
- KEK comes from env `USAGE_KEK` (base64, 32 bytes) via a `KeyEncryptionService` abstraction with a `kekId` column — swapping env-KEK for AWS KMS/Vault later means a new `KeyEncryptionService` implementation plus re-wrap migration, no schema change.
- API is write-only: `PUT` upserts (request body carries the plaintext key over TLS, never logged), `GET` returns provider, `last4`, timestamps only, `DELETE` removes. All `ADMIN`-scoped under `/api/v1/tenants/{tenantId}/provider-keys`.

Alternatives: Postgres `pgcrypto` (puts plaintext key and passphrase into SQL text — worse), storing keys only in env per tenant (does not scale past a handful of tenants, no API), Vault-only storage (new mandatory infrastructure dependency; kept as upgrade path instead).

### D9 — BYOK resolution: tenant-keyed client cache in `ChatModelResolver`

`ChatModelResolver.resolve(provider)` gains a tenant-aware overload. Resolution order: tenant key (if a `tenant_provider_key` row exists for (tenant, provider)) → global key from `AiProviderProperties`. Because API keys are baked into `OpenAiApi`/`AnthropicApi` at construction, tenant clients are built lazily and held in a Caffeine cache keyed `(provider, tenantId)` with a bounded size and time-based expiry; a key upsert/delete evicts the entry. Global clients keep today's startup construction untouched. A provider `401` with a tenant key is surfaced as a clear client error naming the tenant key (last4), not silently retried on the global key — silently billing the operator for a tenant's broken key is the exact failure this change exists to prevent.

### D10 — Usage API shape

`GET /api/v1/usage?from=&to=&groupBy=day|month&format=json|csv`. `USER` role: own rows only. `ADMIN`: whole tenant, optional `userId` filter. Response rows: period, provider, model, requestType, promptTokens, completionTokens, cachedTokens, requestCount. CSV export is the same aggregation with `text/csv` content type — enough for invoicing without any payment logic. Backed by a Spring Data JPA aggregate query on the ledger table with a covering index `(tenant_id, occurred_at)`.

### D11 — Observability integration

- `GenAiTokenUsageRecorder` gains `tenant` and `request_type` tags on `gen_ai.client.token.usage` (bounded cardinality: tenants are operator-created, request types are a closed set of four).
- New counters: `usage.ledger.write_failed`, `usage.quota.rejected{scope}`, `usage.quota.warning{scope}`, `rate_limit.rejected{scope,endpoint}`, `rate_limit.redis_unavailable`.
- One new provisioned dashboard `infra/observability/grafana/dashboards/usage-quotas.json`: tokens by tenant over time, top users, quota-consumption gauges, 429 rates.

## Risks / Trade-offs

- [Single-request quota overshoot (D4)] → accepted and documented; budgets should be set with one-request headroom. Soft warning at 80% gives operators lead time.
- [Redis outage weakens rate limiting (fail-open, D6)] → quota gate still bounds absolute spend via Postgres rebuild; `rate_limit.redis_unavailable` metric alerts operators.
- [Ledger insert per chat turn adds write load] → single-row insert on an async executor, indexed narrow table; at this platform's request volume partitioning is premature. Revisit with a monthly-partition Liquibase changelog if row count warrants it.
- [KEK in an env var is weaker than KMS] → envelope design (D8) isolates the KEK behind `KeyEncryptionService` + `kekId`, making a KMS swap a bounded follow-up; `harden-cloud-deployment` owns secret delivery.
- [Tenant tag on Prometheus metrics could explode cardinality if tenants become self-service] → tenants are operator-created in this platform's model; if that changes, drop the tag and rely on the ledger (Grafana Postgres datasource) instead.
- [Sibling-change coupling: identity and tenant model land in parallel] → this change builds against their spec'd contracts (principal + `tenant` claim, tenant entity). Implementation order must be auth → tenant → this change; tasks call that out.
- [Streamed responses could lose usage rows if the client disconnects mid-stream] → recorder runs in the stream completion/termination callback (both normal completion and cancellation with whatever partial usage metadata the provider delivered); noted for the streaming change to honour.

## Migration Plan

1. Liquibase changelog is purely additive (three new tables) — deploys ahead of code safely.
2. Feature flags: `app.usage.metering.enabled` (ledger writes), `app.usage.quotas.enabled`, `app.usage.rate-limit.enabled`, `app.usage.byok.enabled` — all default `true` in docker posture, `false` only useful for debugging. Disabling quotas/rate-limits reverts to today's unlimited behavior; disabling metering stops new rows but keeps the API serving historical data.
3. Rollback: flip flags off; tables remain (no destructive rollback needed). BYOK rollback additionally clears the tenant client cache so all traffic reverts to global keys.
4. Ships after `add-auth-and-identity` and `add-tenant-isolation` are merged; no standalone value before them.

## Open Questions

1. Embedding-call granularity: one ledger row per embedding batch (recommended — matches provider billing) vs per ingested document. Tasks assume per-batch; confirm during implementation against the ingestion pipeline's batching.
2. Exact Bucket4j Redis integration artifact (`bucket4j-redis` Lettuce module version compatible with Spring Boot 3.5.4's Lettuce) — pin during implementation, not in spec.
