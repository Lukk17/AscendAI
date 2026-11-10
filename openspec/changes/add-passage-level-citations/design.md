## Context

See proposal.md, "Why", for the motivation and the three defects this change closes. What follows is only the state that shapes the approach.

Retrieval today runs in `RagRetrievalService.retrieve`. It asks Qdrant for `topK` candidates with the similarity threshold pinned to `0.0`, then filters in Java against `app.rag.similarity-threshold` so the near-miss scores stay visible in the logs. The kept list feeds two independent consumers: `buildContextBlock`, which concatenates raw chunk text under a `<rag_context>` wrapper until `app.rag.max-context-chars` runs out, and `buildSourceRefs`, which reads `bucket`, `key`, `displayName`, `mimeType`, `source` and `title` from the same chunks and deduplicates per object. The two disagree today: a chunk dropped by the character budget still contributes a `SourceRef`.

Chunk metadata is stamped by four producers. `IngestionService.processMarkdown` and `parseUnstructuredResponse` stamp `source`, `title`, `type`. `DoclingClient` and `AscendOcrClient` stamp `source` and `type` only. The shared key names live in `IngestionMetadataKeys`. `DocumentService.splitDocuments` runs Spring AI's `TokenTextSplitter` over the whole batch at once and returns a flat list, which copies parent metadata onto each chunk but adds nothing that identifies the chunk's position.

Two ingestion routes exist and they are not equivalent. The prompt-attachment route (`DocumentIngestionService`) calls `DocumentRouter`, which does extension-based routing including a per-page PDF split, but its output is never indexed. The corpus route (`ManualIngestionService.ingestObject`) indexes, but branches only on markdown versus unstructured and never reaches the router. Where the router does split pages, it labels each request with a synthetic filename (`filename + "_page" + n + ".pdf"`) that the parser clients then stamp as the chunk's `source`, so routing that path into the corpus as it stands would poison both `DocumentService.removeOldDocuments` (which deletes by `source ==`) and source presigning (which looks up the object by key).

`add-deployment-modules` (build group 3, position 6 of the owner build order of 2026-10-04) changes the chat path this change threads citations through. `ChatContextAssembler` stops importing `RagRetrievalService` and takes a list of `ChatContextContributor` beans instead, `RagRetrievalService` provides the contributor of document search (`rag`, part of the core), each contributor returns blocks with the sources it cites, and `BuiltUserMessage` and `SourceRef` move out of `service/rag` into the chat package of `core-chat`. The labeled context and its citations of this change ride on that contributor (D10).

Two other changes delta the same capability this one does and are not yet archived: `add-document-management-api` (build group 3, position 8, lands earlier: document registry, `documentId` and `contentPath` on `SourceFile`, bucket-scan routing) and `add-tenant-isolation` (company, build group 5, lands later: tenant filter on every search, tenant-prefix check on every presign).

## Goals / Non-Goals

Goals:

- A label in the prompt that the model can cite cheaply and that resolves deterministically to one document and one location inside it.
- Provenance that is carried, not reconstructed: whatever the parser knew about a page reaches the vector store, and whatever the vector store holds reaches the response.
- Graceful degradation from page to ordinal for sources without pages. Never a failure and never a fabricated location.
- Composition with the two other changes on the same capability that is stated, not assumed.

Non-Goals:

- Character offsets or bounding boxes inside a page. See D1.
- Verifying after the fact that the model's inline labels are honest. The response guarantees that every label it issued resolves. It does not police the generated text.
- Highlighting the cited span inside the downloaded file, or deep-linking a viewer to a page.
- Any reindex, backfill or compatibility handling for points indexed before this change. See the migration plan.
- Retrieval quality: scoring, chunk sizing, reranking and the threshold are all untouched.

## Decisions

### D1. Citation granularity is the retrieved passage, not the document and not a character range

A citation names the chunk that was actually injected, identified by its document plus its page and its ordinal within that document.

Document-level attribution was the cheap option and is what the `sources` array already does. It fails the owner's actual requirement: a reader given a 200-page handbook and told the answer came from that handbook cannot check the claim. Character-level attribution, meaning a start and end offset into the source file, was rejected on three counts. Offsets into the original file do not survive parsing, since the text the model saw came out of Docling or an OCR engine and does not sit at a known offset in the PDF's byte stream. Offsets would be invalidated by every re-parse, so a router improvement would silently break every stored citation. And the model cannot be trusted to reproduce an exact span, so the offsets would have to be inferred from generated text, which is a second guessing problem stacked on the first.

