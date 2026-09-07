# Tasks — Add Usage Metering and Quotas

Depends on `add-auth-and-identity` (principal + roles) and `add-tenant-isolation` (tenant model) being merged first.

## 1. Schema and dependencies

- [ ] 1.1 Create Liquibase changelog `apps/ascend-ai-agent/src/main/resources/db/changelog/02-usage-metering.xml` with three tables: `usage_ledger` (tenant_id, user_id, conversation_id nullable, provider, model, prompt_tokens, completion_tokens, cached_tokens, request_type, occurred_at UTC; covering index `(tenant_id, occurred_at)` plus `(user_id, occurred_at)`), `tenant_quota_config` (tenant_id unique, monthly_token_budget, per_user_daily_token_budget nullable overrides), `tenant_provider_key` (tenant_id + provider unique, wrapped_dek, ciphertext, gcm_nonce, kek_id, key_last4, created_at, updated_at)
- [ ] 1.2 Reference the new changelog from `db.changelog-master.yaml`; run `./gradlew integrationTest` to confirm Liquibase applies cleanly on Testcontainers Postgres
- [ ] 1.3 Add the Redis-backed Bucket4j dependency (Lettuce integration compatible with Spring Boot 3.5.4) to `apps/ascend-ai-agent/build.gradle.kts` and `gradle/libs.versions.toml`; pin the version (design Open Question 2)
- [ ] 1.4 Add `app.usage.*` configuration block to `application.yaml` (metering/quotas/rate-limit/byok `enabled` flags, default tenant monthly budget, default user daily budget, warning threshold 0.8, per-endpoint bucket capacities and refill rates) and a `UsageProperties` `@ConfigurationProperties` class; mirror env vars (`USAGE_KEK` etc.) in `compose.yaml`

## 2. Usage ledger

- [ ] 2.1 Create `UsageContext` record (tenantId, userId, conversationId, provider, requestType) and extend `PromptCacheStrategy.recordOutcome` to accept it; update `ChatExecutor`, `SemanticMemoryExtractor`, and all four strategy implementations
- [ ] 2.2 Create `service/usage/UsageLedgerRecorder` with JPA entity + Spring Data repository; insert runs on a dedicated bounded async executor; failures log ERROR and increment `usage.ledger.write_failed` without propagating
- [ ] 2.3 Wire `UsageLedgerRecorder` into every `recordOutcome` implementation alongside `GenAiTokenUsageRecorder`, reading prompt/completion/cached tokens from the response metadata (Anthropic `cacheReadInputTokens`, OpenAI/Gemini `PromptTokensDetails.cachedTokens`)
- [ ] 2.4 Extend `ChatHistoryCompactionService` to build a `UsageContext` with `request_type = compaction` and record its provider calls
- [ ] 2.5 Extend the embedding call path to record one ledger row per embedding batch with `request_type = embedding` (confirm batch granularity against the ingestion pipeline — design Open Question 1)
- [ ] 2.6 Add `tenant` and `request_type` tags to `GenAiTokenUsageRecorder`
- [ ] 2.7 Test: integration test asserting one chat turn writes exactly one `usage_ledger` row with `request_type = 'chat'`, correct tenant/user attribution, and token counts matching the stubbed provider usage metadata
- [ ] 2.8 Test: ledger insert failure (repository throws) still returns the chat response and increments `usage.ledger.write_failed`
- [ ] 2.9 Test: Anthropic response with `cacheReadInputTokens=487` produces a row with `cached_tokens = 487`

## 3. Usage query API

- [ ] 3.1 Create `controller/UsageController` with `GET /api/v1/usage` (`from`, `to`, `groupBy=day|month`, `format=json|csv`, optional `userId` for ADMIN) and `service/usage/UsageQueryService` backed by a JPA aggregate query on `usage_ledger`
- [ ] 3.2 Enforce scoping: `USER` sees only own rows (any `userId` param rejected with 403 or ignored — pick one and test it), `ADMIN` sees tenant-wide with optional user filter
- [ ] 3.3 Implement CSV rendering (`text/csv`, header row + one row per group) sharing the JSON aggregation
- [ ] 3.4 Test: MockMvc tests for day/month grouping, USER self-scoping, ADMIN tenant scope + `userId` filter, CSV content type and shape
- [ ] 3.5 Add Bruno requests for `GET /api/v1/usage` (JSON and CSV) under `docs/api/request/AscendAI/`

## 4. Quota enforcement

- [ ] 4.1 Create `service/usage/QuotaGate` reading Redis counters `quota:tenant:{id}:{yyyy-MM}` and `quota:user:{id}:{yyyy-MM-dd}`; on missing key rebuild from a Postgres `SUM` over the window and `SET` with TTL past window end
- [ ] 4.2 Increment both counters from `UsageLedgerRecorder` at write time (total tokens per row)
- [ ] 4.3 Invoke the gate pre-provider-call on chat, memory-extraction, compaction, and embedding paths; throw `QuotaExceededException` when a budget is met or exceeded
- [ ] 4.4 Implement `Retry-After` = seconds to window rollover (start of next UTC day/month) and the `429` body (`code=QUOTA_EXCEEDED`, `scope`, `limit`, `used`, `windowEnd`, `retryAfterSeconds`) in the global exception handler
- [ ] 4.5 Implement the soft-warning: crossing the configured threshold emits one WARN + `usage.quota.warning{scope}` per (scope, window), idempotent via a Redis `SETNX` marker
- [ ] 4.6 Load per-tenant overrides from `tenant_quota_config` with fallback to `app.usage.quotas` defaults; honour `app.usage.quotas.enabled=false` (gate becomes a no-op, ledger untouched)
- [ ] 4.7 Test: user with exhausted daily budget gets `429` with correct body and `Retry-After`, and no provider call is made (verify via mocked `ChatModel`)
- [ ] 4.8 Test: tenant budget exhaustion rejects a second user of the same tenant while a user of another tenant passes
- [ ] 4.9 Test: flushed Redis counter is rebuilt from the Postgres ledger before the decision
- [ ] 4.10 Test: warning fires exactly once per window across repeated over-threshold requests

