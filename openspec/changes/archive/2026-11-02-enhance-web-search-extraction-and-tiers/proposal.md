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
- One pinned fetch and one byte fetch: the curl_cffi hop function that pins each hop, and its call to the
  `follow_guarded_redirects` redirect loop of the `ascend-python-common` library, move from the `curl_cffi` fetcher
  into `src/fetch/pinned_fetch.py`, and every routed file is fetched by the shared `stream_to_file` in
  `src/fetch/byte_fetch.py`, which `add-file-download` reuses.
- Errors are RFC 7807 problem bodies with the `https://ascend.ai/errors/` type base, a `code` and a `traceId`, built
  by the shared problem builder of the `ascend-python-common` library. The four new codes are entries in the
  service's error registry, the library logs, counts and maps them to MCP tool errors, and this change adds no error
  helper of its own.
- Everything here is part of ascend-web-hunter and adds no switch of its own. `add-deployment-modules` (build group 3,
  position 6) lands later and lists ascend-web-hunter as its module `web-search`. This change does not wait for it.

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
  canonical `extraction_schema`, `screenshot` results are never cached, and clearing a session purges that domain's
  cached reads in every running container through a Redis channel (owner answer 87 of 2026-10-08).

## Dependencies and Build Order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders, among them the owner order of
2026-10-01): build group 2 (web-hunter), position 6. It needs `enhance-web-search-tier-ladder` (position 5) only for
the `screenshot` format, which needs a browser tier and is taken from whichever browser tier served the read.
Everything else works on the HTML any tier returns. It also needs `add-ascend-python-common` (position 1), which gives
the service its problem builder, error registry and refusal handling (design D8), and `add-python-runtime-upgrades`
(position 2), so the MCP tools and tests of this change are written against FastMCP 4 and every test that uses
`fastmcp.Client` names its protocol era (`add-python-runtime-upgrades` D9). Its e2e specs use the shared fake site of
`add-web-search-scraping-e2e` (build group 1). Later changes build on it: `enhance-web-search-crawl-at-scale`
(position 9) for per-page extraction, and `add-file-download` (position 10) for its downloads on
`src/fetch/pinned_fetch.py` and `stream_to_file` of this change (its D2).

## Impact

- `apps/ascend-web-hunter/src/reader/extraction.py`: ensemble scoring, embedded data, tables.
- `apps/ascend-web-hunter/src/reader/schema_extraction.py` and `src/reader/recipe_store.py`: new.
- `apps/ascend-web-hunter/src/reader/document_router.py`: new, the three platform clients.
- `apps/ascend-web-hunter/src/fetch/pinned_fetch.py` (the pinned curl_cffi hop and the library redirect call moved
  out of `src/reader/strategies/curl_cffi_fetcher.py`) and `src/fetch/byte_fetch.py` (`stream_to_file`): new.
- `apps/ascend-web-hunter/src/api/exception_handlers.py`: the four D8 codes as entries of the service's error
  registry. The problem builder and the handlers come from `ascend-python-common`.
- `apps/ascend-web-hunter/src/reader/web_reader.py`: `OutputFormat`, `_cache_key`, format dispatch, and the purge
  broadcast on the Redis channel `read_cache_purge` with its subscriber task in the lifespan of `src/main.py`.
- `apps/ascend-web-hunter/src/api/rest/rest_endpoints.py` and `src/api/mcp/mcp_server.py`: the new fields and the
  `include_links` rule.
- `apps/ascend-web-hunter/src/config/config.py`: the settings in `design.md`, each passed by both compose files as
  `${VAR:-default}` with the same default and added to both `.env.example` files and the bundle README by the sync
  rule (owner rule 98 of 2026-10-08).
- `apps/ascend-web-hunter/pyproject.toml`: `extruct` (embedded data) and `jsonschema`, exact pins.
- e2e: three new specs (next free numbers at implementation time) against the shared e2e fake site:
  `<N>-structured-extraction` (deterministic, no model, only the steps no unit test proves, owner answer 91.3 of
  2026-10-08), `<N>-document-routing` (deterministic, full stack, runs alone)
  and `<N>-schema-extraction-ai` (AI-run, a real model), their Bruno folder
  `docs/api/request/AscendAI/web-hunter/testing/extraction/`, and their places in `docs/E2E_RUN_SCENARIOS.md`.
  The shared fake site gains `files/canary.mp3`, `files/oversized.pdf` and the page `/pdf-link-blocked` for the
  document routing spec.
- Docs: `AGENTS.md`, `README.md`, `docs/configuration.md`, ADR-016 (ensemble, superseding ADR-009), ADR-017 (schema
  extraction, recipes and model-input safety), CHANGELOG with a bump from 0.0.11 to 0.0.12.

## Relevant Skills

- `/python-patterns`
- `/tdd-workflow`
- `/api-design`
- `/security-review`
- `/architecture-decision-records`
