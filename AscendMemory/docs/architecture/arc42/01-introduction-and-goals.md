# 1. Introduction and Goals

---

### Purpose

AscendMemory is the semantic memory microservice for the AscendAI platform. It accepts text or conversation messages,
embeds them with a configurable provider (LM Studio, OpenAI, or Gemini), stores the resulting vectors in Qdrant, and
returns ranked search results on demand.

Two API surfaces expose identical memory operations. The REST API under `/api/v1/memory/` is the primary path used by
AscendAgent. The MCP server at `/mcp` exposes the same four operations as FastMCP tools so any MCP-capable agent can
reach memory without an HTTP client library. Both surfaces run on the same Uvicorn process, port 7020.

(`src/main.py:58-95`, `src/config/startup_banner.py:95-104`)

---

### Stakeholders

| Role | Expectation |
| :--- | :---------- |
| AscendAgent (primary caller) | Fast insert and search via REST; sub-second p99 on typical user memory sets. |
| Platform operator | Simple env-var configuration; observable startup and readiness state. |
| MCP-capable agents | All four operations available as named tools over Streamable HTTP. |
| Developer | Swappable embedding providers with zero code changes; testable in isolation. |

---

### Quality goals

| Priority | Goal | Scenario |
| :------- | :--- | :------- |
| 1 | **Correctness** | Search returns only results for the requested `user_id`; cross-user leakage must not occur. |
| 2 | **Availability** | The service reports `/health 503` during cold-boot, then `200` once Qdrant is confirmed reachable. |
| 3 | **Extensibility** | Adding a new embedding provider requires only a new entry in `PROVIDER_CONFIGS` and two env vars. |
| 4 | **Observability** | Every request logs method, path, and provider. Startup banner reports Qdrant connectivity and embedding config. |
