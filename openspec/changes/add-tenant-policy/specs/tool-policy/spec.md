## ADDED Requirements

### Requirement: Per-tenant MCP tool allow-list filters the model's tool set

Each tenant SHALL have an effective allow-list of MCP tools its model may call. When a chat request assembles its tool callbacks, the agent SHALL include only the tools on the tenant's allow-list, so a disallowed tool is never exposed to the model and therefore cannot be invoked. A tool absent from the deployment default SHALL be off for every tenant until explicitly allowed within the default's bounds.

#### Scenario: Disallowed tool is not exposed to the model

- **WHEN** a tenant's policy disallows the web-search tool and a user sends a prompt
- **THEN** the web-search tool is absent from the tool callbacks given to the model for that request

#### Scenario: Allowed tool is available

- **WHEN** a tenant's policy allows the weather tool
- **THEN** the weather tool is present in the tool callbacks for that tenant's requests

### Requirement: Tool allow-listing mitigates RAG-injection exfiltration

Because a disallowed tool is never given to the model, a prompt-injection payload in retrieved RAG content that instructs the model to call an egress tool (e.g., web search) with tenant data SHALL NOT be able to invoke that tool when the tenant has disallowed it. This mitigation SHALL be by construction (the tool is absent), not by inspecting tool-call arguments.

#### Scenario: Injected web-search call cannot fire when disallowed

- **WHEN** a tenant disallows web search and a retrieved document contains an instruction telling the model to call web search with sensitive text
- **THEN** no web-search tool call is executed because the tool is not present in the model's tool set
- **AND** no request carrying that text leaves the deployment via the web-search tool

#### Scenario: Egress tool defaults off

- **WHEN** the deployment default policy does not list an egress tool
- **THEN** no tenant's model is given that tool until an admin allows it within the default's bounds

### Requirement: Tenant-admin policy API scoped to the caller's tenant

ascend-ai-agent SHALL expose `/api/v1/admin/policy` (tenant `ADMIN`) to get and update the caller's tenant policy (provider/model and tool allow-lists). The operated tenant SHALL be derived from the token, never a parameter; a non-admin SHALL receive 403 and a cross-tenant attempt SHALL receive 403. An update that widens beyond the deployment default SHALL be rejected with a 4xx, and every policy change SHALL emit an audit event and evict the tenant's policy cache so the next request sees it without a restart.

#### Scenario: Update takes effect without restart

- **WHEN** a tenant `ADMIN` updates the tenant's allowed tools and a new request is made
- **THEN** the new request's tool set reflects the updated policy with no restart
- **AND** an audit row records the policy change

#### Scenario: Widen beyond default rejected

- **WHEN** a tenant `ADMIN` attempts to allow a provider or tool outside the deployment default
- **THEN** the update is rejected with a 4xx and the stored policy is unchanged
