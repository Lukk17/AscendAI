## Purpose

Lets the assistant fetch a file from the web as bytes through ascend-web-hunter, safely and within limits, reusing the service's sessions, fetch tiers and human help, so the owner receives files such as datasheets, schematics, PDFs, images and archives.

## ADDED Requirements

### Requirement: Download operation on MCP and REST

ascend-web-hunter SHALL expose the MCP tool `web_download_file` and the REST endpoint `POST /api/v2/web/downloads`, both taking `url`, an optional `expected_type` (one of `pdf`, `image`, `archive`, `text`, `office`), an optional `file_name` and an optional `profile`. A stored new file SHALL be answered with the download record on MCP and with HTTP 201 and a `Location` header on REST. A file whose content the tenant already holds SHALL be answered with the existing record marked `deduplicated: true`, with HTTP 200 on REST. The record SHALL carry `download_id`, `file_name`, `family`, `content_type`, `size_bytes`, `sha256`, `source_url`, `source_host`, `first_fetched_at`, `last_fetched_at`, `fetch_path`, `scan`, `deduplicated`, `download_url` and `link_expires_at`.

#### Scenario: A PDF is downloaded and stored

- **WHEN** a caller downloads a URL that serves a 2 MiB PDF
- **THEN** the REST answer is 201 with `family` `pdf`, `size_bytes` equal to the file size and `sha256` equal to the SHA-256 of the bytes
- **AND** the answer carries a `download_url` and a `link_expires_at`

#### Scenario: The same file is downloaded twice

- **WHEN** a caller of one tenant downloads the same file a second time, from the same or another URL
- **THEN** the answer is 200 with the same `download_id` and `deduplicated` true
- **AND** no second copy of the content is stored

### Requirement: SSRF guard and connect-time pinning on every hop

A download SHALL accept only `http` and `https` URLs without user info. The first URL and every redirect hop SHALL be checked against the private, loopback, link-local, multicast, reserved and unspecified address rules and SHALL be connected to only at the addresses that check resolved, for every in-process fetch of the download. A relative redirect SHALL be resolved against the hop that returned it before the check. At most 10 redirects SHALL be followed. Requests made through a browser during a download SHALL each be checked before they are sent. A refused URL or hop SHALL be answered with code `unsafe_uri` (HTTP 400 on REST) and SHALL store nothing.

#### Scenario: Private address refused at the start

- **WHEN** a caller downloads `http://10.0.0.5/firmware.zip`
- **THEN** the answer is code `unsafe_uri`
- **AND** no request is sent to that address

#### Scenario: Redirect to a private address refused

- **WHEN** a public URL answers with a redirect to `http://169.254.169.254/latest/meta-data/`
- **THEN** the redirect is not followed and the answer is code `unsafe_uri`

#### Scenario: User info refused

- **WHEN** a caller downloads `https://user:secret@files.example.com/a.pdf`
- **THEN** the answer is code `unsafe_uri`

### Requirement: Streaming with a size limit

The body SHALL be written to a temporary file as it arrives, and the whole file SHALL never be held in memory. A response whose `Content-Length` is above `DOWNLOAD_MAX_BYTES` SHALL be refused before its body is read. A body that grows past `DOWNLOAD_MAX_BYTES` SHALL be cut off at once. Both SHALL be answered with code `file_too_large` (HTTP 422) and SHALL store nothing. The temporary file SHALL be deleted when the call ends, whatever the outcome.

#### Scenario: Declared size over the limit

- **WHEN** the server declares a `Content-Length` one byte over `DOWNLOAD_MAX_BYTES`
- **THEN** the answer is `file_too_large` and no body byte is read

#### Scenario: Undeclared size over the limit

- **WHEN** the server sends no `Content-Length` and streams more than `DOWNLOAD_MAX_BYTES`
- **THEN** reading stops when the count passes the limit and the answer is `file_too_large`
- **AND** no temporary file is left behind

### Requirement: Type decided by content against an allow list

