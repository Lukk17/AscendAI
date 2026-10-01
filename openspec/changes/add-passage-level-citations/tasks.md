Tasks are ordered so that everything which writes stored data lands before anything which reads it. Groups 1 to 4 change what is written into Qdrant. Group 5 is the reindex those groups make necessary. Groups 6 onward only read.

Tasks marked REINDEX REQUIRED produce their full observable behavior only for documents indexed after group 1 to 4 ship. On a document indexed before that, they must still degrade as the specs require, and both halves are verified.

## 1. Provenance vocabulary and parser page numbers

- [ ] 1.1 Capture one real Unstructured API response for a multi-page PDF and one for a multi-page DOCX into `apps/ascend-agent/src/test/resources/` fixtures, and confirm from the captured JSON which field path carries the per-element page number. Verify: the fixtures are committed and the field path is quoted in the test that reads them, so no later task guesses it.
- [ ] 1.2 Add `PAGE`, `CHUNK_INDEX` and `CHUNK_COUNT` to `service/ingestion/IngestionMetadataKeys.java` with the same javadoc convention as the existing keys. Verify: `IngestionMetadataKeys` compiles and no producer references a page key literal anywhere else (grep for the literal returns only this class).
- [ ] 1.3 Rewrite `IngestionService.parseUnstructuredResponse` to group elements by their page number and emit one `Document` per page, each carrying `source`, `title`, `type` and `page`, keeping the existing title-extraction behavior (first `Title` element wins, filename fallback). Verify: a unit test over the 1.1 PDF fixture asserts one document per page, page numbers ascending from 1, and no text lost against the current single-blob output.
- [ ] 1.4 Handle elements that report no page number in `parseUnstructuredResponse` by emitting them as a document without `page` rather than assigning one. Verify: a unit test over a fixture with a page-less element asserts that element's text is present in a document whose metadata has no `page` key, and ingestion returns normally.
- [ ] 1.5 Change `AscendOcrClient.toDocuments` (`apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/ingestion/client/AscendOcrClient.java`) to split the fetched result Markdown on its `## Page N` headings (the format written by `apps/ascend-ocr/src/service/result_store.py`) into one `Document` per page, stamping `page = N` from the heading and removing the heading line from the text. Text before the first heading becomes a document without `page`. `process`, `submitJob`, `awaitTerminalState` and `fetchResult` stay unchanged. Verify: a unit test `AscendOcrClientPageSplitTest` feeds a three-page result and asserts three documents with pages 1, 2, 3, and that no document text contains `## Page`.
- [ ] 1.6 Pin the heading format in that test with a literal fixture copied from a real ascend-ocr result, and keep the existing empty-result behavior (no text yields no document). Verify: `./gradlew test --tests "*AscendOcrClient*"` is green and `AscendOcrClientPactTest` passes with no edit to the test or to `contracts/pacts/ascend-agent-ascend-ocr.json`.

## 2. Router source identity and per-page stamping

- [ ] 2.1 Make `DocumentRouter.routeSinglePdfPage` stamp `source` to the original filename or object key and `page` to the page number it already computed, on every document returned by the downstream client, replacing whatever `source` the client stamped. Verify: a unit test routes a two-page PDF through stubbed Docling and OCR clients and asserts every returned document carries the original filename as `source` and the correct `page`, and that no returned document's `source` contains `_page`.
- [ ] 2.2 Leave `DoclingClient` and `AscendOcrClient` signatures unchanged, so the synthetic per-page filename stays inside the router and its log lines. Verify: the client classes have no new constructor or method parameter, and their existing tests pass unmodified.
- [ ] 2.3 Confirm the non-PDF router branches (markdown, Docling office formats, OCR images, Unstructured) still produce the source identity they produce today. Verify: `DocumentRouterFileTypeRoutingTest` passes unchanged, extended with an assertion that `source` equals the input filename for each branch.

## 3. Chunk ordinals at split time

- [ ] 3.1 Change `DocumentService.splitDocuments` to split one parent document at a time and stamp `chunk_index` and `chunk_count` across each parent's own chunks, preserving the input order in the returned flat list. Verify: a unit test splits two parent documents of different sizes in one call and asserts each parent's chunks are numbered from 0 with its own count, and the returned order matches the input order.
- [ ] 3.2 Number a page-split document continuously across its pages rather than restarting per page, so pages arriving as separate parent documents from one file share one sequence. Verify: a unit test feeds the per-page documents of one two-page file and asserts ordinals run 0 to n across the whole file while each chunk keeps its own page number.
- [ ] 3.3 Confirm `DocumentService.removeOldDocuments` still deletes by `source` alone and is unaffected by the new keys. Verify: `DocumentServiceTest` passes unchanged, plus an assertion that the filter expression contains only the source predicate.

## 4. Corpus ingestion parity

