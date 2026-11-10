# Spec Delta

## ADDED Requirements

### Requirement: Every job is visible from any container

Every job SHALL be readable, listable and cancellable through any running container of the service, on both surfaces,
whichever container received the submission and whichever container reads the document. Reading a job's state, its
progress, its result address and its poll hint SHALL give the same answer on every container at the same moment. No
job state SHALL live only in the memory or on the disk of one container.

#### Scenario: A job submitted to one container is read on another

- **WHEN** a document is submitted to one container and its identifier is read on another container
- **THEN** the second container reports the same state, page count and result address as the first

#### Scenario: A finished job is removed through another container

- **WHEN** finished work submitted to one container is removed through another container
- **THEN** its record and its stored result are removed
- **AND** a later read of its identifier on any container reports that it is unknown

## MODIFIED Requirements

### Requirement: Work in flight can be listed

The service SHALL offer an operation that lists every piece of work currently waiting or running, on both surfaces.
Each entry SHALL carry the work's identifier, its state, how many of the document's pages are done out of how many,
how long it has been waiting or running, and its position in the queue. Work that has finished SHALL NOT appear, so
the listing describes what the service is doing rather than what it has done. The listing SHALL hold the work of the
whole service, the same on every container, and SHALL be bounded by the queue's own document bound plus one running
document per running container, so it needs no paging.

#### Scenario: Listing a busy service

- **WHEN** several documents are submitted and the listing is read while one is being read
- **THEN** it reports the running document with its live progress and every waiting document
- **AND** the positions it reports are in submission order and match what each document's own state reports

#### Scenario: Listing through another container

- **WHEN** documents are submitted to one container and the listing is read on another container
- **THEN** it reports the same entries in the same order as the listing read on the first container

#### Scenario: Listing an idle service

- **WHEN** the listing is read while nothing is queued or running
- **THEN** it answers successfully with an empty listing rather than with an error

#### Scenario: Finished work is not listed

- **WHEN** work finishes and the listing is read while its record is still retained
- **THEN** the finished work does not appear in the listing
- **AND** reading it by its own identifier still returns it

#### Scenario: The listing is bounded

- **WHEN** the queue holds as many documents as it will admit and every running container is reading one
- **THEN** the listing returns every one of them in a single answer with no paging

### Requirement: Progress is observable while the work runs

While work is running the service SHALL report how many of the document's pages it has finished reading, both when
its own state is read and in the listing of work in flight, on every container, including a container that is not the
one reading the document. An operator or a caller SHALL be able to tell work that is progressing from work that is
not, without reading logs.

#### Scenario: Progress advances

- **WHEN** the state of running work is read twice, with at least one page's worth of time between the reads and the
  work healthy
- **THEN** the second read reports at least as many completed pages as the first
- **AND** the completed page count never exceeds the document's page count

#### Scenario: Progress read on another container

- **WHEN** a document is being read by one container and its state is read on another container
- **THEN** the completed page count is the one the reading container reached, not zero

#### Scenario: Progress at the moment work starts

- **WHEN** the state is read for work that has just started and has finished no page
- **THEN** it reports zero completed pages rather than omitting the count

### Requirement: Cancelling stops the work

A caller SHALL be able to cancel submitted work at any point before it has finished, through any container. Cancelling
work that has not started SHALL remove it from the queue so that it is never read. Cancelling work that is running
SHALL stop the inference that is in flight on the container that reads it rather than merely marking the record, and
that container SHALL be serving the next submission within the time it takes to make a worker available again.
Cancelling work that has already finished SHALL remove its record and its stored result.

#### Scenario: Cancelling work that has not started

- **WHEN** work that is waiting for the worker is cancelled
- **THEN** no page of it is ever read
- **AND** the work that was behind it in the queue moves up

#### Scenario: Cancelling work that is running

- **WHEN** running work is cancelled
- **THEN** the inference in flight for it stops rather than continuing to the end of the document
- **AND** the service accepts and serves the next submission once a worker is available again

#### Scenario: Cancelling through another container

- **WHEN** work that one container is reading is cancelled through another container
- **THEN** the state reads cancelled at once on every container
- **AND** the container that was reading it stops the inference in flight and stores no result for it

#### Scenario: Cancelling work that already finished

- **WHEN** finished work is cancelled
- **THEN** its record and its stored result are removed
- **AND** a later read of its identifier reports that it is unknown
