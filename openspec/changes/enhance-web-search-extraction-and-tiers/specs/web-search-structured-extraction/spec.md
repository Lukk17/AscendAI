## ADDED Requirements

### Requirement: Embedded structured data on the structured format

When `output_format` is `structured`, ascend-web-hunter SHALL parse JSON-LD, OpenGraph and microdata from the page and return them in a `metadata` object beside the existing article fields. A parse failure SHALL leave `metadata` empty and SHALL NOT fail the read.

#### Scenario: Product page with JSON-LD

- **WHEN** a page carrying a JSON-LD `Product` block is read with `output_format` `structured`
- **THEN** `metadata` contains that block's fields

#### Scenario: Broken JSON-LD

- **WHEN** a page carries malformed JSON-LD
- **THEN** the read succeeds with an empty `metadata` and a WARNING is logged

### Requirement: Scored ensemble main-content extraction

ascend-web-hunter SHALL run trafilatura and readability-lxml on the same HTML for every extraction, score each by text length, link density and boilerplate ratio, and return the higher scoring result, with ties going to trafilatura.

#### Scenario: Readability scores higher

- **WHEN** readability's result scores higher than trafilatura's on a page
- **THEN** readability's result is returned even though trafilatura's was not thin

### Requirement: Schema-guided extraction through a configurable endpoint

With `output_format` `schema` and an `extraction_schema`, ascend-web-hunter SHALL return a JSON object validated against that schema, produced by the OpenAI-compatible endpoint in `EXTRACTION_LLM_BASE_URL`. An answer that does not validate SHALL be refused with HTTP 502 and code `EXTRACTION_FAILED`. When no endpoint is configured the request SHALL be refused with HTTP 400.

#### Scenario: Valid schema extraction

- **WHEN** a caller reads a product page with `output_format` `schema` and a schema requiring `name` and `price`
- **THEN** the response is a JSON object with `name` and `price` that validates against the schema

#### Scenario: Endpoint not configured

- **WHEN** `EXTRACTION_LLM_BASE_URL` is empty and a caller asks for `schema`
- **THEN** the request is refused with HTTP 400 naming the missing setting

### Requirement: Page content sent to a model is untrusted data

Page content sent to the extraction model SHALL be cut to `EXTRACTION_LLM_MAX_INPUT_CHARS`, SHALL be placed only inside a delimited data block that the system message declares untrusted, and SHALL never be sent as raw HTML with scripts. Nothing the model returns SHALL be executed or fetched, and its answer SHALL be accepted only after schema validation.

#### Scenario: Prompt injection in the page

- **WHEN** a page's text tells the model to ignore its instructions and return a secret
- **THEN** the request sent to the model carries that text only inside the data block
- **AND** the response is accepted only if it validates against the caller's schema

### Requirement: Self-healing per-domain selector recipes

On a schema extraction the model SHALL also return one CSS selector per field, stored under the registrable domain and the SHA-256 of the canonical schema with TTL `RECIPE_TTL_SECONDS`. A later extraction with the same domain and schema SHALL replay the selectors without calling the model. A replay that fails validation SHALL delete the recipe and call the model again.

#### Scenario: Recipe replay skips the model

- **WHEN** a second schema extraction runs for the same domain and schema and the page structure is unchanged
- **THEN** the model is not called

#### Scenario: Drift rebuilds the recipe

- **WHEN** a replay yields an object that fails the schema
- **THEN** the recipe is deleted, the model is called, and the new selectors are stored

### Requirement: Non-HTML content routed to the platform services

A PDF SHALL be converted by docling-serve, an image SHALL be read through the ascend-ocr job API (`POST /v1/ocr/jobs`, then `GET /v1/ocr/jobs/{job_id}`), and audio SHALL be transcribed by ascend-audio-scribe. Every routed document SHALL be fetched through the SSRF-guarded client and capped at `DOCUMENT_MAX_BYTES`. A routing failure SHALL return the HTML extraction with a `routing_error` field rather than fail the read.

#### Scenario: PDF converted by docling-serve

- **WHEN** a read targets a URL whose response is `application/pdf`
- **THEN** the returned content is the Markdown docling-serve produced

#### Scenario: Image read through the OCR job API

- **WHEN** a read targets a URL whose response is `image/png`
- **THEN** an ascend-ocr job is submitted, polled to a terminal state, and its Markdown is returned

### Requirement: Tables and screenshot output formats

`output_format` `tables` SHALL return each HTML table as a list of rows. `output_format` `screenshot` SHALL return a base64 full-page PNG taken by the browser tier that served the read, and SHALL be refused with HTTP 400 when no browser tier is enabled.

#### Scenario: Table page

- **WHEN** a page with one HTML table is read with `output_format` `tables`
- **THEN** the response holds that table as rows
