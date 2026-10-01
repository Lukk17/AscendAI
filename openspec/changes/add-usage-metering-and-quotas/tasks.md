# Tasks - Add Usage Metering and Quotas

Depends on `add-auth-and-identity` (principal and roles) and `add-tenant-isolation` (tenant model) being merged first. Build order (owner, 2026-10-01): groups A, B, D, `harden-cloud-deployment`, `add-auth-and-identity`, `add-tenant-isolation`, this change, then `add-audit-and-gdpr-compliance`, `add-tenant-administration`, `add-tenant-policy`.

## 1. Schema and dependencies

- [ ] 1.1 Create Liquibase changelog `apps/ascend-agent/src/main/resources/db/changelog/<NN>-usage-metering.xml` (NN is the next free number at implementation time) with three tables: `usage_ledger` (tenant_id, user_id, conversation_id nullable, provider, model nullable, prompt_tokens, completion_tokens, cached_tokens (all three default 0), request_type, nullable `pages`, `processing_ms`, `files`, `bytes`, `chunks`, `audio_seconds NUMERIC(12,3)`, `tier` (design D12), occurred_at UTC; covering index `(tenant_id, occurred_at)` plus `(user_id, occurred_at)`), `tenant_quota_config` (tenant_id unique, monthly_token_budget, per_user_daily_token_budget, ocr_pages_per_month, transcription_seconds_per_month, all nullable overrides), `tenant_provider_key` (tenant_id + provider unique, wrapped_dek, ciphertext, gcm_nonce, kek_id, key_last4, created_at, updated_at)
- [ ] 1.2 Reference the new changelog from `db.changelog-master.yaml`; run `./gradlew integrationTest` to confirm Liquibase applies cleanly on Testcontainers Postgres
- [ ] 1.3 Recheck Maven Central for the latest `com.bucket4j:bucket4j_jdk17-lettuce` release (8.20.0 accepted on 2026-10-01, take a newer patch if one exists), then add it (design Closed Question 2) and `com.github.ben-manes.caffeine:caffeine` (version from the Spring Boot dependency management) to `apps/ascend-agent/gradle/libs.versions.toml` and reference both from `apps/ascend-agent/build.gradle.kts`. Acceptance: `./gradlew dependencies --configuration runtimeClasspath` lists both and `./gradlew build` passes
- [ ] 1.4 Add `app.usage.*` configuration block to `application.yaml` (metering/quotas/rate-limit/byok `enabled` flags, default tenant monthly budget, default user daily budget, optional `ocr-pages-per-month` and `transcription-seconds-per-month` (unset means unlimited), warning threshold 0.8, per-endpoint bucket capacities and refill rates) and a `UsageProperties` `@ConfigurationProperties` class; mirror env vars (`USAGE_KEK` etc.) in `compose.yaml`

## 2. Usage ledger

