# 2. Constraints

---

### Technical constraints

| Constraint | Reason |
| :--------- | :----- |
| Python 3.11 | Matches the other Python services in the monorepo (AudioScribe, AscendWebSearch, PaddleOCR). |
| mem0ai 1.0.3 | The mem0 API changed across minor versions; the `Memory.from_config` pattern and the `results` key in return values are pinned to this version. Upgrading requires verifying the dict shapes in `src/service/memory_client.py:109-166`. |
| Qdrant as the only supported vector store | mem0ai supports multiple backends; this service hard-codes `"provider": "qdrant"` in the config dict (`src/service/memory_client.py:76-101`). |
| OpenAI-compatible embedding API | All three providers (LM Studio, OpenAI, Gemini) must expose an OpenAI-compatible `/embeddings` endpoint. The `embedder.provider` in the mem0 config is always `"openai"` regardless of which service backs it. |
| Single Qdrant instance | The service connects to one Qdrant host; there is no read-replica or sharding configuration. |

---

### Organisational constraints

| Constraint | Reason |
| :--------- | :----- |
| No database other than Qdrant | Memory persistence lives entirely in Qdrant vectors. There is no relational backing store for metadata or audit logs. |
| User-scoped isolation by convention | Qdrant does not enforce per-user access control. The `user_id` filter applied at search time is the only isolation boundary. A caller who passes another user's `user_id` will see that user's memories. No auth layer enforces user identity at the memory endpoint. |
| No test suite at time of writing | `tests/` directory does not exist in the repository. Correctness is validated manually via the Bruno collection at `docs/api/request/AscendAI/memory/`. This is a known gap (see chapter 11). |
