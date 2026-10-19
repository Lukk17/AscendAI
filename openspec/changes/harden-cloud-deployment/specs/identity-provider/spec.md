## ADDED Requirements

### Requirement: Keycloak login and token endpoints are rate limited

Login (/realms/ascend-ai/login-actions/authenticate) and token (/realms/ascend-ai/protocol/openid-connect/token) SHALL be rate limited per address in the proxy before Keycloak. Over-limit SHALL answer 429 and SHALL NOT reach Keycloak. Limits SHALL be env with defaults as VAR:-default: 10 per 1m per address (KEYCLOAK_LOGIN_RATE_LIMIT_EVENTS 10, KEYCLOAK_LOGIN_RATE_LIMIT_WINDOW 1m). The rule SHALL live on the Keycloak site of gateway/Caddyfile.

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
