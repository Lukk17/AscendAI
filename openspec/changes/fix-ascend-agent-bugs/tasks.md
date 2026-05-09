## 1. Bug 3 — Docling endpoint path (smallest, unblocks PDF flow)

- [x] 1.1 Update `AscendAgent/src/main/resources/application.yaml`: change `app.docling.api-path` default from `/v1/convert` to `/v1/convert/file`
- [x] 1.2 In `DoclingClient`, change the `@Value` default for `doclingApiPath` to `/v1/convert/file` to match
- [x] 1.3 Add a defensive normalization step in `DoclingClient` constructor: if the configured path equals exactly `/v1/convert`, append `/file` and log a WARN
- [x] 1.4 Add `@PostConstruct` log line: `[DoclingClient] Configured upload endpoint: <baseUrl><apiPath>`
- [ ] 1.5 Add unit test `DoclingClientTest` asserting the constructed URI ends with `/v1/convert/file?to_formats=json` for the default config and for the legacy `/v1/convert` override
- [ ] 1.6 Manual verification: run docker-compose, run the bug-3 curl, expect 200 with summary in response

## 2. Bug 2 — Defensive image MIME parsing

- [x] 2.1 Refactor `ChatExecutor.handleImageContext` so MIME resolution is in a small helper `resolveImageMimeType(MultipartFile)` returning a never-null `MimeType`
- [x] 2.2 Inside the helper: (a) read `getContentType()`, (b) reject null/blank/no-`/`, (c) try `MimeType.valueOf` with try/catch on `InvalidMimeTypeException`, (d) fall back to filename extension (`.jpg/.jpeg/.png/.webp/.gif`), (e) final default `IMAGE_PNG`
- [x] 2.3 Catch `InvalidMimeTypeException` explicitly inside `handleImageContext` so it never reaches the broad `catch (Exception)` wrapping
- [x] 2.4 Log at INFO when a fallback path is taken, including the original (bad) Content-Type value
- [ ] 2.5 Add parameterized unit test `ChatExecutorImageTest` covering: `null`, `""`, `"file"`, `"application/octet-stream"` + `.jpg` filename, `"image/jpeg"` — all produce a valid `MimeType`, none throw
- [ ] 2.6 Manual verification: run the bug-2 curl (after fixing the trailing space in `image =@`); expect 200 with image description

## 3. Bug 1 — Robust semantic memory extraction

