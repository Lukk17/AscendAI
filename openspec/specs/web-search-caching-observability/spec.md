# web-search-caching-observability Specification

## Purpose

Defines how ascend-web-hunter avoids repeating work and how its operator sees what it is doing: the read-result cache and what invalidates it, the per-domain breakdown of strategy outcome metrics, and the circuit breaker that makes a failing SearXNG fail fast and show up in readiness.

## Requirements

### Requirement: Read-result caching

Successful read results SHALL be cached and served from cache on a repeat request, keyed by the request identity, meaning the URL plus the flags that change the result: `heavy_mode`, `include_links`, `profile`, `output_format`, `tier`, and the SHA-256 of the canonical `extraction_schema` when one is given. Results with `output_format` `screenshot` SHALL NOT be cached. The cache TTL SHALL be configurable. A cache hit SHALL NOT re-run the extraction chain. The cache lives in the service process and does not survive a restart. Clearing a stored session SHALL also purge the cached results for that domain in every running container of the service, so a read captured before the session was known bad cannot be served afterwards by any of them. A crawl page read SHALL neither be served from nor write to this cache, so a page a crawl job reports as `fetched` was fetched by that job.

#### Scenario: Repeat read of the same URL

- **WHEN** a URL is read successfully and the same request is issued again within the cache TTL
- **THEN** the second response is served from cache without re-running the strategy chain

#### Scenario: Different flags bypass the cache entry

- **WHEN** the same URL is read with a different `output_format`
- **THEN** the cached entry for the other format is not served and a fresh extraction runs

#### Scenario: Different schemas do not share an entry

- **WHEN** the same URL is read with `output_format` `schema` and two different `extraction_schema` values
- **THEN** the second read does not receive the first read's cached result

#### Scenario: A crawl read skips the cache

- **WHEN** the read cache holds an entry for a URL and a crawl job reads that URL
- **THEN** the crawl fetches the page itself
- **AND** the cache holds no entry the crawl read wrote

#### Scenario: Screenshots are not cached

- **WHEN** the same URL is read twice with `output_format` `screenshot`
- **THEN** both reads run the strategy chain

#### Scenario: Clearing a session purges that domain's cached reads

- **WHEN** the stored session for a domain is cleared
- **THEN** the cached read results for that domain are dropped
- **AND** the count of dropped entries is reported back to the caller

#### Scenario: Clearing a session on one container purges the others

- **WHEN** two containers of the service hold a cached read of a domain and the stored session for that domain is
  cleared through one of them
- **THEN** a repeat of that read on the other container is not served from its cache

### Requirement: Per-domain success metrics

Strategy outcome metrics SHALL carry a registrable-domain label (cardinality-capped, with an `other` bucket beyond the cap) so success rate can be observed per `(strategy, domain)`.

#### Scenario: Success rate per domain

- **WHEN** reads are performed across several domains
- **THEN** the metrics expose per-strategy outcomes broken down by registrable domain
- **AND** domain cardinality is bounded by the configured cap

### Requirement: Circuit breaker on SearXNG

Calls to SearXNG SHALL be wrapped in a circuit breaker so that, when SearXNG is failing, searches fail fast instead of consuming its full timeout. The breaker SHALL open after `BREAKER_FAILURE_THRESHOLD` consecutive failures and SHALL let one probe through after `BREAKER_RECOVERY_TIMEOUT_SECONDS`. Breaker state SHALL be reflected in the readiness endpoint as the `searxng_breaker` check. SearXNG is the only dependency behind a breaker. The FlareSolverr breaker was removed with the FlareSolverr tier.

#### Scenario: SearXNG is down

- **WHEN** SearXNG has failed `BREAKER_FAILURE_THRESHOLD` times in a row and its breaker is open
- **THEN** subsequent searches fail at once without calling SearXNG
- **AND** `/ready` reports the `searxng_breaker` check as `degraded` and answers 503 `not-ready`

#### Scenario: SearXNG recovers

- **WHEN** the breaker has been open for `BREAKER_RECOVERY_TIMEOUT_SECONDS` and the next probe to SearXNG succeeds
- **THEN** the breaker closes and `/ready` reports the `searxng_breaker` check as `ok`
