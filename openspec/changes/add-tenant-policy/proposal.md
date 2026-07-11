## Why

AscendAI's sovereignty pitch is "your data stays on your infrastructure — pick a local model and nothing leaves your GPU." Today that is a convention, not a control. Provider and model are chosen per request by whoever sends the prompt (`provider` / `model` form fields resolved in `ChatModelResolver`), so any user can route a prompt — and the RAG context stapled to it — to OpenAI or Anthropic even if the customer's policy is local-only. `add-usage-metering-and-quotas` adds per-tenant BYOK keys but still does not constrain which providers a tenant may use.

The same gap exists for tools. MCP tools (web search, weather, and future tools) are exposed to the model globally. A poisoned RAG document can instruct the model to call the web-search tool with sensitive tenant content embedded in the query string — a prompt-injection exfiltration channel that sends private data to an external search engine, entirely within a single chat turn. Nothing lets a tenant say "my users may not use web search" or "only local providers."

This change adds a per-tenant policy surface that makes both enforceable: which providers and models a tenant's requests may use, and which MCP tools its model may call. Allow-listing tools is also the robust mitigation for the injection-exfiltration channel — a tool the model is never given cannot be called.

## What Changes

- **Per-tenant provider and model allow-list**: a policy per tenant naming the permitted providers (subset of `lmstudio`, `openai`, `gemini`, `anthropic`, `minimax`) and, optionally, permitted models per provider. A chat or embedding request selecting a provider or model outside the tenant's allow-list SHALL be rejected with a clear error before any provider call — enforced at `ChatModelResolver`, the same resolution point BYOK and metering already hook. A local-only policy (`lmstudio` alone) makes "data never leaves our infrastructure" enforceable.
- **Per-tenant MCP tool allow-list**: a policy naming the MCP tools a tenant's model may call. Tool availability is filtered per tenant when the chat request assembles its tool callbacks, so a disallowed tool is never exposed to the model and cannot be invoked — closing the RAG-injection exfiltration channel for egress tools like web search.
- **Policy management API** under `/api/v1/admin/policy`, restricted to tenant `ADMIN`, scoped to the caller's tenant: get and update the tenant's provider/model and tool policy. A deployment-level default policy applies to tenants with no explicit policy; a tenant admin may only narrow within the deployment default, never widen beyond it.
- **Default-deny option**: the deployment default policy is configurable; a security-forward deployment can default to local-only providers and no egress tools, with tenants opting in.

## Capabilities

### New Capabilities

- `provider-model-policy`: per-tenant allow-list of providers and models enforced at resolution; requests outside the allow-list rejected before any provider call; deployment default with narrow-only tenant overrides.
- `tool-policy`: per-tenant MCP tool allow-list enforced at tool-callback assembly so disallowed tools are never exposed to the model; the ADMIN policy API; the injection-exfiltration mitigation this provides for egress tools.

### Modified Capabilities

(none as spec deltas — provider resolution (`add-usage-metering-and-quotas`'s tenant-aware `ChatModelResolver`) and MCP tool wiring are defined in sibling/existing code, not in an archived `openspec/specs/` capability this change can modify. The enforcement requirements live in this change's two new capabilities; the resolver and tool-assembly hook points are named in the tasks for coordination.)

## Impact

- **Depends on**: `add-tenant-isolation` (tenant context), `add-auth-and-identity` (ADMIN role), `add-usage-metering-and-quotas` (the tenant-aware `ChatModelResolver` this change gates, and the same policy-cache pattern). Coordinates with `add-audit-and-gdpr-compliance` (policy changes and policy-denied requests emit audit events).
- **AscendAgent (new code)**: `service/policy/TenantPolicyService.java` (+ Caffeine cache keyed by tenant, evicted on update, matching the BYOK client-cache pattern), `model/TenantPolicy` entity + repository, Liquibase changelog for a `tenant_policy` table (JSONB or normalized columns for provider/model/tool allow-lists), `controller/admin/PolicyController.java`; enforcement hooks in `ChatModelResolver` (provider/model gate) and in the chat tool-callback assembly (tool filter).
- **Config**: `app.policy.default.*` for the deployment default policy (allowed providers, allowed tools), env-overridable per `harden-cloud-deployment`.
- **Docs**: a policy section in `docs/SECURITY.md`; `AGENTS.md` endpoint notes; Bruno requests for the policy API.
- **Tests**: request with a disallowed provider rejected before any provider call; local-only policy blocks a request that selects `openai`; a disallowed MCP tool is absent from the model's tool set and a prompt trying to invoke it cannot; tenant admin cannot widen beyond the deployment default; policy change audited.

## Relevant Skills

- `/springboot-security`
- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/jpa-patterns`
- `/database-migrations`
- `/security-review`
- `/springboot-tdd`
