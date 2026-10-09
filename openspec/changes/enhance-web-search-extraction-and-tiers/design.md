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
selector per field. When `EXTRACTION_LLM_BASE_URL` is empty the `schema` format answers HTTP 400
`extraction_not_configured` naming the missing setting. The endpoint can be LM Studio, any OpenAI-compatible local model, or a cloud provider.

### D4: Recipes keyed by domain and schema

Key `recipe:{registrable_domain}:{sha256 of canonical schema}` in Redis, TTL `RECIPE_TTL_SECONDS` (default 604800).
A replay runs the stored selectors with `lxml.cssselect`, builds the object and validates it with `jsonschema`. On a
validation failure or an empty required field the recipe is deleted and the model runs again. Selectors are plain CSS
strings, never JavaScript and never XPath with functions, and a selector longer than `RECIPE_SELECTOR_MAX_CHARS`
(default 512) is rejected.

### D5: Model-input safety

- Page text is put in the user message inside a delimited block and the system message says the block is untrusted
  data and any instruction in it must be ignored.
- The text is cut to `EXTRACTION_LLM_MAX_INPUT_CHARS` (default 60000) before sending.
- The answer is parsed as JSON and validated against the caller's schema. Anything else is HTTP 502 with code
  `extraction_failed`. Nothing the model returns is executed or fetched.
- The model call has a timeout `EXTRACTION_LLM_TIMEOUT_SECONDS` (default 60).

### D6: Non-HTML routing

