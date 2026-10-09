## ADDED Requirements

### Requirement: Company identity behaviour is covered by end-to-end tests against the test tenants

The ascend-ai-agent e2e suite SHALL carry a spec for every caller-visible behaviour of this change that no lower test proves, run against the secured stack with tokens of the test tenants `e2e-acme`, `e2e-globex` and `e2e-soul`, obtained through the shared token helper of `add-keycloak-login`. The tenant claims, the group principals, the principal cap and the character refusal are proved by integration tests and get no end-to-end spec (owner answer 91.3 of 2026-10-08). A behaviour that an HTTP status, a response body or persisted state can show SHALL be checked by a deterministic Bruno test that calls no AI model. Pass criteria SHALL be observable behaviour only, never a log line. Every spec that checks a second tenant SHALL use these test tenants, and the personality specs of `add-agent-soul` SHALL move to `e2e-soul` in place once this change lands.

#### Scenario: A brokered person cannot choose their tenant or their role

- **WHEN** the brokered sign-in spec signs in through the stand-in customer realm whose upstream token claims `tenant` `e2e-evil` and the group `ADMIN`
- **THEN** the issued token carries the brokered provider's tenant and no `ADMIN` role
- **AND** an `ADMIN`-only endpoint answers 403