## 5. Rate limiting

- [ ] 5.1 Create `service/usage/RateLimiterService` wrapping Bucket4j Redis buckets keyed `{endpointGroup}:{user|tenant}:{id}` with capacities/refill from `UsageProperties`
- [ ] 5.2 Register a `HandlerInterceptor` on `POST /api/v1/ai/prompt` and `POST /api/v1/ingestion/upload` consuming from the user and tenant buckets; rejection throws `RateLimitExceededException` → `429` with `code=RATE_LIMITED`, `scope`, `retryAfterSeconds`, and `Retry-After` header from the bucket's nanos-to-wait
- [ ] 5.3 Wrap ascend-web-hunter MCP tool callbacks with a dedicated `web-search` bucket; on empty bucket, short-circuit the tool call and return a tool result telling the model the retry delay (chat request itself still returns `200`)
- [ ] 5.4 Fail-open on Redis errors: admit the request, WARN once per incident window, increment `rate_limit.redis_unavailable`; honour `app.usage.rate-limit.enabled=false`
- [ ] 5.5 Test: burst past the per-user chat bucket returns `429` with consistent header/body before controller logic runs
- [ ] 5.6 Test: per-tenant bucket rejects aggregate over-rate traffic with `scope="tenant"` while each user is under their own limit
- [ ] 5.7 Test: rate-limited web-search tool invocation never reaches the (mocked) MCP client and the chat turn completes with `200`
- [ ] 5.8 Test (Testcontainers): stopped Redis container → request admitted, `rate_limit.redis_unavailable` incremented

## 6. BYOK provider keys

- [ ] 6.1 Create `service/usage/KeyEncryptionService` (AES-256-GCM envelope: random per-row DEK, DEK wrapped by `USAGE_KEK` from env, `kek_id` recorded) with a pluggable interface for a future KMS implementation
- [ ] 6.2 Create `tenant_provider_key` JPA entity + repository and `service/usage/TenantProviderKeyService` (upsert, list, delete; compute `last4`; plaintext key never logged — verify no `toString` leakage)
- [ ] 6.3 Create `controller/ProviderKeyController` with `ADMIN`-only endpoints under `/api/v1/tenants/{tenantId}/provider-keys` (PUT upsert, GET list returning provider/last4/timestamps only, DELETE)
- [ ] 6.4 Extend `ChatModelResolver` with a tenant-aware `resolve(provider, tenantId)`: Caffeine cache keyed `(provider, tenantId)` building tenant-keyed clients lazily; fallback to the existing global clients when no tenant key exists; eviction hooked into upsert/delete
- [ ] 6.5 Route chat, memory-extraction, compaction, and embedding client resolution through the tenant-aware overload; provider `401` on a tenant key surfaces an error naming the provider and `last4`, with no silent retry on the global key
- [ ] 6.6 Test: with a stored tenant key, the outbound provider call (captured via mock server or request interceptor) authenticates with the tenant key; without one, with the global key
- [ ] 6.7 Test (encrypted-at-rest assertion): after upsert, read the raw `tenant_provider_key` row via JDBC and assert the plaintext key appears in no column, and decrypting with a wrong KEK fails
- [ ] 6.8 Test: GET list returns `last4` only; `USER` role gets `403` on every endpoint; deleted key evicts the cached client (next call uses global key without restart)
- [ ] 6.9 Add Bruno requests for the provider-key endpoints

## 7. Observability and documentation

- [ ] 7.1 Register the new counters (`usage.ledger.write_failed`, `usage.quota.rejected{scope}`, `usage.quota.warning{scope}`, `rate_limit.rejected{scope,endpoint}`, `rate_limit.redis_unavailable`) and verify they appear on `/actuator/prometheus`
- [ ] 7.2 Build `infra/observability/grafana/dashboards/usage-quotas.json`: tokens by tenant over time, top users by tokens, quota-consumption gauges per tenant, 429 rate by code/scope; register in the dashboards provisioning
- [ ] 7.3 Author `docs/USAGE_AND_QUOTAS.md`: ledger schema, usage API examples (JSON + CSV), quota semantics (windows, overshoot, warning), rate-limit config, BYOK key lifecycle and KEK rotation notes; link from root README Documentation section
- [ ] 7.4 Update `apps/ascend-ai-agent/AGENTS.md` (new package `service/usage/`, new endpoints, new env vars) and root `AGENTS.md` if the endpoint table changes
- [ ] 7.5 Add an ADR under `apps/ascend-ai-agent/docs/architecture/decisions/` covering the envelope-encryption choice and the fail-open rate-limiting posture

## 8. Verification

- [ ] 8.1 Run `./gradlew test` and `./gradlew integrationTest` green
- [ ] 8.2 End-to-end smoke against the live stack: one chat turn → ledger row visible in Postgres, usage API returns it, Grafana dashboard renders it; exhaust a tiny test budget → `429` with `Retry-After`
- [ ] 8.3 Update `openspec/changes/add-usage-metering-and-quotas/tasks.md` checkboxes as work proceeds
