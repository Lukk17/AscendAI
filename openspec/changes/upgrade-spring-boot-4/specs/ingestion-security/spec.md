## MODIFIED Requirements

### Requirement: MIME-type allowlist enforced on upload

The ingestion controller SHALL accept uploads only when the request's `Content-Type` matches one of the entries in `app.ingestion.upload.allowed-mime-types`. The default allowlist SHALL include at least `application/pdf`, `text/markdown`, `text/plain`, `image/png`, `image/jpeg`, `image/webp`, and the common DOCX/PPTX MIME types. When every file of an upload is refused, the controller SHALL return HTTP 415 with an `application/problem+json` body whose `code` is `unsupported_media_type` (capability `agent-error-responses`) and whose `detail` names each refused file. Clients and tests SHALL rely on the `code`, not on the wording of the `detail`.

#### Scenario: Allowed type accepted

- **WHEN** a `.pdf` file is uploaded with Content-Type `application/pdf`
- **THEN** the request proceeds to ingestion

#### Scenario: Disallowed type rejected

- **WHEN** an `.exe` file is uploaded with Content-Type `application/x-msdownload`
- **THEN** the controller returns HTTP 415 with `Content-Type: application/problem+json`
- **AND** the body has `code` `unsupported_media_type`
- **AND** no S3 write or Qdrant write occurs

#### Scenario: Missing or generic Content-Type sniffed

- **WHEN** a file is uploaded with Content-Type `application/octet-stream` and a `.pdf` extension
- **THEN** the controller sniffs the first bytes (`%PDF-`) and treats the upload as `application/pdf`

### Requirement: Multipart size limits configured

`application.yaml` SHALL set `spring.servlet.multipart.max-file-size` to 100 MB and `spring.servlet.multipart.max-request-size` to 110 MB, the values the agent ships today, and an operator MAY override both through the environment variables `SPRING_SERVLET_MULTIPART_MAX_FILE_SIZE` and `SPRING_SERVLET_MULTIPART_MAX_REQUEST_SIZE`. An upload over either limit SHALL fail with HTTP 413 and an `application/problem+json` body whose `code` is `content_too_large` (capability `agent-error-responses`) and whose `detail` names the maximum upload size, and SHALL NOT exhaust the heap of the JVM. Clients and tests SHALL rely on the `code`, not on the wording of the `detail`.

#### Scenario: Large upload rejected gracefully

- **WHEN** a 120 MB PDF is uploaded to `POST /api/v1/ingestion/upload` with the shipped limits
- **THEN** the controller returns HTTP 413 with `Content-Type: application/problem+json`
- **AND** the body has `code` `content_too_large`
- **AND** ascend-ai-agent does not exhaust its heap or crash

#### Scenario: Request over the per-request limit rejected

- **WHEN** one request uploads two 60 MB PDFs, each under the 100 MB file limit but 120 MB together, with the shipped limits
- **THEN** the controller returns HTTP 413 with `code` `content_too_large`
- **AND** no S3 write or Qdrant write occurs

#### Scenario: File under both limits accepted

- **WHEN** a 90 MB PDF is uploaded alone with the shipped limits
- **THEN** the request is not refused for its size and proceeds to the MIME-type check
