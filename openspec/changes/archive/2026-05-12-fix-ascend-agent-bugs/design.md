## Context

AscendAgent (Spring Boot, port 9917) is the entry point for user prompts. Three independent code paths are broken in the current state:

1. **Memory write path** (`SemanticMemoryExtractor` → `SemanticMemoryClient` → AscendMemory :7020 → Qdrant `ascend_memory`). Extraction is the gating step: it makes a separate LLM call to turn a user message into a JSON array of facts. With MiniMax-M2.7 (a thinking model), the LLM response routinely contains chain-of-thought ("We need to identify standalone semantic facts… Thus we have two facts… JSON array with two strings.") with no actual `[...]` array, or with reasoning before/after the array. The current parser calls `Jackson.readValue(text, String[].class)` first, then falls back to a single regex `\[.*\]` extraction. Both fail on the observed responses, so the warn is logged and *zero* facts are persisted. End user sees an empty memory.
2. **Image upload path** (`PromptController.prompt` → `ChatExecutor.handleImageContext`). `MultipartFile.getContentType()` returns the literal string `"file"` for the failing request (because the curl command shipped a malformed multipart part header). `MimeType.valueOf("file")` throws `InvalidMimeTypeException` because the value lacks `/`. The exception is wrapped in `AiGenerationException("Failed to process image upload")` → HTTP 500. Logic is too strict: a missing/unparseable Content-Type should default, not 500.
3. **Document ingestion path** (`PromptController` → `DocumentIngestionService` → `DocumentRouter` → `DoclingClient` → docling-serve :5001). The default `app.docling.api-path` is `/v1/convert`, but docling-serve's multipart-file endpoint is `/v1/convert/file`. POST to `/v1/convert` returns `404 {"detail":"Not Found"}` and `DoclingClient` rethrows as `IngestionException` → HTTP 502.
4. **Memory search path** (`SemanticMemoryClient.performSearchCall` → AscendMemory `/api/v1/memory/search`). The Java client builds the URI with query key `userId={userId}` (camelCase). The Python FastAPI endpoint declares `user_id: str` (snake_case). FastAPI's required-parameter validation fails before the route handler runs and returns HTTP 500 (visible in AscendAgent logs as `Status: 500 INTERNAL_SERVER_ERROR`). The insert path on the same client (line 87) already uses `user_id` — only the search URI is wrong. Likely regressed in commit `94790bc` (multi-provider memory routing).

All four are local AscendAgent issues. External services are healthy; the docker-compose stack does not require changes.

## Goals / Non-Goals

**Goals:**
- Restore the four flows end-to-end with the canonical curl examples from the bug reports (after fixing the malformed-curl bug-2 client by making the server defensive).
- Keep the fixes minimal and surgical — bug fixes, not refactors.
- Add unit tests that pin each regression so it cannot silently return.
- Make Docling default work out of the box against `docker-compose.yaml`.
- Make AscendAgent ↔ AscendMemory wire contract consistent (snake_case query params).

**Non-Goals:**
- No re-architecture of memory extraction, no new providers, no model swaps.
- No changes to `docker-compose.yaml` or to AscendMemory / docling-serve source.
- No changes to the public REST contract of `/api/v1/ai/prompt`.

## Decisions

### D1 — Robust JSON-array extraction for thinking-model output
Add a dedicated `extractJsonArray(String)` helper (in `ChatResponseContentResolver` or a new `JsonArrayExtractor`) that:
1. Trims and tries `Jackson.readValue(text, String[].class)` first.
2. If that fails, scans the text from end to start for the last balanced `[ ... ]` substring (depth-counted, to handle nested brackets like `["a [b] c"]`) and tries Jackson on it.
3. If still failing, returns `Optional.empty()` and the caller logs the *full* response at `WARN` (one-line) plus a counter metric `memory.extraction.parse_failed`.

Tighten the extraction prompt to explicitly forbid prose/reasoning ("Output ONLY a JSON array of strings. No prose, no markdown fences, no explanation. If no facts, output `[]`."). This addresses the root cause; D1 is the safety net.

**Alternative considered**: switch the extractor to a non-thinking model (e.g., `MiniMax-M2.5-highspeed` or LM Studio). Rejected for now because per-request provider selection means the user can pick *any* provider; we need defensive parsing regardless.

