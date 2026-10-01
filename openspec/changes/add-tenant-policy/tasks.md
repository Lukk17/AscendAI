# Tasks - add-tenant-policy

## 1. Policy schema, entity, and defaults

Depends on `add-usage-metering-and-quotas` (tenant-aware `ChatModelResolver`, Caffeine), `add-audit-and-gdpr-compliance` and `add-tenant-administration` being merged first. See design, Dependencies.

- [ ] 1.0 Confirm `caffeine` is declared once in `apps/ascend-agent/gradle/libs.versions.toml` (added by `add-usage-metering-and-quotas` task 1.3) and referenced from `apps/ascend-agent/build.gradle.kts`. Add the entry, version from the Spring Boot dependency management, only if it is missing. Acceptance: `grep -c caffeine apps/ascend-agent/gradle/libs.versions.toml` prints 1 and `./gradlew build` passes
- [ ] 1.1 Liquibase changelog `apps/ascend-agent/src/main/resources/db/changelog/<NN>-tenant-policy.xml` (NN is the next free number at implementation time) for `tenant_policy` (tenant id PK and FK to `tenants(id)`, JSONB allowed providers, per-provider allowed models, allowed MCP tools), with rollback, registered in `db.changelog-master.yaml`. Acceptance: `./gradlew integrationTest` applies it on Testcontainers Postgres
- [ ] 1.2 `model/TenantPolicy` Spring Data JDBC aggregate + `repository/TenantPolicyRepository`. Acceptance: a repository integration test saves and reads back a policy with all three lists
- [ ] 1.3 `config/properties/PolicyDefaultProperties.java` binding `app.policy.default.allowed-providers` and `app.policy.default.allowed-tools`; wire defaults into `application.yaml` (env-overridable). Acceptance: a binding test reads both lists from properties
- [ ] 1.4 `service/policy/TenantPolicyService.java`: resolve effective policy (stored ∩ default, default when unset), Caffeine cache keyed by tenant, eviction on update. Acceptance: unit tests cover stored ∩ default, unset → default, and eviction

## 2. Provider/model enforcement

- [ ] 2.1 Gate `ChatModelResolver` (the tenant-aware resolve from `add-usage-metering-and-quotas`): reject a `(provider, model)` outside the tenant's effective allow-list with a policy exception mapped to a clear 4xx, before building any client or spending tokens; cover chat, embedding, memory-extraction, and compaction resolution paths. Acceptance: tasks 2.4 and 2.5 pass
- [ ] 2.2 Map the policy exception to an `ApiError` naming the denied provider/model (no silent fallback to an allowed provider). Acceptance: a MockMvc test asserts status 403 and the provider name in the body
- [ ] 2.3 Emit an `ADMIN_OPERATION` audit event through `AuditRecorder` (`add-audit-and-gdpr-compliance`) on a policy-denied request. Acceptance: the denied request in task 2.4 leaves one `audit_log` row
- [ ] 2.4 Test: a request selecting `openai` under a `lmstudio`-only policy is rejected with a 4xx and no provider call is made; an allowed provider passes
- [ ] 2.5 Test: per-provider model allow-list - an allowed provider with a disallowed model is rejected; empty model list means all models allowed

## 3. Tool policy enforcement

- [ ] 3.1 Extend `getToolCallbacks()` in `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/mcp/FilteredToolCallbackProvider.java`: after `McpToolCallbackCache.getOrList(...)`, keep only callbacks whose sanitized tool name is on the effective tool allow-list of the tenant in `TenantContext`, read through `TenantPolicyService`, and return no tools when no tenant is resolved. Leave `McpToolCallbackCache` tenant-agnostic. Acceptance: `FilteredToolCallbackProviderTest` gains cases for allowed, disallowed and no-tenant, and the existing cases still pass
- [ ] 3.2 Test (injection-exfiltration): with web search disallowed for the tenant, a prompt (including a RAG-injected instruction) that tries to call web search cannot invoke it - the tool is not present; with it allowed, it is present
- [ ] 3.3 Emit an audit event when a tenant's tool set is materially restricted for a request (once per request, not per tool). Acceptance: one `audit_log` row per restricted request in the task 3.2 test

## 4. Policy management API

- [ ] 4.1 `controller/admin/PolicyController.java` under `/api/v1/admin/policy` (tenant `ADMIN`, tenant derived from token): `GET` effective + stored policy; `PUT` update. Acceptance: task 4.5 passes
- [ ] 4.2 Reject a `PUT` that widens beyond the deployment default (a provider/tool outside `app.policy.default.*`) with a clear 4xx. Acceptance: covered by task 4.5
- [ ] 4.3 Evict the tenant's policy cache entry on update (next request sees the new policy, no restart). Acceptance: covered by task 4.5
- [ ] 4.4 Emit an `ADMIN_OPERATION` audit event on policy change. Acceptance: one `audit_log` row per `PUT` in the task 4.5 test
- [ ] 4.5 MockMvc tests: non-admin 403; cross-tenant access refused; widen-beyond-default rejected; update reflected on the next resolution without restart

## 5. Documentation and API collection

- [ ] 5.1 Add a policy section to `docs/SECURITY.md`: provider/model allow-lists, tool allow-lists and the exfiltration mitigation, deployment default and narrow-only overrides, the local-only sovereignty configuration. Acceptance: the section exists and shows a local-only example
- [ ] 5.2 Add Bruno requests for the policy API under `docs/api/request/AscendAI/`. Acceptance: `bru run` of the new folder against the local stack returns the expected statuses
- [ ] 5.3 Note the policy API and the local-only configuration in `apps/ascend-agent/AGENTS.md`. Acceptance: both appear there
- [ ] 5.4 Run `./gradlew test integrationTest` from `apps/ascend-agent`. Acceptance: both green
