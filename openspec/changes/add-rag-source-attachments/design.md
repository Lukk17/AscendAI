## Context

`POST /api/v1/ai/prompt` is the AscendAgent's main entry point. For RAG-grounded answers, the request flows: `PromptController` → `AscendChatService` → `ChatContextAssembler` → `RagRetrievalService` → Qdrant vector search → top-K chunks concatenated into the system message → LLM → textual `AiResponse`. The originating source document for each chunk is stored in the Qdrant point payload at ingestion time (`DocumentIngestionService` writes `bucket`, `key`, `displayName`, `mimeType` into the point metadata) but is read only to format the chunk header in the assembled context — never returned to the caller.

The user wants a mechanism to also return the original files behind those chunks, so a UI can render an "answer + sources" panel and a power user can download the actual `.md` / `.pdf` / `.docx`. The data is already present in Qdrant; the missing pieces are (a) propagating it from `RagRetrievalService` up to the response, and (b) deciding *how* to send the bytes (or pointers to them) to the caller.

## Goals / Non-Goals

**Goals:**
- Add an opt-in parameter that, when set, returns the de-duplicated set of source documents that grounded the RAG answer.
- Keep existing callers untouched — same JSON shape, same response size, no extra round-trip cost — when the flag is unset.
- Keep response payload small even when many large PDFs are involved.
- Use MinIO/S3 native primitives (presigned URLs) rather than streaming bytes through the agent.
- Make the feature observable: log when sources are attached, when files are skipped due to size, and when MinIO presigning fails.

**Non-Goals:**
- No change to ingestion. Sources are already tracked in Qdrant payloads.
- No public download endpoint hosted by AscendAgent. Bytes flow caller → MinIO directly via the presigned URL.
- No retroactive rewrite of historical chat-history to include sources.
- No new authentication scheme. Presigned URL TTL replaces per-user authz for the object fetch.
- No support for "show me the chunks" (the actual snippets that matched). Sources are *file-level*, not chunk-level. A future change could add chunk-level attribution.

## Decisions

### D1 — Parameter name: `attachSources`

Recommended over the alternatives. Considered:

| Name | Verdict | Reason |
|---|---|---|
| `returnRagDocument` | rejected | Singular implies one doc. RAG always retrieves N chunks, possibly across multiple sources. |
| `returnSourceFiles` | viable | Clear, but `return*` is uncommon as a multipart field name. |
| **`attachSources`** | **chosen** | Concise (one word), plural (handles 1..N naturally), uses the same "attach" verb as the user-attached image part, semantically symmetric ("user attaches image, server attaches sources"). |
| `includeSourceFiles` | viable | Slightly verbose. |
| `attachRetrievedDocs` | rejected | "Retrieved" is jargon; "Sources" matches what the UI will label them. |

Default is `false`. Type is `Boolean`, not `boolean` — the controller binds it as a nullable wrapper so a missing field stays missing rather than silently defaulting to `false` (lets future code distinguish "absent" from "explicit false" if needed).

### D2 — Response shape: presigned MinIO URLs (option 2)

Three response-shape options were evaluated:

#### Option 1 — Inline base64 in JSON

`AiResponse.sources` becomes `[{ name, mimeType, dataBase64 }]`.

- **Pros**: single round trip; works with any HTTP client; no extra credential/expiry consideration.
- **Cons**: a single 20 MB PDF balloons the JSON to ~27 MB after base64 (33% overhead); awkward in Bruno UI (no native preview); slow to deserialize on the client; response bytes are doubly buffered (MinIO → agent → caller); "preview before download" UX is impossible.
- **Verdict**: rejected. Wastes bandwidth and CPU when most callers want to render a download link, not the bytes.

#### Option 2 — Presigned MinIO download URLs **[chosen]**

`AiResponse.sources` becomes `[{ name, mimeType, downloadUrl, expiresAt, sizeBytes }]`. The agent uses the AWS SDK `S3Presigner` (configured against the MinIO endpoint and the same access key the ingestion flow uses) to mint a short-lived `GET` URL for each de-duplicated source object.

