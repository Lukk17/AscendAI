# 9. Architecture Decisions

This chapter summarises the six service-level ADRs. Full records with alternatives and consequences are in
[`docs/architecture/decisions/`](../decisions/).

---

### ADR-001: mem0ai as memory orchestrator

mem0ai handles embedding, Qdrant upsert, semantic deduplication, and fact extraction in a single library call. The
alternative (direct Qdrant client + custom embedding + chunking) would require maintaining code that mem0ai already
provides. Accepted. See [ADR-001](../decisions/ADR-001-mem0ai-as-memory-orchestrator.md).

---

### ADR-002: Qdrant as vector backend

Qdrant is already an external prerequisite for AscendAgent's RAG pipeline. Using the same instance avoids running a
second vector database. mem0ai supports other backends (Chroma, Pinecone, Weaviate) but none are already deployed in
the platform. Accepted. See [ADR-002](../decisions/ADR-002-qdrant-as-vector-backend.md).

---

### ADR-003: `user_id` as memory scope boundary

All four operations require a `user_id` string. mem0ai filters Qdrant payloads by `user_id` at search time. This
keeps the API stateless and the scope boundary explicit on every call. The trade-off is that the service itself
performs no authentication; callers must be trusted to pass the correct `user_id`. Accepted. See
[ADR-003](../decisions/ADR-003-user-id-as-scope-boundary.md).

---

### ADR-004: MCP surface mirrors the REST contract

The four MCP tools (`memory_insert`, `memory_search`, `memory_delete`, `memory_wipe`) map one-to-one to the four REST
endpoints. Both surfaces call `get_memory_client()` from the same service module. The main divergence is that
`memory_insert` (MCP) accepts only `text`, not `messages`; the REST endpoint accepts both. Accepted. See
[ADR-004](../decisions/ADR-004-mcp-mirrors-rest-contract.md).

---

### ADR-005: Liveness / readiness split, RFC 7807 errors, Prometheus `/metrics`

`/health` is always-200 liveness; `/ready` actively probes Qdrant, the embedding API, and the mem0 client.
Error responses use `application/problem+json` (400 with `detail` for `ValueError`, 500 with `detail` redacted for
unhandled exceptions). `/metrics` exposes provider-labelled counters and histograms. Every response echoes
`X-Request-ID` for log correlation. Accepted. See
[ADR-005](../decisions/ADR-005-observability-and-error-envelope.md).

---

### ADR-006: mem0ai 1.0.3 → 2.0.4 upgrade, drop OpenAILLM monkey-patch

mem0ai 2.0.4 fixed `delete_all` cross-tenant wipe and ships a native `lmstudio` LLM provider. The service drops both
of its earlier patches (manual per-id wipe loop, `OpenAILLM.generate_response` monkey-patch) and adopts the 2.x
search signature (`top_k=`, `filters={"user_id": ...}`). Accepted. See
[ADR-006](../decisions/ADR-006-mem0ai-2x-upgrade.md).
