# ingestion-correctness Delta Specification

## ADDED Requirements

### Requirement: Page provenance survives from parser to index

Every parser that returns per-page structure SHALL preserve the page number as structured chunk metadata on the documents it produces, rather than flattening pages into a single text blob. This SHALL hold for the Unstructured API path (elements grouped by their reported page number), the OCR path (one document per returned page, using the page number the OCR service reports rather than an inferred one), and the per-page PDF routing path (the page number the router already computes when it slices the file).

A parser response that carries no page information for some or all of its content SHALL produce documents without page metadata rather than a guessed page. Ingestion SHALL NOT fail because page information is absent.

#### Scenario: Multi-page PDF indexes with per-page provenance

- **WHEN** a three-page text PDF is ingested
- **THEN** the chunks stored in the vector store carry page numbers 1, 2 and 3 according to which page each chunk's text came from
- **AND** no chunk carries text from two different pages

#### Scenario: Scanned PDF keeps the OCR service's page numbers

- **WHEN** a scanned two-page PDF is ingested through the OCR path and the OCR service reports `page_number` 1 and 2
- **THEN** the stored chunks carry those page numbers
- **AND** the page numbers are the ones the service reported, not positions inferred from the order of the response

#### Scenario: Office document parsed by the Unstructured path

- **WHEN** a DOCX whose elements report page numbers is ingested
- **THEN** its chunks carry the page number of the element they came from

#### Scenario: Element without a page number

- **WHEN** a parsed element reports no page number
- **THEN** its chunk is stored without page metadata
- **AND** the ingestion completes successfully

#### Scenario: Markdown source has no pages

- **WHEN** a Markdown file is ingested
- **THEN** its chunks carry no page metadata
- **AND** the ingestion completes successfully

### Requirement: Per-page PDF routing stamps the original object key as the chunk source

When a PDF is split into per-page conversion requests, the chunks produced SHALL carry the original document's source identity, not the synthetic per-page filename used internally to label the conversion request. The synthetic name SHALL NOT reach chunk metadata, because the source identity is what deduplication, deletion, and source download all key on: a chunk stamped `report.pdf_page3.pdf` matches no stored object and no registry row.

#### Scenario: Chunks of a routed PDF carry the real key

- **WHEN** `documents/report.pdf` is ingested through the per-page PDF route
- **THEN** every stored chunk carries `source` equal to `documents/report.pdf`
- **AND** no stored chunk carries a source containing the synthetic page suffix

#### Scenario: Re-ingest of a routed PDF replaces rather than accumulates

- **WHEN** the same PDF is ingested twice through the per-page route
- **THEN** the number of stored chunks for that source equals the chunk count of the latest ingestion, not the sum of both

#### Scenario: A routed PDF is downloadable as a source

- **WHEN** a chunk from a per-page routed PDF grounds an answer requested with `attachSources=true`
- **THEN** the source entry resolves to the original object and its download succeeds

### Requirement: Chunk ordinals are stamped at split time

Splitting a parsed document into chunks SHALL stamp each chunk with its zero-based ordinal position and the total number of chunks its parent document produced. Ordinals SHALL be scoped to the parent document: two documents split in the same batch each start at zero, and a document split into pages first SHALL number its chunks across the whole document so a reader sees one continuous sequence.

#### Scenario: Ordinals are contiguous per document

- **WHEN** a document is split into 12 chunks
- **THEN** the stored chunks carry ordinals 0 through 11 with no gap and no repetition
- **AND** each carries a chunk count of 12

#### Scenario: Two documents split together do not share a sequence

- **WHEN** two documents are split in the same operation, one into 3 chunks and one into 5
- **THEN** the first document's chunks carry ordinals 0 to 2 and a count of 3
- **AND** the second document's chunks carry ordinals 0 to 4 and a count of 5

#### Scenario: Page-split document numbers continuously

- **WHEN** a two-page PDF produces 4 chunks from page 1 and 3 chunks from page 2
- **THEN** the stored chunks carry ordinals 0 to 6 across the whole document
- **AND** the page-2 chunks carry ordinals 4 to 6 and page number 2

### Requirement: Corpus ingestion carries the same provenance as the upload path

Objects ingested by a bucket-scan run SHALL end up with the same page and ordinal metadata as the same file uploaded directly. This requirement is the provenance half of the routing fix specified by `add-document-management-api` (its `ingestion-correctness` requirement that every scanned object is routed through the extension-based router). It adds no second routing rule and only asserts the metadata outcome, so that fixing routing without carrying provenance through would still fail.

#### Scenario: Scanned bucket object and uploaded file produce identical provenance

- **WHEN** the same three-page PDF is ingested once by dropping it into the bucket and running a scan, and once by direct upload
- **THEN** the stored chunks carry the same page numbers in both cases
- **AND** the stored chunks carry the same ordinals and chunk counts in both cases

#### Scenario: Corpus-ingested PDF can be cited by page

- **WHEN** an answer is grounded in a passage from a PDF that entered the corpus through a bucket-scan run
- **THEN** the citation for that passage carries the page number of the passage
