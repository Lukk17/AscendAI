## 1. Bug 3 — Docling endpoint path (smallest, unblocks PDF flow)

- [ ] 1.1 Update `AscendAgent/src/main/resources/application.yaml`: change `app.docling.api-path` default from `/v1/convert` to `/v1/convert/file`
- [ ] 1.2 In `DoclingClient`, change the `@Value` default for `doclingApiPath` to `/v1/convert/file` to match
- [ ] 1.3 Add a defensive normalization step in `DoclingClient` constructor: if the configured path equals exactly `/v1/convert`, append `/file` and log a WARN
- [ ] 1.4 Add `@PostConstruct` log line: `[DoclingClient] Configured upload endpoint: <baseUrl><apiPath>`
- [ ] 1.5 Add unit test `DoclingClientTest` asserting the constructed URI ends with `/v1/convert/file?to_formats=json` for the default config and for the legacy `/v1/convert` override
- [ ] 1.6 Manual verification: run docker-compose, run the bug-3 curl, expect 200 with summary in response

## 2. Bug 2 — Defensive image MIME parsing

- [ ] 2.1 Refactor `ChatExecutor.handleImageContext` so MIME resolution is in a small helper `resolveImageMimeType(MultipartFile)` returning a never-null `MimeType`
- [ ] 2.2 Inside the helper: (a) read `getContentType()`, (b) reject null/blank/no-`/`, (c) try `MimeType.valueOf` with try/catch on `InvalidMimeTypeException`, (d) fall back to filename extension (`.jpg/.jpeg/.png/.webp/.gif`), (e) final default `IMAGE_PNG`
- [ ] 2.3 Catch `InvalidMimeTypeException` explicitly inside `handleImageContext` so it never reaches the broad `catch (Exception)` wrapping
- [ ] 2.4 Log at INFO when a fallback path is taken, including the original (bad) Content-Type value
- [ ] 2.5 Add parameterized unit test `ChatExecutorImageTest` covering: `null`, `""`, `"file"`, `"application/octet-stream"` + `.jpg` filename, `"image/jpeg"` — all produce a valid `MimeType`, none throw
- [ ] 2.6 Manual verification: run the bug-2 curl (after fixing the trailing space in `image =@`); expect 200 with image description

## 3. Bug 1 — Robust semantic memory extraction

