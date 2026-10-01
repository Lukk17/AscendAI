## Why

ascend-web-hunter returns one main-content blob from trafilatura, with a readability-lxml recall pass when trafilatura
returns thin content (ADR-009), and an optional `structured` format with title, author, date and site name (ADR-007).
It ignores the structured data most commercial pages already carry (JSON-LD, OpenGraph, microdata), it cannot return
fields a caller asks for by schema, and it ignores linked PDFs, images and audio even though the platform already runs
docling-serve, ascend-ocr and ascend-audio-scribe.

The folder name is historical. On 2026-10-01 the owner split the original change in two: the tier work moved to
`enhance-web-search-tier-ladder`, and this folder now holds only structured extraction.

## What Changes

- Embedded structured data: JSON-LD, OpenGraph and microdata are parsed and returned in a `metadata` object on the
  `structured` format.
- Scored ensemble: trafilatura and readability-lxml both run on every extraction and the higher scoring result wins.
  This replaces the ADR-009 recall pass, which runs readability only when trafilatura is thin. ADR-009 is superseded.
- Schema-guided extraction: `output_format` `schema` with an `extraction_schema` (JSON Schema) returns JSON validated
  against it, produced by a configurable OpenAI-compatible endpoint, which can be a local model.
- Self-healing recipes: the model also returns CSS selectors per field. They are stored per domain and schema hash
  and replayed without the model. When a replay fails validation the recipe is rebuilt.
- Non-HTML routing: a linked or directly read PDF goes to docling-serve (the `docling-serve` service in
  `compose.yaml`, port 5001), an image goes to the ascend-ocr job API (`POST /v1/ocr/jobs` on port 7022, then
  `GET /v1/ocr/jobs/{job_id}`), and audio goes to ascend-audio-scribe (`POST /api/v1/transcribe/local` on port
  7017 with `stream=false`).
- Two more output formats: `tables` (HTML tables as rows) and `screenshot` (full-page PNG, base64).
- Security for page content sent to a model: content is passed as data never as instructions, capped in size, and
  the answer is accepted only when it validates against the caller's schema.

## Capabilities

### New Capabilities

- `web-search-structured-extraction`: embedded structured data, schema-guided extraction, recipes, non-HTML routing,
  the `tables` and `screenshot` formats, and the model-input safety rules.

### Modified Capabilities

- `web-search-extraction-quality`: "Readability fallback for thin extractions" is REMOVED (replaced by the ensemble),
  and "Structured article extraction, selectable by the caller" is MODIFIED: `OutputFormat` grows from
  `Literal["text", "structured"]` to `Literal["text", "structured", "schema", "tables", "screenshot"]`, and
  `include_links` is accepted only with `text`.
- `web-search-caching-observability`: "Read-result caching" is MODIFIED: the cache key adds the SHA-256 of the
  canonical `extraction_schema`, and `screenshot` results are never cached.

## Dependencies and Build Order

Build order fixed by the owner on 2026-10-01: `open-several-novnc-windows-at-once`, then
`detect-challenge-walls-in-any-language`, then `enhance-web-search-tier-ladder`, then this change, then
`enhance-web-search-crawl-at-scale`. This change depends on `enhance-web-search-tier-ladder` only for the `screenshot`
format, which needs a browser tier and is taken from whichever browser tier served the read. Everything else works on
the HTML any tier returns. `enhance-web-search-crawl-at-scale` depends on this change for per-page extraction.

## Impact

- `apps/ascend-web-hunter/src/reader/extraction.py`: ensemble scoring, embedded data, tables.
- `apps/ascend-web-hunter/src/reader/schema_extraction.py` and `src/reader/recipe_store.py`: new.
- `apps/ascend-web-hunter/src/reader/document_router.py`: new, the three platform clients.
- `apps/ascend-web-hunter/src/reader/web_reader.py`: `OutputFormat`, `_cache_key`, format dispatch.
- `apps/ascend-web-hunter/src/api/rest/rest_endpoints.py` and `src/api/mcp/mcp_server.py`: the new fields and the
  `include_links` rule.
- `apps/ascend-web-hunter/src/config/config.py`: the settings in `design.md`.
- `apps/ascend-web-hunter/pyproject.toml`: `extruct` (embedded data) and `jsonschema`, exact pins.
- Docs: `AGENTS.md`, `README.md`, `docs/configuration.md`, ADR-016 (ensemble, superseding ADR-009), ADR-017 (schema
  extraction, recipes and model-input safety), CHANGELOG with a bump to 0.0.9.

## Relevant Skills

- `/python-patterns`
- `/tdd-workflow`
- `/api-design`
- `/security-review`
- `/architecture-decision-records`
