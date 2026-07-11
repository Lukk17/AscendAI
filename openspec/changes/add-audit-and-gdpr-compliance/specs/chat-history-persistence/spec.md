## MODIFIED Requirements

### Requirement: TTL configuration is documented

The `application.yaml` `app.memory.chat-history` section SHALL include a comment describing the TTL semantics and noting that Postgres long-term history is pruned separately by the scheduled retention job configured under `app.retention.chat-history` (see the `data-retention` capability), not by this Redis TTL.

#### Scenario: Comment present in application.yaml

- **WHEN** the file `AscendAgent/src/main/resources/application.yaml` is read
- **THEN** the `chat-history` block contains a comment that describes the Redis TTL and points to `app.retention.chat-history` as the mechanism that prunes Postgres history
