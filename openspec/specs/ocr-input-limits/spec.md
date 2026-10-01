# ocr-input-limits Specification

## Purpose
Refuses a decompression bomb before any of it is decoded, so absurd input is a deterministic error to the caller
instead of an out-of-memory kill that destroys the shared worker. The source pixel ceiling itself, and what happens to
a page larger than the service reads, are owned by the `ocr-page-resolution` capability.

## Requirements

### Requirement: The guard runs before decoding

The service SHALL determine a raster image's pixel count from the submission's header, before the image is decoded
and before any pixel buffer is allocated. A file that declares dimensions above the source pixel ceiling SHALL be
refused during that header read, so that a small compressed file which would expand into an enormous image never
allocates.

#### Scenario: Decompression bomb

- **WHEN** a small file declaring a pixel count far above the source pixel ceiling is submitted
- **THEN** the service refuses it during the header read
- **AND** no full-size pixel buffer is ever allocated

#### Scenario: Guard precedes the worker

- **WHEN** a submission is refused on the source pixel ceiling
- **THEN** the inference worker is never occupied by that request

### Requirement: Refusals reuse the existing error model

Every refusal in this capability SHALL use the service's existing oversized-input error code and its HTTP status.
No new error code SHALL be introduced. Both the REST surface and the MCP surface SHALL refuse identically, with the
same code and the same detail.

#### Scenario: Error code on the REST surface

- **WHEN** any of the limits in this capability refuses a submission over REST
- **THEN** the response carries the service's existing oversized-input error code and its status

#### Scenario: Both surfaces agree

- **WHEN** the same oversized submission is sent to the REST surface and to the MCP tool
- **THEN** both refuse it with the same error code and equivalent detail
