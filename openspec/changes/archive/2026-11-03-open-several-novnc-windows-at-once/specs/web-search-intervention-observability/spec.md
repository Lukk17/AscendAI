## Purpose

Makes the intervention subsystem legible from outside, so an operator can tell a service that is busy with humans
from one that is stuck, and can follow one request from the refusal or the window it produced to the session that was
eventually captured.

## ADDED Requirements

### Requirement: The number of flows in progress is reported

The service SHALL report the number of intervention flows in progress as a metric, and SHALL report a count of flows
started, of requests that joined an existing flow, of requests refused because the maximum was reached, and of flows
reclaimed. The reclamation count SHALL distinguish the reason a flow was reclaimed.

#### Scenario: Flows in progress rise and fall

- **WHEN** a flow starts and later ends
- **THEN** the reported number in progress rises by one and then falls by one

#### Scenario: A join does not count as a new flow

- **WHEN** a request joins a flow already in progress
- **THEN** the join is counted
- **AND** the reported number in progress does not change

#### Scenario: A refusal is counted separately from a join

- **WHEN** one request is refused because the maximum was reached and another joins an existing flow
- **THEN** the two are counted under different names

#### Scenario: Reclamation reasons are distinguishable

- **WHEN** a flow is reclaimed because its lease expired and another because the service shut down
- **THEN** the two reclamations are distinguishable by reason

### Requirement: Every flow outcome is recorded

Each flow SHALL record an outcome when it ends, and cancellation SHALL be a distinct outcome from resolution, from
timeout, and from a rejected intervention. The outcome SHALL be recorded even when the flow's teardown fails.

#### Scenario: A cancelled flow

- **WHEN** a flow is cancelled by reclamation or by shutdown
- **THEN** its outcome is recorded as cancelled, not as a timeout

#### Scenario: Teardown fails

- **WHEN** a flow's browser cannot be closed as it ends
- **THEN** its outcome is still recorded

### Requirement: Logs identify the flow, the window and the request that opened it

Every log line the intervention subsystem writes SHALL carry the flow identifier and the slot. The line recording a
flow being opened SHALL also carry the identifier of the request that opened it. No log line SHALL carry a cookie
value or any part of a stored session.

#### Scenario: Following one request through

- **WHEN** a request opens a flow, the human completes it and a session is captured
- **THEN** the opening line, the window's own lines and the capture line all carry the same flow identifier
- **AND** the opening line also carries the request identifier

#### Scenario: Logs carry no secrets

- **WHEN** a flow captures a session containing cookies
- **THEN** no cookie value appears in any log line

### Requirement: A full intervention registry does not make the service unready

The readiness endpoint SHALL NOT report the service unready because every intervention flow is in progress. Being at
the configured maximum is a capacity state that the refusal response already communicates to the caller, and the rest
of the service continues to serve.

#### Scenario: Readiness at the maximum

- **WHEN** every one of the configured maximum flows is in progress
- **THEN** the readiness endpoint reports the same state it would report with none in progress
- **AND** requests that do not need intervention continue to be served
