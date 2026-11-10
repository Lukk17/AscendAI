## ADDED Requirements

### Requirement: Per-tenant provider and model allow-list enforced at resolution

Each tenant SHALL have an effective policy naming the providers (and optionally the models per provider) its requests may use. A chat, embedding, memory-extraction, or compaction request that resolves to a provider or model outside the tenant's effective allow-list SHALL be rejected with HTTP 403 and the RFC 7807 problem detail that `upgrade-spring-boot-4` defines for every agent error (`application/problem+json` with `type`, `title`, `status`, `detail`, `instance` and a top-level `code`), with `code` `provider_denied` (type `https://ascend.ai/errors/provider-denied`) for a denied provider or `model_denied` (type `https://ascend.ai/errors/model-denied`) for a denied model, and a `detail` naming the denied provider or model, before any provider client is built and before any token is spent. The agent SHALL NOT silently fall back to an allowed provider. An empty model allow-list for an allowed provider SHALL mean all of that provider's models are permitted.

The provider names SHALL include `opencode-go` and `opencode-zen` for the coding runs of `add-coding-agent-delegation`. The policy SHALL be enforced through this change's implementation of the `ModelAccessPolicy` port of `add-deployment-modules`, which `ChatModelResolver` and the coding runs of `add-coding-agent-delegation` ask, so a coding run's provider and model SHALL be checked against the tenant's provider and model allow-lists through the same implementation before the coding run starts.

#### Scenario: Disallowed provider rejected before any call

- **WHEN** a user of a tenant whose policy allows only `lmstudio` sends a prompt with `provider=openai`
- **THEN** the response is HTTP 403 with `Content-Type: application/problem+json`, `code` `provider_denied` and a `detail` naming `openai` as denied
- **AND** no OpenAI client is built and no request is sent to OpenAI

#### Scenario: Allowed provider passes

- **WHEN** the same user sends a prompt with `provider=lmstudio`
- **THEN** the request proceeds through normal resolution

#### Scenario: Model-level restriction

- **WHEN** a tenant policy allows provider `anthropic` but only model `claude-haiku-4-5`, and a request selects `anthropic` with a different model
- **THEN** the request is rejected with HTTP 403, `code` `model_denied` and a `detail` naming the denied model

#### Scenario: Coding run provider checked before the run starts

- **WHEN** a tenant whose provider allow-list does not hold `opencode-go` asks for a coding run of `add-coding-agent-delegation` with provider `opencode-go`
- **THEN** the coding run does not start
- **AND** no request is sent to that provider

### Requirement: Deployment default policy with narrow-only tenant overrides

A deployment-level default policy (`app.policy.default.*`) SHALL define the maximum allowed providers, tools and modules. A tenant with no stored policy SHALL inherit the default, except the tools that ship off for a new tenant, which SHALL stay off until a tenant `ADMIN` stores a policy that lists them, and an empty skill allow-list. A tenant's effective policy SHALL be the intersection of its stored policy and the default, so a tenant can never use a provider, model, tool or module the deployment default forbids.

#### Scenario: Tenant inherits default when unset

- **WHEN** a tenant has no stored policy and the deployment default allows `lmstudio` and `openai`
- **THEN** that tenant's requests may use `lmstudio` and `openai` and no others

#### Scenario: Stored policy cannot exceed the default

- **WHEN** the deployment default allows only `lmstudio` and a tenant's stored policy lists `openai`
- **THEN** the tenant's effective policy still excludes `openai`

#### Scenario: Local-only tenant asks for a hosted coding provider

- **WHEN** a tenant whose provider policy allows only the local provider asks `delegate_coding` for provider `opencode-go`
- **THEN** the tool result is an error that names the provider as denied by policy
