# ocr-job-retention Specification

## Purpose
Says how long a completed result lives, where it lives, who removes it, and what happens to work that was in flight
when the service stopped, so that a long reading is not lost to a restart and a document's text does not accumulate
in the platform's object storage forever.

## Requirements

### Requirement: A completed result is kept for a bounded window and then removed by the service

The service SHALL keep a completed result, both the record and the stored object it points at, for a configurable
retention window measured from the moment the work finished, and SHALL remove both once that window has passed,
without an operator or a caller having to ask. The default window SHALL be long enough that a caller whose polling
stopped can restart it and still collect the result, and the documentation SHALL state what the window costs, which
is that a document's extracted text remains in the platform's object storage for that long.

#### Scenario: Result inside the retention window

- **WHEN** a completed result is read at any point before its retention window has passed
- **THEN** the service returns its state and the address of the stored object
- **AND** the stored object is still there

#### Scenario: Result after the retention window

- **WHEN** the retention window for a completed result has passed
- **THEN** the service has removed the record and the stored object within a bounded time of the window ending
- **AND** reading its identifier reports that the identifier is unknown or expired

#### Scenario: Removal needs nobody

- **WHEN** results pass their retention window while no caller reads anything and no operator acts
- **THEN** they are still removed

#### Scenario: The object goes before the record

- **WHEN** a result is removed, whether by the sweep or by a caller
- **THEN** the stored object is deleted before the record that names it
- **AND** a failure part-way through leaves a record pointing at nothing rather than an object nothing points at

### Requirement: A caller can remove its own result immediately

A caller holding an identifier SHALL be able to remove the work, its record and its stored object at any time,
before or after it has finished, without waiting for the retention window. A result holds the document's own text,
so a caller that no longer needs it SHALL NOT have to leave it in the platform's storage.

#### Scenario: Removing a finished result early

- **WHEN** a caller removes finished work
- **THEN** the record and the stored object are gone immediately
- **AND** reading its identifier reports that the identifier is unknown or expired

#### Scenario: Removing work twice

- **WHEN** a caller removes work it has already removed
- **THEN** the service answers with its not-found code rather than an error that suggests something went wrong

### Requirement: Retained work is bounded in count as well as in time

The number of finished records the service retains SHALL be bounded by a configurable limit, and when that limit is
reached the oldest finished record and its stored object SHALL be removed first. The default limit SHALL be at least
as large as the number of results the service can produce inside one retention window, so that the time bound is
what ordinarily removes a result and the count bound is a backstop against a defect rather than an eviction policy
callers meet. The documentation SHALL state which of the two bounds a given configuration expects to bind.

#### Scenario: More finished work than the limit

- **WHEN** more work finishes inside a retention window than the count limit allows
- **THEN** the oldest finished records and their stored objects are removed first
- **AND** the number retained never exceeds the limit

#### Scenario: Eviction does not touch unfinished work

- **WHEN** the count limit is reached while other work is waiting or running
- **THEN** only finished records are removed
- **AND** no waiting or running work is lost

#### Scenario: A caller working at full speed does not evict itself

- **WHEN** a caller submits and collects single page documents as fast as the service can read them, for a whole
  retention window
- **THEN** no result is removed by the count bound before its retention window has passed

### Requirement: A completed result survives a restart of the service

A result that was complete before the service stopped SHALL still be readable by its identifier after the service
starts again, for the remainder of its retention window, provided the service's own storage was not itself
discarded. Reading a document is expensive enough that losing a finished result to an ordinary restart is not
acceptable. Because the text itself lives in the platform's object storage rather than on the service's own disk, a
restart that discards the service's storage SHALL lose the address rather than the text, and the documentation SHALL
state plainly which kinds of restart preserve which, and what an operator does if the address must survive too.

#### Scenario: Reading a result after a restart

- **WHEN** work finishes, the service is restarted, and the identifier is read afterwards
- **THEN** the result address is returned as before the restart
- **AND** its retention window is measured from when it finished, not from the restart

#### Scenario: A restart that discards the service's own storage

- **WHEN** the service's own storage is discarded and a previously finished identifier is read
- **THEN** the service reports that the identifier is unknown or expired
- **AND** the documentation states that the text is still in the object store under that identifier, reachable by an
  operator and not by the caller, and says what to configure so the address survives too

### Requirement: Work in flight when the service stopped is failed, not left hanging