- **Pros**: JSON stays small (a URL plus metadata is ~300 B per source); bytes only move when the caller actually clicks; MinIO already supports v4 presigning natively (no plugin); streaming-friendly (MinIO can range-serve large PDFs); separates concerns — the agent doesn't proxy file bytes; aligns with the cloud target (S3 production behaves identically).
- **Cons**: caller must follow the URL (one extra GET per source); presigned URLs are sensitive (anyone with the URL within TTL can fetch); MinIO endpoint must be reachable from the caller's network — for the docker-compose deployment this means the agent should presign against the *external* MinIO URL (`http://localhost:9070`), not the docker-internal hostname (`http://minio:9000`).
- **Verdict**: chosen. Best fit for the "answer + downloadable sources" UX. Default TTL 15 minutes.

The endpoint-routing concern (internal vs external MinIO host) is solved by introducing `app.minio.public-endpoint` (defaulting to `app.minio.endpoint`). Presigning uses the public endpoint; ingestion writes use the internal one. Production typically sets both to the same managed S3 URL.

#### Option 3 — Multipart response (`Content-Type: multipart/mixed`)

The first part is the JSON `AiResponse`; subsequent parts are the file bodies.

- **Pros**: idiomatic for "JSON + files" in one request/response; bytes flow once; no presigning required.
- **Cons**: most JS HTTP clients (fetch, axios) do NOT parse `multipart/mixed` responses out of the box (only `multipart/form-data` *requests*); Spring's response builder for `multipart/mixed` requires custom `HttpMessageConverter` work; Bruno/Postman render this poorly; chunked streaming + LLM streaming responses don't compose; couples the agent to file bytes (proxying defeats the docker-compose isolation point).
- **Verdict**: rejected. High implementation cost on both server and client for a UX that is strictly worse than presigned URLs for the "download a file later" case.

### D3 — Source de-duplication keyed by S3 (bucket, key)

A single retrieved set of N chunks may include 3 chunks from `pdf-A`, 2 chunks from `pdf-B`, and 1 chunk from `markdown-C`. The response array MUST contain `pdf-A`, `pdf-B`, `markdown-C` exactly once each — not 6 entries. Dedup key: the tuple `(bucket, key)` from each Qdrant point's payload. `LinkedHashSet` preserves first-seen order so the strongest-similarity source comes first.

### D4 — Size cap before presigning

Before presigning, the service issues a `HEAD` on each candidate object to read `Content-Length`. Objects larger than `app.rag.source-attachments.max-file-size` (default 25 MB) are skipped with a single `WARN` log of the form `Skipping source attachment for s3://{bucket}/{key} ({sizeBytes} > {maxBytes})`. Skipping does NOT fail the request — the rest of the sources are returned and the answer text is unchanged.

The size is also returned in the response (`sizeBytes`) when known. If the `HEAD` fails (e.g., transient MinIO error), the source is omitted from the response array (best-effort) and a single `WARN` line is logged; the request still returns 200. This protects callers from getting unusable URLs for files that no longer exist or are unreachable.

### D5 — Empty result handling

When `attachSources=true` but `RagRetrievalService` returned zero chunks above threshold (Soft-RAG cutoff), `AiResponse.sources` is an empty JSON array `[]`. NOT `null`, NOT absent, NOT a 4xx. The contract is: "if you asked for sources, you get an array; the array may be empty". This makes UI code trivial (`response.sources?.length ?? 0`).

When `attachSources=false` (default), `AiResponse.sources` is omitted from the JSON entirely via `@JsonInclude(JsonInclude.Include.NON_NULL)`. This preserves byte-for-byte backward compatibility with today's response.

### D6 — Security

- Presigned URLs are signed with the agent's MinIO credentials. They are unauthenticated for the duration of the TTL — anyone holding the URL can fetch the object. This is the standard S3 model.
- TTL default 15 minutes. Configurable down to 1 minute and up to 1 hour. Values outside this range are clamped at startup with a WARN log.
- The agent never logs presigned URLs (they expand to long pre-signed query strings that, if leaked to log aggregation, leak file access). Logs include only `s3://{bucket}/{key}` and the TTL.
- The agent does NOT add the presigned URL to chat history persisted in Postgres (the URL would be expired by the time anyone reads the history; persisting it is just clutter and a security smell).
- The agent does NOT bypass any authn it enforces. Today the agent's authn model is "trust the caller's `userId`" — the same model that gates `/api/v1/ai/prompt` gates this feature. If/when a real authz layer is added, presigning happens AFTER the authz check inside the controller, so unauthorized callers never see URLs.
- Presigned URLs are scoped to a single `GET` on a single object key — no list, no put, no delete. SDK builder enforces this.

### D7 — Tracking sources end-to-end