The passage is the natural unit because it is exactly the unit of evidence: it is what was retrieved, what was scored, and what the model actually read. It is also the only unit that is stable under re-parse, since page numbers and ordinals are re-derived by the same pipeline that produced them.

This decision is recorded as an ADR taking the next free number in `apps/ascend-agent/docs/architecture/decisions/` at implementation time.

### D2. The label is `S` plus an integer, assigned per response

The label form is `[S1]`, `[S2]` and so on. It is two or three tokens inline, it does not collide with prose numbers or with Markdown footnote syntax the way a bare `[1]` does, and it is short enough that a model citing six passages in one answer spends a negligible share of its output on labels.

Alternatives considered. A bare `[1]` is shorter but ambiguous against ordinary numbering in the answer text. The document title (`[doc: notes-2026]`, which is what the system prompt asks for today) is long, is not unique across a corpus, and changes when a file is renamed. A chunk UUID is unique and stable but costs many tokens per citation and invites transcription errors. A composite such as `[handbook.pdf p12]` is self-describing but long, and it duplicates into the answer text data that the `citations` array already carries.

Labels are scoped to a single response and assigned by descending score with a deterministic tie-break, so the same retrieval result always yields the same mapping. They are not stable across responses, which is stated in the spec so no caller builds a cache on them.

### D3. Provenance is carried as chunk metadata, from the parser that knew it to the index

Each parser that knows a page number stamps it on the document it emits, and the splitter stamps the ordinal. `IngestionMetadataKeys` gains `PAGE`, `CHUNK_INDEX` and `CHUNK_COUNT` alongside the existing `SOURCE`, `TITLE` and `TYPE`, so the vocabulary stays in one place.

Concretely: the Unstructured path groups elements by their reported page number and emits one document per page instead of one per file. The OCR path splits the result Markdown inside `AscendOcrClient.toDocuments` on its `## Page N` headings (written by `apps/ascend-ocr/src/service/result_store.py`): one document per heading, `page = N`, and the heading line itself removed from the chunk text. Text before the first heading, if any, becomes a document without `page`. A unit test pins the heading format, so a change on the ascend-ocr side fails loudly. `AscendOcrClientPactTest` is not touched, because the split runs after the HTTP exchange the pact covers. `DocumentRouter` stamps the page number it computes when it slices the PDF, overwriting whatever the downstream client stamped rather than parsing it back out of the synthetic filename.

Alternative considered: reconstruct the page at query time by re-parsing the source object and locating the chunk text in it. Rejected outright. It re-runs OCR or Docling on every answer, it is fuzzy matching rather than a fact, and it produces a different answer after any parser upgrade.

Alternative considered: keep one document per file and store a page map, meaning a list of character ranges to page numbers, in that document's metadata. Rejected because the splitter would then need to interpret the map to decide each chunk's page, which puts parsing knowledge into the splitter and breaks the moment a parser emits pages out of order.

This decision is recorded as an ADR taking the next free number after the D1 record at implementation time.

### D4. The router owns the source identity for per-page work

`DocumentRouter` restamps `source` to the original filename or object key on every document its per-page path produces, so the synthetic per-page filename never leaves the router. That name stays useful where it belongs, in the conversion request and the log line.

The alternative of passing both the real name and the page number down into `DoclingClient` and `AscendOcrClient` was rejected. It widens two client signatures for the benefit of one caller, and it puts knowledge of a PDF page split into clients that also serve single-file calls where there is no page.

### D5. Ordinals are stamped by splitting per parent document, not over the batch

`DocumentService.splitDocuments` currently hands the whole list to `TokenTextSplitter` at once and gets a flat list back, which loses the parent link. It will instead split one parent document at a time, then stamp ordinals across the concatenation of that parent's chunks, so a document split into pages first gets one continuous sequence rather than a per-page one. A per-page sequence would make ordinal 2 ambiguous across a ten-page file.

This costs one splitter invocation per parent document instead of one per batch. The splitter is pure CPU over already-loaded text, so the cost is noise next to the OCR and conversion calls that precede it.

### D6. Ingestion time lives on the source entry and comes from the registry

`SourceFile` gains `ingestedAt`, read from the document registry row that `add-document-management-api` introduces (its last-indexed timestamp).