- [ ] 2.1 Create `UsageContext` record (tenantId, userId, conversationId, provider, requestType) and extend `PromptCacheStrategy.recordOutcome` to accept it; update `ChatExecutor.execute(...)` (`service/chat/ChatExecutor.java` line 97), `SemanticMemoryExtractor` (line 100), and the three strategy implementations `AnthropicPromptCacheStrategy`, `OpenAiPromptCacheStrategy`, `NoopPromptCacheStrategy` in `service/cache/`. Acceptance: `./gradlew test` passes with the existing `*PromptCacheStrategyTest` classes updated
- [ ] 2.2 Create `service/usage/UsageLedgerRecorder` with a Spring Data JDBC aggregate and repository, insert runs on a dedicated bounded async executor; failures log ERROR and increment `usage.ledger.write_failed` without propagating
- [ ] 2.3 Wire `UsageLedgerRecorder` into every `recordOutcome` implementation alongside `GenAiTokenUsageRecorder`, reading prompt/completion/cached tokens from the response metadata (Anthropic `cacheReadInputTokens`, OpenAI/Gemini `PromptTokensDetails.cachedTokens`)
- [ ] 2.4 Extend `ChatHistoryCompactionService` to build a `UsageContext` with `request_type = compaction` and record its provider calls
- [ ] 2.5 Extend the embedding call path to record one ledger row per embedding batch with `request_type = embedding` (one row per provider call, design Closed Question 1). Acceptance: a test ingesting a document split into two batches writes exactly two `embedding` rows
- [ ] 2.6 Add `tenant` and `request_type` tags to `GenAiTokenUsageRecorder`
- [ ] 2.7 Test: integration test asserting one chat turn writes exactly one `usage_ledger` row with `request_type = 'chat'`, correct tenant/user attribution, and token counts matching the stubbed provider usage metadata
- [ ] 2.8 Test: ledger insert failure (repository throws) still returns the chat response and increments `usage.ledger.write_failed`
- [ ] 2.9 Test: Anthropic response with `cacheReadInputTokens=487` produces a row with `cached_tokens = 487`
- [ ] 2.10 Extend `AscendOcrClient`'s `JobRecord` to read `pages_done`, `started_at` and `finished_at` from the ascend-ocr job record, and record one `ocr` row per succeeded job with `pages` and `processing_ms = (finished_at - started_at) * 1000`. A failed job writes no row. Acceptance: a WireMock test of a succeeded job with `pages_done = 3`, `started_at = 100.0`, `finished_at = 112.5` writes one `ocr` row with `pages = 3` and `processing_ms = 12500`, and a failed job writes none
- [ ] 2.11 Record one `ingestion` row per ingested file after chunking, with `files = 1`, `bytes` (the stored object size) and `chunks` (the number of chunks written). Acceptance: an integration test ingesting a 2048-byte file split into 4 chunks writes one `ingestion` row with `bytes = 2048` and `chunks = 4`, next to its `embedding` rows
- [ ] 2.12 Create an MCP tool-callback wrapper (one class, also used by task 5.3) that records a `transcription` row for the ascend-audio-scribe tools (`provider` from the tool name `transcribe_local`, `transcribe_openai`, `transcribe_hf`, `audio_seconds` from the result), a `web-search` row per search tool call and a `web-read` row per page-read tool call with the `tier` from the result. An error result writes no row, and a missing or negative `audio_seconds` writes the row with the field empty plus a WARN. Acceptance: unit tests with a stubbed tool for each case, including an error result writing no row
- [ ] 2.13 In ascend-audio-scribe, add `audio_seconds` (decoded input length, float) to the success result of `transcribe_local`, `transcribe_openai` and `transcribe_hf`. Acceptance: a test per tool asserts `audio_seconds` equals the length of a fixture of known length within 0.05 s, and `.venv/Scripts/python.exe -m pytest` passes in `apps/ascend-audio-scribe`
- [ ] 2.14 In ascend-web-hunter, check whether the page-read result names the tier that produced the content, and add a `tier` field to the result only if it does not. Acceptance: a test asserts the field for a page served by the first tier and for one served after an escalation, and the module's 100% branch-coverage gate passes
- [ ] 2.15 Record one `memory-search`, `memory-insert` or `memory-delete` row per `SemanticMemoryClient` REST call made for a tenant user, with `provider` = the embedding provider sent. `wipeUserMemory` called by erasure writes no row. Acceptance: a WireMock test of one search, one insert and one delete writes exactly one row of each type, and an erasure wipe writes none

## 3. Usage query API

- [ ] 3.1 Create `controller/UsageController` with `GET /api/v1/usage` (`from`, `to`, `groupBy=day|month`, `format=json|csv`, optional `userId` for ADMIN) and `service/usage/UsageQueryService` backed by a Spring Data JDBC `@Query` aggregate on `usage_ledger`, returning the sums of the D12 columns (`pages`, `processing_ms`, `files`, `bytes`, `chunks`, `audio_seconds`) next to the token sums and the request count
- [ ] 3.2 Enforce scoping: `USER` sees only own rows (any `userId` param rejected with 403 or ignored - pick one and test it), `ADMIN` sees tenant-wide with optional user filter
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
- [ ] 4.11 Add the OCR page and transcription second budgets (design D13): counters `quota:tenant:{id}:{yyyy-MM}:ocr-pages` and `quota:tenant:{id}:{yyyy-MM}:transcription-seconds` incremented by the recorder and rebuilt from the ledger, the OCR gate before `AscendOcrClient` submits a job (`429` with `scope = "tenant"` and `code = QUOTA_EXCEEDED`), the transcription gate in the tool-callback wrapper (tool result naming the retry time, chat turn still `200`). Acceptance: a tenant at its OCR page budget gets `429` on upload and ascend-ocr (WireMock) receives no submission, a tenant at its transcription budget gets a tool result naming the retry time and ascend-audio-scribe receives no call, and a tenant with no budget set is never rejected

## 5. Rate limiting

