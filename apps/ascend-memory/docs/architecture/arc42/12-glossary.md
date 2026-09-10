# 12. Glossary

| Term | Definition |
| :--- | :--------- |
| **mem0ai** | Python library (v2.0.4) that orchestrates memory operations: embedding, Qdrant upsert, semantic deduplication, and LLM-assisted fact extraction. `src/service/memory_client.py`. |
| **AscendMemoryClient** | Thin wrapper around `mem0.Memory`. One singleton instance per provider, cached in `_client_instances`. Provides `search`, `add`, `delete`, `wipe_user`. |
| **Provider** | A named embedding configuration: `lmstudio`, `openai`, or `gemini`. Each maps to a base URL, API key env var, embedding model, and Qdrant collection. `src/config/config.py:PROVIDER_CONFIGS`. |
| **PROVIDER_CONFIGS** | Module-level dict in `src/config/config.py` mapping provider name to its full configuration. The single place to add a new provider. |
| **Qdrant** | Vector database used for storing and searching memory embeddings. Collections are named `ascend_memory_768` (768-dim) and `ascend_memory_1536` (1536-dim). |
| **Collection** | A named Qdrant vector set. AscendMemory uses one collection per embedding dimension: `ascend_memory_768` for lmstudio/gemini, `ascend_memory_1536` for openai. |
| **user_id** | String identifier that scopes all memory operations. Passed on every insert, search, delete, and wipe. mem0ai filters Qdrant by this value at query time. |
| **MCP** | Model Context Protocol. JSON-RPC 2.0 over Streamable HTTP. AscendMemory exposes tools via FastMCP at `/mcp`. |
| **FastMCP** | Python library (v2.14.5) for building MCP servers. Mounts as an ASGI sub-app inside FastAPI. |
| **warmup_client** | Background asyncio task that probes Qdrant connectivity on startup. Sets `is_ready=True` on first success. `src/main.py:28-55`. |
| **is_ready** | Module-level boolean in `src/main.py`. Drives `/health` status code (503 when False, 200 when True). |
| **MEM0_INFER_MEMORY** | Boolean setting. When `True`, mem0ai uses the LLM to infer and compress facts from the input rather than storing it verbatim. Default `False`. |
| **lmstudio LLM provider** | mem0's native LLM provider for LM Studio (`provider="lmstudio"`), in use since the mem0ai 2.0.4 upgrade. Replaced an `OpenAILLM.generate_response` monkey-patch that stripped `response_format={"type":"json_object"}` for LM Studio. See ADR-006. `src/service/memory_client.py:134-137`. |
| **wipe_user** | Calls `self.memory.delete_all(user_id=...)` directly, one Qdrant call scoped by a `user_id` filter. Replaced a manual per-id delete loop after mem0 2.0.4 fixed `delete_all`'s cross-user `reset()` bug. See ADR-006. `src/service/memory_client.py:245-264`. |
