## ADDED Requirements

### Requirement: Import a captured browser storage state through the REST API

ascend-web-hunter SHALL expose `POST /api/v2/web/session/import` accepting `url`, an optional `profile`, a Playwright `storage_state` (`cookies` and `origins`) and an optional `user_agent`. Before storing anything it SHALL refuse a URL that fails the safe external URL check with `400 UNSAFE_URL`, a profile outside `^[A-Za-z0-9_-]{1,64}$` with `400 INVALID_PROFILE` and a storage state with no cookie for the URL's registrable domain with `400 NO_COOKIES_FOR_DOMAIN`. On success it SHALL drop cookies of other domains, store the rest under the URL's registrable domain and the effective profile with provenance `import` in the same record shape a NoVNC capture produces, clear the read cache for that domain, and answer `200` with the domain, the profile and the counts of stored and dropped cookies. The endpoint SHALL NOT refuse a storage state for its size or for its number of cookies.

#### Scenario: Imported session is replayed on the next read

- **WHEN** a caller imports a storage state holding a valid `saucedemo.com` login cookie for `https://www.saucedemo.com/inventory.html` with profile `e2e`
- **THEN** the answer is `200` with `domain` `saucedemo.com` and `profile` `e2e`
- **AND** a following read of `https://www.saucedemo.com/inventory.html` with `profile=e2e` returns the logged-in page instead of the login wall

#### Scenario: Private address is refused

- **WHEN** a caller imports a storage state for `http://127.0.0.1/admin`
- **THEN** the answer is `400` with code `UNSAFE_URL`
- **AND** nothing is written to the session store

#### Scenario: Large storage state is accepted

- **WHEN** a caller imports a storage state holding 1000 cookies for the URL's registrable domain
- **THEN** the answer is `200`
- **AND** all 1000 cookies are stored

#### Scenario: Cookies for another site only

- **WHEN** every cookie in the storage state belongs to `example.org` and the URL is on `saucedemo.com`
- **THEN** the answer is `400` with code `NO_COOKIES_FOR_DOMAIN`
- **AND** nothing is written to the session store

#### Scenario: Foreign cookies are dropped

- **WHEN** the storage state holds two `saucedemo.com` cookies and one `example.org` cookie
- **THEN** the answer is `200` with `dropped_cookies` equal to `1`
- **AND** the stored record holds no `example.org` cookie

#### Scenario: Invalid profile is refused

- **WHEN** a caller imports with profile `../work`
- **THEN** the answer is `400` with code `INVALID_PROFILE`
