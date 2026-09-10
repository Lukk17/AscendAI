# quota-enforcement — Delta Specification

## ADDED Requirements

### Requirement: Token budgets are enforced before the provider call

ascend-ai-agent SHALL enforce a per-tenant monthly token budget and a per-user daily token budget on every LLM-touching request, evaluated **before** the provider call. Budget windows are calendar month and calendar day in UTC. Platform-wide default budgets SHALL be configurable in `application.yaml` (`app.usage.quotas.*`), with per-tenant overrides stored in a Liquibase-managed quota configuration table. A request whose tenant or user budget is already met or exceeded SHALL be rejected with HTTP `429`.

#### Scenario: Exhausted user budget rejects the request pre-call

- **WHEN** a user's recorded token usage for the current UTC day has reached their daily budget and the user sends a chat request
- **THEN** the response is `429` and no call is made to any AI provider

#### Scenario: Exhausted tenant budget rejects all tenant users

- **WHEN** a tenant's recorded token usage for the current UTC month has reached the tenant's monthly budget
- **THEN** chat requests from every user of that tenant are rejected with `429`, while users of other tenants are unaffected

#### Scenario: Budget window rollover restores service

- **WHEN** a user was quota-rejected and the UTC day boundary passes
- **THEN** the user's next chat request is served normally

#### Scenario: Per-tenant override beats the platform default

- **WHEN** the platform default tenant budget is X tokens and a tenant has a configured override of 2X
- **THEN** that tenant is only rejected after consuming 2X tokens in the window

### Requirement: Quota rejection carries a structured error and Retry-After

A quota-rejected request SHALL return `429` with a `Retry-After` header equal to the seconds remaining until the exhausted window rolls over, and a JSON body containing `code = QUOTA_EXCEEDED`, `scope` (`tenant` or `user`), `limit`, `used`, `windowEnd`, and `retryAfterSeconds`.

#### Scenario: Error body identifies the exhausted scope

- **WHEN** a request is rejected because the tenant monthly budget is exhausted
- **THEN** the `429` body has `code = "QUOTA_EXCEEDED"`, `scope = "tenant"`, the configured `limit`, the `used` amount, and a `Retry-After` header matching the seconds until the start of the next UTC month

### Requirement: Quota accounting uses rebuildable Redis counters with PostgreSQL as source of truth

The quota gate SHALL read per-window Redis counters incremented at ledger-write time. When a counter key is absent, it SHALL be rebuilt from a PostgreSQL aggregate over the usage ledger for the window and set with a TTL past the window end. Enforcement is post-paid within a single request: a request admitted with remaining budget MAY overshoot the budget by its own usage.

#### Scenario: Missing counter is rebuilt from the ledger

- **WHEN** Redis has been flushed and a user with prior usage this window sends a request
- **THEN** the quota gate rebuilds the counter from the PostgreSQL ledger sum before deciding, and the decision reflects the user's true recorded usage

#### Scenario: Admitted request may overshoot by one request

- **WHEN** a user has budget remaining below the size of their next request
- **THEN** the request is admitted and its full usage is recorded, and the following request is rejected

### Requirement: Soft-warning threshold emits an observable event once per window

When recorded usage crosses a configurable warning threshold (default 80%) of a tenant or user budget, ascend-ai-agent SHALL log one WARN line and increment `usage.quota.warning{scope}` exactly once per (scope, window).

#### Scenario: Crossing 80% fires exactly one warning

- **WHEN** a tenant's monthly usage crosses 80% of its budget across two successive requests
- **THEN** exactly one WARN log line naming the tenant and one `usage.quota.warning{scope="tenant"}` increment are emitted for that month, and later requests within the same month emit no further warning

### Requirement: Quota enforcement is toggleable without redeploy

`app.usage.quotas.enabled=false` SHALL disable the quota gate entirely (no pre-request check, no rejections) while leaving ledger recording untouched.

#### Scenario: Disabled quotas never reject

- **WHEN** `app.usage.quotas.enabled=false` and a user is far past every budget
- **THEN** requests are served normally and ledger rows continue to be written
