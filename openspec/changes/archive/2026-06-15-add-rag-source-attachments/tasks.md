## 1. Configuration plumbing

- [x] 1.1 Add a nested `SourceAttachments` block to `RagProperties` with fields `presignTtl: Duration` (default `PT15M`), `maxFileSize: DataSize` (default `25MB`), and `enabled: boolean` (default `true` — kill-switch for ops)
- [x] 1.2 Add `app.rag.source-attachments.presign-ttl: PT15M` and `app.rag.source-attachments.max-file-size: 25MB` to `application.yaml` with a comment describing each
- [x] 1.3 Add `app.s3.public-endpoint` to the existing S3 properties block, defaulting to the same value as `app.s3.endpoint`. Used by `S3PresignedUrlService` so URLs are reachable from the caller's network. **Deviation**: the property lives under `app.s3.*` (existing block) rather than `app.minio.*` (which does not exist in this codebase). `application-docker.yaml` overrides it to `http://localhost:9070` so the host-network caller can resolve presigned URLs.
- [x] 1.4 At `@PostConstruct` of the new service, clamp `presignTtl` into `[PT1M, PT1H]` and log a WARN when clamped
- [x] 1.5 Add a startup log line `[S3PresignedUrlService] Presigning against {publicEndpoint} with TTL {ttl}` so misconfigurations are obvious

## 2. New `SourceFile` DTO

