## Purpose

Passage-level attribution for RAG-backed answers: every retrieved passage reaches the model under a short stable label, and every label resolves back to a real document and a real location inside it, so a reader can tell which claim came from which file and which part of that file.

## ADDED Requirements

### Requirement: Retrieved passages are labeled in the injected context

The retrieval context injected into the prompt SHALL present each retrieved passage as its own labeled block rather than as unlabeled concatenated text. Each block SHALL carry, at minimum, the passage's label, the document's display name, and its locator when one is known. A passage SHALL be labeled if and only if at least one character of its text is injected into the prompt, so a passage dropped entirely by the context-size budget receives no label.

The label SHALL be short enough that repeating it inline costs the model a small, bounded number of tokens: the form is the letter `S` followed by a decimal integer, wrapped in square brackets when cited (for example `[S1]`).

#### Scenario: Three passages from two documents are labeled

- **WHEN** retrieval keeps three chunks above the similarity threshold, two from `handbook.pdf` and one from `notes.md`, and all three fit the context budget
- **THEN** the injected context contains three separate labeled blocks
- **AND** the labels are `S1`, `S2` and `S3`
- **AND** each block states the display name of the document the passage came from

#### Scenario: Passage dropped by the context budget gets no label

- **WHEN** the context-size budget is exhausted before the last kept chunk is reached, so that chunk contributes no characters to the prompt
- **THEN** that chunk receives no label
- **AND** the labels present in the context are contiguous from `S1` with no gap

#### Scenario: Partially truncated passage keeps its label

- **WHEN** a chunk is truncated by the context-size budget but still contributes at least one character
- **THEN** it keeps its label
- **AND** its labeled block contains the truncated text

#### Scenario: Retrieval returns nothing

- **WHEN** no chunk scores above the similarity threshold
- **THEN** no retrieval context is injected
- **AND** no labels are issued

### Requirement: Label assignment is deterministic

Labels SHALL be assigned by descending similarity score over the passages that are injected, ties broken first by the ascending source object key, then by the ascending chunk ordinal within the document, and finally, for a chunk carrying no ordinal, by its stable vector-store identifier. Numbering SHALL start at 1 and SHALL be contiguous. The same retrieval result SHALL therefore always produce the same label-to-passage mapping, and labels SHALL be scoped to a single response: a label from one response carries no meaning in another.

#### Scenario: Same retrieval result yields the same labels

- **WHEN** the identical set of scored chunks is injected twice
- **THEN** both runs assign the same label to the same chunk

#### Scenario: Tied scores are ordered deterministically

- **WHEN** two injected chunks have the same similarity score, one from `a-manual.pdf` chunk ordinal 4 and one from `b-manual.pdf` chunk ordinal 0
- **THEN** the chunk from `a-manual.pdf` is labeled before the chunk from `b-manual.pdf`

#### Scenario: Labels do not carry across responses

- **WHEN** two different prompts each produce a passage labeled `S1`
- **THEN** the two `S1` labels may refer to different passages
- **AND** each response's own `citations` array is the only authority for what its labels mean

### Requirement: The response carries a citations array that resolves every label

