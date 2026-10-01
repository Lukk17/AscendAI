# Architecture Decision Records

---

### Monorepo-level decisions

| ID                                                                      | Decision                                                                        | Status   |
| :---------------------------------------------------------------------- | :------------------------------------------------------------------------------ | :------- |
| [ADR-M001](ADR-M001-monorepo-structure.md)                              | Monorepo with polyglot services (Java + Python)                                 | Accepted |
| [ADR-M002](ADR-M002-mcp-for-tool-services.md)                           | MCP as the standard protocol for tool services                                  | Accepted |
| [ADR-M003](ADR-M003-external-infrastructure-prerequisites.md)           | Infrastructure services (Redis, Qdrant, S3-compatible object storage) as external prerequisites | Accepted |
| [ADR-M004](ADR-M004-acl-mirroring-onto-chunks.md)                       | Mirror access lists onto chunks rather than querying the source per request                     | Accepted |
| [ADR-M005](ADR-M005-pre-filter-in-vector-search.md)                     | Filter inside the vector search, not after it                                                   | Accepted |
| [ADR-M006](ADR-M006-deny-by-default-on-missing-acl.md)                  | A chunk with no recorded access list is invisible                                               | Accepted |
| [ADR-M007](ADR-M007-group-principals-membership-at-login.md)            | Access lists name groups, membership resolves at login                                          | Accepted |
| [ADR-M008](ADR-M008-email-join-with-provider-identifiers.md)            | Join provider identities on email, keep both provider identifiers                               | Accepted |
| [ADR-M009](ADR-M009-enforcement-in-the-agent.md)                        | Enforcement lives in the agent's retrieval path, not behind a network hop                       | Accepted |
| [ADR-M010](ADR-M010-consumer-driven-contract-in-repo.md)                | Agent to OCR contract as a Pact file committed in the repository, no Pact Broker                | Accepted |

ADR-M004 through ADR-M009 are the decision set behind [permission-aware retrieval](../permission-aware-retrieval.md), which is the design document they belong to.

---

### ascend-ai-agent-specific decisions

Detailed ADRs for the ascend-ai-agent internal architecture live in [apps/ascend-agent/docs/architecture/decisions/](../../../apps/ascend-agent/docs/architecture/decisions/).

| ID      | Decision                                                |
| :------ | :------------------------------------------------------ |
| [ADR-001](../../../apps/ascend-agent/docs/architecture/decisions/ADR-001-multi-provider-ai.md) | Multi-provider AI with per-request routing. |
| [ADR-002](../../../apps/ascend-agent/docs/architecture/decisions/ADR-002-openai-compatible-gemini-minimax.md) | OpenAI-compatible endpoints for Gemini and MiniMax. |
| [ADR-003](../../../apps/ascend-agent/docs/architecture/decisions/ADR-003-semantic-memory-rest-over-mcp.md) | Semantic memory via REST instead of MCP. |
| [ADR-004](../../../apps/ascend-agent/docs/architecture/decisions/ADR-004-mcp-for-tool-integration.md) | MCP for tool integration. |
| [ADR-005](../../../apps/ascend-agent/docs/architecture/decisions/ADR-005-thinking-model-response-resolution.md) | Thinking model response resolution. |
| [ADR-006](../../../apps/ascend-agent/docs/architecture/decisions/ADR-006-multi-provider-semantic-memory-routing.md) | Multi-provider semantic memory routing. |
| [ADR-007](../../../apps/ascend-agent/docs/architecture/decisions/ADR-007-ingestion-auto-default-off.md) | Ingestion auto-poller off by default. |
| [ADR-008](../../../apps/ascend-agent/docs/architecture/decisions/ADR-008-mcp-startup-tolerance.md) | MCP startup tolerance via `initialized=false` and deferred init loop. |
| [ADR-009](../../../apps/ascend-agent/docs/architecture/decisions/ADR-009-docling-bounded-retry-fanout-cap.md) | Bounded retry and fan-out cap for Docling page conversion. |
| [ADR-010](../../../apps/ascend-agent/docs/architecture/decisions/ADR-010-mcp-tool-listing-cache.md) | MCP tool listing cached per connected-server set, with a 60 s expiry and invalidation on tools-changed notifications. |