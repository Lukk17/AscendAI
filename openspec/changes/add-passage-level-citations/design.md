## Context

See proposal.md, "Why", for the motivation and the three defects this change closes. What follows is only the state that shapes the approach.

Retrieval today runs in `RagRetrievalService.retrieve`. It asks Qdrant for `topK` candidates with the similarity threshold pinned to `0.0`, then filters in Java against `app.rag.similarity-threshold` so the near-miss scores stay visible in the logs. The kept list feeds two independent consumers: `buildContextBlock`, which concatenates raw chunk text under a `<rag_context>` wrapper until `app.rag.max-context-chars` runs out, and `buildSourceRefs`, which reads `bucket`, `key`, `displayName`, `mimeType`, `source` and `title` from the same chunks and deduplicates per object. The two disagree today: a chunk dropped by the character budget still contributes a `SourceRef`.

Chunk metadata is stamped by four producers. `IngestionService.processMarkdown` and `parseUnstructuredResponse` stamp `source`, `title`, `type`. `DoclingClient` and `AscendOcrClient` stamp `source` and `type` only. The shared key names live in `IngestionMetadataKeys`. `DocumentService.splitDocuments` runs Spring AI's `TokenTextSplitter` over the whole batch at once and returns a flat list, which copies parent metadata onto each chunk but adds nothing that identifies the chunk's position.

Two ingestion routes exist and they are not equivalent. The prompt-attachment route (`DocumentIngestionService`) calls `DocumentRouter`, which does extension-based routing including a per-page PDF split, but its output is never indexed. The corpus route (`ManualIngestionService.ingestObject`) indexes, but branches only on markdown versus unstructured and never reaches the router. Where the router does split pages, it labels each request with a synthetic filename (`filename + "_page" + n + ".pdf"`) that the parser clients then stamp as the chunk's `source`, so routing that path into the corpus as it stands would poison both `DocumentService.removeOldDocuments` (which deletes by `source ==`) and source presigning (which looks up the object by key).

Two sibling changes delta the same capability this one does and are not yet archived: `add-document-management-api` (document registry, `documentId` and `contentPath` on `SourceFile`, bucket-scan routing) and `add-tenant-isolation` (tenant filter on every search, tenant-prefix check on every presign).

## Goals / Non-Goals

Goals:

- A label in the prompt that the model can cite cheaply and that resolves deterministically to one document and one location inside it.
- Provenance that is carried, not reconstructed: whatever the parser knew about a page reaches the vector store, and whatever the vector store holds reaches the response.
- Graceful degradation at three levels: page, then ordinal, then document. Never a failure and never a fabricated location.
- Composition with the two pending siblings that is stated, not assumed.

Non-Goals:

- Character offsets or bounding boxes inside a page. See D1.
- Verifying after the fact that the model's inline labels are honest. The response guarantees that every label it issued resolves. It does not police the generated text.
- Highlighting the cited span inside the downloaded file, or deep-linking a viewer to a page.
- Automatic backfill of already-indexed documents. See the migration plan.
- Retrieval quality: scoring, chunk sizing, reranking and the threshold are all untouched.

## Decisions

### D1. Citation granularity is the retrieved passage, not the document and not a character range

A citation names the chunk that was actually injected, identified by its document plus its page and its ordinal within that document.

Document-level attribution was the cheap option and is what the `sources` array already does. It fails the owner's actual requirement: a reader given a 200-page handbook and told the answer came from that handbook cannot check the claim. Character-level attribution, meaning a start and end offset into the source file, was rejected on three counts. Offsets into the original file do not survive parsing, since the text the model saw came out of Docling or an OCR engine and does not sit at a known offset in the PDF's byte stream. Offsets would be invalidated by every re-parse, so a router improvement would silently break every stored citation. And the model cannot be trusted to reproduce an exact span, so the offsets would have to be inferred from generated text, which is a second guessing problem stacked on the first.

The passage is the natural unit because it is exactly the unit of evidence: it is what was retrieved, what was scored, and what the model actually read. It is also the only unit that is stable under re-parse, since page numbers and ordinals are re-derived by the same pipeline that produced them.

This decision is recorded as ADR-010.

### D2. The label is `S` plus an integer, assigned per response

