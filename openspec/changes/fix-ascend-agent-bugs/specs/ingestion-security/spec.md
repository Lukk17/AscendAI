## ADDED Requirements

### Requirement: Filename sanitization before storage

The ingestion controller SHALL sanitize the user-supplied filename before using it in any storage key (S3 object key, local path, Qdrant `source` metadata). Sanitization SHALL replace any character outside `[A-Za-z0-9._-]` with `_`, strip leading dots (no `.htaccess`-style hidden files), collapse repeated separators, and cap the length at 200 characters.

#### Scenario: Path-traversal attempt is neutralized

- **WHEN** a user uploads a file named `../../etc/passwd.txt`
- **THEN** the stored S3 key contains `_.._.._etc_passwd.txt` (or equivalent) — no `/` separators or leading dots survive
- **AND** the upload does NOT write outside its configured prefix

#### Scenario: Unicode and control characters

- **WHEN** the filename contains spaces, emoji, or control characters
- **THEN** all such characters are replaced with `_` and the resulting key is ASCII-safe

### Requirement: MIME-type allowlist enforced on upload

The ingestion controller SHALL accept uploads only when the request's `Content-Type` matches one of the entries in `app.ingestion.upload.allowed-mime-types`. The default allowlist SHALL include at least `application/pdf`, `text/markdown`, `text/plain`, `image/png`, `image/jpeg`, `image/webp`, and the common DOCX/PPTX MIME types. Mismatches SHALL return HTTP 415 with a clear message.

#### Scenario: Allowed type accepted

- **WHEN** a `.pdf` file is uploaded with Content-Type `application/pdf`
- **THEN** the request proceeds to ingestion

#### Scenario: Disallowed type rejected

- **WHEN** an `.exe` file is uploaded with Content-Type `application/x-msdownload`
- **THEN** the controller returns HTTP 415 with body containing `Unsupported MIME type`
- **AND** no S3 write or Qdrant write occurs

#### Scenario: Missing or generic Content-Type sniffed

- **WHEN** a file is uploaded with Content-Type `application/octet-stream` and a `.pdf` extension
- **THEN** the controller sniffs the first bytes (`%PDF-`) and treats the upload as `application/pdf`

### Requirement: Multipart size limits configured

`application.yaml` SHALL set `spring.servlet.multipart.max-file-size` and `max-request-size` (default 25 MB / 30 MB respectively, override-able via env). Uploads exceeding the limit SHALL fail with HTTP 413 (Payload Too Large) and a clear message, not OOM the JVM.

#### Scenario: Large upload rejected gracefully

- **WHEN** a 100 MB PDF is uploaded with default limits
- **THEN** the controller returns HTTP 413 with body containing `Maximum upload size`
- **AND** AscendAgent does not exhaust heap or crash
