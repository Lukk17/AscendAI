## Why

An answer grounded in the user's own documents cannot currently say where it came from. `RagRetrievalService.buildContextBlock` concatenates the raw text of every retrieved chunk inside a `<rag_context>` wrapper with no label of any kind, so the model receives an anonymous wall of text. The `source`, `title` and `type` metadata that would identify each chunk is present on every Qdrant point and is read a few lines later to build the `sources` array, yet it is never written into the text the model sees.

The system prompt in `apps/ascend-agent/src/main/resources/application.yaml` then asks the model to do something the context makes impossible: attribute inline with the document's title or id, for example `[doc: notes-2026]`, and never fabricate ids. No id is ever supplied, so a well-behaved model omits citations entirely and a badly-behaved one invents them. This is a live defect, not a design choice.

Page provenance is destroyed at ingestion even though every parser returns it. `IngestionService.parseUnstructuredResponse` iterates the Unstructured API's per-element array and appends each element's `text` into one `StringBuilder`, emitting a single `Document` per file with the per-element page number discarded. `AscendOcrClient` is job based (`process`, `submitJob`, `awaitTerminalState`, `fetchResult`, `toDocuments`): it fetches the job's result Markdown from object storage and `toDocuments` returns one `Document` for the whole file. The ascend-ocr service writes each page under a `## Page N` heading (`apps/ascend-ocr/src/service/result_store.py`), so the page number is present in the text but never reaches chunk metadata. `DocumentRouter.routePdfPerPage` does know the page number, but only encodes it into a synthetic filename (`filename + "_page" + n + ".pdf"`) that the parser clients then stamp as the chunk's `source`, which is both unusable as a locator and wrong as a source key. Separately, `ManualIngestionService.ingestObject`, the route that feeds the RAG corpus, does not call `DocumentRouter` today. add-document-management-api fixes that routing, and this change builds on it.

Source citation is the product's stated differentiator. Today the platform cannot do it at any granularity.

## What Changes

- Retrieved passages are labeled in the prompt. `buildContextBlock` emits one labeled block per injected chunk, carrying a short stable label, the document title, and a locator (page number where one exists), so the model has something real to cite and no reason to invent one.
- A new `citations` array on the prompt response resolves every label back to a real document and location: label, registry document id, display name, page when known, and the chunk's ordinal position within its document. Label assignment is deterministic from the retrieval result.
- The system prompt's Citations block is rewritten to name the label format the model is actually given, replacing the current instruction to cite an id that is never supplied.
- Page provenance survives ingestion on every parser path. Unstructured elements are grouped by `metadata.page_number` into one document per page, the ascend-ocr result Markdown is split inside `AscendOcrClient.toDocuments` on its `## Page N` headings into one document per page with `page = N` and the heading removed from the text, and `DocumentRouter` stamps the page number it already computes as structured metadata instead of burying it in a synthetic filename. The original object key stays the chunk's `source` on the per-page PDF path.
- Chunk ordinal metadata (`chunk_index` and `chunk_count`, scoped per parent document) is stamped during splitting, so a chunk from a page-less source such as a Markdown file or a scraped web page still has a locator.
- The corpus ingestion route gains the per-page treatment because add-document-management-api routes every bucket-scan object through `DocumentRouter` (its tasks 3.2a and 3.2b). That change owns the routing. This change adds only the provenance guarantee on top and verifies it on the corpus path.
- `SourceFile` gains `ingestedAt`, the instant the document's chunks were last written to the vector store, so a reader can judge whether an answer is stale. It is read from the document registry's last-indexed timestamp and sits on the source entry, not on the citation, because ingestion time is a property of the document and is identical for every passage inside it.
- Page and chunk-ordinal metadata are new payload fields on Qdrant points, and every chunk written after this change carries them (the page only when the source has pages). There is no reindex, backfill or compatibility handling for points written before this change. The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that there is no existing data to keep, and this holds only until the first real customer deployment. The owner wipes or re-ingests local data when he wants to.
- No existing field on `AiResponse.sources[*]` is renamed, removed, retyped, or moved. The presigned `downloadUrl` and its `expiresAt` stay exactly as they are.
- Citations are part of document search (`rag`), which belongs to the always-on core and is not a module (owner decision of 2026-10-03, `add-deployment-modules` D0): the citation parts of the retrieval path carry no `@ConditionalOnModule`, like the rest of it, and the labeled passages and their citations reach the chat path through the RAG `ChatContextContributor` of `add-deployment-modules` D6, which keeps the placement of retrieved context in one place. The import rule of `ModuleMarkingCoverageTest` checks only references from core classes to classes of switchable modules, so it does not apply here: both sides are core.

## Capabilities

### New Capabilities

- `rag-citations`: passage-level attribution end to end. Labeled retrieval context in the prompt, the `citations` array that resolves each label to a document and a location, deterministic label assignment, degradation when a chunk has no page, and the system-prompt contract that ties the two together.

### Modified Capabilities

