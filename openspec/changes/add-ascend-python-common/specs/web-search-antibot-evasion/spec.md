# Spec Delta

## REMOVED Requirements

### Requirement: No service-side request rate limiting

**Reason**: Owner answer 56 of 2026-10-03 gives all four Python services rate limiting with per-service limits in settings. This requirement forbids any per-caller limit. OpenSpec does not let a MODIFIED block rename a requirement, and the old name would be false, so it is removed and added again below under a new name.

**Migration**: A caller that sends more requests than `RATE_LIMIT_DEFAULT` (or the service's stricter named limit) allows in its window gets HTTP 429 with a `Retry-After` header on REST and a tool error starting with `rate_limited: ` on MCP. The ascend-agent is one caller address, so the limit is flood protection set far above its load, `1200/minute` by default (`design.md` of `add-ascend-python-common`, D9, owner answer 60.4 of 2026-10-03).

## ADDED Requirements

### Requirement: No outbound self-throttling, and inbound limits only per caller

The service SHALL NOT impose per-domain rate limiting or self-throttling on its outbound fetches. Throughput control of outbound fetches is delegated to the deployment stack. The only request limit the service applies SHALL be the inbound per-caller limit of `python-service-platform`, read from settings.

#### Scenario: Rapid successive reads within the caller's limit

- **WHEN** many read requests are issued in quick succession and stay within the caller's configured limit
- **THEN** the service does not delay, queue, or reject them for rate-limiting reasons

#### Scenario: Reads of one domain are not throttled

- **WHEN** many reads of pages on the same domain arrive within the callers' limits
- **THEN** the service fetches each of them without waiting for an earlier fetch of that domain

#### Scenario: A caller over its limit

- **WHEN** one caller sends more read requests than its configured limit allows in the window
- **THEN** the next request answers HTTP 429 with code `rate_limited`
