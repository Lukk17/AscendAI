## 1. Configuration plumbing

- [ ] 1.1 Add a nested `SourceAttachments` block to `RagProperties` with fields `presignTtl: Duration` (default `PT15M`), `maxFileSize: DataSize` (default `25MB`), and `enabled: boolean` (default `true` — kill-switch for ops)
- [ ] 1.2 Add `app.rag.source-attachments.presign-ttl: PT15M` and `app.rag.source-attachments.max-file-size: 25MB` to `application.yaml` with a comment describing each
- [ ] 1.3 Add `app.minio.public-endpoint` to the existing MinIO properties block, defaulting to the same value as `app.minio.endpoint`. Used by `S3PresignedUrlService` so URLs are reachable from the caller's network
- [ ] 1.4 At `@PostConstruct` of the new service, clamp `presignTtl` into `[PT1M, PT1H]` and log a WARN when clamped
- [ ] 1.5 Add a startup log line `[S3PresignedUrlService] Presigning against {publicEndpoint} with TTL {ttl}` so misconfigurations are obvious

## 2. New `SourceFile` DTO

- [ ] 2.1 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/dto/SourceFile.java` as a Java `record` with fields `String name`, `String mimeType`, `String downloadUrl`, `Instant expiresAt`, `Long sizeBytes` (nullable)
- [ ] 2.2 Annotate fields with `@Schema(description = "...")` for OpenAPI / Swagger documentation
- [ ] 2.3 Annotate the record with `@JsonInclude(JsonInclude.Include.NON_NULL)` so `sizeBytes=null` is omitted from JSON

## 3. Extend `AiResponse`

- [ ] 3.1 Add `List<SourceFile> sources` field to `AiResponse` (or whatever the agent's main response DTO is named — verify in `dto/`)
- [ ] 3.2 Annotate the field with `@JsonInclude(JsonInclude.Include.NON_NULL)` so a `null` value (the default for callers who didn't ask) is omitted from JSON entirely
- [ ] 3.3 Update any existing constructors / builders so old call sites compile without changes (the new field defaults to `null`)
- [ ] 3.4 Verify no test fixture comparing exact JSON of `AiResponse` breaks because of the new field

## 4. `RagRetrievalService` returns source refs

- [ ] 4.1 Introduce a record `RagRetrievalResult(String context, List<SourceRef> sources)` (package-private under `service/rag/`)
- [ ] 4.2 Introduce a record `SourceRef(String bucket, String key, String displayName, String mimeType)` (package-private)
- [ ] 4.3 Change `RagRetrievalService.retrieve(...)` return type from `String` to `RagRetrievalResult`. Inside, after collecting chunks above threshold, build the de-duplicated source list keyed by `(bucket, key)` using `LinkedHashSet` to preserve first-seen order
- [ ] 4.4 Read source metadata from `Document.getMetadata()` keys `bucket`, `key`, `displayName`, `mimeType` (the keys ingestion already writes; verify against `DocumentIngestionService`)
- [ ] 4.5 If a chunk's metadata is missing `bucket` or `key`, log at DEBUG and skip it for source-tracking — but still include the chunk text in the assembled context (no UX regression)
- [ ] 4.6 Update the single caller (`ChatContextAssembler` or whichever builds the system message) to use `result.context()` for the existing behavior and pass `result.sources()` upward
- [ ] 4.7 Add unit test `RagRetrievalServiceSourceTrackingTest`: mock `VectorStore` returns chunks with mixed `bucket+key` metadata; assert dedup, ordering, and that chunks with missing metadata are tolerated

## 5. New `S3PresignedUrlService`

- [ ] 5.1 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/rag/S3PresignedUrlService.java`
- [ ] 5.2 Inject AWS SDK v2 `S3Presigner` configured against `app.minio.public-endpoint` and the existing MinIO credentials. Configure a separate `S3Client` for `HEAD` calls
- [ ] 5.3 Public method `Optional<SourceFile> presign(SourceRef ref)`: (a) `HEAD` the object to read `Content-Length` and `Content-Type`, (b) skip + log WARN if `Content-Length > maxFileSize`, (c) build `GetObjectPresignRequest` with `signatureDuration = presignTtl`, (d) return `SourceFile` with the URL, expiry, size, and effective MIME type (HEAD-derived if available, else `ref.mimeType()`)
- [ ] 5.4 Public method `List<SourceFile> presignAll(List<SourceRef> refs)`: presign in parallel via `CompletableFuture.supplyAsync` on a small bounded executor; collect non-empty `Optional` results in input order
- [ ] 5.5 Catch SDK exceptions per source — one failed presign does NOT fail the whole list; log WARN and omit that source
- [ ] 5.6 Never log the produced presigned URL itself; only `s3://{bucket}/{key}` and the TTL
- [ ] 5.7 Unit test `S3PresignedUrlServiceTest`: mock `S3Presigner` and `S3Client`; cover happy path, oversized-file skip, HEAD failure, presigner exception, parallel presign of 3 refs

