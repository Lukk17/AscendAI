# Spec Delta

## Purpose

Keeps the transcript files that ascend-audio-scribe offers for download in shared object storage with a bounded
lifetime, so that a download link works on every container of the service and no transcript outlives its expiry.

## ADDED Requirements

### Requirement: A transcript download link works on any container

When ascend-audio-scribe offers a transcript for download (the `download_url` of the final event of a streamed
transcription), the transcript SHALL be stored outside every container, in the object storage the service is
configured with, and `GET /api/v1/transcribe/download/{file_id}` SHALL answer with the transcript on any running
container of the service, with the same file name and content type as today, until the download expires. The
answer to a transcription request itself SHALL NOT change.

#### Scenario: Downloading from another container

- **WHEN** a streamed transcription runs on one container and its `download_url` is requested from another container
  before it expires
- **THEN** the answer is HTTP 200 with the transcript as a Markdown file
- **AND** its content equals the transcription the stream reported

#### Scenario: The transcription answer is unchanged

- **WHEN** a transcription is requested with `stream=false`
- **THEN** the answer is the same Markdown file response as before this capability existed

### Requirement: A transcript download expires and is removed

A stored transcript SHALL be downloadable for `DOWNLOAD_FILE_TTL_SECONDS` after it was stored and SHALL then answer
HTTP 404 on every container with a problem body, as an unknown identifier does today. The service SHALL remove the
stored object of an expired transcript within one cleanup interval (`DOWNLOAD_CLEANUP_INTERVAL_SECONDS`) after it
expired. The removal SHALL be safe when several containers run it at once, and a container that stops SHALL leave no
transcript behind that the others do not remove.

#### Scenario: An expired download

- **WHEN** a transcript's download is requested on any container after `DOWNLOAD_FILE_TTL_SECONDS` have passed
- **THEN** the answer is HTTP 404 with a problem body

#### Scenario: The stored object is removed

- **WHEN** a transcript expired more than one cleanup interval ago
- **THEN** the object storage holds no object for it

#### Scenario: Two containers clean up at once

- **WHEN** two containers run their cleanup at the same moment over the same expired transcripts
- **THEN** every expired transcript is removed once and neither cleanup fails

#### Scenario: An unknown identifier

- **WHEN** a download is requested for an identifier that was never issued
- **THEN** the answer is HTTP 404 with a problem body