- [x] 3.1 Locate the extraction prompt template (search `SemanticMemoryExtractor` for the prompt source) and tighten it: append `Output ONLY a JSON array of strings. No prose, no markdown fences, no explanation. If no facts, output [].`
- [x] 3.2 Add helper `Optional<String[]> extractJsonArray(String text)`: (a) trim, strip ```` ```json ```` fences, try `objectMapper.readValue(t, String[].class)`, (b) on failure, scan from end for the last balanced `[ ... ]` substring (depth-counted, string-aware), retry parse, (c) return `Optional.empty()` if all fail
- [x] 3.3 Wire the helper into `SemanticMemoryExtractor.parseJsonArray` (or replace the existing fallback `extractEmbeddedJsonArray`)
- [x] 3.4 On parse failure, log full raw response at WARN once (Micrometer counter deferred to `add-observability` change)
- [x] 3.5 Already uses `ChatResponseContentResolver` (verified)
- [ ] 3.6 Add `SemanticMemoryExtractorTest` with a fixture taken verbatim from the bug-1 log (the "Thus we have two facts…" response)
- [ ] 3.7 Add a second test fixture: pure `["User's name is Luke", "User is a software engineer"]` → returns both facts
- [ ] 3.8 Manual verification: run the two bug-1 curls in sequence; check Qdrant `ascend_memory_*` is populated after request 1; request 2 returns an answer that mentions Luke / software engineer

## 4. Bug 4 — AscendMemory search query parameter mismatch

- [x] 4.1 In `SemanticMemoryClient.performSearchCall` (line 47), change the URI template `userId={userId}` to `user_id={userId}` (positional placeholder unchanged). Final URI: `${baseUrl}/api/v1/memory/search?user_id={userId}&query={query}&limit={limit}&provider={provider}`
- [x] 4.2 Audit the rest of `SemanticMemoryClient` for any other camelCase query keys (`topK`, etc.) and align with AscendMemory's FastAPI contract; align in the same commit if any are found
- [x] 4.3 Add `SemanticMemoryClientTest` capturing the outgoing URI for `search(...)` via mocked `RestClient`/`MockRestServiceServer`; assert it contains `user_id=` and not `userId=`
- [x] 4.4 Add a second test asserting the insert POST body remains `{"user_id":..., "text":..., "provider":...}` so this contract cannot drift
- [ ] 4.5 Manual verification: with AscendMemory running, run any prompt curl as user `frosty`; confirm AscendAgent logs `Received N semantic memory items` (or 0 with HTTP 200) and never `Status: 500 INTERNAL_SERVER_ERROR`

## 5. Bug 5 — Memory client gaps and silent failures

- [x] 5.1 Add `wipeUserMemory(userId, embeddingProvider)` to `SemanticMemoryClient`: POST `/api/v1/memory/wipe` with body `{"user_id":..., "provider":...}`
- [x] 5.2 Add `deleteMemory(userId, memoryId, embeddingProvider)` to `SemanticMemoryClient`: HTTP DELETE `/api/v1/memory?memory_id=...&provider=...` matching the FastAPI signature
- [x] 5.3 Validate non-blank `userId` at entry of every public method on `SemanticMemoryClient`; log WARN once and return empty/no-op when blank
- [x] 5.4 Update `SemanticMemoryProperties` default `baseUrl` from `http://localhost:8770` to `http://localhost:7020`
- [x] 5.5 In `SemanticMemoryExtractor`, replace `facts.forEach(memoryClient::insertMemory)` with a try/catch loop that tallies ok/failed counts and logs `Inserted {ok}/{N} facts for user '{userId}' (failed: {n})` at WARN when any insert fails
- [ ] 5.6 ~~(Optional) Increment a Micrometer counter `memory.insert.failed` on each failed insert~~ **moved to OpenSpec change `add-observability`**
- [ ] 5.7 Tests: `wipeUserMemoryTest`, `deleteMemoryTest`, `blankUserIdShortCircuitTest`, `failedInsertAggregationTest`

## 6. Bug 6 — Chat-history Redis TTL

- [x] 6.1 Bind `app.memory.chat-history.ttl` into `PersistentChatMemory` via `@Value("${app.memory.chat-history.ttl:PT24H}")` (parses to `Duration`)
- [x] 6.2 After every Redis `rightPush` / `rightPushAll`, call `redisTemplate.expire(key, ttlDuration)`
- [x] 6.3 In-source comment added to `PersistentChatMemory` explaining the TTL purpose and Postgres-pruning separation
- [ ] 6.4 Test: `PersistentChatMemoryTtlTest` using `embedded-redis` or Testcontainers — write a message, assert `getExpire(key)` returns a non-zero ttl close to configured value
- [ ] 6.5 Manual verification: send a prompt, `redis-cli TTL chat:<userId>` returns a positive number ≤ 86400

## 7. Bug 7 — RAG similarity threshold at search time

- [x] 7.1 In `RagRetrievalService`, replace the `SearchRequest.SIMILARITY_THRESHOLD_ACCEPT_ALL` argument with `ragProperties.getSimilarityThreshold()`
- [x] 7.2 Remove the post-filter that drops the entire context when only the top hit fails the threshold
- [ ] 7.3 Test: with a mocked `VectorStore` returning hits `[0.91, 0.85, 0.80, 0.74, 0.60]` and threshold `0.75`, assert the assembled context contains exactly 3 hits
- [ ] 7.4 Test: with hits `[0.74, 0.80, 0.85]`, assert 2 hits are returned and `RAG Context Injected: YES` is logged
- [ ] 7.5 Manual verification: upload a known doc, ask a relevant question, confirm RAG context is present in logs