### D2 — Defensive MIME parsing for uploaded images
Replace the unsafe `Optional.ofNullable(image.getContentType()).map(MimeType::valueOf).orElse(IMAGE_PNG)` with:
1. Read `image.getContentType()`. If null/blank/does-not-contain-`/`: skip to step 3.
2. Try `MimeType.valueOf(...)` inside a try/catch for `InvalidMimeTypeException`. On success, use it.
3. Fallback: detect from filename extension (`.jpg/.jpeg → image/jpeg`, `.png → image/png`, `.webp → image/webp`, `.gif → image/gif`); else `IMAGE_PNG`.
4. Log at INFO which path was taken so a malformed client is observable.

Catch `InvalidMimeTypeException` explicitly inside `handleImageContext` so this specific class no longer reaches `AiGenerationException`.

**Alternative considered**: sniffing magic bytes via `Files.probeContentType` or Apache Tika. Rejected — adds a dependency and the extension-based fallback is sufficient for the supported `image=@file` curl flow.

### D3 — Correct Docling endpoint path
Change the default `app.docling.api-path` from `/v1/convert` to `/v1/convert/file` in `application.yaml`. `DoclingClient` already concatenates `baseUrl + apiPath + "?to_formats=json"`, so no code change is required if the property is fixed; however we will also normalize: if the configured path equals exactly `/v1/convert` we will append `/file` defensively at startup with a WARN log, to protect against pre-existing overrides in `application-*.yaml` profiles.

Add a `@PostConstruct` startup probe (HEAD/GET to `${baseUrl}/health` if available, else log the resolved URL) so a misconfiguration is visible at boot.

### D5 — Align AscendMemory search query parameter
Change `SemanticMemoryClient.performSearchCall` URI from `?userId={userId}&...` to `?user_id={userId}&...` so the call matches the FastAPI route's required parameter name. No server-side change needed; the insert call already uses `user_id`. Also audit the rest of the client for other camelCase query keys against AscendMemory (a quick grep on `userId=` / `topK=` etc.) and align any further mismatches in the same commit.

**Alternative considered**: change AscendMemory to accept both `userId` and `user_id` via FastAPI alias. Rejected — it's a wire-contract bug in the client, not the server, and aliasing would just hide the next mismatch.

### D4 — Test fixtures
- `SemanticMemoryExtractorTest`: feed verbatim the failing MiniMax response from the bug log; assert two facts are extracted ("User's name is Luke", "User is a software engineer").
- `ChatExecutorImageTest`: parameterized — null content type, `"file"`, `"image/jpeg"`, `""`, `"application/octet-stream"` + `.jpg` filename. All non-null/parseable cases produce a valid `MimeType`; 500 is never thrown.
- `DoclingClientTest`: with mocked `RestClient`, assert the URI ends with `/v1/convert/file?to_formats=json`.
- `SemanticMemoryClientTest`: with mocked `RestClient`, capture the outgoing URI for `search(...)` and assert it contains `user_id=<userId>` (not `userId=`). Also assert insert body still has `user_id` key. Add tests for `wipeUserMemory` and `deleteMemory` (URI + body shape) and for blank-userId short-circuit.

### D6 — Memory client completeness and observability
- Add `SemanticMemoryClient.wipeUserMemory(userId, embeddingProvider)` (POST `/api/v1/memory/wipe`, body `{"user_id":..., "provider":...}`) and `deleteMemory(userId, memoryId, embeddingProvider)` (DELETE `/api/v1/memory`) to mirror the FastAPI surface.
- Validate non-blank `userId` at the entry of every public method; log WARN and return empty list / no-op when blank.
- Fix `SemanticMemoryProperties` default `baseUrl` from `http://localhost:8770` → `http://localhost:7020` to match docker-compose.
- In `SemanticMemoryExtractor`, replace `facts.forEach(memoryClient::insertMemory)` with a try/catch loop that tallies failures and logs `Inserted {ok}/{total} facts for user '{userId}' (failed: {n})`. Increment a Micrometer counter `memory.insert.failed`.