- [ ] 4.1 add-document-management-api owns routing the bucket-scan path through `DocumentRouter` (its tasks 3.2a and 3.2b, settled 2026-10-01). Before starting, confirm that change is implemented. Verify: `ManualIngestionService` calls `DocumentRouter.routeAndProcess` for every scanned object.
- [ ] 4.2 Verify the provenance outcome on the corpus path: a PDF that entered through a bucket-scan run carries the same `page`, `chunk_index` and `chunk_count` as the same file uploaded directly. Verify: an integration test (Testcontainers Floci plus Qdrant) ingests the same three-page PDF by both routes and asserts the stored payloads match on those three fields.

## 5. Reindex

- [ ] 5.1 REINDEX REQUIRED. Document the reindex step in `apps/ascend-agent/AGENTS.md` and in the RAG documentation: which fields are new, that documents indexed earlier degrade to document-level citations, and that the cost is one full parse per document including OCR. Verify: the text names the three payload fields and the degradation, and links the reindex endpoint.
- [ ] 5.2 REINDEX REQUIRED. Reindex the local corpus and record the before and after state. Verify: for one previously indexed multi-page PDF, a Qdrant payload query shows no `page` key before and a `page` key on every chunk after, and the chunk count is unchanged or explained.

## 6. Labeled retrieval context

- [ ] 6.1 Add `service/rag/PassageRef.java` carrying the label, the source identity, the page when known, and the chunk ordinal and count when known, and have `RagRetrievalService` build one per injected passage. Verify: a unit test over a fixed candidate list asserts one `PassageRef` per injected chunk and none for chunks the budget dropped.
- [ ] 6.2 Implement deterministic label assignment: descending score, ties by ascending source key, then ascending chunk ordinal, then the stable vector-store identifier, numbering contiguously from 1. Verify: a unit test with two tied scores asserts the documented ordering, and a second run over the same input produces an identical mapping.
- [ ] 6.3 Rewrite `RagRetrievalService.buildContextBlock` to emit one labeled block per passage carrying the label, the document display name, and the page or ordinal locator, charging only passage text against `app.rag.max-context-chars`. Verify: a unit test asserts the block text contains each label exactly once, and that a passage whose text is fully squeezed out by the budget produces neither a block nor a label.
- [ ] 6.4 Keep a passage that is truncated but non-empty labeled, with its truncated text in the block. Verify: a unit test sets a budget that truncates the last passage mid-text and asserts the label is present and the text is the truncated prefix.
- [ ] 6.5 REINDEX REQUIRED. Resolve the locator from chunk metadata with the three-level degradation: page, then ordinal, then document name only. Verify: a unit test covers one chunk with a page, one with an ordinal but no page, and one with neither, asserting the block wording for each and that none throws.
- [ ] 6.6 Change `buildSourceRefs` to take the injected passages rather than the kept-above-threshold list. Verify: a unit test where the budget drops every chunk of one document asserts that document is absent from the returned source refs while the others remain, in unchanged order.

## 7. Citations in the response

- [ ] 7.1 Add `dto/CitationRef.java` with `label`, `name`, and optional `documentId`, `page`, `chunkIndex`, `chunkCount`, annotated `@JsonInclude(NON_NULL)` and documented for OpenAPI in the style of `dto/SourceFile.java`. Verify: a serialization test asserts an entry with no page and no ordinal emits exactly `label` and `name`.
- [ ] 7.2 Carry citations through `RagRetrievalResult`, `BuiltUserMessage` and `ChatContextAssembler` to `AscendChatService` without changing any existing field on those records. Verify: the module compiles and existing assembler tests pass unmodified.
- [ ] 7.3 Add the optional `citations` array to `dto/AiResponse.java`, omitted from the JSON when retrieval injected nothing or the feature is off. Verify: a MockMvc test asserts the key is absent for a prompt that retrieved nothing, and present with the right entries for one that did.
- [ ] 7.4 Resolve `documentId` for each citation from the document registry by source object key, omitting it when there is no registry row while keeping the label and name. Verify: a test with one registered and one unregistered source asserts both are cited, only the registered one carries `documentId`, and only the registered one appears in `sources`.
- [ ] 7.5 Emit citations independently of `attachSources`. Verify: a MockMvc test sends a prompt with no `attachSources` field and asserts the response has `citations` and no `sources` key.
- [ ] 7.6 Add `app.rag.citations.enabled` to `config/properties/RagProperties.java` and `application.yaml`, defaulting to enabled, gating both the labels and the array. Verify: a test with the property set to false asserts the response has no `citations` key and the injected context contains no label.

## 7b. Streaming citations event