The file family SHALL be decided from the bytes of the file, never from the server's `Content-Type` header or the file name. Executables, Java and Android archives, HTML, XHTML, SVG, text starting with `#!`, macro-enabled Office Open XML files and legacy OLE office files SHALL always be refused. A file whose family is not in `DOWNLOAD_ALLOWED_FAMILIES` SHALL be refused. Both refusals SHALL use code `file_type_not_allowed` (HTTP 422). When `expected_type` is given and the sniffed family differs, the answer SHALL be code `type_mismatch` (HTTP 422). Nothing refused SHALL be stored.

#### Scenario: Executable served as a PDF

- **WHEN** a URL ending in `.pdf` with `Content-Type: application/pdf` serves a Windows executable
- **THEN** the answer is `file_type_not_allowed` and nothing is stored

#### Scenario: KiCad schematic accepted as text

- **WHEN** a caller downloads a KiCad schematic file
- **THEN** the record has `family` `text`

#### Scenario: Expected type not met

- **WHEN** a caller asks for `expected_type` `pdf` and the URL serves a zip archive
- **THEN** the answer is `type_mismatch`

#### Scenario: Macro-enabled office file refused

- **WHEN** the URL serves an Office Open XML file that holds a VBA project part
- **THEN** the answer is `file_type_not_allowed`

### Requirement: Web pages are not files

When a URL serves HTML where a file was asked for, the service SHALL decide with its challenge detection whether the page is a wall. A wall SHALL start the escalation of the next requirement. A page that is not a wall SHALL be answered with code `not_a_file` (HTTP 422), and the detail SHALL tell the caller to read the page and pick the file link from it.

#### Scenario: Landing page instead of a file

- **WHEN** a caller downloads the URL of a product page that links to its datasheet
- **THEN** the answer is `not_a_file` and the detail names reading the page with its links

### Requirement: Reuse of sessions, tiers and human help

A download SHALL replay the stored session of the target domain and profile, including an imported one, on its first request. When that request is blocked, the download SHALL use the service's browser tiers in ladder order to pass the wall, SHALL retry the plain request once with the session they stored, and when still blocked SHALL take the file through the browser. When a browser tier meets a captcha or a login, the call SHALL answer the same human help result a read answers (`human_intervention_required` with `intervention_type` and `vnc_url` on MCP, HTTP 428 with the established body on REST), and a later call after the human solved it SHALL succeed with the captured session. A captured login that no longer validates SHALL be answered as `session_expired` (HTTP 409 on REST) without an anonymous attempt. The record's `fetch_path` SHALL be `direct`, `browser_session` or `browser_download`, naming the step that produced the file.

#### Scenario: Cloudflare wall passed by a browser tier

- **WHEN** the plain request gets a challenge wall and a browser tier passes it
- **THEN** the file is fetched again with the session that tier stored
- **AND** the record has `fetch_path` `browser_session`

#### Scenario: Captcha needs the human

- **WHEN** every automated step meets a captcha
- **THEN** the MCP answer is `human_intervention_required` with a `vnc_url`
- **AND** after the human solves it, the same call returns the stored file

#### Scenario: Imported session used

- **WHEN** a session for the target domain and profile was imported and the file needs that login
- **THEN** the first request carries that session's cookies and the file is stored with `fetch_path` `direct`

### Requirement: Limits on time and concurrency

One download SHALL end within `DOWNLOAD_TIMEOUT_SECONDS` across all automated steps, else it SHALL be answered with code `download_timeout` (HTTP 504) and store nothing. At most `DOWNLOAD_MAX_CONCURRENT` downloads SHALL run at once in one process, and a call beyond that SHALL be answered with code `too_many_downloads` (HTTP 503 with a `Retry-After` of `DOWNLOAD_BUSY_RETRY_AFTER_SECONDS`, a setting with the default 10) without fetching. An upstream failure after every automated step SHALL be answered with code `download_failed` (HTTP 502).

#### Scenario: Slow server

- **WHEN** a server sends the body so slowly that `DOWNLOAD_TIMEOUT_SECONDS` passes
- **THEN** the answer is `download_timeout` and nothing is stored