### D7 — Chat-history Redis TTL
- Bind `app.memory.chat-history.ttl` (already declared) into `PersistentChatMemory` via `@ConfigurationProperties` or `@Value("${app.memory.chat-history.ttl:PT24H}")`.
- After every Redis `rightPush`/`rightPushAll`, call `redisTemplate.expire(key, ttl)`. Idempotent — Redis updates expiration each write.
- Postgres pruning is out of scope for this change but document the gap as a follow-up TODO in `application.yaml` or an ADR.

### D8 — RAG similarity threshold applied at query
- In `RagRetrievalService`, replace the hard-coded `SearchRequest.SIMILARITY_THRESHOLD_ACCEPT_ALL` with `ragProperties.getSimilarityThreshold()` so Qdrant filters server-side.
- Remove the post-filter that drops the entire context when only the top hit fails the threshold; trust Qdrant's filter.
- Keep `topK` and `embeddingProvider`-driven collection routing unchanged.

### D9 — Ingestion upload security and limits
- New helper `IngestionSecurity.sanitizeFilename(String)`: strip control chars, replace anything outside `[A-Za-z0-9._-]` with `_`, collapse repeats, strip leading dots, hard-cap length at 200.
- Configurable allowlist `app.ingestion.upload.allowed-mime-types` defaulting to `application/pdf, text/markdown, text/plain, image/png, image/jpeg, image/webp, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/vnd.openxmlformats-officedocument.presentationml.presentation`.
- `IngestionController` validates MIME against the allowlist (sniffs first 8 bytes when Content-Type is `application/octet-stream` or missing) and returns HTTP 415 on mismatch.
- Configure Spring `spring.servlet.multipart.max-file-size: 25MB`, `max-request-size: 30MB` (override-able via env).

### D10 — HTTP-upload deduplication
- Reuse the metadata store used by `ManualIngestionService` (`int_metadata_store` table). Key the dedup tuple as `(sanitized-filename, sha256-of-bytes)`.
- Before adding new chunks, call `documentService.removeOldDocuments(source=<sanitized-filename>)` (existing method) so re-upload replaces rather than duplicates.

### D11 — Vision capability gate
- Static map `Map<Provider, Set<String>> visionCapableModels` (e.g., `lmstudio: qwen3-vl-*`, `openai: gpt-4o*`, `anthropic: claude-*-vision*`, `gemini: gemini-*-pro|flash`). Check with prefix/wildcard.
- When `image` is attached and `(provider, model)` is not in the map, return HTTP 400 with `{"message":"Model {model} on provider {provider} does not support image input"}`.
- Map is configuration-overridable via `app.ai.vision.providers` so users can extend it without code change.

### D12 — Documentation and ADRs
- Add a "RAG ingestion lifecycle" section to `AscendAgent/README.md` covering: (1) put files in `knowledge-base/{obsidian,documents}/` in MinIO; (2) call `POST /api/ingestion/run` (manual) OR set `app.ingestion.auto.enabled: true` (auto-poll); (3) which collection (`ascendai-{dims}`) is used per embedding provider; (4) how to switch providers safely (re-index required); (5) how RAG corpus differs from semantic memory and chat history.
- Add ADR `AscendAgent/docs/architecture/decisions/ADR-00X-ingestion-auto-default-off.md` documenting why `app.ingestion.auto.enabled` defaults to OFF (cost, accidental indexing, predictable startup).

## Risks / Trade-offs

- **[Risk]** Tightening the extraction prompt may cause some non-thinking models to over-strictly return `[]` on ambiguous input → **Mitigation**: D1 safety net keeps recall high; add the prompt-tighten as a separate commit so it can be reverted independently.
- **[Risk]** Defensive MIME fallback could mask a real client bug → **Mitigation**: log at INFO with the original (bad) value so it remains observable.
- **[Risk]** The Docling path may differ between docling-serve versions → **Mitigation**: leave it configurable via `app.docling.api-path`; only the *default* changes.
- **[Trade-off]** No retry on memory-extractor parse failure for v1 — keeps the fix small. A retry-with-stricter-prompt loop is listed as a follow-up task.

## Migration Plan

No data migration. Deploy is a single AscendAgent restart. Rollback is a `git revert`. No DB changes, no compose changes.