The label form is `[S1]`, `[S2]` and so on. It is two or three tokens inline, it does not collide with prose numbers or with Markdown footnote syntax the way a bare `[1]` does, and it is short enough that a model citing six passages in one answer spends a negligible share of its output on labels.

Alternatives considered. A bare `[1]` is shorter but ambiguous against ordinary numbering in the answer text. The document title (`[doc: notes-2026]`, which is what the system prompt asks for today) is long, is not unique across a corpus, and changes when a file is renamed. A chunk UUID is unique and stable but costs many tokens per citation and invites transcription errors. A composite such as `[handbook.pdf p12]` is self-describing but long, and it duplicates into the answer text data that the `citations` array already carries.

Labels are scoped to a single response and assigned by descending score with a deterministic tie-break, so the same retrieval result always yields the same mapping. They are not stable across responses, which is stated in the spec so no caller builds a cache on them.

### D3. Provenance is carried as chunk metadata, from the parser that knew it to the index

Each parser that knows a page number stamps it on the document it emits, and the splitter stamps the ordinal. `IngestionMetadataKeys` gains `PAGE`, `CHUNK_INDEX` and `CHUNK_COUNT` alongside the existing `SOURCE`, `TITLE` and `TYPE`, so the vocabulary stays in one place.

Concretely: the Unstructured path groups elements by their reported page number and emits one document per page instead of one per file. The OCR path emits one document per entry in the `pages` array, using the `page_number` that service already returns. `DocumentRouter` stamps the page number it computes when it slices the PDF, overwriting whatever the downstream client stamped rather than parsing it back out of the synthetic filename.

Alternative considered: reconstruct the page at query time by re-parsing the source object and locating the chunk text in it. Rejected outright. It re-runs OCR or Docling on every answer, it is fuzzy matching rather than a fact, and it produces a different answer after any parser upgrade.

Alternative considered: keep one document per file and store a page map, meaning a list of character ranges to page numbers, in that document's metadata. Rejected because the splitter would then need to interpret the map to decide each chunk's page, which puts parsing knowledge into the splitter and breaks the moment a parser emits pages out of order.

This decision is recorded as ADR-011.

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

Alternative considered: stamp `ingested_at` on each chunk and take the maximum. Rejected on both counts above, and it would add a third field to the reindex cost for no gain.

### D7. Citations are not gated on `attachSources`, and get their own kill switch

The inline labels and the `citations` array ship together under `app.rag.citations.enabled`, default on, independent of the `attachSources` request flag.

Gating the array on `attachSources` was considered because it would keep the default response byte-identical. It was rejected: the labels appear in the answer text whenever retrieval grounded the answer, so gating the resolution table on an unrelated download-link flag would leave a caller holding `[S1]` in the prose with nothing to resolve it against. The marker and its table are one feature and ship as one.

The consequence is an intentional, additive change to the default response shape: a new optional `citations` key, absent when retrieval injected nothing or when the feature is off. The kill switch exists for the operator who needs the old shape exactly, and turning it off also removes the labels from the prompt, so the answer text goes back to what it was.

### D8. `sources` is derived from the injected passages

`buildSourceRefs` moves from operating on the kept-above-threshold list to operating on the passages that were actually injected. Today a chunk dropped by the character budget still produces a source entry, so the response can offer a download for a document that contributed nothing to the answer. Once `citations` exists, that divergence becomes visible as a source with no citation, which reads as a bug to any caller.

This narrows the `sources` array in one case only, and only to documents that did not influence the answer.

### D9. Composition with the two pending siblings, and the archive order

Recommended archive order: `add-document-management-api`, then `add-tenant-isolation`, then this change.

`add-document-management-api` first, because this change consumes three of its outputs. Its document registry supplies the `documentId` a citation carries and the last-indexed timestamp `ingestedAt` reads. Its `SourceFile` amendment adds `documentId` and `contentPath`, and this change's `SourceFile` delta carries that text forward and adds `ingestedAt` on top, which is only correct if theirs landed first. Its requirement that every bucket-scanned object is routed through `DocumentRouter` is the routing half of the corpus provenance fix, which this change asserts the metadata outcome of rather than re-specifying.

`add-tenant-isolation` second, because it modifies a different requirement in the same capability (the presign requirement) and adds a tenant filter to retrieval. There is no textual overlap with this change's deltas, so the ordering between it and this change is not forced, but keeping it ahead means the retrieval path is already tenant-filtered when labels are attached to it and no scenario has to be written twice.

