## ADDED Requirements

### Requirement: Per-tenant provider and model allow-list enforced at resolution

Each tenant SHALL have an effective policy naming the providers (and optionally the models per provider) its requests may use. A chat, embedding, memory-extraction, or compaction request that resolves to a provider or model outside the tenant's effective allow-list SHALL be rejected with a 4xx `ApiError` naming the denied provider or model, before any provider client is built and before any token is spent. The agent SHALL NOT silently fall back to an allowed provider. An empty model allow-list for an allowed provider SHALL mean all of that provider's models are permitted.

#### Scenario: Disallowed provider rejected before any call

- **WHEN** a user of a tenant whose policy allows only `lmstudio` sends a prompt with `provider=openai`
- **THEN** the response is a 4xx `ApiError` naming `openai` as denied
- **AND** no OpenAI client is built and no request is sent to OpenAI

#### Scenario: Allowed provider passes

- **WHEN** the same user sends a prompt with `provider=lmstudio`
- **THEN** the request proceeds through normal resolution

#### Scenario: Model-level restriction

- **WHEN** a tenant policy allows provider `anthropic` but only model `claude-haiku-4-5`, and a request selects `anthropic` with a different model
- **THEN** the request is rejected with a 4xx naming the denied model

### Requirement: Deployment default policy with narrow-only tenant overrides

A deployment-level default policy (`app.policy.default.*`) SHALL define the maximum allowed providers and tools. A tenant with no stored policy SHALL inherit the default. A tenant's effective policy SHALL be the intersection of its stored policy and the default, so a tenant can never use a provider or model the deployment default forbids.

#### Scenario: Tenant inherits default when unset

- **WHEN** a tenant has no stored policy and the deployment default allows `lmstudio` and `openai`
- **THEN** that tenant's requests may use `lmstudio` and `openai` and no others

#### Scenario: Stored policy cannot exceed the default

- **WHEN** the deployment default allows only `lmstudio` and a tenant's stored policy lists `openai`
- **THEN** the tenant's effective policy still excludes `openai`
