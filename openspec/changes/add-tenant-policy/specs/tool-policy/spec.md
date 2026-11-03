## ADDED Requirements

### Requirement: Per-tenant tool allow-list filters the model's tool set

Each tenant SHALL have an effective allow-list of the tools its model may call, MCP tools and agent native tools alike. When a chat request or a subagent run assembles its tool callbacks, the agent SHALL include only the tools on the tenant's allow-list, through this change's implementation of the `TenantToolPolicy` port of `add-agent-skills`, which `ChatToolset` applies to every tool, MCP and agent native, so a disallowed tool is never exposed to the model and therefore cannot be invoked. Tools SHALL be named by the prefixed names of `add-mcp-tool-servers`. A tool absent from the deployment default SHALL be off for every tenant until explicitly allowed within the default's bounds. `skill_search` SHALL have no entry of its own and SHALL be offered only when `Skill` or `Task` is offered.

#### Scenario: Disallowed tool is not exposed to the model

- **WHEN** a tenant's policy disallows the web-search tool and a user sends a prompt
- **THEN** the web-search tool is absent from the tool callbacks given to the model for that request

#### Scenario: Allowed tool is available

- **WHEN** a tenant's policy allows the weather tool
- **THEN** the weather tool is present in the tool callbacks for that tenant's requests

#### Scenario: Agent native tool governed by the same allow-list

- **WHEN** a tenant's allow-list does not hold `Task`
- **THEN** `Task` is absent from the tools of that tenant's chat requests and subagent runs
- **AND** `skill_search` is offered only when `Skill` is allowed for that tenant

### Requirement: Server entries, own integrations and a deny list

An allow-list entry `server:<id>` SHALL allow every exposed tool of the MCP server entry with that id. The entry `integrations:own` SHALL allow every tool of the tenant's own integrations of `add-self-built-integrations`. The policy SHALL have one deny list, next to the allow-list, holding tool names and global skill entries written `skill:<name>`. Its deployment part SHALL be read from the settings `app.tool-policy.denied-tools` and `app.tool-policy.denied-global-skills` of `add-agent-skills`, and no other deny setting SHALL exist. The effective deny list SHALL be the union of the deployment part and the tenant's own entries, and a tool or global skill on it SHALL be `denied` whatever an allow-list says.

#### Scenario: Denied tool never found by tool search

- **WHEN** the tenant's policy does not allow `notes_delete_note` and the model searches for "delete a note"
- **THEN** `notes_delete_note` is not in the result and is never added to the request

#### Scenario: A whole server is allowed

- **WHEN** a tenant's allow-list holds `server:ascend-web-hunter`
- **THEN** every exposed tool of that server is in the tenant's tool set

#### Scenario: The deny list wins over a server entry

- **WHEN** a tenant's allow-list holds `server:ascend-web-hunter` and its deny list holds `web_session_establish`
- **THEN** `web_session_establish` is absent from the tenant's tool set
- **AND** the other tools of that server are present

#### Scenario: The deployment deny settings are part of the one deny list

- **WHEN** `app.tool-policy.denied-tools` names `web_session_establish` and `app.tool-policy.denied-global-skills` names `api-design`, and a tenant's policy allows both
- **THEN** `web_session_establish` is absent from the tenant's tool set and `api-design` is not offered to the tenant

#### Scenario: Own integrations are allowed as one entry

- **WHEN** a tenant's allow-list holds `integrations:own`
- **THEN** the tools of that tenant's own integrations are in its tool set
- **AND** no tool of another tenant's integration is

### Requirement: A tool can require approval

Next to the allow-list, a tenant policy SHALL hold an approval-required list. The deployment default SHALL gain `app.policy.default.approval-required-tools`, empty by default, and the effective approval list SHALL be the union of the default and the tenant's own list, so a tenant can add tools and can never remove one the default lists. A tool on both the allow-list and the effective approval list SHALL be `requires_approval`: it SHALL be offered to the model and SHALL never run before an approval of `add-action-approvals`. A tool not on the allow-list SHALL stay `denied`. This change SHALL register its implementation of the `ToolModeResolver` port of `add-action-approvals`, backed by `TenantPolicyService`, in place of that change's configuration-only default. The policy API SHALL read and update the approval list under the same narrow-only rule.

#### Scenario: A requires_approval tool is offered and waits for approval