Work that was waiting or running when the service stopped SHALL be reported as finished unsuccessfully once the
service starts again, with a distinct reason that identifies the restart as the cause and marks the work as safe to
resubmit. The service SHALL NOT restart such work by itself, because it cannot know whether the document being read
is what brought the service down. A caller SHALL NOT be left polling work that nothing will ever finish.

#### Scenario: Running work at the moment of a restart

- **WHEN** the service is restarted while a document is being read and the identifier is read afterwards
- **THEN** the state reports failure with the restart as its reason
- **AND** the reason distinguishes it from a document the service could not read, so a caller knows resubmitting is
  worthwhile

#### Scenario: Waiting work at the moment of a restart

- **WHEN** the service is restarted while documents are waiting and their identifiers are read afterwards
- **THEN** each reports the same restart failure
- **AND** none of them is read after the restart without being submitted again

#### Scenario: Nothing is left in a non-terminal state

- **WHEN** every identifier the service holds is read after a restart
- **THEN** none of them reports waiting or running unless it was submitted after the restart

### Requirement: A result that cannot be stored fails the work with a reason that says so

Where the service cannot write a finished result to the object store, it SHALL retry a bounded number of times and
then finish the work unsuccessfully with a distinct reason naming the result store as the cause. That reason SHALL
be distinguishable from the reason given for a document the service could not read, so that a caller knows
resubmitting the same document is worthwhile. The service SHALL keep accepting, reading and recording work while the
object store is unavailable, because the record of what happened does not depend on it.

#### Scenario: A transient store failure

- **WHEN** the first attempt to store a result fails and a later attempt succeeds
- **THEN** the work finishes successfully and carries the stored result's address
- **AND** the caller sees no failure

#### Scenario: A store that stays unavailable

- **WHEN** every attempt to store a result fails
- **THEN** the work finishes unsuccessfully with the result-store reason
- **AND** the reason is distinguishable from the code used for a document that could not be read
- **AND** no successful state is ever reported for that work

#### Scenario: The service keeps working without the store

- **WHEN** the object store is unreachable and a document is submitted
- **THEN** the submission is accepted, queued, read, and recorded as failed with the result-store reason
- **AND** the service does not report itself unable to take work

### Requirement: Work that outlives its maximum lifetime is failed

Work SHALL NOT remain waiting or running beyond a maximum lifetime derived from the queue's page bound plus the
page ceiling, multiplied by the per-page allowance of the slowest engine any accepted language can load, which is
the longest any document could legitimately wait and
then be read for. Work that reaches that lifetime without becoming terminal SHALL be finished unsuccessfully with a
distinct reason that says the lifetime was exceeded, and its submitted bytes SHALL be removed. Without this, a
record wedged by a defect nothing else catches is polled forever by a caller that is never told anything.

#### Scenario: A record wedged beyond its lifetime

- **WHEN** a record has been waiting or running for longer than the maximum lifetime
- **THEN** the service finishes it unsuccessfully with the lifetime-exceeded reason
- **AND** the bytes it was holding are removed

#### Scenario: The lifetime is derived, not configured

- **WHEN** the queue's page bound, the page ceiling or any engine's per-page allowance changes
- **THEN** the maximum lifetime changes with them
- **AND** no setting can put the lifetime below the longest legitimate wait plus the longest legitimate read

#### Scenario: Legitimate long work is untouched

- **WHEN** a document at the page ceiling waits behind a full queue and is then read to completion
- **THEN** it is never failed for the lifetime, because its wait plus its reading is within it

### Requirement: A submission's bytes live only as long as its work, and results live where nothing else writes

The service SHALL hold a submission's bytes from the moment it is accepted until its work reaches a terminal state or
is removed by a caller, and SHALL remove them then. Results SHALL be written to storage the service owns exclusively,
so that an operator can expire anything left behind there without reasoning about who else writes to it, and the
documentation SHALL say so.

#### Scenario: Running work keeps its bytes

- **WHEN** a document is waiting or being read
- **THEN** the submitted bytes it needs are not removed

#### Scenario: Bytes of finished work

- **WHEN** work finishes, successfully or not, or is removed by a caller
- **THEN** the submitted bytes it was holding are removed
- **AND** only the record and, on success, the stored result remain until the retention window ends

#### Scenario: Results live where nothing else does

- **WHEN** the object storage the service writes results to is inspected
- **THEN** it holds results of this service and nothing else
- **AND** the documentation states that expiring everything older than the retention window there is safe, which is
  how an object left behind by a partial failure is eventually removed
