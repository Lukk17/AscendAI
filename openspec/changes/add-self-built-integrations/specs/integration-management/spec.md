## Purpose

Gives the owner full control over the integrations the assistant built: list, read, review, disable, enable, update, roll back and remove them, with tenant scoping, audit events, self-improvement change records with their undo, metrics and logs.

## ADDED Requirements

### Requirement: Integrations have a fixed set of states

An integration SHALL be in exactly one state: `building` (its first version is being built), `build_failed` (its first version failed), `awaiting_owner` (registered, with an egress or credential approval still open), `active`, `blocked` (a destination or a required credential was denied or expired), `disabled` (by the owner or the model), or `disabled_failing` (by the failure rule). A version SHALL be in exactly one state: `building`, `rejected`, `ready`, `awaiting_owner`, `active`, `superseded` or `failed`. State changes SHALL be conditional updates, so two callers can never both move one integration.

#### Scenario: First build passes

- **WHEN** the first version passes every check and its container is healthy
- **THEN** the integration moves from `building` to `awaiting_owner`, and to `active` once every destination and required credential is approved

#### Scenario: Denied destination

- **WHEN** the owner denies the egress approval of one declared destination
- **THEN** the integration moves to `blocked` and its tools return a result naming the denied host

### Requirement: The owner lists and reads integrations

`GET /api/v1/integrations` SHALL list the integrations of the caller's tenant with cursor pagination, and `GET /api/v1/integrations/{id}` SHALL return one integration with its state, active version, previous version, destinations with their approval state, credentials with their state and whether a value is set, tools with their effect and review state, the failure count, the last failure time, the container state and the time of the last change. `GET /api/v1/integrations/{id}/versions` SHALL list its versions with state, commit, coding run id, build run id, cost and the first failed check. An integration of another tenant SHALL answer 404.

#### Scenario: Other tenant

- **WHEN** a user of tenant `b` reads an integration of tenant `a`
- **THEN** the response is 404 with code `integration_not_found`

### Requirement: The owner reviews tools

`PUT /api/v1/integrations/{id}/tools/{tool}/review` with a mode `allowed` or `requires_approval` SHALL store the review for that tool at its current definition digest as a remembered rule of kind `integration_tool_review` of the approval service, written and removed only through the approval service, and the next request SHALL use that mode. The review shown on the integration view SHALL be read from those rules. A review SHALL never be written by a tool of the model. Deleting the review SHALL make the tool `requires_approval` again.

#### Scenario: Review applies at once

- **WHEN** the owner reviews `quotes_get_quote` as `allowed`
- **THEN** the next chat request offers it as `allowed`

### Requirement: The owner and the model can disable, only the owner enables

`POST /api/v1/integrations/{id}/disable` and the tool `integration_disable` SHALL set the integration to `disabled`, stop its container and withdraw its tools. `POST /api/v1/integrations/{id}/enable` SHALL be the only way back to `active` or `awaiting_owner`, from `disabled` or `disabled_failing`, and SHALL reset the failure counts.

#### Scenario: Model disables

- **WHEN** the model calls `integration_disable` for `quotes` with a reason
- **THEN** the integration is `disabled`, its container is gone, and the audit event names the model as the actor and holds the reason

### Requirement: Updates keep the running version until the new one is ready

The tool `integration_update` and `POST /api/v1/integrations/{id}/update` SHALL start a build of a new version from the current source and a change request, under the same checks and limits as a first build. The current active version SHALL keep serving while the new version builds. The new version SHALL become active only after it passed every check, every destination it adds has an approved egress approval, and every credential it adds or whose host, kind, header or path prefixes changed has a granted approval. The previous active version SHALL be kept as `superseded` with its image for rollback, and older images SHALL be removed.

#### Scenario: New destination waits

- **WHEN** version 2 adds the destination `api2.quotes.example`
- **THEN** version 1 keeps serving and version 2 is `awaiting_owner` until that egress approval is approved

#### Scenario: Failed update changes nothing

- **WHEN** version 2 fails its contract check
- **THEN** version 1 stays active and version 2 is `rejected`

### Requirement: The owner rolls back and removes integrations