- **WHEN** a tool is on a tenant's allow-list and on its approval-required list, and the model calls it
- **THEN** the tool was in the tool set given to the model
- **AND** the call does not run before it is approved

#### Scenario: A tenant cannot remove a default approval entry

- **WHEN** the deployment default approval-required list holds a tool and a tenant's own list does not
- **THEN** that tool is still `requires_approval` for the tenant

### Requirement: Module grants per tenant

A tenant policy SHALL hold the module names granted to the tenant, narrowed against `app.policy.default.modules` (default: every active switchable module). A grant SHALL cover only the switchable modules `ocr`, `audio`, `web-search`, `web-download`, `weather`, `obsidian`, `channels`, `openclaw-apps`, `coding`, `self-built-integrations`, `subagents`, `skills`, `self-improvement` and `scheduler`. The always-on parts `core-chat`, `observability` (monitoring), `rag`, `memory`, `sandbox` and the prerequisites SHALL NOT be granted, SHALL NOT be listed in `app.policy.default.modules`, and SHALL be effective for every tenant, so they never answer `module_denied`. Single tools of an always-on module, such as the shell tools `shell`, `file_read` and `file_write` of `sandbox`, SHALL stay governed per tenant by the tool allow-list and the deny list. This change SHALL register its implementation of the `ModuleAccess` port of `add-deployment-modules`, backed by `TenantPolicyService`, replacing the default `AllActiveModuleAccess`. The tool filter SHALL drop the tools of modules not effective for the tenant before it applies the allow-list. An update naming an inactive or unknown module, an always-on module, or a set not closed under `requires`, SHALL be refused with 400.

#### Scenario: A module the tenant lacks is hidden and refused

- **WHEN** the module `subagents` is active but not granted to a tenant
- **THEN** `Task` is absent from that tenant's tool set even when its allow-list holds it
- **AND** a request of that tenant to `/api/v1/subagents/definitions` answers 403 with `code` `module_denied`

#### Scenario: Tenant policy without weather hides its tools

- **WHEN** the tenant policy grants tenant `acme` no `weather` and a user of `acme` sends a prompt
- **THEN** no `weather_` tool is offered to the model for that turn

#### Scenario: Tenant policy never denies a core route

- **WHEN** the tenant policy grants tenant `acme` no switchable module and a user of `acme` calls `POST /api/v1/ingestion/upload`
- **THEN** the request is not refused with `module_denied`

#### Scenario: A grant set not closed under requires is refused

- **WHEN** a tenant `ADMIN` grants `subagents` without `skills`, which `subagents` requires
- **THEN** the update is refused with 400 and the stored policy is unchanged

#### Scenario: An always-on module is never granted or denied

- **WHEN** a tenant `ADMIN` stores a policy whose module grants name `rag`
- **THEN** the update is refused with 400 and the stored policy is unchanged
- **AND** a tenant whose grant list is empty still reaches `/api/v1/documents` and is never answered `module_denied` for `rag`, `memory`, `sandbox` or `observability`

#### Scenario: Shell tools are turned off for one tenant as tools

- **WHEN** a tenant's deny list names `shell`, `file_read` and `file_write`
- **THEN** none of the three tools is in that tenant's tool set
- **AND** another tenant whose allow-list lists them still gets them

### Requirement: Skill allow-list

A tenant policy SHALL hold a skill allow-list of global skill names. A global skill SHALL be offered to a tenant only when its name is on the list. A tenant's own skills SHALL always be offered to that tenant when `Skill` is allowed. A new tenant SHALL start with an empty list.

#### Scenario: A new tenant is offered no global skill

- **WHEN** a tenant has no stored policy
- **THEN** no global skill is in its per-request catalog
- **AND** its own skills are offered when `Skill` is allowed

### Requirement: New tools ship off for a new tenant and tenant default is seeded

The tools that design D8 marks off for a new tenant SHALL be off for a tenant with no stored policy, even when the deployment default lists them, until a tenant `ADMIN` allows them within the default. The default policy of the personal deployment SHALL list the tools design D8 marks for it. The Flyway migration SHALL seed the policy of tenant `default` with those tools, the five tools of `add-obsidian-vault` and the four `web_crawl_*` tools of `enhance-web-search-crawl-at-scale` among them. The global skills of tenant `default` SHALL NOT be seeded by the migration. They SHALL be seeded at agent startup, after the first load of the global catalog, from `SkillCatalog.globalSkillNames()` of `add-agent-skills`: the seed SHALL add to the skill allow-list of tenant `default` every global skill name it has never added before and SHALL record the names it added, so a newly shipped global skill reaches tenant `default` and a name a tenant `ADMIN` removed stays removed.

