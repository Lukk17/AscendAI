## Context

See proposal.md for the motivation. The facts below shape the approach, read from the code and the active changes on 2026-10-02. On 2026-10-04 the agent parts of this change (the agent native tool `knowledge_add_download`, `POST /api/v1/documents/from-download`, the agent's download client and the module marking of the tools on the agent's server entry) moved to the personal change `add-download-ingestion`, and the retention moved from an agent system task into ascend-web-hunter itself (owner rule and instruction of 2026-10-04: the personal assistant comes first, nothing personal, web-hunter or base may depend on company work, and this web-hunter change is build group 2). Decision numbers stay, and D11 now points there.

- `fetch_with_curl_cffi` in `apps/ascend-web-hunter/src/reader/strategies/curl_cffi_fetcher.py` turns off automatic redirects, resolves each `Location` against the hop that returned it, and pins every hop with `CURLOPT_RESOLVE` (ADR-012). After `add-ascend-python-common` (its D21, owner answer 63.2) the check, the pinning and the redirect loop are the library's `check_fetch_uri` and `follow_guarded_redirects`, and `fetch_with_curl_cffi` passes them a curl_cffi `send_hop` that sets `CURLOPT_RESOLVE` from the checked `FetchTarget`. It reads the whole body as text, so it cannot serve a binary file.
- The browser tiers (`4-playwright_stealth`, `6-novnc`, and after `enhance-web-search-tier-ladder` also `4a-patchright` and `4b-camoufox`) load the stored session with `new_context(storage_state=...)`. Their route handler only applies the ad blocklist. ADR-012 already records that the browser cannot be pinned, only checked before dispatch.
- Stored sessions live in Redis per registrable domain and profile (`CookieManager`). `add-web-session-import` adds a way to put a captured login there over REST, and the producer of a session (ADR-010) decides where a read restarts.
- `detect-challenge-walls-in-any-language` adds `ChallengeDetector.assess(status_code, headers, html)`, which returns one verdict with a score and the intervention type.
- `enhance-web-search-extraction-and-tiers` (build group 2, position 6, before this change) fetches PDF, image and audio bytes with `stream_to_file` in `src/fetch/byte_fetch.py`, built on `src/fetch/pinned_fetch.py`, which holds the pinned curl_cffi `send_hop` and its call to the library's `follow_guarded_redirects` (its D6). This change builds its download fetch on the same two functions (D2) instead of a second binary fetch.
- `enhance-web-search-crawl-at-scale` (build group 2, position 9, before this change) creates the one S3 client of the service in `src/storage/object_store.py`, configured by `OBJECT_STORE_S3_ENDPOINT`, `OBJECT_STORE_S3_ACCESS_KEY` and `OBJECT_STORE_S3_SECRET_KEY`, and keeps its own `CRAWL_RESULT_S3_BUCKET` and `CRAWL_RESULT_S3_PREFIX` (its D3). This change stores downloads on that client (D12) and creates no second one.
- `add-mcp-tool-servers` (build group 4, lands later) gives every MCP tool its server prefix (`web` for ascend-web-hunter). A tool whose name already starts with the prefix keeps its name, so `web_search` and `web_read` are unchanged and `session_establish` becomes `web_session_establish`. This change names its tools with the prefix at the source (D1), so it needs nothing of that change.
- `add-agent-skills` (build group 4, lands later) puts `tenant_id`, `user_id` and `request_id` into the tool context of every chat request. Spring AI 2.0.0 ships `ToolContextToMcpMetaConverter`, which turns a tool context into the `_meta` object of an MCP tool call (Spring AI 2.0.0 API index, checked through Context7 on 2026-10-02). Until the agent sends `_meta`, no MCP call carries a tenant and every call runs as `default` (D8).
- Tenant ids are `[a-z0-9-]{1,64}` and every tenant object lives under `tenant/{tenantId}/`, the rule `add-tenant-isolation` later applies to the agent's own buckets and the rule `enhance-web-search-crawl-at-scale` already follows. A personal deployment runs as the tenant `default`. `add-keycloak-login` closes the Python services behind a service token, so only the agent can call them once it is applied.
- ascend-web-hunter error bodies already use `application/problem+json` with the type base `https://ascend.ai/errors`. `add-ascend-python-common` (build group 2, position 1) moves every web-hunter error body onto the problem builder of the `ascend-python-common` library, with the shape that change defines (owner answer 70.1 of 2026-10-04, which the agent follows later in `upgrade-spring-boot-4` D19): a `code` extension field in snake case, a `traceId` and the type slug with `-` for `_`.
- `add-deployment-modules` (build group 3, position 6, lands later) makes `COMPOSE_PROFILES` in the root `.env` the one module switch. The agent receives the list as `ASCEND_MODULES` from that change, and a service that needs the list gets the same line `ASCEND_MODULES: ${COMPOSE_PROFILES:-}` from the change that adds the need (its D2), so this change gives it to ascend-web-hunter itself (D16) and needs nothing of that change. Its catalog later lists the module `web-download` for this change, requiring `web-search`, with the companion `clamav`, and marks the `web_download_*` tools of the `ascend-web-hunter` connection with that module through the per tool module override `tools.overrides.<tool>.module` that `add-mcp-tool-servers` adds to a server entry. The module entry `web-download` joins its `personal` preset, and no preset holds the companion `clamav` (owner decision 51.2 of 2026-10-03). By the owner decision of 2026-10-03, core chat, monitoring, `rag`, memory, the sandbox and the prerequisites are always on and are never switchable modules, so the knowledge base that `knowledge_add_download` writes to is always present. The standalone web-search bundle keeps no profiles and sets no `ASCEND_MODULES`, so it carries no companion of another module.
- ascend-web-hunter has no scheduler library of its own. Its Redis already holds the session store, the tier memory and the indexes of D7, so a periodic job of its own can take a Redis lock to run in one process at a time.

## Goals / Non-Goals

**Goals:**

- One download path that reuses the shared pinned fetch, the stored sessions, the tier ladder and NoVNC, with no copied fetch code.
- Bytes on disk only in a bounded temporary file, never a whole file in memory.
- Every stored object scoped by tenant and found again by its SHA-256.
- No full URL in any log line or metric label.

**Non-Goals:**

- Unpacking, previewing or converting a downloaded file. Archives are stored as they are.
- Resuming a broken download with range requests.
- A job API with polling. A download is one bounded call (see D3).
- Moving a downloaded file into a sandbox workspace of `add-agent-sandbox`. Owner decision of 2026-10-02: a later change, if a subagent ever needs to work on downloaded files.
- Any paid scanning, proxy or solving service.

## Decisions

### D1: Interface

MCP tools on the web-hunter server, named with the `web_` prefix at the source so the name the model sees and the name the service registers are the same:

| Tool | Arguments | Result |
| :--- | :--- | :--- |
| `web_download_file` | `url`, `expected_type` (optional), `file_name` (optional), `profile` (optional) | The download record with a fresh link, or a status object (see below) |
| `web_download_get` | `download_id` | The record with a fresh link |
| `web_download_list` | `limit` (1 to `DOWNLOAD_LIST_MAX_LIMIT`, default `DOWNLOAD_LIST_DEFAULT_LIMIT`, D4), `cursor` (optional) | Records newest first, each with a fresh link, and `next_cursor` |
| `web_download_delete` | `download_id` | `{"status": "deleted", "download_id": ...}`, idempotent |
| `web_download_keep` | `download_id`, `file_name` (optional) | The kept file record with a fresh link (D7) |
| `web_download_kept_get` | `download_id` | The kept file record with a fresh link |
| `web_download_kept_list` | `limit` (1 to `DOWNLOAD_LIST_MAX_LIMIT`, default `DOWNLOAD_LIST_DEFAULT_LIMIT`, D4), `cursor` (optional) | Kept files newest first by keep time, each with a fresh link, and `next_cursor` |
| `web_download_kept_delete` | `download_id` | `{"status": "deleted", "download_id": ...}`, idempotent |

REST on `rest_router_v2` style, a new router `/api/v2/web/downloads`. The `kept` paths are declared before `/{download_id}`, and a `download_id` is always 64 hex characters, so the paths never clash:

| Method | Path | Answer |
| :--- | :--- | :--- |
| POST | `/api/v2/web/downloads` | 201 with the record and a `Location` header, 200 with the record when it was deduplicated, 428 human help (problem body with code `human_intervention_required`), 409 `novnc_busy` (problem body), problem bodies below |
| GET | `/api/v2/web/downloads/{download_id}` | 200 with the record and a fresh link, 404 `download_not_found` |
| GET | `/api/v2/web/downloads` | 200 with `items` and `next_cursor` |
| DELETE | `/api/v2/web/downloads/{download_id}` | 204, also when it did not exist |
| POST | `/api/v2/web/downloads/{download_id}/keep` | 201 with the kept file record and a `Location` header, 200 when the file was already kept, 404 `download_not_found` |
| GET | `/api/v2/web/downloads/kept/{download_id}` | 200 with the kept file record and a fresh link, 404 `download_not_found` |
| GET | `/api/v2/web/downloads/kept` | 200 with `items` and `next_cursor` |
| DELETE | `/api/v2/web/downloads/kept/{download_id}` | 204, also when it did not exist |

