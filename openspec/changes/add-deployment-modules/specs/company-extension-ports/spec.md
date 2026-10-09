## Purpose

Lets every personal and base change record audit events and units of usage, ask for quota and ask whether a tenant may use a provider and model through four shared ports with safe defaults, so a personal deployment runs without company work and a company change later plugs in its own implementation without editing any personal change.

## ADDED Requirements

### Requirement: Audit events go through one port with a logging default

The agent SHALL offer one `AuditEventPort` with the operation `record(AuditEvent)`. An `AuditEvent` SHALL hold the event name, the tenant, the actor, the target and the outcome, and SHALL NOT hold a secret, a token or the content of a document, a prompt or an answer. An `AuditEvent` MAY also hold `details`, a map of extra non-secret text values such as a note path. The default implementation SHALL write exactly one structured INFO log line per event with those five values and nothing else, SHALL never print `details`, and SHALL exist only while no other implementation is registered. A registered implementation SHALL replace the default with no edit of any caller. Every later change that records an audit event SHALL call this port and SHALL NOT declare an audit port of its own.

#### Scenario: Default writes one log line

- **WHEN** a deployment with no company work records one audit event
- **THEN** exactly one INFO log line holds the event name, tenant, actor, target and outcome
- **AND** the line holds no other value of the event's subject and no entry of `details`

#### Scenario: A registered implementation replaces the default

- **WHEN** a deployment registers its own `AuditEventPort` bean
- **THEN** every recorded audit event reaches that implementation and the default writes no line
- **AND** no class of the calling changes was edited to make that happen

### Requirement: Usage events go through one port with a no-op default

The agent SHALL offer one `UsageEventPort` with the operation `record(UsageEvent)`. A `UsageEvent` SHALL hold the usage kind, the tenant, the user and its measured quantities by name. The default implementation SHALL do nothing and SHALL exist only while no other implementation is registered. A registered implementation SHALL replace the default with no edit of any caller. Every later change that records usage SHALL call this port and SHALL NOT declare a usage port of its own.

#### Scenario: Default does nothing

- **WHEN** a deployment with no company work records one usage event
- **THEN** the call returns without error and nothing is stored

#### Scenario: A registered implementation receives usage

- **WHEN** a deployment registers its own `UsageEventPort` bean and a usage event is recorded
- **THEN** that implementation receives the event with its kind, tenant, user and quantities

### Requirement: Metered actions ask one quota gate with an allow-all default

The agent SHALL offer one `QuotaGate` with the operation `check(QuotaRequest)`, asked before a metered action. A `QuotaRequest` SHALL hold the tenant, the user, the request type, the provider and model when known, and the run when there is one. The answer SHALL say whether the action is allowed and, when it is not, SHALL carry the reason `quota_exceeded` and the time until the quota window rolls over when known. The default implementation SHALL allow every call and SHALL exist only while no other implementation is registered. A registered implementation SHALL replace the default with no edit of any caller. Every later change that gates a metered action SHALL call this port and SHALL NOT declare a quota port of its own.

#### Scenario: Default allows every call

- **WHEN** a deployment with no company work asks the quota gate before a model call of a run
- **THEN** the answer is allowed

#### Scenario: A registered gate refuses

- **WHEN** a deployment registers its own `QuotaGate` bean that refuses with `quota_exceeded`
- **THEN** every caller receives that refusal from that implementation
- **AND** no class of the calling changes was edited to make that happen

### Requirement: Provider and model access goes through one policy with a configured default

The agent SHALL offer one `ModelAccessPolicy` that answers whether a tenant may use a provider and model, and SHALL ask it before it builds a chat client and before any token is spent, with the tenant `TenantContext.currentTenantId()` answers. A refusal SHALL answer HTTP 403 with an RFC 7807 problem detail whose `code` is `provider_denied` or `model_denied` and whose `detail` names the denied provider or model. The default implementation SHALL allow every provider the deployment has enabled, SHALL refuse a provider the deployment's provider configuration disables, and SHALL exist only while no other implementation is registered. A registered implementation SHALL replace the default with no edit of any caller.

#### Scenario: Default allows an enabled provider

- **WHEN** a deployment with no company work sends a prompt to an enabled provider and any model of it
- **THEN** the policy allows it and the prompt reaches the provider

#### Scenario: A registered policy denies a model before any call

- **WHEN** a deployment registers its own `ModelAccessPolicy` bean that denies a model and a prompt names that model
- **THEN** the answer is HTTP 403 with `code` `model_denied` and a `detail` naming the model
- **AND** no request reaches the provider