## 8. Bug 8 — Ingestion upload security & limits

- [x] 8.1 Create utility `IngestionSecurity.sanitizeFilename(String)`: strip control chars, replace `[^A-Za-z0-9._-]` → `_`, collapse repeats, strip leading dots, cap length at 200 with extension preservation
- [x] 8.2 Wire sanitization into `IngestionController.uploadDocument` everywhere `getOriginalFilename()` is used
- [x] 8.3 Add config property `app.ingestion.upload.allowed-mime-types` with default allowlist (pdf, md, txt, png, jpeg, webp, docx, pptx, octet-stream fallback)
- [x] 8.4 In `IngestionController`, validate the MIME type against the allowlist; return HTTP 415 on mismatch (byte-sniffing deferred — Content-Type check + extension routing covers the common cases)
- [x] 8.5 Bumped to `spring.servlet.multipart.max-file-size: 100MB` / `max-request-size: 110MB` per user direction (was 25MB/30MB in original task spec)
- [ ] 8.6 Tests: `IngestionSecurityTest` (filename sanitization edge cases), `IngestionControllerSecurityTest` (415 on bad MIME, 413 on oversize)

## 9. Bug 9 — HTTP-upload deduplication

- [x] 9.1 Already covered: `ManualIngestionService.ingestIntoActiveCollection` (line 129) calls `documentService.removeOldDocuments(chunks, store)` before adding new chunks. Re-uploading an existing file via `/upload` overwrites the S3 object (same key); the next `/run` detects the changed eTag and re-ingests with dedup.
- [ ] 9.2 (Optional) SHA-256 content-hash check — deferred (current eTag-based dedup is sufficient for the typical re-upload path)
- [ ] 9.3 Test: upload `notes.md`, then upload a modified `notes.md`; assert Qdrant point count for `source=notes.md` equals only the new version's chunk count (not the sum)
- [ ] 9.4 Manual verification with MinIO console: re-upload an `.md` file, run `/api/v1/ingestion/run`, confirm no duplicate hits in subsequent prompts

## 10. Bug 10 — Vision capability gate & docker URL audit

- [x] 10.1 Add config `app.ai.vision.providers` as a `Map<String, List<String>>` with defaults (lmstudio: `*-vl-*`, `qwen*-vl*`, `*llava*`; openai: `gpt-4o*`, `gpt-5*`; anthropic: `claude-*`; gemini: `gemini-*`; minimax: empty)
- [x] 10.2 Add `VisionCapabilityResolver` that glob-matches `(provider, model)` against the configured patterns
- [x] 10.3 In `PromptController`, reject with HTTP 400 + clear message when an image is attached and the resolved provider/model has no matching glob
- [ ] 10.4 Test: parameterized — `(lmstudio, qwen3-vl-4b, image) → 200`, `(minimax, MiniMax-M2.7, image) → 400`
- [ ] 10.5 Verify both `application.yaml` and `application-docker.yaml` resolve `app.unstructured.base-url` correctly for host vs container; add a `@PostConstruct` log line `[Unstructured] Configured base URL: ...`

## 11. Bug 11 — Documentation & RAG UX

- [x] 11.1 Add a "RAG ingestion lifecycle" section to `AscendAgent/README.md` covering (a) MinIO bucket + folder layout; (b) manual `POST /api/ingestion/run` vs auto-poll toggle (`app.ingestion.auto.enabled`); (b1) DONE in `docs/INGESTION.md` — full two-step lifecycle, upload+run flow, auto-poller opt-in. AscendAgent README cross-link still pending.
- [x] 11.2 Add ADR `AscendAgent/docs/architecture/decisions/ADR-007-ingestion-auto-default-off.md` (Status / Context / Decision / Consequences / Alternatives / Related) explaining why auto-ingest defaults to OFF
- [ ] 11.3 (Optional) Add a sequence diagram or mermaid snippet to the architecture docs showing MinIO → Router → (Markdown | Docling | Unstructured | PaddleOCR) → splitter → VectorStore → Qdrant
- [ ] 11.4 Update root `README.md` to cross-link the new section