All eight routes and the eight tools are registered only when `ASCEND_MODULES` holds `web-download` (D16).

`expected_type` is one of the family names of D5. `profile` has the meaning it has on `web_read`. A `download_id` is the 64 character lower-case hex SHA-256 of the content, and anything else is answered as not found.

The record:

```json
{
  "download_id": "9f2c...e1",
  "file_name": "LM317-datasheet.pdf",
  "family": "pdf",
  "content_type": "application/pdf",
  "size_bytes": 1843200,
  "sha256": "9f2c...e1",
  "source_url": "https://www.ti.com/lit/ds/symlink/lm317.pdf",
  "source_host": "www.ti.com",
  "first_fetched_at": "2026-10-02T09:12:44Z",
  "last_fetched_at": "2026-10-02T09:12:44Z",
  "fetch_path": "direct",
  "scan": {"status": "skipped"},
  "deduplicated": false,
  "download_url": "http://localhost:9070/web-hunter-downloads/tenant/default/downloads/9f2c...e1/content?X-Amz-...",
  "link_expires_at": "2026-10-03T09:12:44Z"
}
```

Status objects of `web_download_file` on MCP, the same shapes `web_read` returns: `human_intervention_required` (with `intervention_type`, `vnc_url`, `message`), `novnc_busy` and `session_expired`. On REST `session_expired` is a 409 problem body, because a POST that creates a resource has no 200 answer for "nothing was created". Every other failure is a problem body on REST and a FastMCP `ToolError` reading `<code>: <detail>` on MCP. The tools raise the registered exceptions of D13, and the library's `McpRefusalMiddleware` maps each to that tool error. The tools and their tests are written against FastMCP 4, which `add-python-runtime-upgrades` (build group 2, position 2, its D8 and D9) puts in every Python service before this change: a test that asserts session behaviour (the `mcp-session-id` header, a status object or refusal on a session) builds `fastmcp.Client` with `mode="legacy"`, and no code or test reads a protocol model field by its camelCase name.

The tool description tells the model how to find a file first: search with `web_search`, read the result page with `web_read` and `include_links` (a `link_filter` such as `.pdf` helps), then call `web_download_file` with the file link, and show the owner `download_url`. It also says that a download is deleted 24 hours after its last download, that downloading the same file again starts the 24 hours again, that the link lasts at most 24 hours, that `web_download_keep` keeps a file the owner or the assistant needs for longer, and that a tenant may store at most the monthly download budget of D4.

Alternative rejected: the name `download_file` at the source. The agent would show it as `web_download_file` anyway, and two names for one tool make logs and docs harder to match.

### D2: One shared pinned fetch, moved not copied

The curl_cffi transport of `fetch_with_curl_cffi` moves into `src/fetch/pinned_fetch.py`: one curl_cffi `send_hop` that sends one request with automatic redirects off to the `FetchTarget` the library guard checked, with `CURLOPT_RESOLVE` set from its addresses, and returns the response without reading the body. The redirect loop is the library's `follow_guarded_redirects` (`add-ascend-python-common` D21, owner answer 63.2): at most 10 redirects, each `Location` resolved against the hop that returned it and checked with `check_fetch_uri` before it is requested. `pinned_fetch` returns the final response object without reading the body. `fetch_with_curl_cffi` keeps its signature and reads `.text` from it. The byte fetch of `enhance-web-search-extraction-and-tiers` D6 is built on the same function (required edit there), as `stream_to_file(url, max_bytes, ...)` in `src/fetch/byte_fetch.py`: it reads the body with `stream=True` in chunks, refuses before reading when `Content-Length` is above the limit, counts bytes as they arrive, stops and deletes the file the moment the count passes the limit, and computes the SHA-256 while it writes. The download path calls `stream_to_file` too. So one redirect loop and one byte fetch serve the read tiers, document routing and downloads.

Alternative rejected: a separate `httpx` client for downloads. It would need its own pinning (httpx has no `CURLOPT_RESOLVE`), and the curl_cffi browser impersonation that already gets past simple bot checks would be lost.

### D3: One bounded call, no job API

A download finishes inside one call, bounded by `DOWNLOAD_TIMEOUT_SECONDS` (default 300) across every step of D6 except the human step, which answers at once with the NoVNC link exactly as a read does. With the default size limit of 100 MiB, 300 seconds allows about 0.35 MiB per second, which covers the owner's use (datasheets and schematics are usually a few MiB). The agent's request timeout for the web-hunter MCP server is raised to cover it (required edit to `add-mcp-tool-servers`, which the agent change `add-download-ingestion` checks).

Alternative rejected: a polling job API like the crawl change. It doubles the operations the model must learn for a call that ends in seconds in nearly every case. If a real need for very large files appears, the crawl job model is the place to add it.

### D4: Limits

| Setting | Default | Meaning |
| :--- | :--- | :--- |
| `DOWNLOAD_MAX_BYTES` | `104857600` (100 MiB) | Largest file. Checked against `Content-Length` first and against the byte count always |
| `DOWNLOAD_TIMEOUT_SECONDS` | `300` | Wall clock for one download, all automated steps together |
| `DOWNLOAD_MAX_CONCURRENT` | `2` | Downloads running at once in one process. One more is refused with 503 `too_many_downloads` and a `Retry-After` of `DOWNLOAD_BUSY_RETRY_AFTER_SECONDS`. Each ascend-web-hunter instance counts its own, because the limit guards that instance's temporary disk and memory |
| `DOWNLOAD_BUSY_RETRY_AFTER_SECONDS` | `10` | The `Retry-After` of a `too_many_downloads` refusal. Refused at startup when zero or negative |
| `DOWNLOAD_LIST_DEFAULT_LIMIT` | `20` | Page size of the download and kept file lists when the call names no `limit` (D1). Refused at startup when below 1 or above `DOWNLOAD_LIST_MAX_LIMIT` |
| `DOWNLOAD_LIST_MAX_LIMIT` | `100` | Largest `limit` of the download and kept file lists (D1). Refused at startup when below 1 |
| `DOWNLOAD_FILE_NAME_MAX_LENGTH` | `200` | Longest file name in characters, for a caller name (refused above it) and a server name (cut to it, extension kept) (D5). Refused at startup when below 1 |
| `DOWNLOAD_WATCHDOG_INTERVAL_SECONDS` | `0.5` | How often the size watchdog of the browser download step reads the partial file (D6 step 5). Refused at startup when zero or negative |
| `DOWNLOAD_BUDGET_COUNTER_EXPIRY_DAYS` | `40` | Days after the start of its month that the budget counter expires (budget below). Refused at startup when below 31, the longest month |
| `DOWNLOAD_LINK_TTL_SECONDS` | `86400` (24 hours) | Lifetime of a presigned link. Refused at startup above `86400`, because a link lasts at most 24 hours (owner decision of 2026-10-02). S3 signature version 4 would allow 7 days |
| `DOWNLOAD_TEMP_DIR` | `ascend-web-hunter-downloads` under the system temp path | Where the stream lands. Each download gets its own file, deleted in a `finally` block whatever the outcome. Files older than `DOWNLOAD_TIMEOUT_SECONDS` are removed at startup |
| `DOWNLOAD_ALLOWED_FAMILIES` | `pdf,image,archive,text,office` | Families of D5 that may be stored. An unknown name is refused at startup |
| `DOWNLOAD_S3_BUCKET` | `web-hunter-downloads` | The bucket, never `knowledge-base`, which is indexed for RAG |
| `DOWNLOAD_SCAN_MODE` | `off` | `off` or `clamav` (D9) |
| `CLAMAV_HOST` / `CLAMAV_PORT` | `clamav` / `3310` | clamd address, read only when the scan mode is `clamav` |
| `CLAMAV_TIMEOUT_SECONDS` | `60` | One scan |
| `DOWNLOAD_MONTHLY_BUDGET_BYTES` | `10000000000` (10 GB) | Bytes one tenant may store through downloads in one calendar month. Refused at startup when zero or negative |
| `DOWNLOAD_BUDGET_TIME_ZONE` | `Europe/Warsaw` | Time zone of the month boundary of the budget. Refused at startup when it is not a known zone |
| `DOWNLOAD_RETENTION_SECONDS` | `86400` (24 hours) | How long after its last download a file is deleted (D7). Refused at startup when zero, negative or above `86400` |
| `DOWNLOAD_RETENTION_SWEEP_SECONDS` | `900` (15 minutes) | Interval of the retention sweep (D7). Refused at startup when zero or negative |

