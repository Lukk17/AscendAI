## ADDED Requirements

### Requirement: Defensive MIME type resolution for uploaded image

The agent SHALL resolve a usable `MimeType` for an uploaded image part of `/api/v1/ai/prompt` even when the multipart `Content-Type` for the part is missing, blank, or malformed (does not contain `/`). The agent MUST NOT return HTTP 500 due to MIME parsing failure alone.

#### Scenario: Valid Content-Type provided

- **WHEN** a multipart upload has `Content-Type: image/jpeg` for the `image` part
- **THEN** the resolved `MimeType` is `image/jpeg` and the request continues normally

#### Scenario: Missing Content-Type

- **WHEN** the `image` part has a `null` or blank Content-Type and a filename ending in `.jpg`
- **THEN** the resolved `MimeType` is `image/jpeg` (inferred from filename extension) and the request continues normally

#### Scenario: Malformed Content-Type "file"

- **WHEN** the `image` part has Content-Type literally `"file"` (no `/`)
- **THEN** the agent does NOT throw `InvalidMimeTypeException`, falls back to filename extension or `image/png` default, and the request continues normally; an INFO log records the original malformed value

#### Scenario: Unsupported extension and missing Content-Type

- **WHEN** the `image` part has no Content-Type and filename `image` (no extension)
- **THEN** the resolved `MimeType` defaults to `image/png` and the request continues normally

#### Scenario: No image attached

- **WHEN** the request contains no `image` part
- **THEN** the agent treats the prompt as text-only (existing behavior, unchanged)