It belongs on the source entry rather than on the citation because it is a property of the document: every passage in a document was indexed by the same run, so putting it on the citation would repeat one value across every citation of that document and imply a passage-level freshness that does not exist.

It comes from the registry rather than from chunk metadata for two reasons. The registry already owns that fact, so stamping it onto every chunk as well would give one fact two sources of truth. And a max taken over the retrieved chunks is not the document's index time, only the index time of the chunks that happened to come back, so it would be wrong exactly when a document was partially reindexed.

Alternative considered: stamp `ingested_at` on each chunk and take the maximum. Rejected on both counts above, and it would add a third payload field for no gain.

### D7. Citations are not gated on `attachSources`

The inline labels and the `citations` array ship together, always on, independent of the `attachSources` request flag. There is no setting that turns them off (answer 90 of 2026-10-08).

Gating the array on `attachSources` was considered because it would keep the default response byte-identical. It was rejected: the labels appear in the answer text whenever retrieval grounded the answer, so gating the resolution table on an unrelated download-link flag would leave a caller holding `[S1]` in the prose with nothing to resolve it against. The marker and its table are one feature and ship as one.

The consequence is an intentional, additive change to the default response shape: a new optional `citations` key, absent when retrieval injected nothing. The earlier kill switch `app.rag.citations.enabled` and its compose variable `APP_RAG_CITATIONS_ENABLED` existed mainly so an end-to-end spec could recreate the agent with citations off. Answer 90 of 2026-10-08 removes both: no test-only setting lives in service configuration, and an operator who needs the old shape reverts the change.

### D8. `sources` is derived from the injected passages

`buildSourceRefs` moves from operating on the kept-above-threshold list to operating on the passages that were actually injected. Today a chunk dropped by the character budget still produces a source entry, so the response can offer a download for a document that contributed nothing to the answer. Once `citations` exists, that divergence becomes visible as a source with no citation, which reads as a bug to any caller.

This narrows the `sources` array in one case only, and only to documents that did not influence the answer.

### D9. Composition with the two other changes on the capability, and the archive order

Archive order (owner build order of 2026-10-04, build group 4, position 15): archive this change right after its real dependencies, `add-document-management-api` and `add-chat-streaming-and-conversations`, which land earlier. `add-tenant-isolation` is company work of build group 5 and lands later, so it rebases its own `rag-source-attachments` delta on this change's text. This change does not wait for it. (The earlier recommendation of this decision to archive `add-tenant-isolation` before this change is superseded by the owner build order of 2026-10-04.)

`add-document-management-api` first, because this change consumes three of its outputs. Its document registry supplies the `documentId` a citation carries and the last-indexed timestamp `ingestedAt` reads. Its `SourceFile` amendment adds `documentId` and `contentPath`, and this change's `SourceFile` delta carries that text forward and adds `ingestedAt` on top, which is only correct if theirs landed first. Its requirement that every bucket-scanned object is routed through `DocumentRouter` is the routing half of the corpus provenance fix, which this change asserts the metadata outcome of rather than re-specifying.

This change second. On the `rag-source-attachments` capability it modifies `SourceFile DTO shape`, which `add-document-management-api` also modifies, so it is written against their text and applied after it. It also modifies `De-duplication by source object identity`, which neither other change touches. On `ingestion-correctness` it only adds requirements, with names distinct from both other changes', so nothing collides. Its new `rag-citations` capability collides with nothing.

`add-tenant-isolation` later. It modifies a different requirement in the same capability (the presign requirement) and adds a tenant filter to retrieval. There is no textual overlap with this change's deltas, so it writes its delta against the text this change leaves, and its tenant filter wraps the retrieval path that already attaches labels. No scenario of this change depends on it.

If the order with `add-document-management-api` changes, the concrete consequence is bounded and named: this change's `SourceFile DTO shape` delta must be re-edited to drop `documentId` and `contentPath`, `documentId` must become optional on every citation, `ingestedAt` needs another source, and the routing half of the corpus fix must be pulled into this change's tasks.

The streaming sibling, `add-chat-streaming-and-conversations`, emits a `sources` event with the same `SourceFile` shape. This change owns the matching `citations` event on the streaming endpoint. Its payload is `{"citations": [CitationRef, ...]}` with the same shape as the synchronous array, it is emitted at most once, after the last `delta` and before `sources` and `done`, and only when retrieval injected at least one passage.

### D10. Citations belong to document search, part of the core, and reach the chat path through its contributor