Owner rule 98 of 2026-10-08, every value with a default is a setting. Each row above, `OBJECT_STORE_S3_PUBLIC_ENDPOINT` of D12 included, is a field of the web-hunter `Settings` read from the environment variable of the same name, with the code default equal to the table, and the `ascend-web-hunter` service of `compose.ascend-web-hunter.yaml` passes each one as `- VAR=${VAR:-default}`. Two defaults are derived in code and stay derived: `DOWNLOAD_TEMP_DIR` (the folder under the system temp path) and `OBJECT_STORE_S3_PUBLIC_ENDPOINT` (the value of `OBJECT_STORE_S3_ENDPOINT`), and an empty value means that derived default. Their compose lines are `DOWNLOAD_TEMP_DIR=${DOWNLOAD_TEMP_DIR:-}` and `OBJECT_STORE_S3_PUBLIC_ENDPOINT=${OBJECT_STORE_S3_PUBLIC_ENDPOINT:-http://localhost:9070}`, because inside the container the endpoint is `host.docker.internal`, which the owner's browser does not reach, and `http://localhost:9070` is the public address the existing `OCR_RESULT_S3_PUBLIC_ENDPOINT` line of `compose.yaml` already gives ascend-ocr for the same store. The root `.env.example` gets a commented `# VAR=default` line with a one line comment for each, except `DOWNLOAD_SCAN_MODE=off`, which it sets (D9). The standalone bundle gets none of them, an intended difference listed in its README (D9, task 8.5). Each setting gets a row in `apps/ascend-web-hunter/docs/configuration.md` whose description ends with "Added by `add-file-download`.", in the same commit as the setting.

Monthly download budget (owner answer 45 of 2026-10-02). One tenant may store at most `DOWNLOAD_MONTHLY_BUDGET_BYTES` through downloads in one calendar month. A month starts at midnight on its first day in `DOWNLOAD_BUDGET_TIME_ZONE`. The budget counts the `size_bytes` of every file that a download newly stores. A deduplicated download stores no new bytes and adds nothing, and neither does a keep, which copies a file a download already counted.

- The count is the Redis counter `download_budget:{tenantId}:{yyyy-MM}`, with the month taken in the budget time zone. It is raised with `INCRBY` right after the content is stored and expires `DOWNLOAD_BUDGET_COUNTER_EXPIRY_DAYS` (default 40) days after its month starts.
- A download is refused before any fetch when the tenant's count for the current month has reached the budget.
- While a download streams, its byte limit is the smaller of `DOWNLOAD_MAX_BYTES` and the budget left, for the direct fetch and for the size watchdog of the browser download step alike. When the limit that stops a file is the budget left, the answer is `download_budget_exceeded`, otherwise `file_too_large`. Nothing is stored in either case.
- A budget refusal is a problem body with code `download_budget_exceeded` and HTTP 429 on REST, or a tool error starting with that code on MCP. The REST answer carries a `Retry-After` header with the seconds until the next month starts in the budget time zone, and the detail names the budget and the bytes used this month.
- When the counter is missing (a Redis flush), it is rebuilt before the check from the `meta.json` records of the tenant's downloads whose `first_fetched_at` falls in the current month, and one WARNING line says the rebuilt count can be lower than the real one, because downloads deleted 24 hours after their last download are no longer there to count.
- When Redis cannot be reached, the download is refused with `storage_unavailable`, the same fail closed rule as the index.

The budget and the limits above are this service's own and need no other change. `add-usage-metering-and-quotas` (company, build group 5) registers its ledger row for each stored or deduplicated download later (its task 9.5). This change does not wait for it.

### D5: Type sniffing and the allow list

The family is decided from the bytes, in this order, on the first 64 KiB, as soon as they arrive, so a refused type stops the stream early:

1. Refused at once whatever the settings: Windows PE, ELF and Mach-O executables, Java archives (a zip holding `META-INF/MANIFEST.MF` is checked after the file is complete), Android packages, HTML and XHTML (a document that starts with `<!doctype html`, `<html` or `<?xml` followed by an `<html` root), SVG (an XML root `<svg`, because it can carry script), and text that starts with `#!`.
2. `pdf`: `%PDF-` within the first 1024 bytes, as PDF readers accept.
3. `image`: PNG, JPEG, GIF, WebP, TIFF and BMP by their magic bytes.
4. `office`: a zip whose central directory holds `[Content_Types].xml` (Office Open XML). Refused when it holds `vbaProject.bin` or its content types name a macro-enabled type. Legacy OLE files (`.doc`, `.xls`) are refused, because macros cannot be ruled out without parsing them.
5. `archive`: zip, gzip, bzip2, xz, 7z, tar, rar and zstd by their magic bytes.
6. `text`: the first 64 KiB decode as UTF-8 (a multi-byte character cut at the end of the window is allowed) and hold no NUL byte. This covers the electronics formats the owner named: KiCad schematic and board files, Eagle XML, Gerber and drill files, STEP (`ISO-10303-21;`), SPICE netlists and LTspice files, plus CSV and plain text.
7. Anything else is refused with `file_type_not_allowed`.

Magic-byte detection uses `filetype` (pure Python, no system library), pinned to an exact version after its licence and current release are checked in task 1.1. The zip and text checks are this service's own code over the standard `zipfile` module, which lists entries without extracting them.

When the body is HTML on a URL where a file was asked for, the response goes to `ChallengeDetector.assess` with its status and headers. A wall verdict starts the escalation of D6. A page that is not a wall is answered with 422 `not_a_file`, whose detail tells the caller to read the page with `web_read` and `include_links` to find the file link.

`expected_type`, when given, must equal the sniffed family, else 422 `type_mismatch`. The `Content-Type` header is recorded as a hint in the debug log only.

File name: the caller's `file_name`, else the `filename*` or `filename` of `Content-Disposition`, else the last path segment of the final URL, else `download`. A caller name is refused with 400 `invalid_file_name` when it is empty, longer than `DOWNLOAD_FILE_NAME_MAX_LENGTH` (default 200) characters, holds a path separator, a control character or one of `:*?"<>|`, starts with a dot, or ends in a denied extension (`exe`, `dll`, `msi`, `bat`, `cmd`, `com`, `scr`, `ps1`, `psm1`, `vbs`, `vbe`, `js`, `jse`, `wsf`, `hta`, `jar`, `sh`, `apk`, `app`, `dmg`, `pkg`, `lnk`, `reg`, `svg`, `html`, `htm`, `xhtml`). A name taken from the server is cleaned instead of refused: the same characters are removed and it is cut to `DOWNLOAD_FILE_NAME_MAX_LENGTH` characters keeping its extension. In both cases a missing extension, or one that belongs to another family, is replaced by the usual extension of the sniffed type, so a zip is never stored as `datasheet.pdf`.

### D6: Fetch path, cheapest first

1. Validate: the library's `check_fetch_uri` on the URL (`add-ascend-python-common` D21, owner answer 63.2), which already refuses user info, so this change has no user info refusal of its own, then check `file_name`, the tenant and the monthly budget of D4. Refusals cost no fetch.
2. Session gate: when a login was captured for the target and no longer validates, answer `session_expired` (the same rule `WebReader._session_expired` applies to reads).
3. `direct`: `stream_to_file` with the stored cookies and the stored user agent for the domain and profile, the same replay the curl tiers do. When the tier memory of `enhance-web-search-tier-ladder` names a browser tier for the domain, this step is skipped.
4. `browser_session`: when the direct response is blocked (a 401, 403, 429 or 503, or HTML that `assess` calls a wall), the reader runs its browser tiers on the URL, in ladder order from `4-playwright_stealth`, until one returns accepted content or a navigation that ends in a download. A tier that gets through stores its session as it does for a read, with its producer. The direct fetch is then tried once more with that session and the user agent stored with it.
5. `browser_download`: when the retry is still blocked, or the browser navigation itself started a download, the file is taken through the browser: a context with the stored state, `accept_downloads` on, `page.expect_download()`, and a watchdog that reads the size of the partial file every `DOWNLOAD_WATCHDOG_INTERVAL_SECONDS` (default 0.5 seconds) and cancels the download when it passes `DOWNLOAD_MAX_BYTES` or the time is up. Every request of that context goes through a route handler that refuses a URL failing the SSRF check, the residual browser risk ADR-012 already accepts. The SHA-256 is computed from the finished file.
6. Human help: when a browser tier meets a captcha or login, the read path's existing `6-novnc` escalation runs and the call answers `human_intervention_required` with the NoVNC link. After the human solves it, the session is captured as today and the caller calls `web_download_file` again, which then succeeds at step 3.

The step that produced the file is the record's `fetch_path` (`direct`, `browser_session` or `browser_download`). Tier memory is updated with the browser tier that got through, so the next download from that domain starts at step 4.

Alternative rejected: always downloading through the browser. It is slower, has no connect-time pinning and cannot stop a large download until the next size poll, so it is the last automated step, not the first.

### D7: Storage, metadata and deduplication

The shared S3 client of the crawl change (required edit there) writes to `DOWNLOAD_S3_BUCKET`, which the service creates at startup when it is missing. Several instances may start at once, so an instance that finds the bucket already created by another one goes on without an error.

Keys, with `<sha256>` the content hash:

