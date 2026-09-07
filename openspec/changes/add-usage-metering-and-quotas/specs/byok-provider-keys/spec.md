# byok-provider-keys — Delta Specification

## ADDED Requirements

### Requirement: Tenant provider keys are stored encrypted at rest with envelope encryption

ascend-ai-agent SHALL store per-tenant provider API keys in a Liquibase-managed PostgreSQL table, encrypted with AES-256-GCM under a per-row data-encryption key that is itself wrapped by a master key-encryption key supplied via environment variable (`USAGE_KEK`). The row SHALL store only ciphertext, the wrapped DEK, the GCM nonce, a KEK identifier, and the key's last four characters. The plaintext key SHALL never be written to logs or persisted unencrypted anywhere.

#### Scenario: Persisted key is not recoverable from the database alone

- **WHEN** a tenant provider key has been stored and the `tenant_provider_key` table contents are inspected directly in PostgreSQL
- **THEN** neither the provider key nor the unwrapped DEK appears in plaintext in any column, and decryption without the KEK fails

#### Scenario: Key material is absent from logs

- **WHEN** a provider key is created via the management API with logging at DEBUG
- **THEN** no log line contains the plaintext key

### Requirement: Provider-key management API is ADMIN-only and write-only

ascend-ai-agent SHALL expose `ADMIN`-role endpoints under `/api/v1/tenants/{tenantId}/provider-keys`: upsert a key for a provider, list configured keys, and delete a key. Read responses SHALL contain only provider name, `last4`, and timestamps — never the key itself, in any encoding. Non-`ADMIN` callers SHALL receive `403`.

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

For every provider call, ascend-ai-agent SHALL resolve credentials in this order: the calling tenant's stored key for the resolved provider, then the global deployment key from `AiProviderProperties`. Tenant-keyed provider clients SHALL be cached and evicted when the tenant's key is upserted or deleted. A provider authentication failure on a tenant key SHALL be surfaced as a client-visible error identifying the tenant key by `last4`, and SHALL NOT be silently retried on the global key.

#### Scenario: Tenant key is used over the global key

- **WHEN** a tenant has a stored Anthropic key and one of its users sends a chat request on the `anthropic` provider
- **THEN** the outbound Anthropic call authenticates with the tenant's key, not the deployment's `ASCEND_ANTHROPIC_API_KEY`

#### Scenario: Tenant without a key falls back to the global key

- **WHEN** a tenant has no stored key for the resolved provider
- **THEN** the call proceeds with the global deployment key exactly as today

#### Scenario: Deleted tenant key stops being used immediately

- **WHEN** an `ADMIN` deletes a tenant's provider key
- **THEN** the tenant's next request on that provider uses the global key (cache evicted), with no restart required

#### Scenario: Invalid tenant key is not silently absorbed by the operator

- **WHEN** a tenant's stored key is rejected by the provider with an authentication error
- **THEN** the user receives an error identifying the tenant-configured key (by provider and `last4`) as the cause, and no retry is made on the global deployment key