- [ ] 3.1 Locate the extraction prompt template (search `SemanticMemoryExtractor` for the prompt source) and tighten it: append `Output ONLY a JSON array of strings. No prose, no markdown fences, no explanation. If no facts, output [].`
- [ ] 3.2 Add helper `Optional<String[]> extractJsonArray(String text)`: (a) trim, strip ```` ```json ```` fences, try `objectMapper.readValue(t, String[].class)`, (b) on failure, scan from end for the last balanced `[ ... ]` substring (depth-counted, string-aware), retry parse, (c) return `Optional.empty()` if all fail
- [ ] 3.3 Wire the helper into `SemanticMemoryExtractor.parseJsonArray` (or replace the existing fallback `extractEmbeddedJsonArray`)
- [ ] 3.4 On parse failure, log full raw response at WARN once and increment a Micrometer counter `memory.extraction.parse_failed` (or add a TODO if Micrometer not yet wired — do NOT block the flow)
- [ ] 3.5 Ensure the extractor uses `ChatResponseContentResolver` for content (not raw `output.getText()`) so multi-generation thinking responses are handled
- [ ] 3.6 Add `SemanticMemoryExtractorTest` with a fixture taken verbatim from the bug-1 log (the "Thus we have two facts…" response). Assert the parser either (a) extracts both facts if the array is present, or (b) returns an empty list and logs WARN — but never throws
- [ ] 3.7 Add a second test fixture: pure `["User's name is Luke", "User is a software engineer"]` → returns both facts
- [ ] 3.8 Manual verification: run the two bug-1 curls in sequence; check Qdrant `ascend_memory` is populated after request 1; request 2 returns an answer that mentions Luke / software engineer

## 4. Bug 4 — AscendMemory search query parameter mismatch

- [ ] 4.1 In `SemanticMemoryClient.performSearchCall` (line 47), change the URI template `userId={userId}` to `user_id={userId}` (positional placeholder unchanged). Final URI: `${baseUrl}/api/v1/memory/search?user_id={userId}&query={query}&limit={limit}&provider={provider}`
- [ ] 4.2 Audit the rest of `SemanticMemoryClient` for any other camelCase query keys (`topK`, etc.) and align with AscendMemory's FastAPI contract; align in the same commit if any are found
- [ ] 4.3 Add `SemanticMemoryClientTest` capturing the outgoing URI for `search(...)` via mocked `RestClient`/`MockRestServiceServer`; assert it contains `user_id=` and not `userId=`
- [ ] 4.4 Add a second test asserting the insert POST body remains `{"user_id":..., "text":..., "provider":...}` so this contract cannot drift
- [ ] 4.5 Manual verification: with AscendMemory running, run any prompt curl as user `frosty`; confirm AscendAgent logs `Received N semantic memory items` (or 0 with HTTP 200) and never `Status: 500 INTERNAL_SERVER_ERROR`

## 5. Bug 5 — Memory client gaps and silent failures

- [ ] 5.1 Add `wipeUserMemory(userId, embeddingProvider)` to `SemanticMemoryClient`: POST `/api/v1/memory/wipe` with body `{"user_id":..., "provider":...}`
- [ ] 5.2 Add `deleteMemory(userId, memoryId, embeddingProvider)` to `SemanticMemoryClient`: HTTP DELETE `/api/v1/memory` matching the FastAPI signature in `AscendMemory/src/api/rest/rest_endpoints.py`
- [ ] 5.3 Validate non-blank `userId` at entry of every public method on `SemanticMemoryClient`; log WARN once and return empty/no-op when blank
- [ ] 5.4 Update `SemanticMemoryProperties` default `baseUrl` from `http://localhost:8770` to `http://localhost:7020`
- [ ] 5.5 In `SemanticMemoryExtractor`, replace `facts.forEach(memoryClient::insertMemory)` with a try/catch loop that tallies ok/failed counts and logs `Inserted {ok}/{N} facts for user '{userId}' (failed: {n})` at WARN when any insert fails
- [ ] 5.6 (Optional) Increment a Micrometer counter `memory.insert.failed` on each failed insert
- [ ] 5.7 Tests: `wipeUserMemoryTest`, `deleteMemoryTest`, `blankUserIdShortCircuitTest`, `failedInsertAggregationTest`

## 6. Bug 6 — Chat-history Redis TTL

- [ ] 6.1 Bind `app.memory.chat-history.ttl` into `PersistentChatMemory` via `@Value("${app.memory.chat-history.ttl:PT24H}")` (parses to `Duration`)
- [ ] 6.2 After every Redis `rightPush` / `rightPushAll`, call `redisTemplate.expire(key, ttlDuration)`
- [ ] 6.3 Add a comment in `application.yaml` explaining the Redis TTL semantics and that Postgres pruning is separate (TODO follow-up)
- [ ] 6.4 Test: `PersistentChatMemoryTtlTest` using `embedded-redis` or Testcontainers — write a message, assert `getExpire(key)` returns a non-zero ttl close to configured value
- [ ] 6.5 Manual verification: send a prompt, `redis-cli TTL chat:<userId>` returns a positive number ≤ 86400

## 7. Bug 7 — RAG similarity threshold at search time

- [ ] 7.1 In `RagRetrievalService`, replace the `SearchRequest.SIMILARITY_THRESHOLD_ACCEPT_ALL` argument with `ragProperties.getSimilarityThreshold()`
- [ ] 7.2 Remove the post-filter that drops the entire context when only the top hit fails the threshold (or correct it to filter per-hit, not collection-wide)
- [ ] 7.3 Test: with a mocked `VectorStore` returning hits `[0.91, 0.85, 0.80, 0.74, 0.60]` and threshold `0.75`, assert the assembled context contains exactly 3 hits
- [ ] 7.4 Test: with hits `[0.74, 0.80, 0.85]`, assert 2 hits are returned and `RAG Context Injected: YES` is logged
- [ ] 7.5 Manual verification: upload a known doc, ask a relevant question, confirm RAG context is present in logs

## 8. Bug 8 — Ingestion upload security & limits

