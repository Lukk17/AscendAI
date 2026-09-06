## Purpose

Refuses input the service cannot read within its memory limit, before any of it is decoded, so an oversized page is
a deterministic error to the caller instead of an out-of-memory kill that destroys the shared worker.

## ADDED Requirements

### Requirement: One inference receives no more than a configured number of pixels

The service SHALL refuse any submission whose input to a single inference would exceed a configured pixel ceiling.
For a raw image that input is the image's own decoded dimensions. For a document that input is a page rendered at
the fixed resolution the OCR library uses, which is derived from the page's physical size rather than from the
resolution the caller scanned at. The ceiling SHALL be configurable and its default SHALL be derived from measured
memory cost against the container's memory limit.

#### Scenario: Raw image above the pixel ceiling

- **WHEN** an image whose decoded pixel count exceeds the ceiling is submitted
- **THEN** the service refuses it
- **AND** the service continues to serve the next request normally, proving no worker was lost

#### Scenario: Raw image within the pixel ceiling

- **WHEN** an image whose decoded pixel count is at or below the ceiling is submitted
- **THEN** the service processes it as it does today

#### Scenario: Document page above the pixel ceiling

- **WHEN** a document is submitted whose page, at the library's fixed rendering resolution, would exceed the pixel
  ceiling
- **THEN** the service refuses it before any page is rendered

#### Scenario: Byte size and pixel count are separate limits

- **WHEN** a submission is within the existing file size limit but above the pixel ceiling
- **THEN** it is refused on the pixel ceiling
- **AND** the refusal names the measured pixel count and the ceiling it exceeded

### Requirement: The guard runs before decoding

The service SHALL determine the pixel count from the submission's header, before the image is decoded and before
any pixel buffer is allocated. A file that declares dimensions above the ceiling SHALL be refused during that
header read, so that a small compressed file which would expand into an enormous image never allocates.

#### Scenario: Decompression bomb

- **WHEN** a small file declaring a pixel count far above the ceiling is submitted
- **THEN** the service refuses it during the header read
- **AND** no full-size pixel buffer is ever allocated

#### Scenario: Guard precedes the worker

- **WHEN** a submission is refused on the pixel ceiling
- **THEN** the inference worker is never occupied by that request

### Requirement: A document with too many pages to finish is refused up front

The service SHALL refuse a document whose page count multiplied by the per-page time allowance exceeds the absolute
request ceiling, before any inference starts. Starting a job that provably cannot finish inside the service's own
ceiling occupies the only worker for the whole ceiling and tells the caller nothing until it expires. The page count
limit SHALL be configurable and SHALL be derived from the per-page allowance and the request ceiling.

#### Scenario: Document with more pages than the ceiling allows

- **WHEN** a document is submitted whose page count exceeds the derived limit
- **THEN** the service refuses it immediately
- **AND** the refusal names the document's page count and the limit
- **AND** no page is inferred

#### Scenario: Document at the page limit

- **WHEN** a document is submitted whose page count is exactly at the limit
- **THEN** it is accepted and processed

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
