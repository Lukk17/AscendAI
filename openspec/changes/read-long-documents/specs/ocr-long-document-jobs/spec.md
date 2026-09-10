## Purpose

Lets a caller hand the service a document that takes far longer to read than any connection can reasonably be held
open for, and collect the result afterwards, without the service ever computing pages for a caller who has gone.

## ADDED Requirements

### Requirement: A document can be submitted for later collection

The service SHALL accept a document for processing and answer immediately with an identifier for the work, instead
of holding the caller until the document has been read. The answer SHALL state that the work was accepted rather
than completed, SHALL carry the identifier, and SHALL tell the caller where the work's state can be read. The
identifier SHALL be unguessable, so that possession of it is what grants access to the result.

#### Scenario: Submission answers before the work is done

- **WHEN** a document is submitted for later collection
- **THEN** the service answers within the time an ordinary request takes, without waiting for any page to be read
- **AND** the answer carries an identifier for the work and the location its state can be read from
- **AND** the answer distinguishes work accepted from work completed

#### Scenario: The identifier is the credential

- **WHEN** two documents are submitted
- **THEN** each receives its own identifier
- **AND** neither identifier can be derived from the other or from the submission

### Requirement: A caller can observe exactly one of five states

The state of submitted work SHALL be readable at any time and SHALL be exactly one of: waiting to start, running,
finished successfully, finished unsuccessfully, or cancelled. Every state SHALL carry the document's page count and
the time the work was submitted. A state that has finished SHALL carry the time it finished. The two finished states
SHALL be terminal, so a caller that reads one never has to read again.

#### Scenario: Work that has not started

- **WHEN** the state is read for work that is waiting for the worker
- **THEN** it reports that it is waiting
- **AND** it reports its position in the queue and how many pages are ahead of it

#### Scenario: Work in progress

- **WHEN** the state is read for work that is being read now
- **THEN** it reports that it is running
- **AND** it reports how many of the document's pages have been read so far

#### Scenario: Work that succeeded

- **WHEN** the state is read for work that finished successfully
- **THEN** it reports success
- **AND** it carries the complete result for every page of the document
- **AND** the result is identical in shape to the result a synchronous request returns for the same document

#### Scenario: Work that failed

- **WHEN** the state is read for work that failed
- **THEN** it reports failure with a stable error code and a reason
- **AND** it carries no partial page content, for the same reason a synchronous request returns none: a caller
  cannot tell a truncated document from a short one

#### Scenario: Work that was cancelled

- **WHEN** the state is read for work a caller cancelled
- **THEN** it reports cancellation rather than failure
- **AND** it carries no result

#### Scenario: A finished state does not change again

- **WHEN** the state is read twice after the work finished, succeeded or failed
- **THEN** both reads report the same state and the same content

### Requirement: Progress is observable while the work runs

While work is running the service SHALL report how many of the document's pages it has finished reading. An operator
or a caller SHALL be able to tell work that is progressing from work that is not, without reading logs.

#### Scenario: Progress advances

- **WHEN** the state of running work is read twice, with at least one page's worth of time between the reads and the
  work healthy
- **THEN** the second read reports at least as many completed pages as the first
- **AND** the completed page count never exceeds the document's page count

#### Scenario: Progress at the moment work starts

- **WHEN** the state is read for work that has just started and has finished no page
- **THEN** it reports zero completed pages rather than omitting the count

### Requirement: The reading deadline is charged from when reading starts

The per-page allowance and the ceiling that bounds submitted work SHALL be counted from the moment the document
starts being read, not from the moment it was submitted. Time spent waiting for the worker SHALL NOT consume the
document's reading budget, because no caller is holding a connection against it and the wait is bounded separately
by the queue's own limits.

#### Scenario: A long wait does not shorten the reading budget

- **WHEN** work waits for the worker for longer than its own reading ceiling and then starts
- **THEN** it is given its full reading budget from the moment it starts
- **AND** it is not failed for having waited

#### Scenario: The reading budget still binds

- **WHEN** running work exceeds its reading ceiling
- **THEN** it is stopped by the same per-page deadline mechanism a synchronous request uses
- **AND** it finishes unsuccessfully with the service's existing OCR failure code and no partial result

### Requirement: Cancelling stops the work

A caller SHALL be able to cancel submitted work at any point before it has finished. Cancelling work that has not
started SHALL remove it from the queue so that it is never read. Cancelling work that is running SHALL stop the
inference that is in flight rather than merely marking the record, and the service SHALL be serving the next
submission within the time it takes to make a worker available again. Cancelling work that has already finished
SHALL remove its record and its result.

#### Scenario: Cancelling work that has not started

- **WHEN** work that is waiting for the worker is cancelled
- **THEN** no page of it is ever read
- **AND** the work that was behind it in the queue moves up

#### Scenario: Cancelling work that is running

- **WHEN** running work is cancelled
- **THEN** the inference in flight for it stops rather than continuing to the end of the document
- **AND** the service accepts and serves the next submission once a worker is available again

#### Scenario: Cancelling work that already finished

- **WHEN** finished work is cancelled
- **THEN** its record and its result are removed
- **AND** a later read of its identifier reports that it is unknown

### Requirement: An unknown identifier gets a definitive answer

Reading or cancelling work by an identifier the service does not hold SHALL fail with a stable not-found code rather
than with an empty success, a server error, or a wait. The service SHALL NOT distinguish an identifier that never
existed from one whose retention window has passed, and the message SHALL say that the identifier is unknown or
expired so a caller is not left guessing which.

#### Scenario: Identifier that never existed

- **WHEN** work is read by an identifier the service never issued
- **THEN** the service answers with its not-found code

#### Scenario: Identifier whose retention window has passed

- **WHEN** work is read by an identifier whose result was deleted at the end of its retention window
- **THEN** the service answers with the same not-found code as for an identifier that never existed
- **AND** the message states that the identifier is unknown or expired

### Requirement: Both surfaces offer the same three operations and agree on everything observable

Submitting, reading state and cancelling SHALL each be available on the REST surface and on the MCP surface. For the
same document and the same sequence of calls, the two surfaces SHALL report the same states, the same page counts,
the same progress, the same error codes and the same result content. Neither surface SHALL offer an operation, a
state or a bound the other does not.

#### Scenario: The same document through either surface

- **WHEN** the same document is submitted over REST and, separately, through the MCP tool
- **THEN** both report the same sequence of states
- **AND** both return the same result content for the same document

#### Scenario: The same refusal through either surface

- **WHEN** a submission that must be refused is sent to each surface
- **THEN** both refuse it with the same error code and equivalent detail

#### Scenario: Work submitted on one surface is readable on the other

- **WHEN** work submitted over REST is read by its identifier through the MCP tool
- **THEN** the state and the result are the same as reading it over REST

### Requirement: The existing synchronous request is unchanged

The synchronous OCR request SHALL keep its current contract on both surfaces. No request parameter SHALL be added
to it, no response field SHALL be removed from it, no existing error code SHALL change its meaning or its status,
and the documents it accepts today SHALL keep being accepted.

#### Scenario: A caller written before this capability existed

- **WHEN** a caller submits a document synchronously exactly as it did before
- **THEN** the request succeeds with the same response shape as before
- **AND** no new parameter is required of it

#### Scenario: A synchronous submission above the synchronous page limit

- **WHEN** a document with more pages than the synchronous path accepts is submitted synchronously
- **THEN** it is refused with the existing oversized-input code, as it is today
- **AND** the refusal names the job path as the way to read a document that long