Document search (`rag`) is part of the always-on core, not a module (owner decision of 2026-10-03, `add-deployment-modules` D0), and the citations are part of it. `PassageRef`, the label assignment, the labeled context block and the citation assembly live in `RagRetrievalService` and the classes of `service/rag/`, which carry no `@ConditionalOnModule`, like the rest of the retrieval path. The RAG `ChatContextContributor` returns the labeled block for the user message together with its sources and its citations, and `ChatContextAssembler` passes the citations to `AscendChatService` without knowing where they came from. `CitationRef` is a response DTO in `dto/` next to `AiResponse` and `SourceFile`. The import rule of `ModuleMarkingCoverageTest` (`add-deployment-modules` D6) checks only references from core classes to classes of switchable modules, and both the chat path and document search are core, so the rule does not apply to them and needs no entry for this change. This change adds no setting. A turn whose retrieval injected nothing has no label in the injected context, no `citations` key in the response and no `citations` event in the stream.

## Risks / Trade-offs

- Labeled blocks add prompt tokens, roughly one short line per injected passage, and the character budget is spent on labels rather than text. Mitigation: the label form is deliberately terse, and the budget accounting counts only passage text so a label never silently evicts content.
- The model may cite badly: labels on the wrong claim, or a label it invented. Mitigation on the invented-label half is that the array is complete for the passages injected, so an unresolvable label is detectable by the caller. The wrong-claim half is a model-quality matter this change does not attempt to police, and the non-goals say so.
- Splitting per parent document changes the chunk boundaries produced for a multi-document batch, so chunk text after this change is not guaranteed identical to before. Mitigation: this only affects batches, and chunk content is not part of any spec contract.
- Emitting one document per page makes very short pages produce very short chunks, which embed poorly. Mitigation: the splitter's existing minimum-chunk settings already apply per document, and the effect is measured on a real multi-page PDF as part of the verification for that task rather than assumed away.

## Migration Plan

1. Ship the ingestion-side changes (page metadata, source restamping, ordinals) and the retrieval and response changes. From this point every chunk written carries the new payload fields and every answer is labeled.
2. No reindex, no payload backfill and no handling of points that lack the new fields. The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep, and this holds only until the first real customer deployment. Points indexed before this change are not supported, and the owner wipes the Qdrant collections or re-ingests documents when he wants to. After the first real customer deployment, a change to stored payload plans its own migration.
3. Rollback is a revert of this change and a new deployment (answer 90 of 2026-10-08), which removes the labels and the `citations` key and restores the previous response shape. It restores no data. The page and ordinal payload fields written in the meantime stay on the points and are ignored by the previous code.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. This change keeps its rule that points indexed before it are not supported, and it starts from empty stores.

## Owner decisions of 2026-10-07

Answer 75.1 (review of the group 3, 4 and 5 changes of 2026-10-07, fix of all 75 items approved): items 8, 32 and 38 are fixed here. Item 8: task 6b.2 expects eight event types on the stream, the seven of `add-chat-streaming-and-conversations` D2 and `citations`. Item 32: document search (`rag`) is part of the core, not a module, and the import rule of `ModuleMarkingCoverageTest` does not apply to citations because both sides are core (proposal and D10). Item 38: specs 11.2 to 11.6 judge no wording and run on the scripted model of `close-agent-test-gaps`, and only 11.7 stays AI-run.

## Owner decisions of 2026-10-08

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/citations/`, its vector files in `apps/ascend-agent/e2e/fixtures/scripted-model/embeddings/citations/` (task 11.1, spec `rag-citations`). Every check that read the request journal now reads the scripted model's request log, `GET /mockoon-admin/logs` of the Mockoon admin API, and clears it with `POST /mockoon-admin/state/purge`.

Answer 76.3: the citation files go to `responses/citations/` and `embeddings/citations/` under `apps/ascend-agent/e2e/fixtures/scripted-model/`.

Answer 77.1: every scripted vector is 1536 long, because the provider `scripted` sends the embedding provider name `openai`, which the e2e overlay points at the scripted model.

Answer 78.1: the provider `scripted` uses `default-embedding: openai`, and the deterministic phase overlay points the agent's own embedding entry `openai` at Mockoon. There is no separate scripted embedding entry, and every vector file of this change is 1536 long (`ascendai-1536` and `ascend_memory_1536`).

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (tasks 11.1, 11.2, 11.4, 11.5 and 11.6).

Answer 85.1: no plan text of this change exports a key or a secret in a shell. The AI-run spec of task 11.7 takes its hosted provider key from the existing Bruno rows, which read the repository `.env`. Nothing changes here.

Answer 86.1: where the integration test of task 4.2 needs an HTTP fake (the parser or the embedding provider), its Mockoon container loads the same shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json` that the deterministic phase uses (task 4.2).

