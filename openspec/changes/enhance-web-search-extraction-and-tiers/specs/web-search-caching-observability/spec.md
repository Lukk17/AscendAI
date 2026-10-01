## MODIFIED Requirements

### Requirement: Read-result caching

Successful read results SHALL be cached and served from cache on a repeat request, keyed by the request identity, meaning the URL plus the flags that change the result: `heavy_mode`, `include_links`, `profile`, `output_format`, `tier`, and the SHA-256 of the canonical `extraction_schema` when one is given. Results with `output_format` `screenshot` SHALL NOT be cached. The cache TTL SHALL be configurable. A cache hit SHALL NOT re-run the extraction chain. The cache lives in the service process and does not survive a restart. Clearing a stored session SHALL also purge the cached results for that domain, so a read captured before the session was known bad cannot be served afterwards.

#### Scenario: Repeat read of the same URL

- **WHEN** a URL is read successfully and the same request is issued again within the cache TTL
- **THEN** the second response is served from cache without re-running the strategy chain

#### Scenario: Different flags bypass the cache entry

- **WHEN** the same URL is read with a different `output_format`
- **THEN** the cached entry for the other format is not served and a fresh extraction runs

#### Scenario: Different schemas do not share an entry

- **WHEN** the same URL is read with `output_format` `schema` and two different `extraction_schema` values
- **THEN** the second read does not receive the first read's cached result

#### Scenario: Screenshots are not cached

- **WHEN** the same URL is read twice with `output_format` `screenshot`
- **THEN** both reads run the strategy chain

#### Scenario: Clearing a session purges that domain's cached reads

- **WHEN** the stored session for a domain is cleared
- **THEN** the cached read results for that domain are dropped
- **AND** the count of dropped entries is reported back to the caller
