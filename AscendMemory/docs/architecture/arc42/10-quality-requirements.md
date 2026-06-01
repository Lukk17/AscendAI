# 10. Quality Requirements

---

### Quality scenarios

| ID | Quality attribute | Stimulus | Expected response |
| :- | :---------------- | :------- | :---------------- |
| Q1 | **Correctness** | Search with `user_id=A` when memories for users A and B exist | Returns only user A's memories. Qdrant filter on `user_id` in mem0 payload guarantees isolation at the query level. |
| Q2 | **Availability** | Qdrant is temporarily unreachable at container start | `/health` returns 503. Warmup retries for up to 5 minutes. Once Qdrant recovers, `/health` returns 200 without restart. |
| Q3 | **Fault tolerance** | `memory.search()` raises an exception | `AscendMemoryClient.search` catches the exception, logs it, and returns `[]`. The caller's chat flow is not broken. |
| Q4 | **Extensibility** | Adding a new embedding provider (e.g. Mistral) | Add one entry to `PROVIDER_CONFIGS` in `src/config/config.py` and two env vars. No other code changes. |
| Q5 | **Observability** | Cold start completes | Startup banner logs Qdrant connectivity status and the active embedding provider configuration. |
| Q6 | **Correctness (insert)** | Caller omits both `text` and `messages` | `AscendMemoryClient.add` raises `ValueError`. REST handler returns HTTP 400. |

---

### Known gaps

| Gap | Impact |
| :-- | :----- |
| No automated test suite | Regressions in `AscendMemoryClient` logic or API contract go undetected until manual testing. |
| No per-user rate limiting | A single caller can generate unbounded Qdrant writes. |
| No authentication on REST or MCP | Any caller with network access can read or wipe any user's memories. |
| Provider mismatch not detected | Inserting with `lmstudio` and searching with `openai` silently returns empty results (different collections). |
