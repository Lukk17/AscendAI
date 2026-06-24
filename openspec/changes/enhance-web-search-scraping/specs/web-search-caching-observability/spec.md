## ADDED Requirements

### Requirement: Read-result caching

Successful read results SHALL be cached and served from cache on a repeat request, keyed by the request identity (URL plus the flags that change the result: `heavy_mode`, `include_links`, `profile`, `output_format`). The cache TTL SHALL be configurable. A cache hit SHALL NOT re-run the extraction chain.

#### Scenario: Repeat read of the same URL

- **WHEN** a URL is read successfully and the same request is issued again within the cache TTL
- **THEN** the second response is served from cache without re-running the strategy chain

#### Scenario: Different flags bypass the cache entry

- **WHEN** the same URL is read with a different `output_format`
- **THEN** the cached entry for the other format is not served and a fresh extraction runs

### Requirement: Per-domain success metrics

Strategy outcome metrics SHALL carry a registrable-domain label (cardinality-capped, with an `other` bucket beyond the cap) so success rate can be observed per `(strategy, domain)`.

#### Scenario: Success rate per domain

- **WHEN** reads are performed across several domains
- **THEN** the metrics expose per-strategy outcomes broken down by registrable domain
- **AND** domain cardinality is bounded by the configured cap

### Requirement: Circuit breakers on external dependencies

Calls to FlareSolverr and SearXNG SHALL be wrapped in a circuit breaker so that, when a dependency is failing, requests skip that dependency fast instead of consuming its full timeout. Breaker state SHALL be reflected in the readiness endpoint.

#### Scenario: FlareSolverr is down

- **WHEN** FlareSolverr has failed repeatedly and its breaker is open
- **THEN** subsequent reads skip the FlareSolverr tier quickly instead of waiting for its timeout
- **AND** the readiness endpoint reflects the degraded dependency