- `tenant/<tenantId>/downloads/<sha256>/content`: the bytes, with `Content-Type` set to the sniffed type. Written with multipart upload from the temporary file.
- `tenant/<tenantId>/downloads/<sha256>/meta.json`: the record of D1 without the link fields. Written after `content`, so a `meta.json` always means the content exists.

`source_url` is the final URL with the query string, the fragment and any user info removed, because signed CDN links carry their tokens in the query. The full URL is never stored.

Deduplication: after the hash is known and before the upload, the service reads `meta.json` for the same tenant and hash. When it exists, the content is not uploaded again, `last_fetched_at` and `fetch_count` in `meta.json` and the file's score in `download_index:{tenantId}` are updated, the earlier scan result is kept, and the answer has `deduplicated: true`. A hash is never looked up under another tenant, so whether another tenant holds a file is never revealed.

Newest-first listing: a Redis sorted set `download_index:{tenantId}` holds the ids scored by `last_fetched_at`. It is derived data. When the key is missing (a Redis flush), the next list rebuilds it from a listing of the tenant prefix before answering. The cursor is the score and id of the last item, encoded as opaque base64.

Delete removes `content`, then `meta.json`, then the index entry. Each step is a delete-if-exists, so a repeated delete finishes a half-done one. A kept file is deleted the same way under `files/`, and deleting a download never deletes its kept copy.

Retention, owner decision of 2026-10-02: a download is temporary and is deleted automatically 24 hours after its last download (owner answer 47.2 of 2026-10-02). A new download of the same file updates `last_fetched_at` and its score in the index, and so starts the 24 hours again. The deletion runs inside ascend-web-hunter itself (owner instruction of 2026-10-04: no agent system task, so this web-hunter change depends on no agent change). `src/download/retention.py` holds one asyncio task that the service's lifespan starts only when `ASCEND_MODULES` holds `web-download` and cancels on shutdown. Every `DOWNLOAD_RETENTION_SWEEP_SECONDS` (default `900`) it takes the Redis lock `download_retention_lock` with `SET NX EX` for the length of the interval, so with several processes only one sweeps, and a process that does not get the lock skips that round. The sweep lists the tenants that have downloads as the common prefixes under `tenant/` of `DOWNLOAD_S3_BUCKET` (the bucket is the source of truth, so a lost index still finds its tenant), and for each tenant runs the expire operation with `fetched_before` set to now minus `DOWNLOAD_RETENTION_SECONDS` (default `86400`, refused at startup when zero, negative or above `86400`). The expire operation reads the ids scored at or before that time from `download_index:{tenantId}` (rebuilding the index first when it is missing), deletes each one as a delete does, and answers the count. A file is therefore gone at most 24 hours and 15 minutes after its last download. Running a sweep twice deletes nothing more. A failed sweep of one tenant (Redis or the object store down) writes one WARNING line naming the tenant and the failure and is retried at the next round, so an outage delays the deletion and never loses it. The expire operation is internal and has no route and no tool (owner decision 90 of 2026-10-08): its only caller is the sweep, and the fake clock test of task 6.9 proves it.

Keeping a file. When the assistant or the owner needs a file for longer than 24 hours, `web_download_keep` (REST `POST /api/v2/web/downloads/{download_id}/keep`) copies it server side (`CopyObject`, no download through the service) to the persistent folder of the tenant in the same bucket:

- `tenant/<tenantId>/files/<sha256>/content`: the bytes, with the same `Content-Type`.
- `tenant/<tenantId>/files/<sha256>/meta.json`: the download record without the link fields, plus `kept_at` and the `file_name` given to keep (the download's name when none is given, checked by the caller name rules of D5). Written after `content`.

A kept file is listed newest first through a Redis sorted set `kept_index:{tenantId}` scored by `kept_at`, derived data rebuilt from the prefix like the download index. Keeping a file that is already kept answers 200 with the existing record, updating nothing but the name when a new one is given. The retention task never touches `files/`. A kept file stays until it is deleted with `web_download_kept_delete` or by tenant erasure. Its links are signed like download links and last at most 24 hours too (D10).

The three places a downloaded file can be:

| Location | Bucket and key | Lifetime | How it gets there |
| :--- | :--- | :--- | :--- |
| Temporary download | `web-hunter-downloads`, `tenant/<tenantId>/downloads/<sha256>/` | Deleted 24 hours after the last download | `web_download_file` |
| Kept file | `web-hunter-downloads`, `tenant/<tenantId>/files/<sha256>/` | Until deleted | `web_download_keep` |
| Knowledge base | `knowledge-base`, under the tenant prefix of the agent's ingestion path, `documents/<first 16 hex of the id>-<file name>` | Until deleted through document management, and indexed for search | `knowledge_add_download` of `add-download-ingestion` (D11) |

Alternative rejected: an object store lifecycle rule on the `downloads/` prefix. It would delete the bytes behind the service's back and leave the Redis index out of step, and whether Floci, the local object store, applies such rules was not measured.

Alternative rejected on 2026-10-04: the agent system task `web-download-retention` of `add-shared-scheduler` that this design used before. It made a web-hunter change depend on an agent change, which the owner rule of 2026-10-04 forbids for build group 2.

Alternative rejected: a key per file name. Two files with one name would overwrite each other, and the hash is the natural key for deduplication.

### D8: Tenant scoping

Every operation acts on exactly one tenant:

- MCP: the tenant comes from the `_meta` object of the tool call, key `ascend.ai/tenant_id`, which the agent fills from its tool context once `add-mcp-tool-servers` (build group 4) lands (required edit there, checked by `add-download-ingestion`). Until then no MCP call carries it and every call runs as `default`. The model cannot set `_meta`, and the tool schemas have no tenant argument.
- REST: the header `X-Ascend-Tenant`.
- When neither names one, the call runs as the fixed tenant `default`, the tenant a personal deployment runs as, the same rule `enhance-web-search-crawl-at-scale` follows (owner answer 54.5 of 2026-10-03). A caller that needs a tenant and has none of its own, for example a Bruno request for manual use, sends `X-Ascend-Tenant: default`. There is no `DOWNLOAD_DEFAULT_TENANT` setting. A value outside `[a-z0-9-]{1,64}` is refused with 400 `invalid_tenant`.

Until `add-keycloak-login` (build group 3, lands later) closes the service behind its token, any caller who reaches port 7021 can name any tenant. That is the same trust every web-hunter endpoint has today, and the service is meant for the local stack only. After that change only the agent holds the token. Before tenant isolation exists (`add-tenant-isolation`, company, build group 5, which registers its implementation later) every caller of a personal deployment sends `X-Ascend-Tenant: default` or no tenant.

`ascend.ai/request_id` from the same `_meta` is logged as the correlation id of the call.

### D9: Malware scan, off by default everywhere

What ClamAV costs and gives, from its own Docker documentation (https://docs.clamav.net/manual/Installing/Docker.html, read 2026-10-02): the official image is `clamav/clamav:<version>`, clamd listens on 3310, the container needs at least 3 GiB of memory and 4 GiB is preferred, because the signatures alone take about 1.2 GiB and a signature reload briefly needs twice that. freshclam updates the signatures once a day by default. Its detection is signature based, so a new or targeted file is usually not caught.

For the owner's personal deployment the risk it would reduce is small: the service never opens, renders or runs a downloaded file, executables and scripts are refused by D5, and the file reaches the owner's computer through his browser, where his own malware protection scans it. The one place the stack itself parses a downloaded file is the opt-in ingestion of `add-download-ingestion` (D11), where docling-serve and ascend-ocr read a PDF or image. Paying 3 to 4 GiB of memory for a weak signal on that path is not worth it today.

Owner decision 51.2 of 2026-10-03: no virus scanner runs by default anywhere. The seam ships and stays off. `DOWNLOAD_SCAN_MODE` defaults to `off` in every deployment, the personal one, a company deployment and the production setup that `harden-cloud-deployment` (build group 3, position 4) writes later alike. `add-deployment-modules` (build group 3) later keeps the companion `clamav` out of every preset, `personal` included (its preset rule, sent there in the dependency fix of 2026-10-05). `DOWNLOAD_SCAN_MODE=off` records `scan.status: skipped`. `DOWNLOAD_SCAN_MODE=clamav` scans every new file before it is stored, through clamd's `INSTREAM` command over TCP, implemented in about forty lines of `asyncio` in `src/download/scanner.py` rather than through a client package. A `FOUND` answer refuses the file with 422 `malware_detected`, names the signature in a WARNING line and stores nothing. An unreachable or failing clamd refuses with 503 `scanner_unavailable` and stores nothing (fail closed, because an operator who turned scanning on asked for it). Deduplicated files keep their earlier scan result. An operator who wants scanning, for example in a deployment that serves several tenants, adds `clamav` to `COMPOSE_PROFILES` in `.env` and sets `DOWNLOAD_SCAN_MODE=clamav`. Nothing turns it on for him, and `harden-cloud-deployment` keeps it off too.

`compose.ascend-web-hunter.yaml` carries a `clamav` service under the profile `clamav`, which `add-deployment-modules` later lists as the companion of the module `web-download`. It starts only when `COMPOSE_PROFILES` in `.env` holds `clamav`, and the documentation says to add it only next to `web-download`. Once `add-deployment-modules` lands, the agent's module check refuses `clamav` without `web-download`. Nobody passes `--profile` on the command line. The service uses an image pinned to a version tag checked in task 7.2, no published port, the scrapper network only, a named volume for the signature database, `mem_limit` of 4 GiB, a mounted `clamd.conf` that raises `StreamMaxLength`, `MaxFileSize` and `MaxScanSize` to at least `DOWNLOAD_MAX_BYTES` (clamd's own stream limit is lower by default, checked in task 7.2), and no `${VAR:?}` guard, because a service under a profile must not stop a stack that does not start it (the rule `add-deployment-modules` later sets for every service under a module profile). The three clamd limits are derived values whose input is `DOWNLOAD_MAX_BYTES` (owner rule 98 of 2026-10-08). Task 7.2 reads at implementation time, in the documentation of the pinned clamav image, whether its entrypoint takes them from the environment. If it does, the `clamav` service passes them from `${DOWNLOAD_MAX_BYTES:-104857600}` and the mounted file holds none of them. If it does not, they stay in `clamd.conf` at the default of `DOWNLOAD_MAX_BYTES`, and the row of `DOWNLOAD_MAX_BYTES` in `apps/ascend-web-hunter/docs/configuration.md` says that a larger value with the scan on needs the same three lines of that file raised too.

The standalone bundle `apps/ascend-web-hunter/deploy-standalone/` gets no `clamav` service. It keeps no compose profiles and sets no `ASCEND_MODULES`, because it is web search only (the rule `add-deployment-modules` D11 later records too), so its ascend-web-hunter registers no download tool and the scan has nothing to scan. Its README lists the missing `clamav` service and the missing download variables as intended differences (task 8.5).

### D10: Presigned links

Links are signed for `GET` on `content`, with `ResponseContentDisposition` set to `attachment; filename*=UTF-8''<encoded name>` and `ResponseContentType` to the sniffed type, so a browser saves the file instead of rendering it and the owner gets the right name although the key is a hash. Every get, list, create and keep signs a fresh link, valid for `DOWNLOAD_LINK_TTL_SECONDS`, at most 24 hours, for a temporary download and a kept file alike. A link to a temporary download stops working when the retention task deletes the file, even when it was signed less than 24 hours before. The link host is `OBJECT_STORE_S3_PUBLIC_ENDPOINT` (D12), the address the owner's browser reaches, which is not always the address the service reaches. A link is a bearer credential until it expires, so it is never logged.

### D11: Opt-in ingestion is the agent change add-download-ingestion

ascend-web-hunter never calls the agent. Ingestion is an agent operation on an existing download or kept file, and on 2026-10-04 it moved with every other agent part of this change to the personal change `add-download-ingestion` (build group 4): the agent native tool `knowledge_add_download`, `POST /api/v1/documents/from-download` with its role row, the agent's `WebHunterDownloadClient`, and the module marking of the `web_download_*` tools on the agent's `ascend-web-hunter` server entry.

What this change gives it: `GET /api/v2/web/downloads/{id}` and `GET /api/v2/web/downloads/kept/{id}` answer, for the internal caller, the record plus `storage.bucket` and `storage.key`, so the key layout stays known to web-hunter alone and the agent copies the object server side without a second download. The family names of D5 and the key layout of D7 are the contract, and the Pact provider verification of task 8.10 holds this service to it.

### D12: Reusing the crawl change's S3 client

Required edit to `enhance-web-search-crawl-at-scale`: the client is created in `src/storage/object_store.py`, not inside `src/crawl/result_store.py`, configured by `OBJECT_STORE_S3_ENDPOINT`, `OBJECT_STORE_S3_ACCESS_KEY` and `OBJECT_STORE_S3_SECRET_KEY` instead of the three `CRAWL_RESULT_S3_*` connection settings, and it supports multipart upload from a file, get and put of a small JSON object, head, delete, list by prefix with a continuation token, bucket creation, and presigning a `GET`. `result_store.py` keeps the crawl key layout and its own `CRAWL_RESULT_S3_BUCKET` and `CRAWL_RESULT_S3_PREFIX`. This change adds `OBJECT_STORE_S3_PUBLIC_ENDPOINT` (default: the endpoint) and `src/download/download_store.py` with the download key layout on the same client. So one client, one connection setting set, one bucket per purpose.

### D13: Errors

Problem bodies with `type` `https://ascend.ai/errors/<code with - for _>`, `title`, `status`, `detail`, `instance`, the extension field `code` and the extension field `traceId`. `traceId` is the 32 character lower case hex trace id of the current OpenTelemetry span when one is valid, and the field is left out otherwise, never empty and never invented (the rule of `add-ascend-python-common` D10). This change adds no problem helper. Each code below is a `ProblemCode` entry in ascend-web-hunter's `ErrorRegistry` in `src/api/exception_handlers.py`, mapped from the exception that raises it, and the body is built by `problem_response` of the `ascend-python-common` library (its D5), so every body below carries `traceId`. The registry entries of `too_many_downloads` and `download_budget_exceeded` take their `Retry-After` header from the exception. `download_failed` and `download_timeout` are marked as expected upstream codes, like ascend-ocr's `DOWNLOAD_FAILED`, because they report the remote site and not a defect of the service. Codes:

| Code | Status | When |
| :--- | :--- | :--- |
| `unsafe_uri` | 400 | Not http or https, user info in the URL, or a host or redirect hop that resolves to a non-public address |
| `invalid_file_name` | 400 | D5 rules for a caller name |
| `invalid_tenant` | 400 | D8 |
| `not_a_file` | 422 | The URL serves a web page that is not a wall |
| `file_type_not_allowed` | 422 | D5 refusal or a family not in `DOWNLOAD_ALLOWED_FAMILIES` |
| `type_mismatch` | 422 | Sniffed family differs from `expected_type` |
| `file_too_large` | 422 | Over `DOWNLOAD_MAX_BYTES` |
| `malware_detected` | 422 | D9 |
| `download_not_found` | 404 | Unknown id, an id of another tenant, or not a 64 hex string |
| `session_expired` | 409 | D6 step 2, REST only |
| `download_failed` | 502 | Upstream error after every automated step |
| `download_timeout` | 504 | `DOWNLOAD_TIMEOUT_SECONDS` passed |
| `too_many_downloads` | 503 | D4, with `Retry-After` |
| `download_budget_exceeded` | 429 | D4 monthly budget reached, or a file that would pass it, with `Retry-After` |
| `scanner_unavailable` | 503 | D9 |
| `storage_unavailable` | 503 | The object store or the index failed |

The 428 human help and the 409 `novnc_busy` are the problem bodies `add-ascend-python-common` D5 gives every web-hunter answer of that kind (owner answer 60.2 of 2026-10-03, which supersedes the body shape of ADR-003): code `human_intervention_required` with the extension members `intervention_type` and `vnc_url` (and the `flow_id`, `joined` and `window` of `open-several-novnc-windows-at-once`), and code `novnc_busy` with `holder_url`, `holder_profile`, its flow fields and `Retry-After`. They are the same answers `web_read` gives and this change registers no entry for them. Only the internal 500 carries the library's fixed detail. `download_failed`, `download_timeout`, `too_many_downloads`, `scanner_unavailable` and `storage_unavailable` keep a detail that says what failed (for example the remote status code, or that `DOWNLOAD_TIMEOUT_SECONDS` passed). No detail names an internal host, an internal path, an exception text or a full target URL (D14).

### D14: Logs and metrics

`src/observability/url_redaction.py` renders a URL for a log line as `<scheme>://<host>/#<first 12 hex of SHA-256 of the full URL>`. Every log line of `src/fetch/`, `src/download/` and the read path that names a target URL (for example `WebReader.read` and the strategies) uses it, so no line of the service writes a full URL any more. The redaction applies to the service's own log lines only, because the library guard writes no URL into its detail or its log lines (`add-ascend-python-common` D21). The path is left out as well, because some sites put tokens in it. A download writes one INFO line when it ends: redacted URL, outcome, `fetch_path`, family, size, duration, deduplicated flag, tenant and request id. Refusals are logged by the refusal handling of the `ascend-python-common` library, one WARNING line with the code and no traceback on REST and MCP alike, and this change adds no refusal logging of its own. A D13 detail never holds a full target URL, so that line keeps the redaction rule above. Presigned links and cookie values are never logged.

Metrics, all without a URL or file name label:

- `ascendwebhunter_downloads_total{outcome, fetch_path}`, outcome one of `stored`, `deduplicated`, `refused`, `human_intervention`, `failed`.
- No refusal counter of its own. The library's `ascend_service_errors_total{code, surface, operation}` counts every D13 refusal by code, surface and operation (the route template or the tool name), and `ascendwebhunter_downloads_total{outcome="refused"}` counts refused downloads. The `operation` label tells a download refusal from a crawl refusal for the codes both use (`unsafe_uri`, `invalid_tenant`, `storage_unavailable`).
- `ascendwebhunter_download_bytes` histogram, buckets 64 KiB, 256 KiB, 1 MiB, 4 MiB, 16 MiB, 64 MiB, 100 MiB.
- `ascendwebhunter_download_duration_seconds{fetch_path}` histogram, buckets 0.5, 1, 2, 5, 10, 30, 60, 120, 300.
- `ascendwebhunter_downloads_in_flight` gauge.
- `ascendwebhunter_download_scans_total{result}`, result `clean`, `infected`, `error`.
- `ascendwebhunter_downloads_expired_total`, files deleted by the retention sweep.
- `ascendwebhunter_download_keeps_total{outcome}`, outcome one of `kept`, `already_kept`, `not_found`.

The retention sweep of D7 logs one INFO line per tenant with the deleted count, one WARNING line when a tenant's sweep fails, and counts its rounds in `ascendwebhunter_download_retention_sweeps_total{outcome}`, outcome one of `swept`, `skipped_locked`, `failed`.

The startup banner gets one block: bucket, public endpoint, size limit, timeout, concurrency, allowed families, monthly budget and its time zone, scan mode, and whether the bucket and clamd answered. `/ready` reports `object_store` and, in `clamav` mode, `download_scanner` as components, and neither changes the overall verdict, because reads and searches do not need them.

### D15: Tests

- A fake transport in `tests/download/conftest.py`, on the test side only (owner decision 90 of 2026-10-08): the curl_cffi `send_hop` of `pinned_fetch` is replaced in the test by an in-memory fake that answers per URL, the way httpx's `MockTransport` does for httpx clients (the download fetch is curl_cffi, which httpx's `MockTransport` cannot serve), and the guard's address lookup is patched in the test with `unittest.mock` to answer a public address for the test host names. The fake serves a PDF, a PNG, a zip, an Office file with and without a macro part, a KiCad text file, an ELF header, an HTML wall page, an HTML landing page, a file over the limit with and without `Content-Length`, a slow body under a fake clock, redirect chains (relative, absolute, to a private address), and `Content-Disposition` names. The service has no resolver seam, no allowed test host and no `ALLOWED_PRIVATE_HOSTS` value for these tests, and a test with the real lookup proves the guard refuses loopback.
- The browser steps are tested with the strategies faked, as the existing reader tests do. The clamd client is tested against a fake TCP server that answers `OK`, `FOUND`, an error and a closed socket.
- The S3 client is tested with a stubbed client for keys, metadata order, deduplication and delete order, the server side copy of a keep, and the expire operation deleting only downloads fetched before the cutoff and never a kept file.
- The gate is the existing one: `--cov=src --cov-branch --cov-fail-under=100`, with no `pragma: no cover` and no ignore entry.
- The retention sweep with a fake clock and a fake Redis lock: one round per interval, a round skipped while another process holds the lock, every tenant prefix of the bucket swept, a failed tenant retried at the next round, and the task absent with the module off.
- The Pact provider verification for `GET /api/v2/web/downloads/{id}` and `GET /api/v2/web/downloads/kept/{id}` against the pact file the consumer test of `add-download-ingestion` writes, the pattern the agent and ascend-ocr pair already follow, because the agent relies on `storage.key` and the family names.
- End-to-end, per design D10 to D14 of `add-web-search-scraping-e2e`: one deterministic web-hunter spec (`<N>-downloads` against the shared e2e fake site), a public datasheet row in the real-world spec 7 and a human download part in spec 11. Owner decision 91.3 of 2026-10-08 dropped the refusal spec and the limits spec, whose steps the unit tests already prove, the timeout among them through a fake clock instead of a 300 second wait. The agent specs are `add-download-ingestion`'s. The fake site serves the same fixture bytes as the unit test server. Four behaviours are not end-to-end: the log redaction (a log line can never be a pass criterion, so the unit log capture of task 3.2 owns it), the retention (fifteen minutes and 24 hours, so the sweep and its expire operation are proven by the fake clock test of task 6.9), the module switched off (it needs a restart without `web-download`, which no scenario does) and the ClamAV scan (off in every preset by owner decision 51.2, so task 7.3 checks it by hand with the owner's approval).