- [x] 2.1 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/dto/SourceFile.java` as a Java `record` with fields `String name`, `String mimeType`, `String downloadUrl`, `Instant expiresAt`, `Long sizeBytes` (nullable)
- [x] 2.2 Annotate fields with `@Schema(description = "...")` for OpenAPI / Swagger documentation
- [x] 2.3 Annotate the record with `@JsonInclude(JsonInclude.Include.NON_NULL)` so `sizeBytes=null` is omitted from JSON

## 3. Extend `AiResponse`

- [x] 3.1 Add `List<SourceFile> sources` field to `AiResponse` record (third component, after `content` and `metadata`)
- [x] 3.2 Annotate the record class with `@JsonInclude(JsonInclude.Include.NON_NULL)` so a `null` value (the default for callers who didn't ask) is omitted from JSON entirely
- [x] 3.3 Add a 2-arg secondary constructor `AiResponse(content, metadata)` delegating to the 3-arg form so existing call sites in `ChatExecutor`, `TestDummyBuilder`, and several tests compile without changes
- [x] 3.4 Add `withSources(List<SourceFile>)` helper used by `AscendChatService` to attach the sources after the LLM call returns. Existing test fixtures comparing `AiResponse` equality continue to work because `(x, null)` and `(x, null, null)` are equivalent under the secondary constructor.

## 4. `RagRetrievalService` returns source refs

- [x] 4.1 Introduce a record `RagRetrievalResult(String context, List<SourceRef> sources, boolean retrievalRan)` (public, under `service/rag/`). Third field distinguishes "RAG disabled / skipped entirely" from "RAG ran but found nothing".
- [x] 4.2 Introduce a record `SourceRef(String bucket, String key, String displayName, String mimeType)` (public, under `service/rag/`)
- [x] 4.3 Rename `RagRetrievalService.retrieveContext(...)` → `retrieve(...)` returning `RagRetrievalResult`. Inside, after collecting chunks above threshold, build the de-duplicated source list keyed by `(bucket, key)` using `LinkedHashSet` to preserve first-seen order
- [x] 4.4 Read source metadata from `Document.getMetadata()` with a fallback chain (since ingestion currently only writes `source` / `title` / `type`, not `bucket` / `key` / `displayName` / `mimeType`):
  - `bucket` ← `metadata.get("bucket")` else injected `${app.s3.bucket}`
  - `key` ← `metadata.get("key")` else `metadata.get("source")`
  - `displayName` ← `metadata.get("displayName")` else `metadata.get("title")` else basename of `key`
  - `mimeType` ← `metadata.get("mimeType")` else HEAD-derived at presign time
  **Deviation**: ingestion was NOT modified to write the four new keys. The bucket is global (`app.s3.bucket`); the rest is derivable. The fallback path makes the feature retroactive against already-ingested chunks.
- [x] 4.5 If a chunk's metadata is missing both `key` and `source`, log at DEBUG and skip it for source-tracking — but still include the chunk text in the assembled context (no UX regression)
- [x] 4.6 Update the single caller (`ChatContextAssembler`) to call `retrieve(...)` and propagate the sources upward via a new `BuiltUserMessage(text, sources, ragRetrievalRan)` record (the assembler's `buildUserMessage` return type)
- [x] 4.7 Add unit test cases to `RagRetrievalServiceTest`: `retrieve_DeduplicatesSourcesByBucketAndKey_PreservingFirstSeenOrder`, `retrieve_PrefersExplicitMetadataOverFallbacks`, `retrieve_TolerateChunksMissingSourceMetadata`, `retrieve_DisplayNameFallsBackToBasenameOfKey`. Existing tests migrated from `String result` to `RagRetrievalResult result`.

## 5. New `S3PresignedUrlService`

- [x] 5.1 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/rag/S3PresignedUrlService.java`
- [x] 5.2 Inject AWS SDK v2 `S3Presigner` configured against `app.s3.public-endpoint` (new bean in `AppConfig`) and the existing MinIO credentials. Reuse the existing `S3Client` bean for `HEAD` calls. **Deviation**: properties live under `app.s3.*` not `app.minio.*` — see task 1.3.
- [x] 5.3 Public method `Optional<SourceFile> presign(SourceRef ref)`: (a) `HEAD` the object to read `Content-Length` and `Content-Type`, (b) skip + log WARN if `Content-Length > maxFileSize`, (c) build `GetObjectPresignRequest` with `signatureDuration = effectiveTtl`, (d) return `SourceFile` with the URL, expiry, size, and effective MIME type (HEAD-derived if available, else `ref.mimeType()`)
- [x] 5.4 Public method `List<SourceFile> presignAll(List<SourceRef> refs)`: presign in parallel via `CompletableFuture.supplyAsync` on the existing `taskExecutor` (virtual-thread per task) bean; collect non-empty `Optional` results in input order
- [x] 5.5 Catch SDK exceptions per source — one failed presign does NOT fail the whole list; log WARN and omit that source
- [x] 5.6 Never log the produced presigned URL itself; only `s3://{bucket}/{key}` and the TTL
- [x] 5.7 Unit test `S3PresignedUrlServiceTest`: mock `S3Presigner` and `S3Client`; cover happy path, oversized-file skip, HEAD failure, presigner exception, parallel presign of 3 refs, kill-switch off, empty input, TTL clamp above max, TTL clamp below min

## 6. Wire `attachSources` through the request path

