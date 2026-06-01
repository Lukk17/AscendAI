# Architecture Decision Records

---

### Monorepo-level decisions

| ID                                                                      | Decision                                                                        | Status   |
| :---------------------------------------------------------------------- | :------------------------------------------------------------------------------ | :------- |
| [ADR-M001](ADR-M001-monorepo-structure.md)                              | Monorepo with polyglot services (Java + Python)                                 | Accepted |
| [ADR-M002](ADR-M002-mcp-for-tool-services.md)                           | MCP as the standard protocol for tool services                                  | Accepted |
| [ADR-M003](ADR-M003-external-infrastructure-prerequisites.md)           | Infrastructure services (Redis, Qdrant, MinIO) as external prerequisites        | Accepted |

---

### AscendAgent-specific decisions

Detailed ADRs for the AscendAgent internal architecture live in
[AscendAgent/docs/architecture/decisions/](../../../AscendAgent/docs/architecture/decisions/).

| ID      | Decision                                                |
| :------ | :------------------------------------------------------ |
| ADR-001 | Multi-provider AI with per-request routing.             |
| ADR-002 | OpenAI-compatible endpoints for Gemini and MiniMax.     |
| ADR-003 | Semantic memory via REST instead of MCP.                |
| ADR-004 | MCP for tool integration.                               |
| ADR-005 | Thinking model response resolution.                     |
| ADR-006 | Multi-provider semantic memory routing.                 |
| ADR-007 | Ingestion auto-poller off by default.                   |