Today `RagRetrievalService.retrieve(...)` returns `String` (the assembled context block). It needs to return both the assembled context AND the de-duplicated source list. Cleanest shape: introduce a record `RagRetrievalResult(String context, List<SourceRef> sources)` and update the single caller (`ChatContextAssembler`). Internal `SourceRef(String bucket, String key, String displayName, String mimeType)` — populated from each `Document.getMetadata()`. The assembler ignores `sources` when `attachSources=false` so non-RAG paths are unaffected.

### D8 — Where to mint presigned URLs

In `AscendChatService` at the very end of the request, AFTER the LLM has returned the textual answer. Reasons:
- Don't mint URLs that won't be used (if the LLM call throws, the request fails — no need to presign first).
- The TTL window starts as late as possible so users have the maximum 15 minutes to click after they receive the response.
- Presigning happens in parallel for all sources (`CompletableFuture.allOf` against the SDK call) so it adds milliseconds, not seconds, to the response latency even with many sources.

### D9 — OpenAPI documentation

Annotate the `attachSources` parameter on `PromptController.prompt` with `@Parameter(description = "If true, the response includes presigned download URLs for the source documents that grounded the RAG answer. Defaults to false.")`. Annotate `SourceFile` with `@Schema(description = "...")` on each field. Update Swagger UI smoke test in `e2e/testing/rag.md` to include a `-F "attachSources=true"` curl.

### D10 — Test strategy

- **Unit**: `S3PresignedUrlServiceTest` — mock `S3Presigner`, assert the produced `URL`, expiry, HEAD-driven size cap, error handling.
- **Unit**: `RagRetrievalServiceSourceTrackingTest` — mock `VectorStore` returning chunks with mixed source metadata, assert dedup and ordering.
- **Unit**: `AscendChatServiceAttachSourcesTest` — feature flag off → no `sources` in response; flag on, no chunks → empty list; flag on, chunks → presigned URLs returned.
- **Unit**: `PromptControllerAttachSourcesTest` (`@WebMvcTest`) — multipart binding, default-false behavior, OpenAPI annotation present.
- **E2E curl** in `AscendAgent/e2e/testing/rag.md` — full happy path against docker-compose.

## Risks / Trade-offs

- **Risk**: MinIO `public-endpoint` misconfigured → presigned URLs are signed against `minio:9000` and the caller (browser/curl on host) cannot resolve the host. **Mitigation**: a `@PostConstruct` log line `[S3PresignedUrlService] Presigning against {endpoint}` makes the configured value visible at boot. E2E test asserts the URL hostname matches the public endpoint.
- **Risk**: Token leak via copy/paste of the response body (presigned URLs contain a signature). **Mitigation**: 15-minute TTL by default; configurable down to 1 minute for high-security deployments. Document the trade-off.
- **Risk**: Large source document set (e.g., 20 retrieved chunks across 12 unique PDFs) causes 12 sequential `HEAD` + 12 sequential presigns adding hundreds of ms to response latency. **Mitigation**: presign in parallel via `CompletableFuture.supplyAsync`. HEAD requests are cheap (<50 ms typically against local MinIO).
- **Risk**: Caller asks for sources but the request is part of a streaming SSE response. **Mitigation**: scope this change to the non-streaming JSON response only. Streaming sources is a separate concern (would attach them as a final SSE event); add as a follow-up if needed.
- **Trade-off**: Source attribution is file-level, not chunk-level. A future change could add `matchedSnippets: [{ text, score }]` per source for highlight-in-PDF UX. Out of scope here.

## Migration Plan

No migration required. Feature is purely additive.

- Existing callers continue to work byte-for-byte. The `sources` field is omitted from JSON unless explicitly requested.
- Existing Qdrant data (already-ingested documents) carries the source metadata in payloads, so the feature works retroactively against any document ingested under the current pipeline.
- If a deployment ingested documents with an older pipeline that didn't write `bucket`/`key` to Qdrant payloads, those chunks simply don't contribute to the `sources` list (and a single DEBUG log notes the missing metadata).

## Open Questions

- Should the response include the chunk-level *match score* per source (e.g., the max similarity across all chunks from that source)? — leaving out for now; can add as `topScore` later without breaking the schema.
- Should the agent allow the caller to bound the source count (`maxSources=3`)? — leaving out; today RAG `topK` already bounds this transitively. Add only if real demand surfaces.
- Should presigned URLs be cached for repeat requests within the TTL window? — no; cost of presigning is negligible and caching adds invalidation complexity.
