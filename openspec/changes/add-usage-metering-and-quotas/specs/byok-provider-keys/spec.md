# byok-provider-keys - Delta Specification

## ADDED Requirements

### Requirement: Tenant provider keys are stored encrypted at rest in the one secret store

ascend-ai-agent SHALL store per-tenant provider API keys through the `ConnectorCredentialStore` port of `add-connector-framework`, the agent's one encrypted secret store (AES-256-GCM with a fresh nonce per write and the key from `CONNECTOR_CREDENTIALS_KEY`), and SHALL register no secret store of its own (owner answer 89.9 of 2026-10-08). The Flyway-managed table `tenant_provider_key` SHALL store only the provider, the opaque handle the store returned, the key's last four characters and timestamps. An upsert while no `CONNECTOR_CREDENTIALS_KEY` is configured SHALL be refused with HTTP 503 and the code `unavailable`. The plaintext key SHALL never be written to logs or persisted unencrypted anywhere.

#### Scenario: Persisted key is not recoverable from the database alone

- **WHEN** a tenant provider key has been stored and the `tenant_provider_key` table contents are inspected directly in PostgreSQL
- **THEN** the provider key appears in plaintext in no column of `tenant_provider_key` or `connector_credential`, and resolving it with another `CONNECTOR_CREDENTIALS_KEY` fails

#### Scenario: No secret store key configured

- **WHEN** no `CONNECTOR_CREDENTIALS_KEY` is set and an `ADMIN` upserts a provider key
- **THEN** the answer is 503 with `code` `unavailable` and no row is written

#### Scenario: Key material is absent from logs

- **WHEN** a provider key is created via the management API with logging at DEBUG
- **THEN** no log line contains the plaintext key

### Requirement: Provider-key management API is ADMIN-only and write-only

ascend-ai-agent SHALL expose `ADMIN`-role endpoints under `/api/v1/admin/tenants/{tenantId}/provider-keys`: upsert a key for a provider, list configured keys, and delete a key. Read responses SHALL contain only provider name, `last4`, and timestamps - never the key itself, in any encoding. Non-`ADMIN` callers SHALL receive `403`, and an `ADMIN` whose tenant differs from `{tenantId}` SHALL receive `403`.

#### Scenario: Stored key is never returned

- **WHEN** an `ADMIN` upserts an OpenAI key ending in `abcd` for a tenant and then lists that tenant's provider keys
- **THEN** the list response contains an entry with `provider = "openai"` and `last4 = "abcd"` and no field containing the full key

#### Scenario: USER role cannot manage keys

- **WHEN** a `USER`-role caller invokes any provider-key endpoint
- **THEN** the response is `403` and no key state changes

#### Scenario: Upsert replaces the previous key

- **WHEN** an `ADMIN` upserts a new key for a provider that already has a tenant key
- **THEN** subsequent provider calls for that tenant use the new key and the old ciphertext row is replaced

### Requirement: Provider calls resolve the tenant key with fallback to the global key

For every provider call, ascend-ai-agent SHALL resolve credentials in this order: the calling tenant's stored key for the resolved provider, then the global deployment key from `AiProviderProperties`. Tenant-keyed provider clients SHALL be cached with a bounded time-based expiry and evicted on every agent instance when the tenant's key is upserted or deleted, through a Postgres notification sent with the row change. A provider authentication failure on a tenant key SHALL be surfaced as a client-visible error identifying the tenant key by `last4`, and SHALL NOT be silently retried on the global key.

#### Scenario: Tenant key is used over the global key

- **WHEN** a tenant has a stored Anthropic key and one of its users sends a chat request on the `anthropic` provider
- **THEN** the outbound Anthropic call authenticates with the tenant's key, not the deployment's `ASCEND_ANTHROPIC_API_KEY`

#### Scenario: Tenant without a key falls back to the global key

- **WHEN** a tenant has no stored key for the resolved provider
- **THEN** the call proceeds with the global deployment key exactly as today

#### Scenario: Deleted tenant key stops being used immediately

- **WHEN** an `ADMIN` deletes a tenant's provider key
- **THEN** the tenant's next request on that provider uses the global key (cache evicted), with no restart required

#### Scenario: A delete on one instance evicts the client on every instance

- **WHEN** two agent instances serve the same tenant and an `ADMIN` deletes the tenant's provider key through the first instance
- **THEN** the next request of that tenant on the second instance uses the global key, with no restart

#### Scenario: Invalid tenant key is not silently absorbed by the operator

- **WHEN** a tenant's stored key is rejected by the provider with an authentication error
- **THEN** the user receives an error identifying the tenant-configured key (by provider and `last4`) as the cause, and no retry is made on the global deployment key

### Requirement: Trusted agent code resolves a plain provider key in memory only

ascend-ai-agent SHALL register an implementation of the `ProviderKeyResolver` port of `add-coding-agent-delegation` that replaces its default (which returns the deployment key) and returns the plain provider key of a tenant to trusted agent code in memory, the tenant's stored key first and the global deployment key only when the caller allows it. Its caller is the per-workspace credential gateway of `add-coding-agent-delegation`. The resolved key SHALL never be returned through any API, written to a log or put into a response. The providers `opencode-go` and `opencode-zen` SHALL be accepted as BYOK providers.

#### Scenario: Tenant key first, deployment key only when allowed

- **WHEN** the credential gateway asks for the `opencode-go` key of a tenant with no stored key, once with the deployment key allowed and once without
- **THEN** the first call returns the deployment key and the second returns no key

#### Scenario: OpenCode provider key is stored like any other

- **WHEN** an `ADMIN` upserts an `opencode-zen` key for a tenant and lists the tenant's provider keys
- **THEN** the list contains an entry with `provider = "opencode-zen"` and its `last4`, and no field containing the full key
