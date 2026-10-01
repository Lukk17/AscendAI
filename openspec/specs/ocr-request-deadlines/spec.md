# ocr-request-deadlines Specification

## Purpose
Bounds how long an OCR request may occupy the service, so a long document is not failed for being long, an expired
request stops consuming processor time, and the requests behind it are served instead of inheriting the wait.

## Requirements

### Requirement: A document's budget is derived per page

The service SHALL derive each document's time budget from the per-page allowance of the engine that reads it, as
the document's page count multiplied by that allowance. A document SHALL NOT be failed merely for having more pages
than a single-page budget covers. No configured ceiling SHALL cap a document's total duration, because no caller
holds a connection against the work, and the page ceiling on what the service accepts is what keeps the product
bounded. How each engine's allowance is derived, and the configured input it follows, are owned by the
`ocr-page-resolution` capability.

#### Scenario: Multi-page document within the derived budget

- **WHEN** a document of several pages is submitted and each page completes inside the per-page allowance
- **THEN** the service produces the full result
- **AND** the document is not failed for exceeding a single-page budget

#### Scenario: No overall ceiling caps the budget

- **WHEN** a document within the page ceiling is submitted whose page count multiplied by the per-page allowance is
  longer than any caller could hold a connection for
- **THEN** its budget is the full product of its page count and its engine's allowance
- **AND** it is not failed for its total duration

#### Scenario: A single page that runs long

- **WHEN** one page of a document consumes more than the per-page allowance
- **THEN** the service stops the document once the budget for the whole document is exhausted
- **AND** the document finishes as failed rather than running unbounded

### Requirement: An expired request stops computing

When a request's budget is exhausted, the service SHALL stop working on it. The component performing inference
SHALL be given the remaining budget as a duration rather than as an absolute point in time, because clocks are not
comparable across processes, and SHALL check that budget before beginning each page. The service SHALL NOT continue
inferring pages of a request whose caller has already been told the request failed.

#### Scenario: Budget expires part way through a document

- **WHEN** a document's budget is exhausted after some of its pages have been processed
- **THEN** no further page of that document is inferred
- **AND** the processor time consumed after the caller was told the request failed is bounded by at most one page

#### Scenario: Budget already exhausted before the first page

- **WHEN** a request reaches the inference stage with no budget remaining
- **THEN** no page is inferred at all

### Requirement: An expired request fails with the existing OCR failure code and returns nothing partial

A document that exhausts its budget SHALL finish as failed with the service's existing OCR failure code, on both the
REST and the MCP surface. The code SHALL arrive inside the document's state, which is read successfully, rather than
as the status of a request held open against the work. The service SHALL NOT return or store a partial result,
because a caller cannot distinguish a truncated document from a short one.

#### Scenario: Timed-out document on the REST surface

- **WHEN** a document submitted over REST exhausts its budget
- **THEN** reading its state reports it failed with the existing OCR failure code
- **AND** the state carries no page or text content and no stored result exists for it

#### Scenario: Timed-out document on the MCP surface

- **WHEN** the same document is submitted through the MCP tool
- **THEN** its state reports the same error code as the REST surface
- **AND** no partial page content is returned

### Requirement: One job at a time, and the limit is explicit

The service SHALL process one OCR job at a time. The concurrency limit SHALL come from a single configured value
that governs both the number of inference workers and the number of requests admitted for inference
simultaneously, so the two cannot disagree. That value multiplies the service's memory peak as well as its
throughput, so the documented memory ceiling SHALL be stated as one job's cost multiplied by it, and the reason for
the limit SHALL be recorded wherever the limit is described.

#### Scenario: A second request arrives while one is running

- **WHEN** a request arrives while another is being inferred
- **THEN** it waits rather than being inferred alongside the first
- **AND** the peak memory of the service does not rise by a second job's cost

#### Scenario: Configured limit governs both sides

- **WHEN** the configured concurrency limit is read
- **THEN** the number of inference workers and the number of simultaneously admitted requests are both equal to it

### Requirement: A worker that will not stop is replaced

A single page's inference cannot be interrupted from outside the process performing it. When the inference process
has not returned within a grace period, derived from its own engine's allowance, after its own budget expired, the service SHALL replace that
process so the queue behind it is served. The service SHALL report itself as unable to take work while the
replacement is in progress, and SHALL resume serving once the replacement is ready.

#### Scenario: Worker does not return after its budget expired

- **WHEN** the inference process has not returned by the end of the grace period following its expired budget
- **THEN** the service replaces it
- **AND** requests waiting in the queue are served by the replacement rather than waiting for the abandoned job

#### Scenario: Service state during replacement

- **WHEN** a replacement is in progress
- **THEN** the service reports that it cannot take work
- **AND** it reports that it can take work again once the replacement is ready

#### Scenario: Normal expiry needs no replacement

- **WHEN** the inference process observes its own expired budget and returns on its own
- **THEN** no replacement occurs
- **AND** the next queued request is served without waiting for a new process to warm up

### Requirement: A worker pool that has broken is rebuilt rather than left broken

When the inference process dies, the pool it belongs to becomes permanently unusable and every subsequent request
would otherwise fail immediately for as long as the service runs. The service SHALL rebuild the pool when it finds
it unusable, by the same path it uses to replace a worker that will not stop, and SHALL resume serving once the
rebuild is ready, without needing the container to be restarted.

#### Scenario: The only worker dies

- **WHEN** the inference process is killed while serving a request
- **THEN** that request fails with the service's existing OCR failure code
- **AND** the service rebuilds the pool and serves the next request rather than failing every request from then on

#### Scenario: The request that killed the worker is not retried

- **WHEN** a request's inference process dies while serving it
- **THEN** that request is not resubmitted for inference

#### Scenario: A document waiting during a rebuild

- **WHEN** a document is waiting for the worker while a rebuild is in progress
- **THEN** it is dispatched once the rebuild completes, with its full reading budget
- **AND** it is not failed for the time it spent waiting

#### Scenario: Repeated rebuild failures stop

- **WHEN** rebuilds fail consecutively up to the configured limit
- **THEN** the service stops rebuilding, reports that it cannot take work, and answers requests definitively
  instead of rebuilding again
- **AND** the count of consecutive failures resets once a request completes successfully

#### Scenario: Rebuilds are visible

- **WHEN** the pool is rebuilt for any reason
- **THEN** the rebuild is recorded so that a service rebuilding repeatedly is observable
