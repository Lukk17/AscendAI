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
- REINDEX REQUIRED: page and chunk-ordinal metadata are new payload fields on Qdrant points. Documents indexed before this change carry none of them and degrade to a document-level citation with no page and no ordinal until they are reindexed. Every task that depends on reindexing is marked in tasks.md.
- No existing field on `AiResponse.sources[*]` is renamed, removed, retyped, or moved. The presigned `downloadUrl` and its `expiresAt` stay exactly as they are.

## Capabilities

### New Capabilities

- `rag-citations`: passage-level attribution end to end. Labeled retrieval context in the prompt, the `citations` array that resolves each label to a document and a location, deterministic label assignment, degradation when a chunk has no page, and the system-prompt contract that ties the two together.

### Modified Capabilities

- `rag-source-attachments`: `SourceFile` gains a mandatory `ingestedAt` instant. The requirement text carries forward the `documentId` and `contentPath` fields added by `add-document-management-api`, so this change is the third and last delta on that capability. Archive order is stated in design.md.
- `ingestion-correctness`: new requirements that page provenance survives from parser to index on every path that feeds the corpus, that the per-page PDF route stamps the original object key as `source` rather than the synthetic page filename, and that chunk ordinals are stamped at split time.

## Impact

- Affected code (ascend-ai-agent):
  - `service/rag/RagRetrievalService.java`: labeled context block, citation assembly, locator resolution.
  - `service/rag/RagRetrievalResult.java`, `service/rag/SourceRef.java`, plus new `service/rag/PassageRef.java` and `dto/CitationRef.java`: carry label, page and ordinal alongside the existing source identity.
  - `service/rag/S3PresignedUrlService.java` and `dto/SourceFile.java`: `ingestedAt` on the source entry.
  - `service/chat/AscendChatService.java`, `service/chat/ChatContextAssembler.java`, `service/rag/BuiltUserMessage.java`, `dto/AiResponse.java`: thread citations from retrieval to the response.
  - `service/ingestion/IngestionService.java`, `service/ingestion/client/AscendOcrClient.java`, `service/ingestion/client/DoclingClient.java`, `service/ingestion/DocumentRouter.java`, `service/ingestion/DocumentService.java`, `service/ingestion/ManualIngestionService.java`, `service/ingestion/IngestionMetadataKeys.java`: page and ordinal provenance.
- Configuration: the `app.system-prompt` Citations block is rewritten in `apps/ascend-agent/src/main/resources/application.yaml`, and new `app.rag.citations.*` keys are bound through `config/properties/RagProperties.java`.
- Stored data: Qdrant points gain `page`, `chunk_index` and `chunk_count` payload fields. Existing points are not migrated in place, so a reindex is required to populate them.
- API: `AiResponse` gains an optional `citations` array and `SourceFile` gains `ingestedAt`. Both are additive.
- Architecture documentation: two new records under `apps/ascend-agent/docs/architecture/decisions/`, each taking the next free number at implementation time (ADR-010 is already taken by the MCP tool listing cache record).
- Dependencies: none new.
- Sibling coordination: `add-document-management-api` (registry document id, `contentPath`, bucket-scan routing), `add-tenant-isolation` (tenant filter on retrieval, tenant-scoped presign), and `add-chat-streaming-and-conversations` (this change owns the streaming `citations` event, sent before `sources` and before `done`).
- Contract test: `AscendOcrClientPactTest` must keep passing unchanged. The page split happens after the result Markdown is fetched, so the HTTP interactions the pact records do not change.

## Build order

Third in group D: add-document-management-api, then add-chat-streaming-and-conversations, then this change, then add-flutter-chat-app.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/architecture-decision-records`
- `/tdd-workflow`
- `/postgres-patterns`
- `/coding-standards`
