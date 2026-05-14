## Why

When the AscendAgent answers a user prompt using RAG-retrieved chunks, the user only receives the model's textual answer. The original source documents that grounded the answer (the actual `.md` / `.pdf` / `.docx` files stored in MinIO) are invisible to the caller. There is no way for a user to inspect, download, or cite the documents the model used. This is a frequent ask for "show me the doc you got that from" UX, for human verification of RAG answers, and for clients that want to render an "answer + sources" panel without re-querying Qdrant. The retrieval layer already knows which source documents contributed (each Qdrant point carries the originating S3 key in its metadata), so the data is one hop away — it is purely a response-shape gap.

## What Changes

- **Opt-in multipart parameter on `POST /api/v1/ai/prompt`**: add a new boolean form field `attachSources` (default `false`). When `true`, the agent SHALL include the de-duplicated list of source documents that grounded the RAG context in the response. When `false` or absent, response shape is identical to today (zero behavior change for existing callers).
- **Source-tracking in retrieval**: `RagRetrievalService` SHALL track the set of unique source document references (S3 bucket + key + display name + MIME type) that appear in the Qdrant point metadata of every chunk it returns above the similarity threshold. Today this metadata is read but discarded after the chunk text is concatenated into the system message.
- **New `SourceFile` DTO**: `AiResponse` gains an optional `List<SourceFile> sources` field (always present in JSON when `attachSources=true`, omitted via `@JsonInclude(NON_NULL)` otherwise). Each `SourceFile` carries `name`, `mimeType`, `downloadUrl`, `expiresAt`, and `sizeBytes` (nullable).
- **Presigned MinIO URLs**: a new `S3PresignedUrlService` produces short-lived presigned GET URLs against MinIO via the AWS SDK `S3Presigner`. Default expiry `15m`, configurable via `app.rag.source-attachments.presign-ttl` and clamped at startup into `[PT1M, PT1H]`. The presigner is signed against `app.s3.public-endpoint` (defaulting to `app.s3.endpoint`) so URLs are reachable from the caller's network. The agent SHALL NOT stream file bytes through itself.
- **Size cap**: a new property `app.rag.source-attachments.max-file-size` (default `25 MB`) controls which retrieved sources are eligible. Sources larger than the cap are skipped with a single WARN log per request and do not appear in the response array; the rest are still returned.
- **De-duplication**: when several retrieved chunks point to the same source document (same bucket + key), the document SHALL appear exactly once in the response array, even though it contributed multiple chunks to the system message.
- **Empty case**: when `attachSources=true` but no RAG documents were retrieved (Soft-RAG threshold rejected all hits, or no chunks exist for the user's collection), `sources` is an empty array — never `null`, never a 404, never a 5xx.
- **Capability gate**: the feature only activates for chat requests where RAG retrieval actually ran. Endpoints that never call `RagRetrievalService` (e.g., a future "no-RAG" mode) are unaffected.
- **OpenAPI / Swagger**: `attachSources` is documented on the controller method via `@Parameter` / `@Schema`; `SourceFile` is annotated as a schema component.
- **Tests**: unit tests for `S3PresignedUrlService` (mocked `S3Presigner`), `RagRetrievalService` source-tracking (mocked `VectorStore`), `AscendChatService` plumbing, and `PromptController` multipart binding. End-to-end curl example added to `AscendAgent/e2e/testing/rag.md`.

## Capabilities

### New Capabilities
- `rag-source-attachments`: A new capability covering opt-in return of original RAG source documents alongside the prompt answer.

### Modified Capabilities
- `rag-retrieval`: now responsible for surfacing the set of unique contributing source documents (not just the concatenated chunk text) so the response assembler can attach them.

## Impact

- **Code** (final, as implemented):
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/controller/PromptController.java` — new optional `@RequestParam Boolean attachSources` with OpenAPI `@Parameter` annotation
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/dto/AiResponse.java` — added `List<SourceFile> sources` field with `@JsonInclude(NON_NULL)`; secondary 2-arg constructor preserves source-compat for existing call sites
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/dto/SourceFile.java` — new record DTO with `@JsonInclude(NON_NULL)`
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/AscendChatService.java` — new 8-arg `prompt(...)` overload accepting `boolean attachSources`; presigns at end of orchestration
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/ChatContextAssembler.java` — `buildUserMessage` now returns `BuiltUserMessage` (carries text + sources + ragRetrievalRan)
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/RagRetrievalService.java` — `retrieveContext(...)` renamed to `retrieve(...)` returning new `RagRetrievalResult`. De-dup by `(bucket, key)` via `LinkedHashSet` preserving rank order
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/rag/S3PresignedUrlService.java` — new service wrapping AWS SDK `S3Presigner` + `S3Client`; HEAD-first size check, parallel presign, kill-switch, never logs signed URLs
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/rag/{SourceRef,RagRetrievalResult,BuiltUserMessage}.java` — new internal records
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/AppConfig.java` — new `S3Presigner` bean signed against `app.s3.public-endpoint`
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/properties/RagProperties.java` — new nested `SourceAttachments` block with `enabled`, `presignTtl`, `maxFileSize`
  - `AscendAgent/src/main/resources/application.yaml` — new `app.rag.source-attachments.*` keys + new `app.s3.public-endpoint` (defaults to `app.s3.endpoint`)
  - `AscendAgent/src/main/resources/application-docker.yaml` — overrides `app.s3.public-endpoint=http://localhost:9070` so URLs resolve from host network
  - `AscendAgent/e2e/testing/5-rag-test.md` — new "Optional — attach source files" section with curl + sample JSON
- **APIs**: additive only. `POST /api/v1/ai/prompt` gains an optional multipart field. `AiResponse` gains an optional `sources` field that is omitted from JSON when not requested. No existing field is renamed, removed, or retyped.
- **Dependencies**: AWS SDK v2 `s3` module (`software.amazon.awssdk:s3`) is already present for MinIO interaction in the ingestion path; reused. No new third-party dependency expected. If the project currently uses MinIO's own client only, add `software.amazon.awssdk:s3` (presigned URL support is in the `s3` module, no separate `s3-presigner` artifact needed).
- **Configuration**: new `app.rag.source-attachments.{enabled,presign-ttl,max-file-size}` (defaults `true` / `PT15M` / `25MB`) and new `app.s3.public-endpoint` (defaults to `${app.s3.endpoint}`). All optional with safe defaults; existing deployments need no config changes. Docker profile overrides `public-endpoint` so the host network can resolve the presigned URLs.
- **Database**: no migration. Source metadata already lives in Qdrant point payloads written during ingestion (`source` key holds the S3 object key; bucket is derived from the global `app.s3.bucket` config at retrieval time).

  **Deviation from initial design**: the design assumed ingestion would write `bucket`, `key`, `displayName`, `mimeType` as separate metadata keys. Ingestion already writes only `source` / `title` / `type`. Rather than churn the four ingestion sites (`IngestionService` ×2, `DoclingClient`, `PaddleOcrClient`) to write a constant bucket value to every chunk, the retrieval layer now derives `bucket` from `app.s3.bucket` config, `key` from `source`, `displayName` from `title` then basename-of-key, and `mimeType` from the HEAD response (Content-Type) at presign time. This keeps the feature retroactive against already-ingested chunks AND keeps the ingestion path untouched. If ingestion ever needs per-document bucket metadata (multi-bucket support), both the explicit keys and the fallback chain are honored — the fallback only fires when explicit metadata is absent.
- **Security**: presigned URLs are short-lived, scoped to a single object, and signed by the agent's own MinIO credentials. They do not bypass any authn the agent itself enforces, because the agent only emits them for documents it just retrieved on behalf of the authenticated caller. URLs are NOT logged. Section "Security" in `design.md` covers this in detail.
- **Backward compatibility**: callers that do not send `attachSources` see byte-for-byte identical responses to today. The new `sources` JSON field is omitted (not `null`) when absent.
- **Tests**: new unit tests for `S3PresignedUrlServiceTest`, `RagRetrievalServiceSourceTrackingTest`, `AscendChatServiceAttachSourcesTest`, `PromptControllerAttachSourcesTest`. New integration test using the existing test MinIO container (or mocked S3Presigner) to assert presigned URLs round-trip.