#### Scenario: A new tenant has the new tools off

- **WHEN** a tenant has no stored policy and the deployment default lists `Task`, `shell` and `scheduled_job_create`
- **THEN** none of the three is in that tenant's tool set
- **AND** `user_facts_update` is in it
- **AND** `Skill` and `skill_read_file` are in it

#### Scenario: Crawl tools are off for a new tenant and on for tenant default

- **WHEN** the deployment default lists `web_crawl_submit`, `web_crawl_job_status`, `web_crawl_list_jobs` and `web_crawl_cancel_job`, a tenant has no stored policy, and the personal deployment runs as tenant `default` after the migration
- **THEN** none of the four is in the tool set of the tenant with no stored policy
- **AND** all four are in the tool set of tenant `default`

#### Scenario: A new tenant starts without the sandbox tools

- **WHEN** a tenant is created and its first chat request runs
- **THEN** the main chat's tool list contains none of `shell`, `file_read` and `file_write`
- **AND** the deployment default policy of the personal deployment still offers all three to tenant `default`

#### Scenario: Scheduled job tools start off for a new tenant

- **WHEN** a new tenant is created and its main chat tool list is built
- **THEN** none of `scheduled_job_create`, `scheduled_job_list`, `scheduled_job_update`, `scheduled_job_cancel` and `owner_notify` is offered, while the personal deployment default policy offers all five

#### Scenario: Policy removes an Obsidian write tool

- **WHEN** the tenant's tool allow-list contains `obsidian_read_note` but not `obsidian_create_note`
- **THEN** the model is offered `obsidian_read_note` and not `obsidian_create_note`, through the `TenantToolPolicy` implementation this change registers

#### Scenario: Tenant default keeps working

- **WHEN** the personal deployment runs as tenant `default` after the migration and the first agent startup
- **THEN** every tool design D8 lists for the personal deployment that exists in the build is in its tool set
- **AND** every global skill is offered

#### Scenario: A newly shipped global skill reaches tenant default

- **WHEN** a build adds a global skill that was not there at the previous startup
- **THEN** after the next agent startup that skill is on the skill allow-list of tenant `default`
- **AND** the seed records its name

#### Scenario: A global skill an ADMIN removed stays removed

- **WHEN** a tenant `ADMIN` removes a global skill from the skill allow-list of tenant `default` and the agent restarts
- **THEN** the seed does not add that skill again
- **AND** it is not offered to tenant `default`

### Requirement: Runs and stored work follow the current policy

Subagent definitions, agent-written or saved by the owner, SHALL be validated against the tenant's allow-list at write time, a definition saved through REST that names a tool outside it SHALL be refused with 403 and `code` `tool_not_allowed` of `add-agent-subagents`, and a run SHALL re-check the allow-list at start, so a policy narrowed after a definition was written still binds the run. A tenant policy that removes a tool SHALL NOT change the stored jobs of `add-scheduled-tasks`, and the tool SHALL be dropped at the next firing.

#### Scenario: A definition with a tool outside the allow-list is not saved

- **WHEN** the tenant's allow-list does not hold `shell` and a tenant `ADMIN` saves a subagent definition that names `shell` in `tools`
- **THEN** the response is 403 with `code` `tool_not_allowed`
- **AND** the definition is not stored

#### Scenario: A run does not get a tool removed after its definition was written

- **WHEN** a definition names `shell` and the tenant later removes `shell` from its allow-list
- **THEN** a run of that definition started afterwards does not get `shell`

### Requirement: One policy decision service behind the five plug-in points

One decision service, `TenantPolicyService`, SHALL decide every tenant policy question: whether a provider and model may be used, the mode of a tool, the effective module grants and whether a global skill is offered. It SHALL read one policy store, the `tenant_policy` table with the deployment default `app.policy.default.*` as the fallback for a tenant that has no row, and SHALL apply the one deny list. The plug-in points `ModelAccessPolicy`, `TenantToolPolicy`, `ToolModeResolver`, `ModuleAccess` and `GlobalSkillPolicy` SHALL stay, and the implementation this change registers on each SHALL delegate to `TenantPolicyService` and SHALL hold no rule, list, setting or cache of its own. `TenantToolPolicy` SHALL allow a tool exactly when `ToolModeResolver` answers a mode other than `denied` for it.

