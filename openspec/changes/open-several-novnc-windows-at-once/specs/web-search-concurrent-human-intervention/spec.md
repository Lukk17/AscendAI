## Purpose

Bounds how many human-intervention flows the service runs at once, and what each one owns exclusively, so that a
human working on one site does not make every other site unavailable, and so that a flow that dies costs one flow
rather than all of them.

## ADDED Requirements

### Requirement: Several intervention flows run at once, up to a configured maximum

The service SHALL support more than one human-intervention flow being in progress simultaneously. The maximum number
of simultaneous flows on one container SHALL come from a single configured value. A request that arrives at a
container while fewer than the maximum are in progress there SHALL be given a flow of its own rather than being
refused.

#### Scenario: A second site while the first is still being solved

- **WHEN** an intervention flow is in progress for one site and a read for a different site requires intervention
- **THEN** the second read receives the human-intervention response with a flow of its own
- **AND** the first flow is unaffected

#### Scenario: Up to the configured maximum

- **WHEN** requests requiring intervention arrive for as many distinct sites as the configured maximum allows
- **THEN** each receives a flow of its own

#### Scenario: The maximum is one

- **WHEN** the configured maximum is one and a flow is already in progress for a different site
- **THEN** the second request is refused with the busy response

### Requirement: Each flow owns its browser, its window, its monitor and its session key exclusively

Every intervention flow SHALL have its own browser process, its own browser context, its own page, its own capture
monitor and its own window on the display. No two simultaneous flows SHALL share any of those. No two simultaneous
flows SHALL write to the same stored session record.

#### Scenario: Two flows launch two browsers

- **WHEN** two intervention flows are in progress
- **THEN** two separate browser processes are running
- **AND** each flow's page is in its own browser context

#### Scenario: Two flows write two records

- **WHEN** two intervention flows for two different sites both complete successfully
- **THEN** each captured session is stored under its own key
- **AND** neither capture overwrites or removes the other

### Requirement: Concurrent launches never contend for a debugging port

The service SHALL NOT launch an intervention browser on a fixed remote-debugging port. Each launch SHALL obtain a
port that no other launch can be using. The debugging port SHALL NOT be reachable from outside the container.

#### Scenario: Two launches at once

- **WHEN** two intervention flows launch their browsers while both are in progress
- **THEN** neither launch fails because a debugging port is already in use
- **AND** the two launches do not request the same port

#### Scenario: Debugging port reachability

- **WHEN** an intervention browser is running
- **THEN** its debugging port is bound to the container's loopback interface only

### Requirement: A repeat request for a site and profile that already has a flow joins it

The flow identity SHALL be the registrable domain and the profile, which is the same pair the stored session record is
keyed by. When a request requires intervention for a domain and profile that already has a flow in progress, on the
container that received the request or on any other container of the deployment, the service SHALL return that
flow's details rather than opening a second window and rather than refusing the request. The response SHALL indicate
that an existing flow was joined. Every answer about a flow SHALL give the NoVNC address of the container that owns its
window, built when `NOVNC_PUBLIC_URL` is set from that one shared base address and the host name of the owning
container as `<NOVNC_PUBLIC_URL>/novnc/<hostname>/vnc.html`, and never the address of the container that answers.

#### Scenario: Two callers want the same site

- **WHEN** a second request requires intervention for a domain and profile that already has a flow in progress
- **THEN** the response carries the existing flow's identifier and its intervention address
- **AND** the response indicates the flow was joined rather than newly opened
- **AND** no second window, browser or monitor is created

#### Scenario: A joined flow serves both callers

- **WHEN** the human completes a joined flow
- **THEN** the captured session is stored under the key both callers were waiting on

#### Scenario: Two containers, one site

- **WHEN** a flow is in progress on one container and a request for the same domain and profile reaches another
  container
- **THEN** the response carries the existing flow's identifier, its intervention address and its window
- **AND** the response indicates the flow was joined
- **AND** no window, browser or monitor is created on the second container

#### Scenario: A join on another container gives the owner's address

- **WHEN** two containers share the `NOVNC_PUBLIC_URL` `https://gateway.example`, a flow is in progress on the container with the host name `web-a`, and a request for the same domain and profile reaches the container with the host name `web-b`
- **THEN** the 428 the second container answers carries a `vnc_url` that starts with `https://gateway.example/novnc/web-a/vnc.html`
- **AND** the listing read through the second container gives the same `vnc_url` for that flow

#### Scenario: Two containers at the same moment

- **WHEN** two containers receive a request for the same domain and profile at the same moment and neither has a flow
  for it
- **THEN** exactly one flow is opened
- **AND** the other request joins it

#### Scenario: The same site under a different profile

