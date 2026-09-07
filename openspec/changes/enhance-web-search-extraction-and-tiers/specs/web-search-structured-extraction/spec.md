## ADDED Requirements

### Requirement: Embedded structured data is parsed before heuristics

ascend-web-hunter SHALL parse JSON-LD, OpenGraph, and microdata from a page and return them as structured fields alongside the extracted text, performed before any heuristic or model-based extraction runs.

#### Scenario: JSON-LD and OpenGraph returned

- **WHEN** a page carrying JSON-LD and OpenGraph tags is read
- **THEN** the response includes the parsed JSON-LD and OpenGraph fields as structured data
- **AND** the main-text extraction is still returned

### Requirement: Scored ensemble main-content extraction

ascend-web-hunter SHALL run trafilatura and a readability extractor over the same DOM, score each on text-vs-link density and boilerplate ratio, and return the higher-scoring result as the main content, rather than always preferring one extractor with the other as a fallback.

#### Scenario: Ensemble keeps the better extractor

- **WHEN** a page is extracted where readability scores higher than trafilatura
- **THEN** the readability result is returned as the main content
- **AND** on a page where trafilatura scores higher, its result is returned

### Requirement: Schema-guided extraction returns validated JSON

ascend-web-hunter SHALL offer a read mode (REST and MCP) where the caller supplies a JSON schema and receives JSON validated against it. The extraction SHALL be produced via a configurable OpenAI-compatible endpoint, so it can run against a local model, AscendAgent's provider proxy, or a cloud provider without code change.

#### Scenario: Caller-supplied schema honored

- **WHEN** a caller requests extraction of a page with a JSON schema describing the fields it wants
- **THEN** the response is JSON that validates against the supplied schema

#### Scenario: Extraction endpoint is configurable

- **WHEN** the extraction LLM endpoint is configured to a local model
- **THEN** schema extraction runs against that endpoint and no page content is sent to a cloud provider

### Requirement: Self-healing per-domain selector recipes

On the first schema extraction for a domain, ascend-web-hunter SHALL persist the LLM-emitted CSS/XPath selectors as a recipe. Subsequent extractions for that domain SHALL replay the persisted selectors and skip the model. Every replay SHALL be validated against the caller's schema; on drift (empty or type-mismatched fields), the recipe SHALL be regenerated via the model.

#### Scenario: Recipe replay skips the model

- **WHEN** a second schema extraction is requested for a domain that already has a recipe and the page structure is unchanged
- **THEN** the extraction uses the persisted selectors and does not call the model

#### Scenario: Drift regenerates the recipe

- **WHEN** a recipe replay yields fields that fail the caller's schema because the page structure changed
- **THEN** the recipe is regenerated via the model and the fresh selectors are persisted

### Requirement: Non-HTML content routed into the platform stack and richer output formats

ascend-web-hunter SHALL route linked PDFs to Docling, image-heavy pages and linked images to PaddleOCR, and linked audio to ascend-audio-scribe, merging their extracted text into the result. The service SHALL additionally offer full-page screenshot and extracted-tables-as-rows among the selectable output formats.

#### Scenario: Linked PDF routed to Docling

- **WHEN** a read encounters a page whose primary content is a linked PDF
- **THEN** the PDF is routed to Docling and its extracted text is included in the result

#### Scenario: Table and screenshot outputs

- **WHEN** a caller requests the table output format for a page containing an HTML table
- **THEN** the response contains the table as structured rows
- **AND** requesting the screenshot format returns full-page image bytes