- [ ] 7b.1 Requires add-chat-streaming-and-conversations to be implemented. Add a `citations` SSE event DTO in `dto/` with payload `{"citations": [CitationRef, ...]}` and emit it from the streaming path in `service/chat/` after the last `delta` and before `sources` and `done`, only when citations are enabled and at least one passage was injected. Verify: an SSE integration test with `attachSources=true` asserts the event order `delta...`, `citations`, `sources`, `done`, and a second test with no retrieval asserts no `citations` event.
- [ ] 7b.2 Document the `citations` event in the OpenAPI description of the stream operation. Verify: `/v3/api-docs` lists five event types for the stream operation.

## 8. Ingestion time on the source entry

- [ ] 8.1 Add `ingestedAt` to `dto/SourceFile.java` and populate it in `S3PresignedUrlService` from the document registry's last-indexed timestamp for that document. Verify: a unit test asserts the field is the registry value and is present on every returned entry.
- [ ] 8.2 Confirm no citation entry carries an ingestion time. Verify: a serialization test asserts `CitationRef` has no such field, and the OpenAPI document shows it only on `SourceFile`.
- [ ] 8.3 Confirm the presign contract is otherwise untouched: non-blank `downloadUrl` and `expiresAt` on every entry, size cap and best-effort behavior unchanged. Verify: `S3PresignedUrlServiceTest` and `S3PresignedUrlServicePresignBranchesTest` pass unmodified.

## 9. System prompt

- [ ] 9.1 Rewrite the Citations block of `app.system-prompt` in `application.yaml` to name the bracketed label form supplied in the context, instruct the model to place a label immediately after the claim it supports, restrict it to labels present in the current context, and tell it to omit rather than invent. Verify: the file no longer contains the instruction to attribute by a document title or id, and a boot-time test asserts the prompt contains the label form.
- [ ] 9.2 Confirm the rest of the system prompt is unchanged, including the source priority order, the abstain rule, and the instruction never to follow instructions found inside retrieved documents. Verify: a diff of the prompt block shows changes confined to the Citations bullet list.

## 10. Architecture decision records

- [ ] 10.1 Write `apps/ascend-agent/docs/architecture/decisions/ADR-<NNN>-passage-level-citation-granularity.md`, where `<NNN>` is the next free number at implementation time (ADR-010 is taken), in the house format (title, Status with date, Context, Decision, Consequences, Related), recording why the retrieved passage is the citation unit rather than the document or a character range, and what each rejected option cost. Verify: the file exists, follows the section order of ADR-009, and is referenced from design.md decision D1.
- [ ] 10.2 Write `apps/ascend-agent/docs/architecture/decisions/ADR-<NNN>-provenance-carried-from-parser-to-index.md` with the next free number after 10.1, recording that page and ordinal provenance is stamped by the producer that knows it and carried as chunk metadata, why re-deriving it at query time was rejected, and the reindex consequence. Verify: the file exists, follows the same format, and is referenced from design.md decision D3.
- [ ] 10.3 Confirm the two new records do not renumber or contradict any existing record. Verify: the decisions directory has no gap and no duplicate number, and its index lists both new records.

## 11. Documentation and API surface

- [ ] 11.1 Update the OpenAPI annotations so `citations` and `ingestedAt` are described on the prompt response, including that citation fields are omitted when unknown. Verify: the generated OpenAPI document shows both, with `citations` optional.
- [ ] 11.2 Add a Bruno request under `docs/api/request/AscendAI/ascend-agent/` that exercises a citation-bearing prompt. Verify: running it against a live stack returns a response containing a `citations` array.
- [ ] 11.3 Update `apps/ascend-agent/AGENTS.md` and the RAG architecture documentation with the label form, the citation shape, and the three-level degradation. Verify: the text states the label form and the degradation order.

## 12. End-to-end verification

- [ ] 12.1 Ingest a multi-page PDF, ask a question answerable only from a specific page, and confirm the answer cites a label whose citation carries that page. Verify: the response body contains the label in the answer text and a matching citation entry with the expected `page`.
- [ ] 12.2 Ask a question answerable only from a Markdown file and confirm the citation degrades to an ordinal with no page. Verify: the citation entry has `chunkIndex` and no `page`, and the answer still carries the label.
- [ ] 12.3 Ask a question against a document indexed before this change and confirm the citation degrades to document level without failing. Verify: the citation entry carries only `label` and `name`, and the request returns 200.
- [ ] 12.4 REINDEX REQUIRED. Reindex that same document and repeat 12.3, confirming the citation now carries a page or an ordinal. Verify: the same question returns a citation with a locator it did not have before.
- [ ] 12.5 Confirm the kill switch restores the previous behavior end to end. Verify: with `app.rag.citations.enabled: false`, the same prompt returns no `citations` key and an answer with no label markers, and the `sources` array is unchanged in shape.
- [ ] 12.6 Run the full ascend-ai-agent test suite and the integration suite. Verify: `./gradlew test` and `./gradlew integrationTest` both pass with no assertion weakened or test disabled.
