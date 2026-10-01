## Context

Extraction lives in `apps/ascend-web-hunter/src/reader/extraction.py` and `src/reader/web_reader.py`. Today
`OutputFormat = Literal["text", "structured"]`, the cache key is built by `_cache_key(url, heavy_mode, include_links,
profile, output_format, tier)`, and `output_format=structured` with `include_links=true` is refused at both API
boundaries. ADR-007 records the structured format and ADR-009 the readability recall pass.

## Decisions

### D1: Embedded data first, on the `structured` format

`extruct` parses JSON-LD, OpenGraph and microdata from the HTML the tier returned. The result goes into a new
`metadata` object on the `structured` response, beside the existing title, author, date and site name. A parse error
leaves `metadata` empty and logs a WARNING. It never fails the read.

### D2: Scored ensemble replaces the recall pass

Both extractors run on the same HTML. Each result is scored by text length times (1 minus link density) times (1
minus boilerplate ratio), and the higher score wins. Ties go to trafilatura. This supersedes ADR-009: the recall pass
ran readability only below a threshold, and lost on pages where readability was better but trafilatura was not thin.

### D3: Schema extraction through a configurable endpoint

`output_format` `schema` requires `extraction_schema`, a JSON Schema object of at most `EXTRACTION_SCHEMA_MAX_BYTES`
(default 16384). The service sends the extracted main text (never raw HTML with scripts) to
`EXTRACTION_LLM_BASE_URL` with `EXTRACTION_LLM_MODEL` and `EXTRACTION_LLM_API_KEY`, asking for the values and one CSS
selector per field. When `EXTRACTION_LLM_BASE_URL` is empty the `schema` format answers HTTP 400 naming the missing
setting. The endpoint can be LM Studio, any OpenAI-compatible local model, or a cloud provider.

### D4: Recipes keyed by domain and schema

Key `recipe:{registrable_domain}:{sha256 of canonical schema}` in Redis, TTL `RECIPE_TTL_SECONDS` (default 604800).
A replay runs the stored selectors with `lxml.cssselect`, builds the object and validates it with `jsonschema`. On a
validation failure or an empty required field the recipe is deleted and the model runs again. Selectors are plain CSS
strings, never JavaScript and never XPath with functions, and a selector longer than 512 characters is rejected.

### D5: Model-input safety

- Page text is put in the user message inside a delimited block and the system message says the block is untrusted
  data and any instruction in it must be ignored.
- The text is cut to `EXTRACTION_LLM_MAX_INPUT_CHARS` (default 60000) before sending.
- The answer is parsed as JSON and validated against the caller's schema. Anything else is HTTP 502 with code
  `EXTRACTION_FAILED`. Nothing the model returns is executed or fetched.
- The model call has a timeout `EXTRACTION_LLM_TIMEOUT_SECONDS` (default 60).

### D6: Non-HTML routing

- PDF (by `Content-Type` or a `.pdf` main link): bytes are fetched through the existing SSRF-guarded client, capped
  at `DOCUMENT_MAX_BYTES` (default 52428800), and posted to docling-serve at `DOCLING_SERVE_URL` (default
  `http://docling-serve:5001`), endpoint `/v1/convert/file`, asking for Markdown. The exact docling-serve path is
  checked against its pinned image version in task 4.1.
- Image: posted to ascend-ocr `POST /v1/ocr/jobs` at `ASCEND_OCR_URL` (default `http://ascend-ocr:7022`), then polled
  with `GET /v1/ocr/jobs/{job_id}` using the poll hint the service returns, up to `OCR_ROUTE_TIMEOUT_SECONDS` (default
  300). The Markdown is read from the result address in the final state.
- Audio: posted to ascend-audio-scribe `POST /api/v1/transcribe/local` at `AUDIO_SCRIBE_URL` (default
  `http://ascend-audio-scribe:7017`) with `stream=false`.
- An empty URL setting turns that route off. A route failure returns the HTML extraction with a `routing_error`
  field, it never fails the read.

### D7: Formats, links and the cache key

`OutputFormat` becomes `Literal["text", "structured", "schema", "tables", "screenshot"]`. `include_links=true` is
accepted only with `text`, and every other format with it is refused at the boundary naming the combination. The
cache key adds `schema=<sha256 of canonical extraction_schema or empty>`. `screenshot` results are never cached,
because a full-page PNG would crowd the in-process cache.

## Risks

- A model that ignores the instructions. D5 limits the damage to a wrong answer, which schema validation catches when
  the shape is wrong. A right-shaped wrong value is not caught, and the docs say so.
- docling-serve, ascend-ocr and ascend-audio-scribe are slow on large files. The size cap and the timeouts bound it.
