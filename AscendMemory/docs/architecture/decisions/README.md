# Architecture Decision Records — AscendMemory

> Index stamped against commit `cdbb447` (branch `feat/agent-deploy-chat-history-caching-rag-attachments`),
> 2026-06-01.

---

| ID | Title | Status | Date |
| :- | :---- | :----- | :--- |
| [ADR-001](ADR-001-mem0ai-as-memory-orchestrator.md) | mem0ai as memory orchestrator | Accepted | 2026-06-01 |
| [ADR-002](ADR-002-qdrant-as-vector-backend.md) | Qdrant as vector backend | Accepted | 2026-06-01 |
| [ADR-003](ADR-003-user-id-as-scope-boundary.md) | `user_id` as memory scope boundary | Accepted | 2026-06-01 |
| [ADR-004](ADR-004-mcp-mirrors-rest-contract.md) | MCP surface mirrors the REST contract | Accepted | 2026-06-01 |
| [ADR-005](ADR-005-observability-and-error-envelope.md) | Liveness / readiness split, RFC 7807 errors, Prometheus `/metrics` | Accepted | 2026-06-01 |
| [ADR-006](ADR-006-mem0ai-2x-upgrade.md) | mem0ai 1.0.3 → 2.0.4, drop OpenAILLM monkey-patch | Accepted | 2026-06-01 |

---

For platform-level decisions (monorepo structure, MCP as standard protocol, external infrastructure prerequisites)
see [docs/architecture/decisions/](../../../../docs/architecture/decisions/).