This change last. On the `rag-source-attachments` capability it modifies `SourceFile DTO shape`, which `add-document-management-api` also modifies, so it must be written against their text and applied after it. It also modifies `De-duplication by source object identity`, which neither sibling touches. On `ingestion-correctness` it only adds requirements, with names distinct from both siblings', so nothing collides. Its new `rag-citations` capability collides with nothing.

If the order changes, the concrete consequence is bounded and named: this change's `SourceFile DTO shape` delta must be re-edited to drop `documentId` and `contentPath`, `documentId` must become optional on every citation, `ingestedAt` needs another source, and the routing half of the corpus fix must be pulled into this change's tasks.

The streaming sibling, `add-chat-streaming-and-conversations`, emits a `sources` event with the same `SourceFile` shape. It needs a matching `citations` event, which is recorded as an open question below rather than specified here.

## Risks / Trade-offs

- Existing corpora cite worse than new ones until reindexed, and a user may not know which state a given document is in. Mitigation: the degradation is explicit and visible in the response (a citation with no `page` and no `chunkIndex` is exactly the signal that a document predates the change), and the migration plan puts the reindex in front of the operator rather than leaving it implicit.
- Reindexing a large corpus re-runs OCR and Docling conversion, which is the expensive part of ingestion. Mitigation: reindex is per document and operator-driven, so it can be spread out or targeted at the documents that matter, and nothing in this change forces a full-corpus pass.
- Labeled blocks add prompt tokens, roughly one short line per injected passage, and the character budget is spent on labels rather than text. Mitigation: the label form is deliberately terse, and the budget accounting counts only passage text so a label never silently evicts content.
- The model may cite badly: labels on the wrong claim, or a label it invented. Mitigation on the invented-label half is that the array is complete for the passages injected, so an unresolvable label is detectable by the caller. The wrong-claim half is a model-quality matter this change does not attempt to police, and the non-goals say so.
- Splitting per parent document changes the chunk boundaries produced for a multi-document batch, so chunk text after this change is not guaranteed identical to before. Mitigation: this only affects batches, chunk content is not part of any spec contract, and reindexed documents are re-embedded anyway.
- Emitting one document per page makes very short pages produce very short chunks, which embed poorly. Mitigation: the splitter's existing minimum-chunk settings already apply per document, and the effect is measured on a real multi-page PDF as part of the verification for that task rather than assumed away.

## Migration Plan

1. Ship the ingestion-side changes first (page metadata, source restamping, ordinals). They are backward compatible: existing points are untouched and new points simply carry extra payload fields.
2. Ship the retrieval and response changes. From this point every answer is labeled, and documents indexed under the old pipeline degrade to document-level citations.
3. Reindex the corpus, document by document, using the reindex endpoint from `add-document-management-api`. Cost is one full parse per document, including OCR where the document needs it. Nothing is deleted and nothing is lost by not reindexing: an un-reindexed document keeps working and simply cites at document level.
4. Rollback is `app.rag.citations.enabled: false`, which removes the labels and the `citations` key and restores the previous response shape without touching stored data. The ingestion-side metadata is inert when the feature is off, so no reindex is needed to roll back or to roll forward again.

## Open Questions

1. `add-document-management-api` contradicts itself on whether the bucket-scan route is aligned onto `DocumentRouter`. Its design D5 says aligning it is "deliberately left out of scope", while its tasks 3.2a and 3.2b and its `ingestion-correctness` delta all require it. This change assumes the requirement wins, since a spec delta outranks a design note. If the design note wins instead, the routing fix moves into this change's tasks and the corpus provenance requirement here cannot be satisfied without it. Deferrable because it changes which change owns one task, not what the end state is.
2. The streaming `sources` event specified by `add-chat-streaming-and-conversations` has no `citations` counterpart. Whichever of the two changes archives second should add it, and the event's placement relative to `sources` and the terminal event needs deciding there rather than here. Deferrable because the synchronous contract is unaffected.
3. The archived `rag-retrieval` spec states that the similarity threshold is applied server-side in the `SearchRequest`, while the code deliberately passes `0.0` and filters in Java so near-miss scores stay loggable. This change relies on the Java-side filtering only to the extent that it needs the kept list in score order, which both variants provide, so it is not blocked either way. Someone should reconcile the spec with the code, and it is not this change.