- [ ] 5.1 Create `service/usage/RateLimiterService` wrapping Bucket4j Redis buckets keyed `{endpointGroup}:{user|tenant}:{id}` with capacities/refill from `UsageProperties`
- [ ] 5.2 Register a `HandlerInterceptor` on `POST /api/v1/ai/prompt` and `POST /api/v1/ingestion/upload` consuming from the user and tenant buckets; rejection throws `RateLimitExceededException` → `429` with `code=RATE_LIMITED`, `scope`, `retryAfterSeconds`, and `Retry-After` header from the bucket's nanos-to-wait
- [ ] 5.3 In the tool-callback wrapper of task 2.12, give the ascend-web-hunter MCP tools a dedicated `web-search` bucket; on empty bucket, short-circuit the tool call and return a tool result telling the model the retry delay (chat request itself still returns `200`)
- [ ] 5.4 Fail-open on Redis errors: admit the request, WARN once per incident window, increment `rate_limit.redis_unavailable`; honour `app.usage.rate-limit.enabled=false`
- [ ] 5.5 Test: burst past the per-user chat bucket returns `429` with consistent header/body before controller logic runs
- [ ] 5.6 Test: per-tenant bucket rejects aggregate over-rate traffic with `scope="tenant"` while each user is under their own limit
- [ ] 5.7 Test: rate-limited web-search tool invocation never reaches the (mocked) MCP client and the chat turn completes with `200`
- [ ] 5.8 Test (Testcontainers): stopped Redis container → request admitted, `rate_limit.redis_unavailable` incremented

## 6. BYOK provider keys

- [ ] 6.1 Create `service/usage/KeyEncryptionService` (AES-256-GCM envelope: random per-row DEK, DEK wrapped by `USAGE_KEK` from env, `kek_id` recorded) with a pluggable interface for a future KMS implementation
- [ ] 6.2 Create `tenant_provider_key` Spring Data JDBC aggregate and repository and `service/usage/TenantProviderKeyService` (upsert, list, delete; compute `last4`; plaintext key never logged - verify no `toString` leakage)
- [ ] 6.3 Create `controller/admin/ProviderKeyController` with `ADMIN`-only endpoints under `/api/v1/admin/tenants/{tenantId}/provider-keys` (PUT upsert, GET list returning provider/last4/timestamps only, DELETE), 403 when `{tenantId}` is not the caller's tenant
- [ ] 6.4 Extend `ChatModelResolver` with a tenant-aware `resolve(provider, tenantId)`: Caffeine cache keyed `(provider, tenantId)` building tenant-keyed clients lazily; fallback to the existing global clients when no tenant key exists; eviction hooked into upsert/delete
- [ ] 6.5 Route chat, memory-extraction, compaction, and embedding client resolution through the tenant-aware overload; provider `401` on a tenant key surfaces an error naming the provider and `last4`, with no silent retry on the global key
- [ ] 6.6 Test: with a stored tenant key, the outbound provider call (captured via mock server or request interceptor) authenticates with the tenant key; without one, with the global key
- [ ] 6.7 Test (encrypted-at-rest assertion): after upsert, read the raw `tenant_provider_key` row via JDBC and assert the plaintext key appears in no column, and decrypting with a wrong KEK fails
- [ ] 6.8 Test: GET list returns `last4` only; `USER` role gets `403` on every endpoint, an `ADMIN` of `acme` calling `/api/v1/admin/tenants/globex/provider-keys` gets `403`; deleted key evicts the cached client (next call uses global key without restart)
- [ ] 6.9 Add Bruno requests for the provider-key endpoints

## 7. Observability and documentation

- [ ] 7.1 Register the new counters (`usage.ledger.write_failed`, `usage.quota.rejected{scope}`, `usage.quota.warning{scope}`, `rate_limit.rejected{scope,endpoint}`, `rate_limit.redis_unavailable`) and verify they appear on `/actuator/prometheus`
- [ ] 7.2 Build `infra/observability/grafana/dashboards/usage-quotas.json`: tokens by tenant over time, top users by tokens, quota-consumption gauges per tenant, 429 rate by code/scope; register in the dashboards provisioning
- [ ] 7.3 Author `docs/USAGE_AND_QUOTAS.md`: ledger schema with every request type and its source (design D12), the calls that bypass the agent and are not metered, usage API examples (JSON + CSV), quota semantics (windows, overshoot, warning), rate-limit config, BYOK key lifecycle and KEK rotation notes; link from root README Documentation section
- [ ] 7.4 Update `apps/ascend-agent/AGENTS.md` (new package `service/usage/`, new endpoints, new env vars) and root `AGENTS.md` if the endpoint table changes
- [ ] 7.5 Add an ADR under `apps/ascend-agent/docs/architecture/decisions/`, numbered with the next free number at implementation time (ADR-010 already exists), covering the envelope-encryption choice and the fail-open rate-limiting posture

## 8. Verification

- [ ] 8.1 Run `./gradlew test` and `./gradlew integrationTest` green
- [ ] 8.2 End-to-end smoke against the live stack: one chat turn → ledger row visible in Postgres, one scanned PDF upload → an `ocr` row and an `ingestion` row, one chat turn that calls web search and a transcription tool → `web-search` and `transcription` rows, usage API returns it, Grafana dashboard renders it; exhaust a tiny test budget → `429` with `Retry-After`
- [ ] 8.3 Update `openspec/changes/add-usage-metering-and-quotas/tasks.md` checkboxes as work proceeds
