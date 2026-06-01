# 11. Risks and Technical Debt

---

### Risks

| Risk | Likelihood | Impact | Mitigation |
| :--- | :--------- | :----- | :--------- |
| mem0ai API changes across minor versions | Medium | High | Version is pinned at `1.0.3` in `pyproject.toml`. Review the mem0 changelog before upgrading. Key callsites: `Memory.from_config`, `memory.add`, `memory.search`, `memory.get_all`, `memory.delete` in `src/service/memory_client.py`. |
| `delete_all` bug in mem0ai | Confirmed present | High | Workaround in place (`wipe_user` uses individual deletes). The workaround is O(n) calls. For users with many memories this is slow and generates many Qdrant operations. |
| Qdrant unavailable after startup | Low (stable infra) | High | Warmup retries for 5 min. If Qdrant goes down after `is_ready=True`, subsequent API calls will raise exceptions. REST handlers return HTTP 500. No circuit breaker. |
| LM Studio not running (default provider) | Medium (dev environments) | Medium | `AscendMemoryClient.__init__` fails with `ValueError` on first call. `/health` can return 200 (warmup uses Qdrant only), but insert/search fail at request time. |
| json_object patch breaks future mem0ai version | Low | Medium | The monkey-patch targets `OpenAILLM.generate_response`. If mem0ai renames or restructures the class, the patch silently stops applying. Add an integration test that exercises a local-model insert to detect this. |

---

### Technical debt

| Item | Description | Priority |
| :--- | :---------- | :------- |
| No automated test suite | `tests/` directory is absent. Manual validation only via Bruno collection. | High |
| `wipe_user` is O(n) | Deletes memories one by one due to the mem0ai `delete_all` bug. Performance degrades linearly with memory count per user. | Medium |
| No auth on REST endpoints | Any caller with network access can read or wipe any user's memories. Intended to be addressed at the AscendAgent or API gateway level. | Medium |
| `is_ready` is a module-level global | Not thread-safe for a multi-worker Uvicorn setup (multiple processes). Acceptable for current single-worker deployment; fails silently in multi-worker mode. | Low |
| Provider mismatch detection absent | A caller using mixed providers sees empty search results with no warning. | Low |
