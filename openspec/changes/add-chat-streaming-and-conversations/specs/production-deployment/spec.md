## ADDED Requirements

### Requirement: The gateway streams Server-Sent Events without buffering

The gateway SHALL proxy `POST /api/v1/ai/prompt/stream` without buffering the response and without a proxy timeout that ends a normal stream early.

#### Scenario: A stream passes through the gateway unbuffered

- **WHEN** a client calls `POST /api/v1/ai/prompt/stream` through the gateway and the agent emits `delta` events over several seconds
- **THEN** the client receives each `delta` event as it is produced
- **AND** the connection stays open until the terminal `done` event