`POST /api/v1/integrations/{id}/rollback` SHALL make the previous version active again when its image still exists, and answer 409 with `no_previous_version` otherwise. `DELETE /api/v1/integrations/{id}` SHALL stop and remove its container, gateway, proxy, network and images, withdraw its MCP entry and tool index entries, remove its credential routes from the gateway, delete the remembered rules of that integration of the kinds `integration_egress`, `integration_credential` and `integration_tool_review`, cancel its pending approvals, delete its folder in a commit of the tenant's integration repository, and answer 204. The slug SHALL be free again afterwards.

#### Scenario: Remove

- **WHEN** the owner removes the integration `quotes`
- **THEN** no runner object labelled with it exists, no tool named `quotes_*` is offered, no gateway holds a credential of it, and no remembered rule of the kinds `integration_egress`, `integration_credential` or `integration_tool_review` names it

### Requirement: Integration management is tenant scoped and owner only

Every write endpoint under `/api/v1/integrations` SHALL need `ADMIN` of the integration's tenant, enforced by rows of the authorization matrix in the filter chain of `SecurityConfig` and checked again by the controller. The read endpoints SHALL need an authenticated caller of that tenant. Every integration, version, review, credential, repository and runner object SHALL be keyed by the tenant, and nothing of one tenant SHALL be visible to another. Every integration table SHALL carry `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()` of `add-keycloak-login`, with no foreign key to a tenants table, and every child table SHALL carry a foreign key to its integration together with the tenant. The source SHALL live only under `tenants/<tenantId>/integrations/` and build reports only under the object prefix `tenant/<tenantId>/integration-builds/`. A tool call, an endpoint call or an approval handler with no bound tenant SHALL be refused and SHALL write nothing, and work started without a request SHALL bind the tenant of each integration row with `TenantContext.runAs` before any other step.

#### Scenario: Non-admin cannot remove

- **WHEN** a caller without `ADMIN` calls `DELETE /api/v1/integrations/{id}`
- **THEN** the response is 403 and nothing is removed

#### Scenario: Admin of another tenant

- **WHEN** an `ADMIN` of tenant `globex` calls `POST /api/v1/integrations/{id}/disable` for an integration of tenant `acme`
- **THEN** the response is 404 and the integration stays as it was

#### Scenario: Child row of another tenant refused by the database

- **WHEN** an `integration_version` row of tenant `globex` is inserted for an integration of tenant `acme`
- **THEN** the insert fails on the foreign key `integration_version_integration_fk`

#### Scenario: No tenant resolved

- **WHEN** `integration_build` is called while no tenant is bound
- **THEN** the call is refused with a tool error
- **AND** no row, repository folder, object or runner object is written

### Requirement: Integration events are audited through the audit port

The agent SHALL send the actions `INTEGRATION_BUILD_STARTED`, `INTEGRATION_BUILD_FINISHED`, `INTEGRATION_REGISTERED`, `INTEGRATION_ACTIVATED`, `INTEGRATION_DISABLED`, `INTEGRATION_ENABLED`, `INTEGRATION_ROLLED_BACK`, `INTEGRATION_REMOVED`, `INTEGRATION_TOOL_REVIEWED` and `INTEGRATION_CREDENTIAL_REVOKED` through the `AuditEventPort` of `add-deployment-modules`, with the tenant, the integration id, the version, the actor kind (`owner`, `model` or `system`) and the outcome, and never a credential value, the API notes or source text. With no other implementation registered, the default `LogAuditEventPort` SHALL write one structured INFO line per event. A bean that implements `AuditEventPort` SHALL replace the default with no edit of this change.

#### Scenario: Audit event through the default port

- **WHEN** the owner disables `quotes` and no other `AuditEventPort` is registered
- **THEN** one INFO line names the action `INTEGRATION_DISABLED`, the tenant, the integration id, the actor kind `owner` and the outcome, and holds no credential value

#### Scenario: Port replaced by a bean

- **WHEN** a test registers its own `AuditEventPort` bean and the owner removes `quotes`
- **THEN** that bean receives one `INTEGRATION_REMOVED` event and the default writes no line

### Requirement: Integration events become self-improvement change records with an undo