Answer 87 (rule R1, several agent instances): confirmed. Labels, citations and the `citations` event are computed per request on the instance that serves it from the retrieval result, and provenance is stored on the Qdrant points and the registry rows. This change keeps no state, lock, queue or cache in memory, so a second agent instance changes nothing.

Answer 90: the setting `app.rag.citations.enabled` and the compose variable `APP_RAG_CITATIONS_ENABLED` are removed. Citations are always on, and the rollback is a revert of the change (proposal, D7, D9, D10, the migration plan, the `rag-citations` and `rag-source-attachments` specs). Task 6.6 (the setting), task 11.6 (the spec that recreated the agent with citations off) and task 11.8 (the compose variable) are removed.

Answer 91.1: in the deterministic phase AscendMemory is faked in the one Mockoon container under `/ascend-memory/`, only the agent restarts for the phase, and no deterministic spec wipes memories. The memory wipes of specs 11.1, 11.2 and 11.4 are removed, and the approved fix of 2026-10-08 above no longer applies to them. The AI-run spec 11.7 uses the real AscendMemory.

Answer 91.3: corpus parity between an uploaded and a bucket-scanned file is proven once, by the integration test of task 4.2, so spec 11.2 indexes by upload only. The stream event spec of task 11.5 is removed, because the SSE integration test of task 6b.1, now also comparing the event with the synchronous response, proves the same. Specs 11.1 to 11.4 and the AI-run spec 11.7 stay.

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 98 (owner rule 98, every value with a default is a setting): checked every value of this change. It adds no setting and plans no operational value of its own, so no compose line is added. It reads the existing settings `app.rag.max-context-chars`, `app.rag.similarity-threshold`, `app.rag.top-k` and the `app.ingestion.token-splitter.*` group unchanged, whose rows and compose lines come from the inventory of `fix-linux-docker-host-access`. It changes the default text of the existing setting `app.system-prompt` (task 8.1), so new task 10.4 updates that row of `apps/ascend-agent/docs/CONFIGURATION.md` in the same commit. The prompt stays in `application.yaml` and is not written as a compose default, because it is a text of many lines (listed for the owner in the round report). Kept as constants, because they are not operational: the label form `S<n>` and its bracket form `[S<n>]` (a format the model and the caller read), the payload keys `page`, `chunk_index` and `chunk_count` and the other `IngestionMetadataKeys` names, the `## Page N` heading format of ascend-ocr (a format the unit test of task 1.6 pins), the stream event name `citations`, the label order rule of D2, and the separator characters of the token splitter in `DocumentService` (a text format rule, not a tuning value). No test or measurement of this change uses LM Studio: the deterministic specs use the provider `scripted`, and the AI-run spec 11.7 uses a hosted provider of the existing Bruno rows.

Answer 98.1: the deterministic specs 11.1, 11.2 and 11.4 run in the deterministic phase of `close-agent-test-gaps` D7, in which the test settings reach the running agent by a copy of `apps/ascend-agent/e2e/overlay/application-e2e.yaml` into `/app/config/application.yaml` and a restart, and the phase ends with a recreate of the agent. There is no `e2e` profile any more. Task 11.10 cites D7 instead of the earlier allowlist shape for recreating the agent with an environment override, which belonged to the removed spec 11.6.

## Open Questions

1. Settled 2026-10-01: add-document-management-api owns the bucket-scan routing through `DocumentRouter`. Its design D5 now states it.
2. Settled 2026-10-01: this change owns the streaming `citations` event (see the streaming paragraph above).
3. The archived `rag-retrieval` spec states that the similarity threshold is applied server-side in the `SearchRequest`, while the code deliberately passes `0.0` and filters in Java so near-miss scores stay loggable. This change relies on the Java-side filtering only to the extent that it needs the kept list in score order, which both variants provide, so it is not blocked either way. Closed (owner decision 65.22 of 2026-10-04): knowledge search keeps the Java score filter, and `add-tenant-isolation` corrects the old `rag-retrieval` requirement in its `rag-retrieval` delta (task 5.3a there).