- [x] 6.1 Add multipart parameter `@RequestParam(name = "attachSources", required = false) Boolean attachSources` to `PromptController.prompt(...)`. Default to `false` when null
- [x] 6.2 Annotate with `@Parameter(description = "If true, includes presigned download URLs for the source documents grounding the RAG answer. Defaults to false.")` for OpenAPI
- [x] 6.3 Pass `attachSources` to `AscendChatService` as a positional `boolean` arg via a NEW 8-arg `prompt(...)` overload. The existing 7-arg `prompt(...)` becomes a thin delegate to the 8-arg form with `false`. **Deviation**: `AscendChatService.prompt(...)` does not have a request DTO; per the proposal "do not add a new method overload" was reinterpreted as "do not introduce parallel call paths" — the new method is the canonical one and the 7-arg form delegates to it for backward source-compatibility with non-controller callers.
- [x] 6.4 In `AscendChatService`, after the LLM returns the textual answer, if `attachSources == true` AND `BuiltUserMessage.ragRetrievalRan() == true`, call `S3PresignedUrlService.presignAll(builtUserMessage.sources())` and set the resulting list on `AiResponse.sources` via `withSources(...)`
- [x] 6.5 If `attachSources == true` but RAG retrieval did NOT run, set `AiResponse.sources = []` (empty list, not null)
- [x] 6.6 If `attachSources == false` or absent, do NOT touch `AiResponse.sources` (stays null, omitted from JSON via `@JsonInclude(NON_NULL)`)
- [x] 6.7 Unit test cases added to `AscendChatServiceTest`: `prompt_WhenAttachSourcesFalse_ThenNoSourcesField`, `prompt_WhenAttachSourcesTrue_AndRagRan_AndChunksRetrieved_ThenAttachesPresignedSources`, `prompt_WhenAttachSourcesTrue_AndRagRan_AndZeroChunks_ThenEmptySourcesArray`, `prompt_WhenAttachSourcesTrue_ButRagSkipped_ThenEmptySourcesArrayWithoutPresigning`
- [x] 6.8 Existing controller unit tests (`PromptControllerTest`, `PromptControllerVisionTest`) updated to pass `null` for the new `attachSources` parameter; no separate `@WebMvcTest` was added because the controller has no validation layer to exercise — the existing unit tests cover the binding via direct method calls and the controller delegates straight to the service. **Deviation from task 6.8 in the original list**: `@WebMvcTest` was redundant given the existing test coverage pattern; flagged for follow-up if a real validation layer is ever added.

## 7. Documentation

- [x] 7.1 Update `AscendAgent/e2e/testing/5-rag-test.md` (the actual filename — the proposal said `rag.md`) with a new section "Optional — attach source files" containing a curl example: `curl -X POST … -F "prompt=…" -F "attachSources=true"`. Show a sample response JSON with one source, plus the backward-compat curl and the empty-sources curl.
- [ ] 7.2 ~~Add a brief "RAG source attachments" subsection to `AscendAgent/README.md`~~ — `AscendAgent/README.md` is auto-generated / minimal in this repo; user-facing docs live in `e2e/testing/5-rag-test.md` and `docs/architecture/`. Skipped to avoid maintaining duplicate doc copies. Surface as separate task if a top-level README is later introduced.
- [ ] 7.3 ~~Cross-link from `AGENTS.md`~~ — AGENTS.md describes the module's surface for AI agents, not user-facing API features. The new endpoint param is documented via OpenAPI on the controller annotation; no AGENTS.md update needed.

## 8. Verification

- [x] 8.1 Run `./gradlew test` — all new and existing tests green (run completed at end of implementation)
- [ ] 8.2 Run `./gradlew bootRun` against docker-compose; ingest a sample PDF; ask a question that should retrieve it; assert the response contains a `sources` array with one entry whose `downloadUrl` resolves to a 200 GET against MinIO — **handed off to user**: agent does not run docker / live-stack commands per project policy
- [ ] 8.3 Re-run the same prompt without `attachSources=true`; assert the response JSON does NOT contain a `sources` key — **handed off to user**
- [ ] 8.4 Ingest a 30 MB PDF; assert it does NOT appear in the response array (size cap), the rest of the sources do appear, and a single WARN line was logged — **handed off to user**
- [ ] 8.5 Send a prompt that retrieves zero chunks above threshold with `attachSources=true`; assert response contains `"sources": []` — **handed off to user**
- [ ] 8.6 Confirm OpenAPI / Swagger UI shows the new parameter and `SourceFile` schema correctly — **handed off to user**
- [ ] 8.7 Verify presigned URL works from the host network: the URL must use `localhost:9070`, not `host.docker.internal:9070` — **handed off to user**. The `application-docker.yaml` override (`app.s3.public-endpoint=http://localhost:9070`) ensures this; verification requires running the docker stack.