#### Scenario: Too many at once

- **WHEN** `DOWNLOAD_MAX_CONCURRENT` downloads are running and one more is requested
- **THEN** the answer is `too_many_downloads` with a `Retry-After` header and no request is sent

### Requirement: Monthly download budget per tenant

Each tenant SHALL be allowed to store at most `DOWNLOAD_MONTHLY_BUDGET_BYTES` (default 10 GB, 10,000,000,000 bytes) through downloads in one calendar month, with the month boundary at midnight on the first day of the month in `DOWNLOAD_BUDGET_TIME_ZONE` (default `Europe/Warsaw`). The budget SHALL count the size of every file a download newly stores. A deduplicated download and a keep SHALL add nothing. A download SHALL be refused before any fetch when the tenant has reached the budget for the current month, and a file that would pass the budget left SHALL be cut off while it streams. Both SHALL be answered with code `download_budget_exceeded` (HTTP 429 on REST, with a `Retry-After` header holding the seconds until the next month starts in the budget time zone) and SHALL store nothing. The detail SHALL name the budget and the bytes used this month. A zero or negative budget and an unknown time zone SHALL be refused at startup.

#### Scenario: Budget reached

- **WHEN** tenant `acme` has stored 10 GB through downloads this month and asks for one more file
- **THEN** the answer is `download_budget_exceeded` and no request is sent to the file's host
- **AND** the REST answer carries a `Retry-After` header that ends at midnight on the first day of the next month in `Europe/Warsaw`

#### Scenario: File larger than the budget left

- **WHEN** tenant `acme` has 1 MiB of its budget left and downloads a 5 MiB file
- **THEN** reading stops when the count passes 1 MiB and the answer is `download_budget_exceeded`
- **AND** nothing is stored and the count is unchanged

#### Scenario: A deduplicated download costs nothing

- **WHEN** a tenant downloads a file it already holds
- **THEN** the month's count is unchanged

#### Scenario: New month, new budget

- **WHEN** a tenant reached its budget in September and downloads a file on 1 October at 00:30 in `Europe/Warsaw`
- **THEN** the file is stored and counted against October

### Requirement: Optional malware scan

No virus scanner SHALL run by default anywhere (owner decision 51.2 of 2026-10-03): `DOWNLOAD_SCAN_MODE` SHALL default to `off` in every deployment, the root `.env.example` SHALL NOT put `clamav` in `COMPOSE_PROFILES`, and no committed production setting SHALL hold the companion `clamav` or set the scan mode to `clamav`. An operator turns scanning on only by adding `clamav` to `COMPOSE_PROFILES` and setting `DOWNLOAD_SCAN_MODE` to `clamav`. With `DOWNLOAD_SCAN_MODE` `off` the record SHALL carry `scan.status` `skipped`. With `DOWNLOAD_SCAN_MODE` `clamav` every new file SHALL be scanned before it is stored. A detection SHALL be answered with code `malware_detected` (HTTP 422) and store nothing. A scanner that cannot be reached or fails SHALL be answered with code `scanner_unavailable` (HTTP 503) and store nothing. A deduplicated file SHALL keep the scan result recorded when it was first stored. The ClamAV container SHALL be the compose service `clamav` under the profile `clamav`, the companion of the module `web-download`, in the development stack only, started only when `COMPOSE_PROFILES` in `.env` holds `clamav`, which the documentation names only next to `web-download`. The standalone web-search bundle SHALL carry no ClamAV container, and its README SHALL list that as an intended difference.

#### Scenario: Infected file refused

- **WHEN** scanning is on and clamd reports the EICAR test signature in the file
- **THEN** the answer is `malware_detected` and nothing is stored

#### Scenario: The shipped settings turn no scanner on

- **WHEN** the stack starts with the `COMPOSE_PROFILES` line of the root `.env.example`
- **THEN** `clamav` is not in the list, `docker compose up -d` starts no `clamav` container, and every new download records `scan.status` `skipped`

#### Scenario: ClamAV starts only with its module

