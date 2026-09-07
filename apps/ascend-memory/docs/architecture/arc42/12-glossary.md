# 12. Glossary

| Term | Definition |
| :--- | :--------- |
| **mem0ai** | Python library (v1.0.3) that orchestrates memory operations: embedding, Qdrant upsert, semantic deduplication, and LLM-assisted fact extraction. `src/service/memory_client.py`. |
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
| **json_object patch** | Monkey-patch on `OpenAILLM.generate_response` that strips `response_format={"type":"json_object"}` for providers that do not support it. `src/service/memory_client.py:11-22`. |
| **wipe_user workaround** | Individual-delete loop that replaces the broken `mem0.delete_all`. `src/service/memory_client.py:148-166`. |
