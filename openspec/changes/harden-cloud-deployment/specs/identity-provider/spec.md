## ADDED Requirements

### Requirement: Keycloak login and token endpoints are rate limited

The login form endpoint (`/realms/ascend-ai/login-actions/authenticate`) and the token endpoint (`/realms/ascend-ai/protocol/openid-connect/token`) SHALL be rate limited per client address in the reverse proxy in front of Keycloak, so a password guessing run is slowed before Keycloak brute-force detection locks an account. A request over the limit SHALL receive HTTP 429 and SHALL NOT reach Keycloak. The limit values SHALL be configuration, not code: the gateway SHALL read them from its environment with a default, and compose SHALL pass them as `${VAR:-default}` with the same default (owner rule 98 of 2026-10-08). The defaults SHALL be 10 events per 1 minute per client address (`KEYCLOAK_LOGIN_RATE_LIMIT_EVENTS` 10, `KEYCLOAK_LOGIN_RATE_LIMIT_WINDOW` `1m`, owner answer 102.2 of 2026-10-09). The rule SHALL live on the Keycloak site of `gateway/Caddyfile`, which this change creates after `add-keycloak-login` has added Keycloak (owner answer 72.1 of 2026-10-06).

#### Scenario: A burst of token requests is refused

- **WHEN** one client address sends more token requests in one window than the configured limit
- **THEN** every request over the limit receives HTTP 429
- **AND** Keycloak records no login attempt for those refused requests

#### Scenario: The default limit is 10 per minute

- **WHEN** the gateway runs with neither limit variable set and one client address sends 11 token requests within one minute
- **THEN** the first 10 reach Keycloak
- **AND** the eleventh receives HTTP 429

#### Scenario: Normal sign-in is not affected

- **WHEN** a person signs in once through the login page and exchanges the code at the token endpoint
- **THEN** neither request receives HTTP 429
