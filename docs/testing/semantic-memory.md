### Semantic Memory — End-to-End Test

Verifies semantic memory works end-to-end: a fact stated to the agent in one turn is recalled in a later turn via Qdrant (not from chat history).

#### Pre-flight

Services must be reachable:

```bash
curl http://localhost:7020/health       # AscendMemory
curl http://localhost:6333/collections  # Qdrant
curl http://localhost:9917/             # AscendAgent
```

Use a fresh `user_id` (e.g. `memtest-001`) so prior memories can't pollute results. If reusing one, delete that user's points in the Qdrant Dashboard ([http://localhost:6333/dashboard](http://localhost:6333/dashboard), filter by `user_id`).

The active Qdrant collection depends on the embedding provider — `ascend_memory_768` for `lmstudio` / `gemini`, `ascend_memory_1536` for `openai`. The examples below assume `lmstudio`.

#### Test 1 — Write

**Bruno:** `01-memory-write-fact`. Equivalent curl:

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt \
  -H "X-User-Id: memtest-001" \
  -F "prompt=My name is Luke and I am a software engineer who likes hiking." \
  -F "provider=lmstudio" -F "embeddingProvider=lmstudio"
```

**Pass:** HTTP 200; AscendAgent log shows `Successfully inserted memory fact for user: 'memtest-001'` at least once. Confirm in Qdrant:

```bash
curl -X POST "http://localhost:6333/collections/ascend_memory_768/points/scroll" \
  -H "Content-Type: application/json" \
  -d '{"filter":{"must":[{"key":"user_id","match":{"value":"memtest-001"}}]},"limit":10}' | jq
```

Expect ≥1 point referencing Luke / engineer / hiking.

#### Test 2 — Recall

Before running, clear chat history so the model can't answer from Redis or Postgres instead of Qdrant:

```bash
redis-cli FLUSHALL
psql -h localhost -U postgres -d ascend_ai -c "TRUNCATE TABLE chat_history;"
```

**Bruno:** `02-memory-recall`. Equivalent curl:

```bash
curl -X POST http://localhost:9917/api/v1/ai/prompt \
  -H "X-User-Id: memtest-001" \
  -F "prompt=What do you know about me?" \
  -F "provider=lmstudio" -F "embeddingProvider=lmstudio"
```

**Pass:** AscendAgent log shows `Received N semantic memory items for user: 'memtest-001'` with N ≥ 1, and the response `content` mentions Luke, software engineer, or hiking.
