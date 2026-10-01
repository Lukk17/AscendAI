# ocr-job-lifecycle Specification

## Purpose
Makes every document the service reads a piece of work with an identifier, submitted and collected rather than
waited for on a held connection, so that no document's length decides whether it can be read and the service never
computes pages for a caller who has gone. The text it produces is written to the platform's object storage as a
Markdown file and the work's state carries that file's address, so what a caller polls stays small however long the
document is.

## Requirements

### Requirement: Every document is submitted for later collection

The service SHALL accept a document for processing and answer immediately with an identifier for the work, instead
of holding the caller until the document has been read. This SHALL be the only way a document is read: there SHALL
be no length, parameter or surface at which the service answers a submission with the document's content. The answer
SHALL state that the work was accepted rather than completed, SHALL carry the identifier, and SHALL tell the caller
where the work's state can be read. The identifier SHALL be unguessable, so that possession of it is what grants
access to the result.

#### Scenario: Submission answers before the work is done

- **WHEN** a document is submitted
- **THEN** the service answers within the time an ordinary request takes, without waiting for any page to be read
- **AND** the answer carries an identifier for the work and the location its state can be read from
- **AND** the answer distinguishes work accepted from work completed

#### Scenario: A one page document takes the same path as a long one

- **WHEN** a single page image is submitted
- **THEN** it is accepted with an identifier exactly as a document at the page ceiling is
- **AND** its content is readable only by reading its state afterwards

#### Scenario: There is no synchronous alternative on either surface

- **WHEN** the operations each surface offers are enumerated
- **THEN** neither surface offers any operation that answers with a document's content in the same call that
  supplied the document

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
- **AND** it carries the address of the stored result and the description of the document that does not grow with
  it, which is the source filename, the language, the page count and the time the reading took

#### Scenario: Work that failed

- **WHEN** the state is read for work that failed
- **THEN** it reports failure with a stable error code and a reason
- **AND** it carries no partial page content and no result address, because a caller cannot tell a truncated
  document from a short one

#### Scenario: Work that was cancelled

- **WHEN** the state is read for work a caller cancelled
- **THEN** it reports cancellation rather than failure
- **AND** it carries no result

#### Scenario: A finished state does not change again

- **WHEN** the state is read twice after the work finished, succeeded or failed
- **THEN** both reads report the same state and the same content

### Requirement: The result is a Markdown document in object storage and the state carries its address

The recognised text of a successful reading SHALL be written to the platform's object storage as a single Markdown
document, one object per piece of work, and SHALL NOT be carried in the state a caller polls. The state of
successful work SHALL carry enough to fetch that object both by a caller that can address the storage directly and
by a caller that cannot, and the address SHALL NOT outlive the object it points at. The object SHALL be written
before the work is recorded as successful, so that success always has a result behind it. The size of a state
answer SHALL NOT grow with the document's page count in any state.

#### Scenario: The result is fetchable

- **WHEN** work finishes successfully and its state is read
- **THEN** the answer names the stored object in a form the platform's own services already use to address that
  storage
- **AND** it also carries a time-limited link that a caller holding no credentials can fetch
- **AND** fetching either way returns the same Markdown

#### Scenario: What the Markdown contains

- **WHEN** the stored result of a multi-page document is fetched
- **THEN** it carries the recognised text of every page, in page order and in reading order within a page
- **AND** each page is separated by a heading naming its page number
- **AND** it carries nothing else, so a caller can index it as the document's text without stripping anything first

#### Scenario: A polled state stays small

- **WHEN** the state of a document at the page ceiling is read, both while running and after it succeeded
- **THEN** neither answer is materially larger than the same answers for a single page document

#### Scenario: Success is never claimed without a result

- **WHEN** the result object cannot be stored
- **THEN** the work is never reported as successful
- **AND** it finishes unsuccessfully with a reason that says the result store was at fault rather than the document

#### Scenario: The link cannot outlive the result

- **WHEN** the state of successful work is read shortly before its retention window ends
- **THEN** the link it carries expires no later than the stored object does

### Requirement: Work in flight can be listed

The service SHALL offer an operation that lists every piece of work currently waiting or running, on both surfaces.
Each entry SHALL carry the work's identifier, its state, how many of the document's pages are done out of how many,
how long it has been waiting or running, and its position in the queue. Work that has finished SHALL NOT appear, so
the listing describes what the service is doing rather than what it has done. The listing SHALL be bounded by the
queue's own document bound plus the one running document, so it needs no paging.

#### Scenario: Listing a busy service

- **WHEN** several documents are submitted and the listing is read while one is being read
- **THEN** it reports the running document with its live progress and every waiting document
- **AND** the positions it reports are in submission order and match what each document's own state reports

#### Scenario: Listing an idle service

- **WHEN** the listing is read while nothing is queued or running
- **THEN** it answers successfully with an empty listing rather than with an error

#### Scenario: Finished work is not listed

- **WHEN** work finishes and the listing is read while its record is still retained
- **THEN** the finished work does not appear in the listing
- **AND** reading it by its own identifier still returns it

#### Scenario: The listing is bounded

- **WHEN** the queue holds as many documents as it will admit and one more is being read
- **THEN** the listing returns every one of them in a single answer with no paging

### Requirement: A caller is told when to ask again

Every state that is not terminal SHALL carry a hint saying how long the caller should wait before reading the state
again. The hint SHALL be derived from the work still ahead of the document, each page at its own engine's per-page
allowance, SHALL
never ask a caller to read more than once a second, and SHALL never ask a caller to leave a finished result
uncollected for longer than a short bounded interval. A terminal state SHALL NOT carry the hint, so that its absence
is itself the signal that there is nothing left to ask.

#### Scenario: A hint while the work is waiting or running