One pinned fetch and one byte fetch serve every route. Since `add-ascend-python-common` (its D21, owner answer
63.2) there is one redirect loop in the service: the library's `follow_guarded_redirects`, which checks every hop with
`check_fetch_uri`, resolves each `Location` against the hop that returned it and stops after `MAX_REDIRECT_HOPS` (10).
`fetch_with_curl_cffi` in `src/reader/strategies/curl_cffi_fetcher.py` already calls it with a curl_cffi `send_hop`
that pins each checked hop with `CURLOPT_RESOLVE`. This change moves that `send_hop` and the call to
`follow_guarded_redirects`, not copied, into `src/fetch/pinned_fetch.py`: one function opens a `curl_cffi` session,
runs `check_fetch_uri` on the first URL, hands `follow_guarded_redirects` the pinned `send_hop`, and returns the final
response without reading the body. It writes no redirect loop of its own. `fetch_with_curl_cffi` keeps its signature
and reads `.text` from it. On top of it, `stream_to_file(url, max_bytes, ...)` in `src/fetch/byte_fetch.py` reads the
body with `stream=True` in chunks into a temporary file, refuses before reading when `Content-Length` is above
`max_bytes`, counts bytes as they arrive, and stops and deletes the file the moment the count passes the limit. The
PDF, image and audio bytes of every route are fetched by `stream_to_file` with `DOCUMENT_MAX_BYTES`, which stays its
own setting. `add-file-download` (its D2) builds its downloads on the same two functions, so one redirect loop (the
library's) and one byte fetch serve the read tiers, document routing and downloads.

- PDF (by `Content-Type` or a `.pdf` main link): bytes are fetched by `stream_to_file`, capped
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

The read cache stays in each process, bounded by `READ_CACHE_TTL_SECONDS`, because a read served a little stale by
one container is not a defect. The purge of one domain when its stored session is cleared is different: the
requirement says a read captured before the session was known bad must not be served afterwards, and with several
ascend-web-hunter containers (owner answer 87 of 2026-10-08) a purge in one process alone leaves the other containers
serving it. So the container that clears a session purges its own cache and publishes the registrable domain on the
Redis channel `read_cache_purge`. Every container subscribes to the channel from a task its lifespan starts and stops,
and drops its cached reads for that domain when a message arrives. Redis does not keep a message for a subscriber
that is not connected, so after the subscriber reconnects it drops its whole read cache once. It waits
`READ_CACHE_PURGE_RECONNECT_SECONDS` between two connection attempts. The count the caller gets
back is the count of the container that answered. A Redis error is logged once as a WARNING and never fails the clear: the local purge is done,
and the other containers' entries end at their TTL.

### D8: Error bodies

Every REST error this change adds is an RFC 7807 problem body with media type `application/problem+json`, the shape
that `add-ascend-python-common` (build group 2, position 1, applied before this change) defines and gives every Python
service (owner answer 70.1 of 2026-10-04, the agent follows the same shape later in `upgrade-spring-boot-4` D19): `type`
`https://ascend.ai/errors/<code with - for _>`, `title`, `status`, `detail`, `instance` (the request path), the
extension field `code` and the extension field `traceId`. `traceId` is the 32 character lower case hex trace id of the
current OpenTelemetry span when one is valid, and the field is left out otherwise, never empty and never invented
(the rule of `add-ascend-python-common` D10). This change adds no problem helper of its own. Every body is built
by `problem_response` of the `ascend-python-common` library (its D5), and the handlers already in
`src/api/exception_handlers.py` moved onto the library in `add-ascend-python-common`, so they keep their `type` and
already carry `code` and `traceId`. Each code below is a `ProblemCode` entry in ascend-web-hunter's `ErrorRegistry` in
`src/api/exception_handlers.py`, mapped from the exception that raises it, and the library's handlers answer it.
`enhance-web-search-crawl-at-scale` and `add-file-download` register their codes in the same registry. Codes of this
change:

| Code | Status | When |
| :--- | :--- | :--- |
| `extraction_not_configured` | 400 | `schema` asked for while `EXTRACTION_LLM_BASE_URL` is empty (D3) |
| `screenshot_unavailable` | 400 | `screenshot` asked for while no browser tier is enabled (D7) |
| `bad_request` | 400 | `include_links` with a format other than `text` (D7) |
| `extraction_failed` | 502 | The model's answer is not JSON that validates against the caller's schema (D5) |

A 5xx detail never names an internal host, path or exception text. `extraction_failed` is marked as an expected
upstream code in the registry, like ascend-ocr's `DOWNLOAD_FAILED`, because it reports the model's answer and not a
defect of the service, so it keeps a detail that says what failed (for example that the answer did not validate
against the schema), and only the internal 500 carries the library's fixed detail. The MCP `web_read` tool raises the same registered exceptions, and the library's
`McpRefusalMiddleware` turns each into a tool error whose text starts with its code. The library logs and counts every
refusal on both surfaces (one WARNING line without a traceback, `ascend_service_errors_total{code, surface, operation}`), so this
change adds no refusal logging or counter of its own.

### D9: Module

Everything this change adds is part of ascend-web-hunter, with no setting that switches it. `add-deployment-modules`
(build group 3, position 6) lands later and lists ascend-web-hunter as its module `web-search` (its D3), ascend-ocr as
the module `ocr` and ascend-audio-scribe as the module `audio`. This change does not wait for it and needs no module
switch: when ascend-ocr or ascend-audio-scribe does not run, its route ends with `routing_error` and the HTML
extraction (D6), never with a failed read, both before and after modules exist. docling-serve belongs to document
search, which is core and always runs. An operator who never runs one of them sets its URL setting empty, which turns
the route off.

## Risks

- A model that ignores the instructions. D5 limits the damage to a wrong answer, which schema validation catches when
  the shape is wrong. A right-shaped wrong value is not caught, and the docs say so.
- docling-serve, ascend-ocr and ascend-audio-scribe are slow on large files. The size cap and the timeouts bound it.

## Owner decisions of 2026-10-08

The owner approved on 2026-10-08 the fixes of the review of the group 1 and group 2 changes of 2026-10-07.

- Item 7: D6 and task 1.3 no longer describe a redirect loop of the service. The loop is the library's
  `follow_guarded_redirects` of `add-ascend-python-common`, and this change moves only the curl_cffi `send_hop` and
  the call into `src/fetch/pinned_fetch.py`.
- Item 6: the fake site files and pages the document routing spec of task 7.2 reads, and that no task added, are added
  by task 7.7: the canary audio clip `files/canary.mp3`, the oversized PDF `files/oversized.pdf` and the page
  `/pdf-link-blocked`.
- Item 19: the gate of task 6.3 runs mypy over `src tests`, the same gate as `add-ascend-python-common` D14.
- Owner decision of 2026-10-08, "one named version per change, in build order": this change ships as
  ascend-web-hunter 0.0.12, one patch step after 0.0.11 of `enhance-web-search-tier-ladder` (build group 2,
  position 5), with one CHANGELOG entry (task 6.2).

Answer 87: the read cache is checked against several ascend-web-hunter containers. It stays in each process with its
TTL, because a slightly stale read is not a defect. The purge of a domain on a session clear is a case where a stale
read is a defect, so it now reaches every container through the Redis channel `read_cache_purge` (D7, the MODIFIED
requirement "Read-result caching", task 5.5). The recipes of D4 already live in Redis with a TTL and need nothing more.
No other lock, cache, counter or queue of this change needs to be shared.

Answer 92: review items A1 (document routing done by the agent instead of ascend-web-hunter), A2 (schema extraction
done by the agent) and B4 (no CSS recipes) are not applied, by the owner's own list of things not to apply. Document
routing, schema extraction and the recipes stay in this change.

Answer 91.3: the structured extraction spec of task 7.1 keeps only the steps no lower test proves: the JSON-LD
metadata, the tables and the screenshot on pages the real tiers of the image fetch, the screenshot with a real browser.
The malformed JSON-LD step, the `include_links` refusal and the `extraction_not_configured` refusal are dropped,
because the unit tests of tasks 2.1, 5.1 and 3.1 prove them, with their Bruno requests `structured-broken-jsonld.yml`,
`structured-with-links-refused.yml` and `schema-not-configured.yml`. The document routing spec of task 7.2 stays,
because it is the only test that runs the real docling-serve, ascend-ocr and ascend-audio-scribe. The schema extraction
spec of task 7.3 runs with a real model and stays.

Answer 85.1: the extraction model key of the AI spec (task 7.5) is read from the repository `.env` file like every
other key, and no task of this change exports a key or a secret in a shell.

Answer 93: no small item of the review applies to this change.

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 98: every value of this change that has a default is a setting (owner rule 98 of 2026-10-08). Settings, each
read by `config.py` with its default, passed by `compose.ascend-web-hunter.yaml` and `deploy-standalone/compose.yaml`
as `${VAR:-default}` with the same value, put into both `.env.example` files and the bundle README by the sync rule
(new task 1.5) and listed in `docs/configuration.md` with "Added by `enhance-web-search-extraction-and-tiers`." (task
6.1): `EXTRACTION_SCHEMA_MAX_BYTES` 16384, `EXTRACTION_LLM_BASE_URL` empty, `EXTRACTION_LLM_MODEL` empty,
`EXTRACTION_LLM_MAX_INPUT_CHARS` 60000, `EXTRACTION_LLM_TIMEOUT_SECONDS` 60, `RECIPE_TTL_SECONDS` 604800,
`RECIPE_SELECTOR_MAX_CHARS` 512 (new name, until now a fixed number in D4), `DOCUMENT_MAX_BYTES` 52428800,
`DOCLING_SERVE_URL` `http://docling-serve:5001`, `ASCEND_OCR_URL` `http://ascend-ocr:7022`,
`OCR_ROUTE_TIMEOUT_SECONDS` 300, `AUDIO_SCRIBE_URL` `http://ascend-audio-scribe:7017` and
`READ_CACHE_PURGE_RECONNECT_SECONDS` 5 (new name, the wait of the purge subscriber of D7 between two connection
attempts, default set by owner answer 100.2 of 2026-10-09). `EXTRACTION_LLM_API_KEY` is a secret: no default, `${EXTRACTION_LLM_API_KEY}` from `.env`
only. `EXTRACTION_LLM_MODEL` has no default model, because the format is off until the operator names an endpoint and
its model. The two settings of the recall pass that task 2.2 removes leave the configuration reference, the compose
files, the `.env.example` files and the bundle README in the same commit. Kept as constants, because they are not
operational: the output format names, the problem codes and their statuses (D8), the Redis key shapes `recipe:...` and
the channel name `read_cache_purge`, the docling-serve path `/v1/convert/file` (an API path, read again from the pinned
image in task 4.1), the ascend-ocr and ascend-audio-scribe API paths, the ensemble formula and its tie rule (D2), and
the test-only values of the e2e specs and fake site files (for example the 52428801 byte declared length of
`files/oversized.pdf`, which follows the default of `DOCUMENT_MAX_BYTES`). `MAX_REDIRECT_HOPS` belongs to the library
of `add-ascend-python-common`, which decides it. Tasks changed: 1.2, 2.2, 3.3, 5.5 and 6.1, new task 1.5. No task of
this change is ticked, so nothing is marked for rework. LM Studio in a test: tasks 7.3 and 7.5 ran the AI schema spec
on LM Studio in Scenarios 2 and 4 (owner answer 67.6 of 2026-10-04). This was listed in the round report and is
changed by owner answer 101 of 2026-10-09. No text of this change names the old `e2e` profile, and no text plans several copies elsewhere: D7
already makes the read cache purge reach every container.

## Owner decisions of 2026-10-09

Answer 100.2: `READ_CACHE_PURGE_RECONNECT_SECONDS`, the wait of the D7 purge subscriber between two connection attempts, has the default 5. The Answer 98 record, task 1.2, the compose lines of task 1.5 and the configuration row of task 6.1 carry it.

Answer 101: LM Studio is used only in tests that test LM Studio support. The AI schema extraction spec of task 7.3 does not, so it runs in every scenario on the hosted provider and model the other AI-run specs use, provider `minimax` with model `MiniMax-M2.7` (the model `add-agent-soul` task 3.7 names), through MiniMax's OpenAI-compatible endpoint with `MINIMAX_API_KEY` from `.env`. This replaces owner answer 67.6 of 2026-10-04 (LM Studio in Scenarios 2 and 4, Gemini Flash Lite in Scenarios 1 and 3) for this spec. Tasks 7.3 and 7.5 carry it. The product text of the design that names LM Studio as one possible extraction endpoint stays, because it describes what an operator may configure, not a test.