When retrieval injects at least one labeled passage, the prompt response SHALL contain a `citations` array with exactly one entry per label issued, in label order. Each entry SHALL always carry `label` (the bare label without brackets, for example `S1`) and `name` (the document's display name), so that every citation is at minimum readable as a document-level attribution. Each entry SHALL additionally carry, when and only when that fact is known for the passage: `documentId` (the registry id of the source document), `page` (a one-based page number), `chunkIndex` (the zero-based ordinal of the passage within its document) and `chunkCount` (the number of chunks that document was split into). An unknown field SHALL be omitted from the JSON rather than serialized as `null` or as a sentinel number.

The array SHALL cover exactly the passages injected into the prompt: no entry without a corresponding labeled block, and no labeled block without an entry. When retrieval injects nothing, the `citations` key SHALL be omitted from the JSON rather than serialized as `null` or as an empty array.

#### Scenario: Citations array matches the labels in the prompt

- **WHEN** the injected context contains labeled blocks `S1`, `S2` and `S3`
- **THEN** `response.citations` has exactly three entries with `label` values `S1`, `S2` and `S3` in that order
- **AND** every entry has a non-blank `name`
- **AND** every entry whose passage was indexed with ordinal metadata has an integer `chunkIndex` and an integer `chunkCount`

#### Scenario: Citation resolves back to a real document and location

- **WHEN** a citation entry reports `documentId=d41…`, `name=Employee Handbook`, `page=12`, `chunkIndex=7`
- **THEN** fetching the document by that `documentId` returns the same document whose display name is `Employee Handbook`
- **AND** the passage text in the labeled block for that label is the text of chunk 7 of that document

#### Scenario: Citation joins to the source entry when sources were requested

- **WHEN** a prompt is sent with `attachSources=true` and citations are issued
- **THEN** every citation entry whose `documentId` is present matches the `documentId` of exactly one entry in `response.sources`

#### Scenario: No citations key when retrieval injected nothing

- **WHEN** retrieval returns no chunk above the similarity threshold
- **THEN** the response JSON does not contain a `citations` key

### Requirement: Locator degrades when a passage has no page

A source without pages, for example a Markdown file or a scraped web page, SHALL still produce a usable citation. When the passage carries no page number, the citation entry SHALL omit the `page` field and SHALL still carry `chunkIndex` and `chunkCount`, and the passage's labeled block in the prompt SHALL state the ordinal locator instead of a page. When the passage carries neither page nor ordinal metadata, the citation SHALL degrade one step further to a document-level attribution carrying `label` and `name` alone. Absence of provenance at any level SHALL NOT cause the request to fail, SHALL NOT suppress the label, and SHALL NOT suppress the citation entry.

#### Scenario: Markdown source cites without a page

- **WHEN** a passage from `notes.md` is injected
- **THEN** its citation entry omits `page`
- **AND** it carries `chunkIndex` and `chunkCount`
- **AND** the labeled block identifies the passage by its ordinal position within the document

#### Scenario: Document indexed before page provenance existed

- **WHEN** a passage is retrieved from a document indexed before this change shipped, whose stored chunk carries neither page nor ordinal metadata
- **THEN** the passage is still labeled and still appears in `citations`
- **AND** its entry omits `page`, `chunkIndex` and `chunkCount`
- **AND** its entry still carries `label` and a non-blank `name`
- **AND** its labeled block in the prompt names the document without claiming a location inside it

#### Scenario: Mixed corpus in one answer

- **WHEN** one answer draws on a PDF passage with a page and a Markdown passage without one
- **THEN** both passages are labeled
- **AND** the PDF citation carries `page` while the Markdown citation does not

### Requirement: Citations are independent of the source-attachment opt-in and have a kill switch

Inline labels and the `citations` array SHALL be governed by a single server-side setting, `app.rag.citations.enabled`, shipped enabled. They SHALL NOT be gated on the `attachSources` request flag, because an inline label in the answer text is unusable without the array that resolves it, and gating the array on a download-link flag would leave unresolvable labels in the default response.

When `app.rag.citations.enabled` is `false`, the injected context SHALL contain no labels, the response SHALL contain no `citations` key, and the response shape SHALL be identical to the shape produced before this change.

#### Scenario: Citations returned without requesting sources

- **WHEN** a prompt is sent with no `attachSources` field and retrieval injects two passages
- **THEN** the response contains a `citations` array with two entries
- **AND** the response contains no `sources` key

#### Scenario: Kill switch restores the previous response shape

- **WHEN** `app.rag.citations.enabled: false` is configured and a prompt is answered from retrieved context
- **THEN** the response JSON contains no `citations` key
- **AND** the injected context contains no labels
- **AND** the answer text contains no label markers

### Requirement: The system prompt names the label format that is actually supplied

The configured system prompt SHALL instruct the model to cite using the label form supplied in the retrieval context, and SHALL NOT instruct it to cite an identifier the context does not carry. It SHALL instruct the model to place the label immediately after the claim it supports, to use only labels present in the current context, and to omit a citation rather than invent a label when no injected passage supports the claim.

#### Scenario: Prompt no longer asks for an unsupplied identifier

- **WHEN** the configured `app.system-prompt` is read
- **THEN** its citation guidance names the bracketed label form supplied in the context
- **AND** it contains no instruction to attribute by a document id that the context does not provide

#### Scenario: Answer grounded in one passage cites that passage

- **WHEN** a prompt is answered from a single injected passage labeled `S1`
- **THEN** the answer text contains `[S1]` next to the claim taken from that passage
- **AND** `response.citations` contains the entry for `S1`

#### Scenario: Answer not grounded in retrieval carries no label

- **WHEN** the question is answered from training knowledge because no injected passage covers it
- **THEN** the answer text contains no label marker

### Requirement: A passage from an unregistered source still cites

A retrieved passage whose source object has no document-registry row SHALL still be labeled and SHALL still appear in `citations`, with `documentId` omitted and `name` taken from the chunk's own title or source metadata. This is deliberately weaker than the `sources` array, which omits unregistered sources entirely because it cannot offer a download path for them: a citation names a location, so it stays useful without one.

#### Scenario: Unregistered source is cited but not downloadable

- **WHEN** a passage is retrieved whose source object has no registry row, and the prompt was sent with `attachSources=true`
- **THEN** the passage is labeled and appears in `citations` with `documentId` omitted and a non-blank `name`
- **AND** that source does not appear in `response.sources`
- **AND** the request returns HTTP 200
