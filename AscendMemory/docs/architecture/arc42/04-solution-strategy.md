# 4. Solution Strategy

---

### Key decisions

| Decision | Choice | Rationale |
| :------- | :----- | :-------- |
| Memory orchestration library | mem0ai 1.0.3 | Handles embedding, vector upsert, semantic deduplication, and search in one call. The alternative (managing Qdrant collections directly) would require reimplementing chunking, deduplication, and the entity-extraction LLM pass. See [ADR-001](../decisions/ADR-001-mem0ai-as-memory-orchestrator.md). |
| Vector store | Qdrant | Already a platform prerequisite for AscendAgent's RAG pipeline. Avoids a second vector database. See [ADR-002](../decisions/ADR-002-qdrant-as-vector-backend.md). |
| Memory scope | `user_id` string | Simple, stateless, and consistent between REST and MCP callers. No session or JWT required on the memory service itself. See [ADR-003](../decisions/ADR-003-user-id-as-scope-boundary.md). |
| Dual API surface | REST + MCP | REST serves AscendAgent (Java HTTP client). MCP serves any FastMCP-capable agent. Both share `get_memory_client()` so there is one code path. See [ADR-004](../decisions/ADR-004-mcp-mirrors-rest-contract.md). |
| Per-provider singletons | `_client_instances` dict keyed by provider name | mem0ai's `Memory.from_config` is expensive (LLM client init, Qdrant collection check). Singletons amortise that cost across requests. `src/service/memory_client.py:24-44`. |
| Startup readiness gate | Background warmup task with retry loop | Qdrant may not be reachable immediately at container start (Docker networking race). The warmup retries up to 60 times at 5-second intervals before giving up. `/health` returns `503` until the probe succeeds. `src/main.py:28-55`. |
| `wipe_user` implementation | Individual deletes in a loop | mem0ai's `delete_all` resets the entire collection, not just one user's entries. The workaround fetches all memories for the user then deletes them one by one. `src/service/memory_client.py:148-166`. This is a known defect in the upstream library. |
| json_object response format patch | Monkey-patch on `OpenAILLM.generate_response` | Some local models (LM Studio) do not support `response_format={"type":"json_object"}`. The patch strips the unsupported parameter before the call, avoiding a 400 from the local endpoint. `src/service/memory_client.py:11-22`. |