- **WHEN** a request requires intervention for a domain that already has a flow, under a different profile
- **THEN** a separate flow is opened with its own window and its own session key
- **AND** it counts against the configured maximum

### Requirement: Refusal happens only when the maximum is reached

The service SHALL refuse an intervention request with HTTP 409 and the busy code `novnc_busy` (an RFC 7807 problem
body on HTTP, the busy status object on the tool surface) only when every one of the configured maximum flows is in
progress on the container that received the request. No other condition SHALL produce that refusal. The refusal SHALL
carry a retry hint, the number of flows in progress on that container, the configured maximum, and a description of
each of those flows in the same flow shape the listing uses.

#### Scenario: Refused at the maximum

- **WHEN** every one of the configured maximum flows is in progress and a further distinct site requires intervention
- **THEN** the response is HTTP 409 with the busy code
- **AND** it states how many flows are in progress and what the maximum is
- **AND** it carries a retry hint

#### Scenario: Busy refusal over HTTP is a problem body

- **WHEN** four flows are in progress under a configured maximum of four and a read under a fifth profile of the same site requires intervention over HTTP
- **THEN** the response is HTTP 409 with media type `application/problem+json`, `code` `novnc_busy`, `type` `https://ascend.ai/errors/novnc-busy` and a `traceId` of 32 lower case hex characters
- **AND** it carries a `Retry-After` header, `active_flows` 4, `max_concurrent_flows` 4 and four entries in `flows`

#### Scenario: A duplicate is never refused

- **WHEN** a request requires intervention for a domain and profile that already has a flow in progress
- **THEN** it is not refused with the busy code, whatever the number of flows in progress

#### Scenario: A slot freed by a completed flow is reusable

- **WHEN** a flow ends and a further request requiring intervention arrives
- **THEN** it is given a flow rather than refused

### Requirement: A flow's failure is contained within that flow

A flow that fails, is cancelled, times out, or loses its browser SHALL close its own browser, release its own slot and
record its own outcome, and SHALL NOT affect any other flow's window, browser, monitor, slot or stored session. A
session already captured SHALL remain stored regardless of what later happens to the flow that captured it. A flow's
teardown SHALL NOT remove any stored session.

#### Scenario: One flow raises while others are in progress

- **WHEN** one flow fails with an error while two others are in progress
- **THEN** the other two continue, keeping their windows, their slots and their monitors
- **AND** the failed flow's slot is released

#### Scenario: Teardown fails part way

- **WHEN** a flow's browser cannot be closed during teardown
- **THEN** its slot is still released
- **AND** its outcome is still recorded

#### Scenario: A capture survives a later failure

- **WHEN** a flow stores a captured session and then fails before it ends
- **THEN** the stored session remains present and unmodified

### Requirement: A flow that stops without releasing is reclaimed, window included

Each flow SHALL carry a lease running from its own start, of the intervention timeout plus a grace that a setting
gives. When a
flow's lease expires, the service SHALL cancel that flow, which SHALL close its browser and remove its window from the
display, and SHALL free its slot. Each container SHALL attempt reclamation of its own flows on an interval that a
setting gives, so a
dead flow is reclaimed without a further request. Reclamation SHALL be bounded: a flow that does not finish within a
cancellation grace that a setting gives SHALL have its slot freed regardless, and the fact recorded. The shared record of a flow
SHALL expire with its lease, so the flow of a container that stopped without a shutdown is not joined after its lease
ends.

#### Scenario: A wedged flow is reclaimed

- **WHEN** a flow stops making progress and never releases its slot, and its lease expires
- **THEN** that flow is cancelled, its browser closed and its slot freed
- **AND** no other flow is cancelled

#### Scenario: Reclamation without a new request

- **WHEN** a flow's lease expires and no further request arrives
- **THEN** the flow is still reclaimed within the sweep interval

#### Scenario: A container stops without a shutdown

- **WHEN** a container stops while it runs a flow and does not run its shutdown
- **THEN** after the flow's lease no request on any other container joins that flow
- **AND** a new request for that site and profile opens a new flow

#### Scenario: A browser that will not close

- **WHEN** a cancelled flow does not finish within the cancellation grace
- **THEN** its slot is freed regardless
- **AND** the unfinished teardown is recorded

### Requirement: Shutdown ends every flow in progress

On shutdown a container SHALL cancel every flow in progress on it and wait, within a bounded time, for each to close
its browser and remove its shared record. It SHALL NOT abandon a browser process at shutdown and SHALL NOT touch the
flows of another container.

#### Scenario: Shutdown with flows in progress

- **WHEN** the service shuts down while flows are in progress
- **THEN** each flow is cancelled and its browser closed
- **AND** the shutdown completes within the bounded time even if a teardown does not finish
