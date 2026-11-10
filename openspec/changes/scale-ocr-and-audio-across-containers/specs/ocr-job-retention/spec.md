# Spec Delta

## MODIFIED Requirements

### Requirement: A completed result survives a restart of the service

A result that was complete before a container of the service stopped SHALL still be readable by its identifier after
that container or any other container starts, for the remainder of its retention window. Reading a document is
expensive enough that losing a finished result to an ordinary restart is not acceptable. The record that carries the
result address SHALL live outside every container, in the shared store the containers use, so recreating or removing a
container SHALL lose neither the address nor the text. The documentation SHALL state plainly that only losing the
shared store's data loses the address, that the text then stays in the object store under the job's identifier, and
what an operator does in that case.

#### Scenario: Reading a result after a restart

- **WHEN** work finishes, the container that read it is restarted, and the identifier is read afterwards
- **THEN** the result address is returned as before the restart
- **AND** its retention window is measured from when it finished, not from the restart

#### Scenario: Reading a result after the container is recreated

- **WHEN** work finishes, every container of the service is removed and created again, and the identifier is read
- **THEN** the result address is returned as before

#### Scenario: A restart that discards the service's own storage

- **WHEN** the data of the shared store the containers use is discarded and a previously finished identifier is read
- **THEN** the service reports that the identifier is unknown or expired
- **AND** the documentation states that the text is still in the object store under that identifier, reachable by an
  operator and not by the caller

### Requirement: Work in flight when the service stopped is failed, not left hanging

Work that a container was reading when that container stopped SHALL be reported as finished unsuccessfully once the
container's hold on it has expired, with a distinct reason that identifies the restart as the cause and marks the work
as safe to resubmit, whether or not that container starts again and whichever container notices it. The service SHALL
NOT restart such work by itself, because it cannot know whether the document being read is what brought the container
down. Work that was waiting when a container stopped SHALL stay in the shared queue and SHALL be read by any running
container in its turn, because no container had started it and its submitted bytes live outside every container. A
caller SHALL NOT be left polling work that nothing will ever finish.

#### Scenario: Running work at the moment of a restart

- **WHEN** a container is stopped while it reads a document and the identifier is read after the container's hold has
  expired
- **THEN** the state reports failure with the restart as its reason
- **AND** the reason distinguishes it from a document the service could not read, so a caller knows resubmitting is
  worthwhile

#### Scenario: Running work of a container that never comes back

- **WHEN** a container is removed while it reads a document and another container keeps running
- **THEN** the other container reports the document as failed with the restart as its reason once the hold has expired
- **AND** no page of it is read again

#### Scenario: Waiting work at the moment of a restart

- **WHEN** a container is restarted while documents wait in the shared queue
- **THEN** each of them is still waiting, in its place, and is read in its turn by a running container

#### Scenario: Nothing is left in a non-terminal state

- **WHEN** every identifier the service holds is read after a container stopped and its hold expired
- **THEN** none of them reports running unless a running container is reading it

### Requirement: A submission's bytes live only as long as its work, and results live where nothing else writes

The service SHALL hold a submission's bytes from the moment it is accepted until its work reaches a terminal state or
is removed by a caller, and SHALL remove them then. The bytes SHALL be held outside every container, in the object
storage the service owns exclusively, so any container can read a waiting document. Results SHALL be written to the
same storage the service owns exclusively, apart from the submitted bytes, so that an operator can expire anything left
behind there without reasoning about who else writes to it, and the documentation SHALL say which part holds results,
which holds submitted bytes, and how long each may safely be kept.

#### Scenario: Running work keeps its bytes

- **WHEN** a document is waiting or being read
- **THEN** the submitted bytes it needs are not removed

#### Scenario: Waiting work is readable by any container

- **WHEN** a document submitted to one container is taken from the queue by another container
- **THEN** the other container reads the submitted bytes and the document is read in full

#### Scenario: Bytes of finished work

- **WHEN** work finishes, successfully or not, or is removed by a caller
- **THEN** the submitted bytes it was holding are removed
- **AND** only the record and, on success, the stored result remain until the retention window ends

#### Scenario: Results live where nothing else does

- **WHEN** the object storage the service writes results to is inspected
- **THEN** it holds results and submitted bytes of this service and nothing else
- **AND** the documentation states that expiring results older than the retention window there is safe, and that
  expiring submitted bytes older than the longest lifetime of a job is safe, which is how an object left behind by a
  partial failure is eventually removed