- [ ] 8.1 Create utility `IngestionSecurity.sanitizeFilename(String)`: strip control chars, replace `[^A-Za-z0-9._-]` → `_`, collapse repeats, strip leading dots, cap length at 200; with full unit tests
- [ ] 8.2 Wire sanitization into `IngestionController` everywhere `getOriginalFilename()` is used (S3 key, Qdrant `source` metadata)
- [ ] 8.3 Add config property `app.ingestion.upload.allowed-mime-types` (list) with the default allowlist (pdf, md, txt, png, jpeg, webp, docx, pptx)
- [ ] 8.4 In `IngestionController`, validate the MIME type against the allowlist; sniff first 8 bytes when `Content-Type` is `application/octet-stream` or missing; return HTTP 415 on mismatch
- [ ] 8.5 Add `spring.servlet.multipart.max-file-size: 25MB` and `max-request-size: 30MB` to `application.yaml` (env-overridable)
- [ ] 8.6 Tests: `IngestionSecurityTest` (filename sanitization edge cases), `IngestionControllerSecurityTest` (415 on bad MIME, 413 on oversize)

## 9. Bug 9 — HTTP-upload deduplication

- [ ] 9.1 In `DocumentIngestionService` (or `IngestionController` before delegating), call `documentService.removeOldDocuments(source=<sanitized-filename>)` before adding new chunks
- [ ] 9.2 (Optional) Add a content-hash check using SHA-256 of bytes; if the hash is unchanged, log `Skipping re-ingest of unchanged document <name>` and return immediately
- [ ] 9.3 Test: upload `notes.md`, then upload a modified `notes.md`; assert Qdrant point count for `source=notes.md` equals only the new version's chunk count (not the sum)
- [ ] 9.4 Manual verification with MinIO console: re-upload an `.md` file, run `/api/ingestion/run`, confirm no duplicate hits in subsequent prompts

## 10. Bug 10 — Vision capability gate & docker URL audit

- [ ] 10.1 Add config `app.ai.vision.providers` as a `Map<String, List<String>>` (provider → list of model patterns/wildcards) with sensible defaults (lmstudio: `*-vl-*`; openai: `gpt-4o*`, `gpt-5*`; anthropic: `claude-*`; gemini: `gemini-*`)
- [ ] 10.2 Add `VisionCapabilityResolver` that returns true if `(provider, model)` matches any pattern
- [ ] 10.3 In `PromptController` (or earliest possible point with a `MultipartFile image`), reject with HTTP 400 + `does not support image input` when the gate fails
- [ ] 10.4 Test: parameterized — `(lmstudio, qwen3-vl-4b, image) → 200`, `(minimax, MiniMax-M2.7, image) → 400`
- [ ] 10.5 Verify both `application.yaml` and `application-docker.yaml` resolve `app.unstructured.base-url` correctly for host vs container; add a `@PostConstruct` log line `[Unstructured] Configured base URL: ...`

## 11. Bug 11 — Documentation & RAG UX

- [ ] 11.1 Add a "RAG ingestion lifecycle" section to `AscendAgent/README.md` covering (a) MinIO bucket + folder layout; (b) manual `POST /api/ingestion/run` vs auto-poll toggle (`app.ingestion.auto.enabled`); (c) embedding-dimension / collection coupling; (d) provider-switch re-index requirement; (e) RAG corpus vs semantic memory vs chat history
- [ ] 11.2 Add ADR `AscendAgent/docs/architecture/decisions/ADR-00X-ingestion-auto-default-off.md` (Context / Decision / Consequences) explaining why auto-ingest defaults to OFF
- [ ] 11.3 (Optional) Add a sequence diagram or mermaid snippet to the architecture docs showing MinIO → Router → (Markdown | Docling | Unstructured | PaddleOCR) → splitter → VectorStore → Qdrant
- [ ] 11.4 Update root `README.md` to cross-link the new section

## 12. Cross-cutting verification

- [ ] 12.1 Run `./gradlew test` — all new tests pass
- [ ] 12.2 Run `./gradlew build` — clean build
- [ ] 12.3 Smoke test: start docker-compose, run all four bug-report curls, confirm each returns 200 with the expected behavior. For bug-1, verify Qdrant `ascend_memory` is populated after request 1 and request 2 recalls Luke / software engineer
- [ ] 12.4 Smoke test (RAG): drop an `.md` into `knowledge-base/obsidian/`, call `POST /api/ingestion/run`, ask a question that should hit it, confirm RAG context is injected (logs show `RAG Context Injected: YES`)
- [ ] 12.5 Smoke test (security): attempt path-traversal filename and oversize upload — both rejected gracefully
- [ ] 12.6 Update `implementation_plan.md` Progress section as each task completes
