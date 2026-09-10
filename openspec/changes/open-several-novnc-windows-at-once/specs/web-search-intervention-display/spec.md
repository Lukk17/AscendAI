## Purpose

Describes how one remote display carries several intervention windows at once, so a human can see them, work on them
in any order, and know which window belongs to which site.

## ADDED Requirements

### Requirement: Every flow's window is placed deterministically and stays fully on screen

Each flow SHALL be assigned a slot, and each slot SHALL map to a fixed window position and size derived from the
configured display and window dimensions. Two flows in progress at the same time SHALL NOT be assigned the same slot
or the same position. Every window SHALL be placed fully within the display, at any configured maximum, however large.

#### Scenario: Two flows, two positions

- **WHEN** two flows are in progress
- **THEN** their windows are at two different positions
- **AND** both windows are fully within the display

#### Scenario: A large configured maximum

- **WHEN** the configured maximum is raised well beyond what the display fits side by side
- **THEN** every slot's window is still placed fully within the display

#### Scenario: A freed slot is reused at its own position

- **WHEN** a flow ends and a new flow takes its slot
- **THEN** the new window appears at that slot's position

### Requirement: Every open window stays reachable by the human

Windows SHALL be offset from one another so that a window opened earlier keeps a region visible and clickable while
later windows are open. The service SHALL NOT resize windows as the number in progress changes, so that a window
remains large enough to complete a challenge whatever else is open.

#### Scenario: Four windows open

- **WHEN** four flows are in progress
- **THEN** each window keeps a visible, clickable region
- **AND** each window is the same size it would be if it were the only one

#### Scenario: Clearing out of order

- **WHEN** the human completes the windows in an order different from the order they were opened
- **THEN** each completion captures that window's own session
- **AND** no other window is affected

### Requirement: A caller can tell which window belongs to which site

The human-intervention response SHALL carry a flow identifier, the slot the flow was given, and the window's position
and size, alongside the existing status, intervention type, intervention address and message. Existing fields SHALL
keep their names, their types and their meanings.

#### Scenario: The intervention response identifies the window

- **WHEN** a request receives the human-intervention response
- **THEN** it carries a flow identifier, a slot and the window's position and size
- **AND** the status, intervention type, intervention address and message fields are unchanged from before

#### Scenario: Two concurrent responses are distinguishable

- **WHEN** two flows are opened for two sites
- **THEN** their responses carry two different flow identifiers and two different slots

### Requirement: The flows in progress can be listed

The service SHALL expose, over both its HTTP and its tool surface, a read-only listing of the flows in progress. Each
entry SHALL identify the flow, the target, the domain, the profile, the intervention type, the slot, the window, how
long the flow has been running and how long remains on its lease. The listing SHALL state the number in progress and
the configured maximum. It SHALL NOT return cookies, stored session content or page content. The listing SHALL NOT be
paginated, because it is bounded by the configured maximum, which it reports.

#### Scenario: Listing with flows in progress

- **WHEN** flows are in progress and the listing is requested
- **THEN** each flow appears once with its identifier, target, slot, window and remaining lease
- **AND** the response states the number in progress and the configured maximum

#### Scenario: Listing with nothing in progress

- **WHEN** no flow is in progress and the listing is requested
- **THEN** the response reports none in progress with an empty list

#### Scenario: The listing carries no session content

- **WHEN** a flow has already captured cookies and the listing is requested
- **THEN** no cookie value and no stored session content appears in the response

#### Scenario: Both surfaces agree

- **WHEN** the listing is requested over the HTTP surface and over the tool surface for the same state
- **THEN** both report the same flows