## 6. Wire `attachSources` through the request path

- [ ] 6.1 Add multipart parameter `@RequestParam(name = "attachSources", required = false) Boolean attachSources` to `PromptController.prompt(...)`. Default to `false` when null
- [ ] 6.2 Annotate with `@Parameter(description = "If true, includes presigned download URLs for the source documents grounding the RAG answer. Defaults to false.")` for OpenAPI
- [ ] 6.3 Add `attachSources` to the internal request DTO that crosses into `AscendChatService` (extend the existing record/object — do not add a new method overload)
- [ ] 6.4 In `AscendChatService`, after the LLM returns the textual answer, if `attachSources == true` AND RAG retrieval ran, call `S3PresignedUrlService.presignAll(result.sources())` and set the resulting list on `AiResponse.sources`
- [ ] 6.5 If `attachSources == true` but RAG retrieval did NOT run (no chunks returned, threshold rejected all hits, or RAG was skipped), set `AiResponse.sources = []` (empty list, not null)
- [ ] 6.6 If `attachSources == false` or absent, do NOT touch `AiResponse.sources` (stays null, omitted from JSON)
- [ ] 6.7 Unit test `AscendChatServiceAttachSourcesTest`: cover (a) flag false → no sources in response, (b) flag true + zero retrieved → empty array, (c) flag true + 3 chunks across 2 unique sources → 2 entries in array
- [ ] 6.8 Web slice test `PromptControllerAttachSourcesTest` (`@WebMvcTest`): verify multipart binding accepts `attachSources=true`, `attachSources=false`, and absence; verify the OpenAPI `@Parameter` annotation is present (reflection)

## 7. Documentation

- [ ] 7.1 Update `AscendAgent/e2e/testing/rag.md` with a new section "Attach source files" containing a curl example: `curl -X POST … -F "userId=frosty" -F "prompt=…" -F "attachSources=true"`. Show a sample response JSON with two sources
- [ ] 7.2 Add a brief "RAG source attachments" subsection to `AscendAgent/README.md` (or `docs/INGESTION.md` if more appropriate) explaining the opt-in flag and presigned-URL TTL
- [ ] 7.3 Cross-link from `AGENTS.md` (the new feature touches the public API surface — worth one bullet)

## 8. Verification

- [ ] 8.1 Run `./gradlew test` — all new and existing tests green
- [ ] 8.2 Run `./gradlew bootRun` against docker-compose; ingest a sample PDF; ask a question that should retrieve it; assert the response contains a `sources` array with one entry whose `downloadUrl` resolves to a 200 GET against MinIO
- [ ] 8.3 Re-run the same prompt without `attachSources=true`; assert the response JSON does NOT contain a `sources` key (byte-for-byte backward compat)
- [ ] 8.4 Ingest a 30 MB PDF; assert it does NOT appear in the response array (size cap), the rest of the sources do appear, and a single WARN line was logged
- [ ] 8.5 Send a prompt that retrieves zero chunks above threshold with `attachSources=true`; assert response contains `"sources": []`
- [ ] 8.6 Confirm OpenAPI / Swagger UI shows the new parameter and `SourceFile` schema correctly
- [ ] 8.7 Verify presigned URL works from the host network (the docker-compose deployment case): the URL must use `localhost:9070`, not `minio:9000`
