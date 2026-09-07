# Tasks — add-tenant-policy

## 1. Policy schema, entity, and defaults

- [ ] 1.1 Liquibase changelog for `tenant_policy` (tenant id PK/FK, allowed providers, per-provider allowed models, allowed MCP tools — JSONB or normalized), with rollback
- [ ] 1.2 `model/TenantPolicy` entity + `repository/TenantPolicyRepository`
- [ ] 1.3 `config/properties/PolicyDefaultProperties.java` binding `app.policy.default.allowed-providers` and `app.policy.default.allowed-tools`; wire defaults into `application.yaml` (env-overridable)
- [ ] 1.4 `service/policy/TenantPolicyService.java`: resolve effective policy (stored ∩ default, default when unset), Caffeine cache keyed by tenant, eviction on update

## 2. Provider/model enforcement

- [ ] 2.1 Gate `ChatModelResolver` (the tenant-aware resolve from `add-usage-metering-and-quotas`): reject a `(provider, model)` outside the tenant's effective allow-list with a policy exception mapped to a clear 4xx, before building any client or spending tokens; cover chat, embedding, memory-extraction, and compaction resolution paths
- [ ] 2.2 Map the policy exception to an `ApiError` naming the denied provider/model (no silent fallback to an allowed provider)
- [ ] 2.3 Emit an audit event (`add-audit-and-gdpr-compliance`) on a policy-denied request
- [ ] 2.4 Test: a request selecting `openai` under a `lmstudio`-only policy is rejected with a 4xx and no provider call is made; an allowed provider passes
- [ ] 2.5 Test: per-provider model allow-list — an allowed provider with a disallowed model is rejected; empty model list means all models allowed

## 3. Tool policy enforcement

- [ ] 3.1 Filter the MCP tool callbacks assembled for a chat call by the tenant's tool allow-list, so a disallowed tool is absent from the tool set given to the model
- [ ] 3.2 Test (injection-exfiltration): with web search disallowed for the tenant, a prompt (including a RAG-injected instruction) that tries to call web search cannot invoke it — the tool is not present; with it allowed, it is present
- [ ] 3.3 Emit an audit event when a tenant's tool set is materially restricted for a request (once per request, not per tool)

## 4. Policy management API

- [ ] 4.1 `controller/admin/PolicyController.java` under `/api/v1/admin/policy` (tenant `ADMIN`, tenant derived from token): `GET` effective + stored policy; `PUT` update
- [ ] 4.2 Reject a `PUT` that widens beyond the deployment default (a provider/tool outside `app.policy.default.*`) with a clear 4xx
- [ ] 4.3 Evict the tenant's policy cache entry on update (next request sees the new policy, no restart)
- [ ] 4.4 Emit an audit event on policy change
- [ ] 4.5 MockMvc tests: non-admin 403; cross-tenant access refused; widen-beyond-default rejected; update reflected on the next resolution without restart

## 5. Documentation and API collection

- [ ] 5.1 Add a policy section to `docs/SECURITY.md`: provider/model allow-lists, tool allow-lists and the exfiltration mitigation, deployment default and narrow-only overrides, the local-only sovereignty configuration
- [ ] 5.2 Add Bruno requests for the policy API
- [ ] 5.3 Note the policy API and the local-only configuration in `apps/ascend-ai-agent/AGENTS.md`
- [ ] 5.4 Run `./gradlew test integrationTest`; all green
