## ADDED Requirements

### Requirement: Docling client targets the correct upload endpoint

The Docling client SHALL POST multipart files to the `/v1/convert/file` endpoint of `docling-serve`. The default configuration SHALL work out of the box against the `docling-serve` instance defined in the monorepo `docker-compose.yaml` (port 5001).

#### Scenario: Default configuration round-trips

- **WHEN** AscendAgent boots with no overrides for `app.docling.base-url` or `app.docling.api-path` and `docling-serve` is running on `http://localhost:5001`
- **THEN** the resolved Docling URL is `http://localhost:5001/v1/convert/file?to_formats=json`
- **AND** a multipart POST to that URL succeeds (HTTP 200) for a valid PDF

#### Scenario: PDF summarization end-to-end

- **WHEN** a user calls `POST /api/v1/ai/prompt` with a `document=@test.pdf` part
- **THEN** the agent does NOT return HTTP 502 with the message `Failed to process document with Docling`
- **AND** the response includes a summarization of the PDF content

#### Scenario: Defensive normalization of legacy path

- **WHEN** `app.docling.api-path` is configured as exactly `/v1/convert` (the previous incorrect default)
- **THEN** the client logs a WARN at startup explaining the value will be normalized to `/v1/convert/file`
- **AND** subsequent requests target `/v1/convert/file`

### Requirement: Docling endpoint visibility at startup

The Docling client SHALL log the fully-resolved upload URL at startup so misconfiguration is detectable without waiting for the first user request.

#### Scenario: Boot-time log

- **WHEN** AscendAgent finishes startup
- **THEN** the logs contain a single INFO line of the form `[DoclingClient] Configured upload endpoint: <fully-resolved-url>`