- **WHEN** the state is read for work that is waiting or running
- **THEN** the answer carries a hint for when to read again
- **AND** the hint is at least one second and at most a short bounded interval

#### Scenario: The hint shrinks as the work progresses

- **WHEN** the state is read early in a long document and again near its end
- **THEN** the later hint is no longer than the earlier one

#### Scenario: No hint on a terminal state

- **WHEN** the state is read for work that succeeded, failed or was cancelled
- **THEN** the answer carries no hint for when to read again

### Requirement: Submission is bounded by the input it must read

The time a submission takes to be answered SHALL be set by reading the submitted bytes and their page header, and
SHALL NOT scale with the document's page count or with the work already queued. Where the document is supplied as a
URI rather than as bytes, the fetch SHALL be bounded by the service's existing download timeout, so that a slow
source delays a submission by a bounded amount rather than indefinitely.

#### Scenario: A long document is accepted as quickly as a short one

- **WHEN** a document at the page ceiling and a one page document are each submitted to an idle service
- **THEN** both are answered in the same order of time, without either being read

#### Scenario: A busy queue does not slow submission

- **WHEN** a document is submitted while other work is waiting and one document is being read
- **THEN** the submission is answered without waiting for any of that work

#### Scenario: A slow source is bounded

- **WHEN** a document is submitted as a URI whose source does not respond
- **THEN** the submission fails on the service's existing download timeout with its existing code
- **AND** no identifier is issued for it

### Requirement: Progress is observable while the work runs

While work is running the service SHALL report how many of the document's pages it has finished reading, both when
its own state is read and in the listing of work in flight. An operator or a caller SHALL be able to tell work that
is progressing from work that is not, without reading logs.

#### Scenario: Progress advances

- **WHEN** the state of running work is read twice, with at least one page's worth of time between the reads and the
  work healthy
- **THEN** the second read reports at least as many completed pages as the first
- **AND** the completed page count never exceeds the document's page count

#### Scenario: Progress at the moment work starts

- **WHEN** the state is read for work that has just started and has finished no page
- **THEN** it reports zero completed pages rather than omitting the count

### Requirement: The reading deadline is charged from when reading starts

The per-page allowance and the ceiling that bounds a document SHALL be counted from the moment the document starts
being read, not from the moment it was submitted. Time spent waiting for the worker SHALL NOT consume the document's
reading budget, because no caller is holding a connection against it and the wait is bounded separately by the
queue's own limits.

#### Scenario: A long wait does not shorten the reading budget

- **WHEN** work waits for the worker for longer than its own reading ceiling and then starts
- **THEN** it is given its full reading budget from the moment it starts
- **AND** it is not failed for having waited

#### Scenario: The reading budget still binds

- **WHEN** running work exceeds its reading ceiling
- **THEN** it is stopped by the same per-page deadline mechanism that governs every document
- **AND** it finishes unsuccessfully with the service's existing OCR failure code and no partial result

### Requirement: Cancelling stops the work

A caller SHALL be able to cancel submitted work at any point before it has finished. Cancelling work that has not
started SHALL remove it from the queue so that it is never read. Cancelling work that is running SHALL stop the
inference that is in flight rather than merely marking the record, and the service SHALL be serving the next
submission within the time it takes to make a worker available again. Cancelling work that has already finished
SHALL remove its record and its stored result.

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
- **THEN** its record and its stored result are removed
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

#### Scenario: An identifier that is not shaped like one

- **WHEN** work is read by an identifier containing path separators, traversal sequences or more characters than an
  identifier holds
- **THEN** the service answers with the same not-found code
- **AND** no path and no storage key is built from it

### Requirement: Both surfaces offer the same four operations and agree on everything observable

Submitting, reading state, listing work in flight and cancelling SHALL each be available on the REST surface and on
the MCP surface. For the same document and the same sequence of calls, the two surfaces SHALL report the same
states, the same page counts, the same progress, the same hints, the same result addresses, the same error codes and
the same listing content. Neither surface SHALL offer an operation, a state or a bound the other does not.

#### Scenario: The same document through either surface

- **WHEN** the same document is submitted over REST and, separately, through the MCP tool
- **THEN** both report the same sequence of states
- **AND** both name a stored result whose content is the same for the same document

#### Scenario: The same refusal through either surface

- **WHEN** a submission that must be refused is sent to each surface
- **THEN** both refuse it with the same error code and equivalent detail

#### Scenario: Work submitted on one surface is readable on the other

- **WHEN** work submitted over REST is read by its identifier through the MCP tool
- **THEN** the state and the result address are the same as reading it over REST

#### Scenario: The listing agrees across surfaces

- **WHEN** the listing is read on both surfaces while the same work is queued and running
- **THEN** both report the same entries, in the same order, with the same positions

### Requirement: The synchronous request is removed

The service SHALL NOT offer an operation that answers a submission with the document's content. The REST endpoint
that did so SHALL answer with a gone status and a distinct code naming the submission operation that replaces it,
for one documented release window, so that a caller compiled against the old URL learns what happened rather than
reading a not-found. The MCP tool that did so SHALL NOT be advertised at all, because a tool catalogue is discovered
on every connection and an advertised tool costs every caller context on every request.

#### Scenario: A caller written before this capability existed

- **WHEN** a caller posts a document to the removed synchronous endpoint
- **THEN** the service answers with the gone status and the removal code
- **AND** the message names the submission operation that replaces it

#### Scenario: The removed tool is not advertised

- **WHEN** the MCP tool catalogue is listed
- **THEN** it offers the submit, status, list and cancel tools
- **AND** it does not offer the removed synchronous tool under any name

#### Scenario: No submission answers with page content

- **WHEN** a document is submitted on either surface
- **THEN** the answer carries an identifier and no page content