### D16: The module switch

ascend-web-hunter reads `ASCEND_MODULES` in its `Settings` and registers the eight MCP tools and the eight routes of D1 only when the list holds `web-download`. This change adds `ASCEND_MODULES: ${COMPOSE_PROFILES:-}` to the `ascend-web-hunter` service of `compose.ascend-web-hunter.yaml` itself, the line `add-deployment-modules` D2 asks the change that adds the need to add, so the operator switches downloads on by adding `web-download` to `COMPOSE_PROFILES` in `.env` with no other change applied. Unset or empty means no download tool, the safe default. With the module off, the routes answer 404 like any unknown path, the tools are not listed, and the retention sweep of D7 does not start. The bucket is created at startup only when the module is on. No setting of this change switches the feature on or off. The agent side of the module switch (the per tool module override on the agent's `ascend-web-hunter` server entry and `@ConditionalOnModule("web-download")` on the agent parts) is `add-download-ingestion`.

## Required edits to other changes

This change edits no other change. Each edit below must be made in the named change. No task of this change waits for one: every edit below is either made already or is the later change's own work. Checked on 2026-10-03: the edits to `add-tenant-isolation` and `add-audit-and-gdpr-compliance` are made there, as noted under each heading. `add-deployment-modules` adds its own catalog entry `web-download` when it lands (see its heading below). The edits to `enhance-web-search-crawl-at-scale` and `enhance-web-search-extraction-and-tiers` are made there as well, checked on 2026-10-03. The edits to `add-mcp-tool-servers`, `add-action-approvals`, `add-usage-metering-and-quotas` and `add-agent-skills` concern agent parts and moved with them to `add-download-ingestion` on 2026-10-04.

### `enhance-web-search-crawl-at-scale`

Made there, checked on 2026-10-03: its D3 creates the client in `src/storage/object_store.py` with the operations of D12 here and the `OBJECT_STORE_S3_*` connection settings, `CRAWL_RESULT_S3_BUCKET` and `CRAWL_RESULT_S3_PREFIX` stay, its proposal Impact and tasks 1.2, 1.3, 5.0 and 5.1 carry the `OBJECT_STORE_S3_*` names for config, both compose files, both `.env.example` files and the standalone README table, and its `web-search-crawl-jobs` requirement "Results stored in Floci under a configured prefix" names `OBJECT_STORE_S3_ENDPOINT`. It also keeps its objects under `tenant/<tenantId>/` and answers problem bodies with `code` and `traceId`, the rules of D8 and D13 here.

1. Design D3, proposal Impact and tasks 1.2, 1.3 and 5.1: the S3 client lives in `src/storage/object_store.py`, configured by `OBJECT_STORE_S3_ENDPOINT`, `OBJECT_STORE_S3_ACCESS_KEY` and `OBJECT_STORE_S3_SECRET_KEY`, with the operations listed in D12 of this design. `CRAWL_RESULT_S3_BUCKET` and `CRAWL_RESULT_S3_PREFIX` stay. The compose files, both `.env.example` files and the standalone README table carry the `OBJECT_STORE_S3_*` names.
2. `specs/web-search-crawl-jobs/spec.md`, requirement "Results stored in Floci under a configured prefix": the endpoint is named `OBJECT_STORE_S3_ENDPOINT`.

### `enhance-web-search-extraction-and-tiers`

Made there, checked on 2026-10-03: its D6, its tasks 1.3, 1.4 and 4.2, its proposal and its `web-search-structured-extraction` spec fetch the PDF, image and audio bytes with `stream_to_file` in `src/fetch/byte_fetch.py`, built on `src/fetch/pinned_fetch.py` and the library's `follow_guarded_redirects`, with `DOCUMENT_MAX_BYTES` as its own setting. The bodies of D13 here are built by the problem builder of the `ascend-python-common` library, and that change adds no problem helper of its own (its D8).

1. Design D6 and its tasks: the PDF, image and audio bytes are fetched by `stream_to_file` in `src/fetch/byte_fetch.py`, built on `src/fetch/pinned_fetch.py` (the pinned curl_cffi `send_hop` and its call to the library's `follow_guarded_redirects`), so this change and document routing share one byte fetch. `DOCUMENT_MAX_BYTES` stays its own setting.

### `add-tenant-isolation`

Made in that change, checked on 2026-10-03 (its decision 14 and `specs/tenant-isolation/spec.md`).

1. Design decision 5 and `specs/tenant-isolation/spec.md`: the `web-hunter-downloads` bucket keeps every object under `tenant/{tenantId}/downloads/` or `tenant/{tenantId}/files/`, the agent passes the tenant to web-hunter as in D8, and a download id of another tenant is answered as not found. This change already keeps that layout for tenant `default` and does not wait for `add-tenant-isolation`.

### `add-audit-and-gdpr-compliance`

Made in that change, checked on 2026-10-03 (its erasure table, its retention matrix with `web-download-retention` and kept files, and its proposal).

1. Design line 7 and the erasure orchestrator: a `TENANT` erasure deletes every object under `tenant/{tenantId}/downloads/` and `tenant/{tenantId}/files/` in `web-hunter-downloads` and the Redis keys `download_index:{tenantId}`, `kept_index:{tenantId}` and `download_budget:{tenantId}:*`, through `DELETE /api/v2/web/downloads/{id}` and `DELETE /api/v2/web/downloads/kept/{id}` for each listed id. The retention matrix of `docs/COMPLIANCE.md` lists temporary downloads at 24 hours after the last download (the retention sweep inside ascend-web-hunter, D7) and kept files until deleted. A `USER` erasure has nothing to delete there, because a download record holds no user id (downloads belong to the tenant, like knowledge base documents).

### `add-deployment-modules`

`add-deployment-modules` (build group 3, position 6) lands after this change and adds the catalog entry `web-download` itself (requires `web-search`, uses nothing, owns the companion `clamav`, joins the `personal` preset, no preset holds `clamav`, owner answers 51.2 and 52 of 2026-10-03), together with its preset and compose consistency checks over the `clamav` service of this change (its D3 and task 4.2, and the items of this change's inbox of the dependency fix of 2026-10-05). This change makes no catalog entry and waits for none of it. What this change owns of the module: ascend-web-hunter reading `ASCEND_MODULES` from its own compose line `ASCEND_MODULES: ${COMPOSE_PROFILES:-}` (D16, the rule of that change's D2), the `clamav` service under the profile `clamav` with no `${VAR:?}` guard (D9), and the missing `clamav` and download variables in the intended differences of `deploy-standalone/README.md` (task 8.5). The module marking of the `web_download_*` tools on the agent's `ascend-web-hunter` connection and `@ConditionalOnModule("web-download")` on `knowledge_add_download` and its endpoint moved to `add-download-ingestion` (build group 4) on 2026-10-04.

### Checked, no edit needed

- `add-shared-scheduler`: no longer used. The retention runs inside ascend-web-hunter (D7, owner instruction of 2026-10-04), so this change registers no system task there.
- `add-web-session-import`: an imported session is stored in the same record shape and is replayed by D6 step 3 with no change.
- `detect-challenge-walls-in-any-language`: D5 and D6 call `assess` as every tier does.
- `enhance-web-search-tier-ladder`: D6 reads and writes its tier memory through its own interface.
- `open-several-novnc-windows-at-once`: the human step is the read path's own, so concurrent windows apply to downloads unchanged.
- `remove-flaresolverr-tier`: the download path never uses `3-flaresolverr`.
- `add-agent-sandbox`: its outputs use their own bucket under `tenant/<tenantId>/sandbox-output/`, the same prefix rule as this change, and are not touched. A sandbox reading a download is a later change (Non-Goals).
- `add-keycloak-login`: its service token closes every web-hunter route and tool with no edit here (its section 4), and its task 10.3 adds the token to every Bruno request under `docs/api/request/AscendAI/web-hunter/`, the download requests of this change included. The agent's matrix row for `POST /api/v1/documents/from-download` is `add-download-ingestion`'s.
- `harden-cloud-deployment` (build group 3, position 4, lands later): it sets no scan mode and adds no `clamav`, which is what owner decision 51.2 asks (D9).
- `upgrade-spring-boot-4`: the web-hunter problem bodies have the shape the library of `add-ascend-python-common` defines (owner answer 70.1 of 2026-10-04), which its D19 later follows for the agent. The agent's `ApiErrorCode` values for ingestion are `add-download-ingestion`'s.

## Risks / Trade-offs

- [A file passes sniffing but is harmful, for example a PDF with an exploit or an archive holding an executable] → The service never opens it, the browser saves it as an attachment, the scan is available, and ingestion is opt-in per file.
- [A presigned link leaks through chat history] → It lasts at most 24 hours, a temporary download is deleted 24 hours after its last download, and the owner can delete a download or a kept file at once, which makes the link answer 404.
- [The browser download step has no connect-time pinning] → Every request is checked before dispatch, the same accepted residual risk as the browser read tiers (ADR-012), and it runs only when the pinned steps fail.
- [The size watchdog of the browser step polls, so a file can pass the limit by what arrives in one `DOWNLOAD_WATCHDOG_INTERVAL_SECONDS`] → The temporary file is deleted, nothing is stored, and the overshoot is bounded by link speed times that interval (0.5 seconds by default).
- [Redis index lost] → It is rebuilt from the bucket on the next list.
- [Storage grows without bound] → Temporary downloads are deleted 24 hours after their last download, and each tenant may store at most the monthly download budget through downloads. Kept files grow only when the assistant or the owner keeps one, and delete exists for them.
- [Two downloads running at once both pass the budget check] → Each one is limited to the budget left when it started, so the month total can pass the budget by at most the size of one file per extra concurrent download (`DOWNLOAD_MAX_CONCURRENT` is 2 per instance, so with several instances the bound grows with the number of instances).
- [A Redis flush loses the budget counter] → It is rebuilt from the downloads still stored, which can count less than was really downloaded this month. The WARNING line says so, and the size limit still bounds each file.
- [A file the owner still needs is deleted after 24 hours] → The tool description tells the model to keep a file that is needed longer, and a deleted download can be fetched again.
- [The retention sweep fails, for example with Redis or the object store down] → It logs a WARNING line per failed tenant and retries at the next round, so the deletion is late, never lost.
- [Two web-hunter processes sweep at once] → The Redis lock lets one process sweep per round, and a second sweep of the same cutoff deletes nothing more anyway.
- [Public endpoint not reachable from outside the home network] → The link works only where Floci is reachable, accepted for now by owner decision of 2026-10-02.

## Migration Plan

1. The required edits to `enhance-web-search-crawl-at-scale` and `enhance-web-search-extraction-and-tiers` are made there (checked on 2026-10-03), and both land before this change (build group 2, positions 9 and 6).
2. Land the web-hunter part after `enhance-web-search-crawl-at-scale`. The bucket is created at startup. There is no data to move.
3. The agent part lands later with `add-download-ingestion` (build group 4).
4. Rollback: deploy the previous images. Objects in `web-hunter-downloads` stay and can be removed with the bucket.

## Owner decisions of 2026-10-02

1. Downloaded files are deleted automatically 24 hours after they were last downloaded, by the system task `web-download-retention`, which owner instruction of 2026-10-04 replaced with the retention sweep inside ascend-web-hunter (D7). A file needed longer is kept in `tenant/<tenantId>/files/` with `web_download_keep`, or added to the knowledge base with `knowledge_add_download` of `add-download-ingestion` (D7). Links last at most 24 hours (D10).
2. Links work on the home network for now. Later the agent can stream a file at `GET /api/v1/downloads/{id}/content` behind its own login, as `add-agent-sandbox` does for run outputs.
3. Putting a downloaded file into a sandbox workspace is a later change (Non-Goals).
4. Answer 45: each tenant has a download budget of 10 GB per calendar month, configurable, with the month boundary in `Europe/Warsaw`, counted in bytes stored by downloads and refused with a problem body and the code `download_budget_exceeded` when it is reached (D4).
5. Answer 47.2: a download is deleted 24 hours after its last download, so downloading the same file again starts the 24 hours again (D7).

## Owner decisions of 2026-10-03

1. Answer 51.2: no virus scanner runs by default anywhere. `DOWNLOAD_SCAN_MODE` stays `off` and ClamAV stays off in every preset and every deployment, `harden-cloud-deployment` included. An operator turns it on alone (D9).
2. Core chat, monitoring, `rag`, memory, the sandbox and the prerequisites are always on. `web-search` and `web-download` are switchable modules, so the agent parts, now in `add-download-ingestion`, name only `web-download` (D11, D16).
3. Answer 54.5: a call that names no tenant runs as the fixed tenant `default`, the same rule as `enhance-web-search-crawl-at-scale`. There is no `DOWNLOAD_DEFAULT_TENANT` setting (D8).

## Owner decisions of 2026-10-04

1. Owner rule: the personal assistant comes first. Nothing personal, web-hunter or base may depend on company work. Company work comes last and only plugs in through extension points with safe defaults. This change is build group 2 and depends on no agent change and no company change.
2. Owner instruction: the agent parts (task group 9, the agent specs, `knowledge_add_download`, `POST /api/v1/documents/from-download` and the agent download client) moved to the new personal change `add-download-ingestion`. The 24-hour retention runs inside ascend-web-hunter itself with no agent system task (D7), and a caller that needs a tenant sends `X-Ascend-Tenant: default` (D8).

## Owner decisions of 2026-10-06

1. Answer 72.4 (accepted): until `add-deployment-modules` lands, the `clamav` service starts only when `COMPOSE_PROFILES` names it, through its compose profile `clamav` (D9). Nothing else starts it.
2. Answer 72.1: `harden-cloud-deployment` moved from build group 1 to build group 3, position 4, so it lands after this change. It still sets no scan mode and adds no `clamav`.
3. Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. This change needs none of today's data. Its download store starts empty.

## Owner decisions of 2026-10-08

The owner approved on 2026-10-08 the fixes of the review of the group 1 and group 2 changes of 2026-10-07.

1. Item 6: the fake site pages that steps 11 of task 10.3 and the spec 11 part of task 10.7 read are added by task
   10.11: `/walled-file.pdf` (answers the captcha wall page `/turnstile-wall` of `open-several-novnc-windows-at-once`
   where a file is asked for) and `/gate/canary.pdf` (a page with one button that clears it in the NoVNC window, then
   the canary PDF).
2. Item 10: the ADR for downloads is ADR-020. ADR-013 to ADR-019 are taken by the group 2 changes before this one
   (ADR-018 by `remove-flaresolverr-tier`, ADR-019 by `enhance-web-search-crawl-at-scale`).
3. Item 19: task 10.1 runs mypy over `src tests`, the same gate as `add-ascend-python-common` D14.
4. Item 21: Context lines 9 and 10 state what `enhance-web-search-extraction-and-tiers` and
   `enhance-web-search-crawl-at-scale` really build, and task 1.1 names all six changes before this one, positions 4 to
   9, `remove-flaresolverr-tier` included.
5. Item 22: the version is one patch step after the change before this one, with one CHANGELOG entry.
6. Owner decision of 2026-10-08, "one named version per change, in build order": this change ships as
   ascend-web-hunter 0.0.16, one patch step after 0.0.15 of `enhance-web-search-crawl-at-scale` (build group 2,
   position 9), with one CHANGELOG entry. The bump moves `pyproject.toml`, the `AGENTS.md` version line and
   `docs/architecture/arc42/02-constraints.md` together (task 8.9).

Answer 87 (rule R1): several ascend-web-hunter instances run at once. The retention sweep keeps its Redis lock `download_retention_lock` with `SET NX EX`, so one instance sweeps per round (review item C20, first part, is not applied), and keeps the names `DOWNLOAD_RETENTION_SECONDS` and `DOWNLOAD_RETENTION_SWEEP_SECONDS`. The budget counter, the download and kept indexes, the tier memory and the session store already live in Redis, which every instance shares. `DOWNLOAD_MAX_CONCURRENT` stays a count inside each instance on purpose, because it guards that instance's own temporary disk and memory (D4), and the budget risk line now says that the overshoot bound grows with the number of instances. Bucket creation at startup tolerates a bucket another instance created first (D7, task 6.1). No other lock, cache, queue, timer or stream of this change lives only inside one process.

Answer 85.1: no task of this change exports a key or a secret in a shell. The object store keys come from the repository `.env` through the compose file, and task 7.3 changes only `COMPOSE_PROFILES` and `DOWNLOAD_SCAN_MODE` in `.env`.

Answer 89.14: the spec scenario for an error body without trace export now names the standard switch, no trace endpoint set, instead of the custom `OTEL_ENABLED` that `add-ascend-python-common` drops.

Answer 90: `POST /api/v2/web/downloads/expire` is removed (review item B14). The design said it existed so "an operator or an end-to-end spec forces it now", and no operator use beyond forcing the sweep early is stated anywhere in the plans, while the sweep already runs the same operation every 15 minutes and the fake clock test of task 6.9 proves it. The expire operation stays as internal code that only the sweep calls (D1, D7, tasks 6.7 and 8.1). The unit tests no longer use a resolver seam or an allowed test host in the service: they replace the curl_cffi `send_hop` with an in-memory fake transport on the test side, the curl_cffi form of httpx's `MockTransport`, and patch the address lookup in the test (D15, task 2.2).

Answer 91.3: the refusal spec of task 10.2 and the limits spec of task 10.4 are removed. Every refusal, the concurrency limit and the 300 second `DOWNLOAD_TIMEOUT_SECONDS` are proven by unit tests, the timeout through a fake clock (task 5.5). The downloads spec of task 10.3 keeps the steps no lower test proves: a real stored file and its presigned link, deduplication in the real store, a second tenant, a redirect to a blocked name with the real address lookup, the human help answer, keeping a file with a real server side copy and a deleted kept link answering 404. Its sniffing, `not_a_file`, size limit, paging, budget refusal and expire steps are removed, because tasks 2.1, 4.1, 5.5, 6.2, 6.8 and 6.9 prove them.

Answer 93: review item C20, second part, is applied through answer 91.3 (the 300 second e2e wait is gone). Review items B2 (ClamAV) and B3 (the kept files store) are not applied, because each would cut a capability the owner kept, and the tenant handling of D8 (review item A4) stays by rule R2. From `open-several-novnc-windows-at-once` (its review item B9): its intervention listing now names the count `active_flows`, so the cleanup of step 6 of task 10.3 waits until `GET /api/v2/session/interventions` reports `active_flows` 0. The 428 and 409 bodies of D13 keep every field name.

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 98: every value of this change that has a default is a setting (D4): a field of the web-hunter `Settings` in the module's `DOWNLOAD_*`, `CLAMAV_*` and `OBJECT_STORE_S3_*` naming with the same code default, the compose line `- VAR=${VAR:-default}` on `ascend-web-hunter` in `compose.ascend-web-hunter.yaml`, a commented line in the root `.env.example`, and a row in `apps/ascend-web-hunter/docs/configuration.md` ending "Added by `add-file-download`.", in the same commit as the setting. The names fixed by earlier owner answers stay: `DOWNLOAD_RETENTION_SECONDS`, `DOWNLOAD_RETENTION_SWEEP_SECONDS` and the lock `download_retention_lock`. Made external (name, default): `DOWNLOAD_MAX_BYTES` 104857600, `DOWNLOAD_TIMEOUT_SECONDS` 300, `DOWNLOAD_MAX_CONCURRENT` 2, `DOWNLOAD_BUSY_RETRY_AFTER_SECONDS` 10 (new, was the fixed `Retry-After: 10`), `DOWNLOAD_LIST_DEFAULT_LIMIT` 20 and `DOWNLOAD_LIST_MAX_LIMIT` 100 (new, were the fixed list bounds), `DOWNLOAD_FILE_NAME_MAX_LENGTH` 200 (new, was the fixed name length), `DOWNLOAD_WATCHDOG_INTERVAL_SECONDS` 0.5 (new, was the fixed 500 ms), `DOWNLOAD_BUDGET_COUNTER_EXPIRY_DAYS` 40 (new, was the fixed 40 days), `DOWNLOAD_LINK_TTL_SECONDS` 86400, `DOWNLOAD_TEMP_DIR` (derived, under the system temp path), `DOWNLOAD_ALLOWED_FAMILIES` `pdf,image,archive,text,office`, `DOWNLOAD_S3_BUCKET` `web-hunter-downloads`, `DOWNLOAD_SCAN_MODE` `off`, `CLAMAV_HOST` `clamav`, `CLAMAV_PORT` 3310, `CLAMAV_TIMEOUT_SECONDS` 60, `DOWNLOAD_MONTHLY_BUDGET_BYTES` 10000000000, `DOWNLOAD_BUDGET_TIME_ZONE` `Europe/Warsaw`, `DOWNLOAD_RETENTION_SECONDS` 86400, `DOWNLOAD_RETENTION_SWEEP_SECONDS` 900, `OBJECT_STORE_S3_PUBLIC_ENDPOINT` (derived from `OBJECT_STORE_S3_ENDPOINT` in code, `http://localhost:9070` as the development compose default, the address `compose.yaml` already gives ascend-ocr's `OCR_RESULT_S3_PUBLIC_ENDPOINT`). The three clamd limits are derived from `DOWNLOAD_MAX_BYTES` (D9, task 7.2). The standalone bundle carries none of them, an intended difference (D9, task 8.5). Kept as constants, not operational: the sniffing window of 64 KiB and the `%PDF-` window of 1024 bytes (file format detection rules of D5, not a tuning knob), the always refused types and the denied extensions (security format lists of D5), the redirect limit of 10 (owned by the library guard of `add-ascend-python-common` D21, not by this change), the histogram buckets of D14 (metric definitions), the `download_id` format of 64 hex characters, the tenant format and the tenant `default`, the Redis key and object key names, the error codes, the API paths and the tool names. The `mem_limit` of 4 GiB of the `clamav` service stays a compose resource limit like the limits of every other service, taken from ClamAV's own documentation (D9). Tasks 1.3, 4.2, 5.3, 5.5, 6.2, 6.8, 7.2, 8.5 and 8.7 carry it, new task 1.4 writes the configuration rows, and the requirements of both specs that named the fixed values name the settings. No test or measurement of this change uses LM Studio, and no text of it names the old `e2e` Spring profile or the overlay mount.

## Open Questions

None.