The service SHALL cache the effective policy per tenant with a bounded time to live (setting `app.policy.cache.ttl`, default 5 minutes) and a bounded size (setting `app.policy.cache.max-size`, default 1000 entries). Several agent instances SHALL see a policy change without waiting for the time to live: a policy write SHALL send a Postgres `NOTIFY` on the channel `tenant_policy_changed` with the tenant id in the transaction of the write, every agent instance SHALL receive it through the one Postgres listener of `add-keycloak-login` and evict the tenant's entry, and an instance that lost its listening connection SHALL clear its whole policy cache once the connection is back.

#### Scenario: Two ports never disagree about one tool

- **WHEN** a tenant's policy allows `server:ascend-web-hunter` and denies `web_session_establish`
- **THEN** `TenantToolPolicy` refuses `web_session_establish` and `ToolModeResolver` answers `denied` for it
- **AND** both answer the same for every other tool of that server

#### Scenario: A policy change reaches another agent instance

- **WHEN** two agent instances serve one tenant and a tenant `ADMIN` updates its tool allow-list through the first instance
- **THEN** the next request of that tenant on the second instance uses the new allow-list
- **AND** it does so before the time to live of the old cache entry ends

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

ascend-ai-agent SHALL expose `/api/v1/admin/policy` (tenant `ADMIN`) to get and update the caller's tenant policy (provider/model and tool allow-lists, the approval-required list, the deny list, the module grants and the skill allow-list). The operated tenant SHALL be derived from the token, never a parameter; a non-admin SHALL receive 403 and a cross-tenant attempt SHALL receive 403. An update that widens beyond the deployment default SHALL be rejected with 400 and `code` `validation`, and every policy change SHALL record one event through `AuditEventPort` of `add-deployment-modules` and evict the tenant's policy cache on every agent instance so the next request on any instance sees it without a restart.

#### Scenario: Update takes effect without restart

- **WHEN** a tenant `ADMIN` updates the tenant's allowed tools and a new request is made
- **THEN** the new request's tool set reflects the updated policy with no restart
- **AND** one `ADMIN_OPERATION` event naming the policy change reaches `AuditEventPort`

#### Scenario: Widen beyond default rejected

- **WHEN** a tenant `ADMIN` attempts to allow a provider or tool outside the deployment default
- **THEN** the update is rejected with 400 `application/problem+json` with `code` `validation` and the stored policy is unchanged

### Requirement: Tenant policy is covered by end-to-end tests against the live stack

The ascend-ai-agent e2e suite SHALL check provider and model denials with a deterministic Bruno test that calls no chat model, and SHALL check tool exposure with a deterministic spec in which the scripted model of the shared e2e harness of `close-agent-test-gaps`, which starts only for deterministic tests and never for AI-run specs, calls the tool on cue and its request log (`GET /mockoon-admin/logs`) shows which tools each request offered, so no AI model decides the verdict. The specs SHALL use the e2e users of tenants `e2e-acme`, `e2e-globex` and `default`, SHALL put back every stored policy they change, and SHALL assert statuses, problem detail codes and persisted rows, never a log line. The audit rows of policy events and the absence of usage rows for refused requests are checked by `add-audit-and-gdpr-compliance` and `add-usage-metering-and-quotas`, which land after this change. The policy API, the module grants and the skill allow-list are proved by integration and MockMvc tests and get no end-to-end spec of their own (owner answer 91.3 of 2026-10-08).

#### Scenario: A denied provider is refused in the live stack before any provider call

- **WHEN** the provider denial spec stores a local-only policy for `e2e-acme` and a user of that tenant prompts with `provider=openai`
- **THEN** the answer is 403 `application/problem+json` with `code` `provider_denied`
- **AND** no `chat_history` row is written for the request

#### Scenario: A denied egress tool is never used in a live chat turn

- **WHEN** the tool exposure spec denies web search for `e2e-acme` and sends a prompt whose scripted model calls the web search tool
- **THEN** the scripted model's request log shows the web search tool was not offered
- **AND** ascend-web-hunter's search session keys are unchanged