- `rag-source-attachments`: `SourceFile` gains a mandatory `ingestedAt` instant. The requirement text carries forward the `documentId` and `contentPath` fields added by `add-document-management-api`, so this change is the second delta on that capability. `add-tenant-isolation` (company, build group 5) lands later and rebases its own delta of that capability on this text. Archive order is stated in design.md.
- `ingestion-correctness`: new requirements that page provenance survives from parser to index on every path that feeds the corpus, that the per-page PDF route stamps the original object key as `source` rather than the synthetic page filename, and that chunk ordinals are stamped at split time.

## Impact

- Affected code (ascend-ai-agent):
  - `service/rag/RagRetrievalService.java`: labeled context block, citation assembly, locator resolution.
  - `service/rag/RagRetrievalResult.java`, `SourceRef` (in the chat package since `add-deployment-modules`), plus new `service/rag/PassageRef.java` and `dto/CitationRef.java`: carry label, page and ordinal alongside the existing source identity.
  - `service/rag/S3PresignedUrlService.java` and `dto/SourceFile.java`: `ingestedAt` on the source entry.
  - `service/chat/AscendChatService.java`, `service/chat/ChatContextAssembler.java`, `BuiltUserMessage` and `SourceRef` (both moved out of `service/rag` into the chat package by `add-deployment-modules`), the RAG `ChatContextContributor` bean of that change, `dto/AiResponse.java`: thread citations from retrieval to the response.
  - `service/ingestion/IngestionService.java`, `service/ingestion/client/AscendOcrClient.java`, `service/ingestion/client/DoclingClient.java`, `service/ingestion/DocumentRouter.java`, `service/ingestion/DocumentService.java`, `service/ingestion/ManualIngestionService.java`, `service/ingestion/IngestionMetadataKeys.java`: page and ordinal provenance.
- Configuration: the `app.system-prompt` Citations block is rewritten in `apps/ascend-agent/src/main/resources/application.yaml`. There is no new setting and no compose variable: citations are always on, and a rollback is a revert of this change (answer 90 of 2026-10-08).
- End-to-end tests: new specs in `apps/ascend-agent/e2e/testing/` cover the citation fields, page provenance on every parser path, the join with `sources`, and one AI-run spec for the answer text citing the right label. Every spec except the AI-run one sends its prompts to the scripted model of the shared e2e harness, because it judges no wording. The deterministic Markdown spec also checks the citation prompt layout from the request log (Mockoon request log `GET /mockoon-admin/logs`) of the scripted model of the shared e2e harness of `close-agent-test-gaps` (its design D5 and task group 4) (owner answer 68.5 of 2026-10-04). The scripted model and the fake MCP server of that harness start only for deterministic tests, never for AI-run e2e specs (owner answer 70.4 of 2026-10-04).
- Stored data: Qdrant points gain `page`, `chunk_index` and `chunk_count` payload fields. Points written before this change are not migrated and not supported (owner decision of 2026-10-02, confirmed by owner answer 73.1 of 2026-10-06, valid until the first real customer deployment).
- API: `AiResponse` gains an optional `citations` array and `SourceFile` gains `ingestedAt`. Both are additive.
- Architecture documentation: two new records under `apps/ascend-agent/docs/architecture/decisions/`, each taking the next free number at implementation time (ADR-010 is already taken by the MCP tool listing cache record).
- Dependencies: none new.
- Sibling coordination: `add-document-management-api` (registry document id, `contentPath`, bucket-scan routing), `add-chat-streaming-and-conversations` (this change owns the streaming `citations` event, sent before `sources` and before `done`), `add-deployment-modules` (the module list in which `rag` is core, and the `ChatContextContributor` port), and `close-agent-test-gaps` (the scripted model of its design D5 whose request log the prompt layout check reads, the way its provider error spec of design D6 and task group 5 reads it). `add-tenant-isolation` (company, build group 5) adds its tenant filter on retrieval and its tenant-scoped presign later, on top of this change. This change does not wait for it.
- Contract test: `AscendOcrClientPactTest` must keep passing unchanged. The page split happens after the result Markdown is fetched, so the HTTP interactions the pact records do not change.

## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 4 (personal), position 15. It needs `close-agent-test-gaps` (the scripted model harness of its design D5 and task group 4, for the prompt layout check), `upgrade-spring-boot-4` (Spring Boot 4 and Spring AI 2 on the chat and retrieval path it edits), `add-deployment-modules` (the module list in which `rag` is core, and the `ChatContextContributor` port that carries the labeled context), `add-document-management-api` (the document registry, `documentId`, `contentPath` and the bucket-scan routing) and `add-chat-streaming-and-conversations` (the stream that carries the `citations` event), which all land earlier. It adds no error case, so the RFC 7807 problem detail of `upgrade-spring-boot-4` needs nothing new here. `add-flutter-chat-app` (build group 4, position 17) shows the citations later. `add-tenant-isolation` (company, build group 5) adds its tenant filter and rebases its `rag-source-attachments` delta on this change later. This change does not wait for it.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/architecture-decision-records`
- `/tdd-workflow`
- `/postgres-patterns`
- `/coding-standards`
