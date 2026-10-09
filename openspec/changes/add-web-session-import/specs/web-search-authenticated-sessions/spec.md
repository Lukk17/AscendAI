## ADDED Requirements

### Requirement: Import a captured browser storage state through the REST API

ascend-web-hunter SHALL expose `POST /api/v2/web/session/import` accepting `url`, an optional `profile`, a Playwright `storage_state` (`cookies` and `origins`) and an optional `user_agent`. Before storing anything it SHALL refuse, with no address lookup because the import makes no request to the URL, a URL whose host has no registrable domain (an IP address literal or a name with no public suffix) with `400 unsafe_uri`, a profile outside `^[A-Za-z0-9_-]{1,64}$` with `400 invalid_profile` and a storage state with no cookie for the URL's registrable domain with `400 no_cookies_for_domain`. On success it SHALL drop cookies of other domains, store the rest under the URL's registrable domain and the effective profile with provenance `import` in the same record shape a NoVNC capture produces, clear the read cache for that domain on every running ascend-web-hunter instance through the same purge a session clear runs, and answer `200` with the domain, the profile and the counts of stored and dropped cookies. The endpoint SHALL NOT refuse a storage state for its size or for its number of cookies. Every later request that uses the imported session SHALL still pass the `check_fetch_uri` guard of the `ascend-python-common` library when it is made.

#### Scenario: The read cache of every instance is cleared

- **WHEN** two ascend-web-hunter instances hold a cached anonymous read of `https://www.example.net/` and a caller imports a session for that URL through the first instance
- **THEN** the import triggers the same domain purge a session clear triggers
- **AND** a following read of that URL on the second instance is not answered from its cache

#### Scenario: Imported session is replayed on the next read

- **WHEN** a caller imports a storage state holding a valid `saucedemo.com` login cookie for `https://www.saucedemo.com/inventory.html` with profile `e2e`
- **THEN** the answer is `200` with `domain` `saucedemo.com` and `profile` `e2e`
- **AND** a following read of `https://www.saucedemo.com/inventory.html` with `profile=e2e` returns the logged-in page instead of the login wall

#### Scenario: Private address is refused

- **WHEN** a caller imports a storage state for `http://127.0.0.1/admin`
- **THEN** the answer is `400` with code `unsafe_uri`
- **AND** nothing is written to the session store
- **AND** no address lookup is made

#### Scenario: Every refusal is a problem body

- **WHEN** an import is refused with `unsafe_uri`, `invalid_profile` or `no_cookies_for_domain`
- **THEN** the answer has media type `application/problem+json`, `type` `https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`, the `code` and a `traceId` of 32 lower case hex characters

#### Scenario: Imported session is reported active

- **WHEN** a caller imports a storage state for `https://www.example.net/` with profile `e2e-import` and then asks `POST /api/v2/web/session/status` for that URL and profile
- **THEN** the status answer is `active`
- **AND** the stored record names `import` as its provenance

#### Scenario: Large storage state is accepted

- **WHEN** a caller imports a storage state holding 1000 cookies for the URL's registrable domain
- **THEN** the answer is `200`
- **AND** all 1000 cookies are stored

#### Scenario: Cookies for another site only

- **WHEN** every cookie in the storage state belongs to `example.org` and the URL is on `saucedemo.com`
- **THEN** the answer is `400` with code `no_cookies_for_domain`
- **AND** nothing is written to the session store

#### Scenario: Foreign cookies are dropped

- **WHEN** the storage state holds two `saucedemo.com` cookies and one `example.org` cookie
- **THEN** the answer is `200` with `dropped_cookies` equal to `1`
- **AND** the stored record holds no `example.org` cookie

#### Scenario: Invalid profile is refused

- **WHEN** a caller imports with profile `../work`
- **THEN** the answer is `400` with code `invalid_profile`