## 11.5 Bug 13 — SemanticMemoryItem JSON field-name mismatch

- [x] 11.5.1 Annotate `SemanticMemoryItem` constructor params (or use `@JsonAlias` on the record components) so JSON `memory` deserializes into `text`, `user_id` into `userId`, and `created_at` into `createdAt`. Use `@JsonAlias` to keep both names accepted (in case any internal call still produces camelCase)
- [x] 11.5.2 Add `SemanticMemoryItemDeserializationTest` that round-trips a mem0-shaped JSON payload through Jackson and asserts `text()`, `userId()`, `createdAt()` are populated
- [ ] 11.5.3 Manual verification: as `frosty`, send "Hello, my name is Luke. I am a software engineer." then "What is my name?". Agent log must show `SemanticMemory: YES (N items)` on the recall request and the model response must mention Luke / software engineer.

## 12. Bug 12 — AscendMemory per-provider OpenAI routing

- [x] 12.1 Extend `AscendMemory/src/config/config.py` `Settings` with three independent base-URL / API-key pairs: `LMSTUDIO_BASE_URL` (default `http://localhost:1234/v1`), `LMSTUDIO_API_KEY` (default `sk_local`), `OPENAI_BASE_URL` (default `https://api.openai.com/v1`), `OPENAI_API_KEY` (no default), `GEMINI_BASE_URL` (default Gemini's OpenAI-compat URL), `GEMINI_API_KEY` (no default)
- [x] 12.2 Add `base_url_setting` and `api_key_setting` fields to each entry in `PROVIDER_CONFIGS` referencing the matching `Settings` attribute names
- [x] 12.3 Refactor `AscendMemory/src/service/memory_client.py` `AscendMemoryClient.__init__` to look up the resolved provider's `base_url` and `api_key` via `getattr(settings, ...)` and use those when building the mem0 `embedder` and `llm` configs, replacing the hardcoded `settings.OPENAI_BASE_URL` / `settings.OPENAI_API_KEY`
- [x] 12.4 Validate that the resolved provider's API key is non-empty at client init; raise a clear `ValueError` mentioning the missing env var name when invoked
- [x] 12.5 Update `docker-compose.yaml` `ascend-memory` service env to pass `LMSTUDIO_BASE_URL=http://host.docker.internal:1234/v1`, `LMSTUDIO_API_KEY=sk_local`, `OPENAI_BASE_URL=https://api.openai.com/v1`, `OPENAI_API_KEY=${OPENAI_API_KEY}`, `GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`, `GEMINI_API_KEY=${GEMINI_API_KEY}`
- [ ] 12.6 Manual verification: rebuild (`docker compose up -d --build ascend-memory`), run prompt as `frosty` with `embeddingProvider=openai`; AscendMemory log shows embedder calling `api.openai.com`; Qdrant gets a fresh `ascend_memory_1536` collection; agent log shows `Inserted 2/2 facts` (or whatever count). Repeat with `embeddingProvider=lmstudio` to confirm LM Studio still works.

## 12.10 Bug 18 — Multi-file ingestion upload

- [x] 12.10.1 Change `IngestionController.uploadDocument` signature from `MultipartFile file` to `List<MultipartFile> files`; iterate each non-empty file, route by extension, accumulate uploaded keys + failures
- [x] 12.10.2 Update Swagger `@Operation` and `@Parameter` descriptions to document multi-file behavior
- [x] 12.10.3 Update `IngestionControllerTest` — wrap existing single-file calls in `List.of(...)` and add a new `uploadDocument_ShouldUploadAllFiles_WhenMultipleProvided` test asserting all three (md, pdf, docx) routed correctly
- [ ] 12.10.4 Manual verification: from Bruno, send `rag ingestion upload` with three `file` rows; expect HTTP 200 with response body listing all three uploaded keys; confirm in MinIO console that all three files landed in the right folders

## 12.9 Bug 17 — RAG/memory-first system prompt

- [x] 12.9.1 Rewrite `app.system-prompt` in `application.yaml` to encode source priority (tool result > user memory > retrieved docs > training), abstain rule, citation conventions, parallel tool-use, prompt-injection defense in prose. No XML tag wrapping.
- [ ] 12.9.2 Manual verification: ask `frosty` (after a memory write turn) "What is my name and what do I do?" — response should ground the answer in user memory without announcing "I remember that...". Then ask a question outside the user's memory and corpus — response should abstain ("I don't have that in your notes") instead of guessing from training.

## 12.8 Bug 16 — Rename ingestion folder `obsidian/` → `markdown/`

- [x] 12.8.1 Rename Java field `obsidianFolder` → `markdownFolder` in `IngestionController`, `ManualIngestionService`, `IngestionPipelineConfig`
- [x] 12.8.2 Update `@Value` defaults from `obsidian/` to `markdown/` and config key from `app.ingestion.folders.obsidian` to `app.ingestion.folders.markdown`
- [x] 12.8.3 Update `application.yaml` `app.ingestion.folders` map key + value
- [x] 12.8.4 Update tests `IngestionControllerTest`, `ManualIngestionServiceTest` (`ReflectionTestUtils.setField` arg, S3 keys in fixtures, test-method names)
- [x] 12.8.5 Update `AscendAgent/README.md` folder routing table
- [ ] 12.8.6 Manual verification: rebuild AscendAgent, upload a `.md` file to `/api/v1/ingestion/upload`, confirm it lands at `s3://knowledge-base/markdown/<name>.md` (not `obsidian/`). Run `/api/v1/ingestion/run?prefix=markdown/&embeddingProvider=lmstudio` and verify the file is ingested.

## 12.7 Bug 15 — Ingestion controller URL prefix alignment

- [x] 12.7.1 Change `IngestionController` `@RequestMapping` from `/api/ingestion` to `/api/v1/ingestion` (hard cut, no alias)
- [x] 12.7.2 Update every doc that references the old path: `README.md`, `docs/INGESTION.md`, `docs/testing/rag.md`
- [ ] 12.7.3 Manual verification: rebuild AscendAgent, hit `POST /api/v1/ingestion/upload` and `POST /api/v1/ingestion/run` — both 200; old `/api/ingestion/*` returns 404

## 12.5 Bug 14 — AscendMemory truncates embeddings to collection dimension

- [x] 12.5.1 Pass `embedding_dims` from `PROVIDER_CONFIGS` into the mem0 `embedder.config` block in `AscendMemory/src/service/memory_client.py` alongside `model`, `api_key`, and `openai_base_url`. This makes the OpenAI-compatible embedder include a `dimensions` parameter in the embedding request, so providers like Gemini (`gemini-embedding-001`) truncate from their native 1536 to the configured collection size.
- [ ] 12.5.2 Manual verification: rebuild AscendMemory, run a prompt as `frosty` with `embeddingProvider=gemini`; AscendMemory log shows embedder calling `https://generativelanguage.googleapis.com/v1beta/openai/embeddings`; insert returns HTTP 200; Qdrant `ascend_memory_768` accepts the vector; agent log shows `Inserted N/N facts`.

## 13. Cross-cutting verification

- [ ] 13.1 Run `./gradlew test` — all new tests pass
- [ ] 13.2 Run `./gradlew build` — clean build
- [ ] 13.3 Smoke test: start docker-compose, run all four bug-report curls, confirm each returns 200 with the expected behavior. For bug-1, verify Qdrant `ascend_memory` is populated after request 1 and request 2 recalls Luke / software engineer
- [ ] 13.4 Smoke test (RAG): drop an `.md` into `knowledge-base/obsidian/`, call `POST /api/ingestion/run`, ask a question that should hit it, confirm RAG context is injected (logs show `RAG Context Injected: YES`)
- [ ] 13.5 Smoke test (security): attempt path-traversal filename and oversize upload — both rejected gracefully
- [ ] 13.6 Update `implementation_plan.md` Progress section as each task completes