- **WHEN** `COMPOSE_PROFILES` in `.env` holds `web-download` but not `clamav`
- **THEN** `docker compose up -d` starts no `clamav` container

#### Scenario: Scanner down while scanning is on

- **WHEN** scanning is on and clamd does not answer
- **THEN** the answer is `scanner_unavailable` and nothing is stored

### Requirement: File names are safe

A caller `file_name` that is empty, longer than `DOWNLOAD_FILE_NAME_MAX_LENGTH` characters (a setting, default 200), holds a path separator, a control character or one of `:*?"<>|`, starts with a dot, or ends in a denied executable, script or web page extension SHALL be refused with code `invalid_file_name` (HTTP 400) before anything is fetched. A name taken from the server SHALL be cleaned by the same rules instead of refused. A missing extension, or one that belongs to another family, SHALL be replaced by the usual extension of the sniffed type.

#### Scenario: Path traversal in the name

- **WHEN** a caller passes `file_name` `../../etc/passwd`
- **THEN** the answer is `invalid_file_name` and nothing is fetched

#### Scenario: Wrong extension corrected

- **WHEN** a caller names the file `board.pdf` and the content is a zip archive
- **THEN** the stored `file_name` ends in `.zip`

### Requirement: Problem bodies for errors

Every REST error of the download endpoints, the human help 428 (code `human_intervention_required`) and the `novnc_busy` 409 included, SHALL be an `application/problem+json` body with `type` `https://ascend.ai/errors/<code with - for _>`, `title`, `status`, `detail`, `instance`, the extension field `code` and the extension field `traceId`, built by the shared problem builder of the `ascend-python-common` library. `traceId` SHALL be the 32 character lower case hex trace id of the current OpenTelemetry span when one is valid, and SHALL be left out otherwise, never empty and never invented. The MCP tools SHALL raise a tool error whose text starts with the same `code`. A 5xx detail SHALL NOT name an internal host, path or exception text.

#### Scenario: Problem body for a large file

- **WHEN** a REST download is refused as too large
- **THEN** the answer has media type `application/problem+json`, `code` `file_too_large` and `type` `https://ascend.ai/errors/file-too-large`

#### Scenario: Human help over REST is a problem body

- **WHEN** a REST download meets a captcha that needs the human
- **THEN** the answer is HTTP 428 with media type `application/problem+json`, `code` `human_intervention_required` and a non-empty `vnc_url` extension member

#### Scenario: Error body carries the trace id

- **WHEN** tracing is on and a caller reads an unknown `download_id`
- **THEN** the problem body carries `code` `download_not_found` and a `traceId` equal to the trace id of that request

#### Scenario: Tracing off still names the trace

- **WHEN** no trace export is configured (`OTEL_EXPORTER_OTLP_ENDPOINT` unset) and a caller reads an unknown `download_id`
- **THEN** the problem body carries `code` `download_not_found` and a `traceId` of 32 lower case hex characters, the id of the unsampled span the library starts for every request

### Requirement: No full URL in logs or metrics

No log line written while serving a download, and no log line of the shared fetch helpers it uses, SHALL contain a full target URL, its path or its query string. Such a line SHALL name the scheme, the host and the first 12 hexadecimal characters of the SHA-256 of the full URL. Presigned links and cookie values SHALL never be logged. No metric label SHALL hold a URL or a file name. The stored `source_url` SHALL have its query string, fragment and user info removed.

#### Scenario: Signed CDN link stays out of the logs

- **WHEN** a caller downloads `https://cdn.example.com/files/a.pdf?token=abc123`
- **THEN** no log line contains `abc123` or `/files/a.pdf`
- **AND** the stored `source_url` is `https://cdn.example.com/files/a.pdf`

### Requirement: Download metrics

ascend-web-hunter SHALL export counters of downloads by outcome and fetch path, refusals by code and scans by result, histograms of size and duration, and a gauge of downloads in flight.

#### Scenario: A stored download is counted

- **WHEN** a download is stored with `fetch_path` `direct`
- **THEN** `ascendwebhunter_downloads_total{outcome="stored",fetch_path="direct"}` grows by one