While the module `self-improvement` is active, the agent SHALL call `SelfChangeRecorder.recordIntegrationEvent(...)` of `add-self-improvement` once after commit for each of these events, with the tenant, the integration id, the version, the operation, a reason text and the request id that started the action: `register` (the first version of an integration becomes `active`), `activate` (a later version that waited in `awaiting_owner` becomes `active`), `update` (a later version replaces the active one at once), `disable` (the model disables the integration through `integration_disable`) and `auto_disable` (the failure rule moves the integration to `disabled_failing`, with no request id). A disable, enable, rollback or remove by the owner SHALL NOT be recorded as a self change. While the module `self-improvement` is not active, no call SHALL be made and no undo handler SHALL exist. A failed recorder call SHALL be logged at WARN and SHALL NOT change the integration's state.

The agent SHALL provide a `SelfChangeUndoHandler` bean of type `integration` that undoes a record through this change's own paths as the deciding identity: `register` and `activate` through the disable path, `update` through the rollback path, and `disable` and `auto_disable` through the enable path. A refusal of that path SHALL be returned as the undo's problem detail with its own code.

#### Scenario: Automatic disable recorded

- **WHEN** the module `self-improvement` is active and the failure rule disables `quotes`
- **THEN** one change record of type `integration` with operation `auto_disable`, the integration id and the version exists

#### Scenario: Owner disable not recorded

- **WHEN** the owner disables `quotes` through `POST /api/v1/integrations/{id}/disable`
- **THEN** no change record is written for it and the audit event names the owner

#### Scenario: Module off

- **WHEN** the module `self-improvement` is not active and version 1 of `quotes` becomes `active`
- **THEN** no recorder call is made and no `SelfChangeUndoHandler` of type `integration` exists

#### Scenario: Undo of an automatic disable

- **WHEN** an `ADMIN` undoes the `auto_disable` record of `quotes`
- **THEN** the integration is enabled through the enable path, its failure counts are reset, and the audit event names the owner as the actor

#### Scenario: Undo of an update with no previous version

- **WHEN** an `ADMIN` undoes an `update` record of `quotes` whose previous version image no longer exists
- **THEN** the undo answers 409 with code `no_previous_version` and the integration does not change

### Requirement: Management actions are measured and logged

Every management action SHALL write one INFO line with the tenant, the integration id, the action, the actor kind and the outcome, and SHALL increase `integration.actions` tagged `action` and `outcome`. A refused action SHALL write one WARN line naming the code.

#### Scenario: Rollback logged

- **WHEN** the owner rolls back `quotes`
- **THEN** one INFO line names the action `rollback` and `integration.actions` has a sample with `action=rollback` and `outcome=ok`

### Requirement: Integration build, approval and management are proven end to end

The repository SHALL hold one deterministic end-to-end spec in `apps/ascend-agent/e2e/testing/`, with Bruno requests in `docs/api/request/AscendAI/ascend-agent/testing/integrations/`, in which the scripted model of the shared e2e harness of `close-agent-test-gaps` (its design D5 and task group 4) calls the integration tools, the fake installed under the real binary name `opencode` in the coding test image writes a fixed integration, and a fake outside system records what reaches it, so that no AI model runs. It SHALL prove the build and its report, the egress and credential approvals, activation after the owner's secrets file step, the tool review, a call that carries the credential to the outside system while the integration container holds no copy, and the login role rules. No setting, profile or overlay of the agent's or the runner's shipped configuration SHALL name a fake, a test host or a test secrets file. A behaviour that an integration test already proves, such as disable and enable, update, rollback, the automatic disable and removal leaving nothing behind, SHALL NOT be repeated by an end-to-end spec. The scripted model and the fake MCP server SHALL start only for the deterministic specs, never for the AI-run spec (owner answer 70.4 of 2026-10-04). An AI-run spec SHALL prove that a real model builds a working integration for the Open-Meteo forecast API with real OpenCode. Every spec SHALL pass only on HTTP answers, approval rows, the fake's request log, Prometheus samples and container inspection, never on a log line.

#### Scenario: Fake build reaches active without a model

- **WHEN** the deterministic spec builds the `quotes` integration through the scripted model, writes the variable line into `integration-secrets.env`, recreates the runner and approves both pending approvals with their digests
- **THEN** the integration reads `active`, the scripted call of `quotes_get_quote` answers with `QUILLMOOR-QUOTE-4217`, and no hosted or local chat model was called
