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

ADR-M004 through ADR-M009 are the decision set behind [permission-aware retrieval](../permission-aware-retrieval.md), which is the design document they belong to.

---

### AscendAgent-specific decisions

Detailed ADRs for the AscendAgent internal architecture live in [AscendAgent/docs/architecture/decisions/](../../../AscendAgent/docs/architecture/decisions/).

| ID      | Decision                                                |
| :------ | :------------------------------------------------------ |
| ADR-001 | Multi-provider AI with per-request routing.             |
| ADR-002 | OpenAI-compatible endpoints for Gemini and MiniMax.     |
| ADR-003 | Semantic memory via REST instead of MCP.                |
| ADR-004 | MCP for tool integration.                               |
| ADR-005 | Thinking model response resolution.                     |
| ADR-006 | Multi-provider semantic memory routing.                 |
| ADR-007 | Ingestion auto-poller off by default.                   |
| ADR-008 | MCP startup tolerance via `initialized=false` and deferred init loop. |
