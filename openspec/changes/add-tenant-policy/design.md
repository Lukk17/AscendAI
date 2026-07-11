# Design — add-tenant-policy

## Context

Provider and model are resolved per request in `ChatModelResolver`, which `add-usage-metering-and-quotas` extends to a tenant-aware `resolve(provider, tenantId)` with a Caffeine cache for BYOK clients. MCP tools are assembled into the chat call's tool callbacks globally, from the Spring AI MCP client connections. Neither resolution point consults any per-tenant policy, so provider choice and tool availability are effectively deployment-wide.

Two concrete risks follow. First, the sovereignty claim is unenforceable: a user on a local-only customer can still route a prompt (with its RAG context) to a cloud provider. Second, MCP tools are an exfiltration channel: a poisoned RAG document can steer the model to call the web-search tool with tenant data in the query, sending private content to an external engine inside one turn.

## Goals / Non-Goals

**Goals:**

- Per-tenant enforcement of which providers and models may be used, at the existing resolution point, before any provider call.
- Per-tenant enforcement of which MCP tools the model may call, by filtering the tool set it is given.
- A tenant-admin policy API that can only narrow within a deployment default, never widen.
- Make local-only ("data never leaves our infrastructure") a hard, testable guarantee.

**Non-Goals:**

- Content-inspection of tool arguments (a heuristic arms race); allow-listing the tool set is the robust control and the one we ship.
- Quota / rate enforcement (owned by `add-usage-metering-and-quotas`).
- Prompt-level DLP or output filtering.
- Any UI.

## Decisions

### D1 — Enforce provider/model policy at `ChatModelResolver`, before the client is built

The provider/model gate lives at the same resolution point BYOK and metering already hook. On resolve, the requested `(provider, model)` is checked against the tenant's allow-list; a violation throws a policy exception surfaced as a clear 4xx before any client is built or any token is spent. Putting it at resolution (not at the controller) covers chat, embedding, memory-extraction, and compaction paths uniformly, since they all resolve through the same component.

### D2 — Enforce tool policy by filtering the tool set given to the model

The tenant's tool allow-list filters the MCP tool callbacks at the point the chat call is assembled, so a disallowed tool is simply absent from the tools the model can see. This is strictly stronger than intercepting tool calls after the fact: a tool the model was never given cannot be invoked, so the RAG-injection exfiltration path for egress tools is closed by construction, not by detection.

### D3 — Deployment default policy, tenant may only narrow

A deployment-level default policy (`app.policy.default.*`) sets the maximum allowed providers and tools. A tenant's stored policy can only be a subset of the default; an update attempting to allow a provider or tool outside the default is rejected. This lets a security-forward operator ship local-only, no-egress-tools defaults and have tenants opt into more only within bounds the operator permits. A tenant with no stored policy inherits the default.

### D4 — Policy storage and caching mirror the BYOK pattern

Policy is a `tenant_policy` row per tenant (provider allow-list, per-provider model allow-list, tool allow-list), cached in Caffeine keyed by tenant and evicted on update — the same shape as `add-usage-metering-and-quotas`'s BYOK client cache, so the resolution path stays a cache read, not a database hit per request.

## Risks / Trade-offs

- [A future tool that is both useful and egress-capable] → the allow-list is per tool, so a new egress tool ships default-off and a tenant opts in explicitly; no blanket on/off.
- [Model selection bypass via a raw base-URL provider] → the gate is on the resolved provider key; any request resolves to one of the known provider keys, and an unknown provider already fails resolution.
- [Policy cache staleness after an update] → eviction on update (same as BYOK) makes the next request see the new policy with no restart.
- [Over-blocking breaks a legitimate flow] → policy-denied requests emit an audit event and a clear error naming the denied provider/model/tool, so an admin can see and adjust.

## Open Questions

- None blocking. Whether per-provider model allow-lists are required at launch or providers-only suffices is settled as: providers-only is mandatory, per-provider model lists optional (empty means all models of an allowed provider).
