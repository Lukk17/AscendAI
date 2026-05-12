# Semantic memory — e2e test

## What this verifies

- A fact stated in one turn is extracted and stored in Qdrant via AscendMemory.
- The fact is retrieved on a later, independent turn after chat history has been cleared.
- The response on the recall turn references the stored fact.

The reset between turns guarantees that recall cannot come from short-term chat history — only from semantic memory.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the AscendAgent health endpoint.

```bash
curl -fsS http://localhost:9917/actuator/health
```

Expect HTTP 200 with `{"status":"UP"}`.

Check AscendMemory is reachable.

```bash
curl -fsS http://localhost:7020/health
```

Expect HTTP 200.

Check Qdrant is reachable.

```bash
curl -fsS http://localhost:6333/healthz
```

Expect HTTP 200.

Check Redis responds.

```bash
redis-cli -h localhost -p 6379 ping
```

Expect `PONG`.

Check Postgres responds.

```bash
psql "postgresql://postgres:local@localhost:5432/ascend_ai" -c "SELECT 1"
```

Expect a row with `1` in the output.

The Bruno requests pin `X-User-Id: frosty`. The reset commands below assume that user id.

## Reset state

Clear short-term chat for `frosty` in Redis.

```bash
redis-cli -h localhost -p 6379 DEL chat:frosty
```

Clear archived chat history for `frosty` in Postgres.

```bash
psql "postgresql://postgres:local@localhost:5432/ascend_ai" -c "DELETE FROM chat_history WHERE user_id = 'frosty';"
```

Wipe stored semantic memory points for `frosty` in Qdrant.

```bash
curl -X POST http://localhost:6333/collections/ascend_memory_1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"user_id","match":{"value":"frosty"}}]}}'
```

## Run

Step 1 — save turn. Send the request and wait for HTTP 200 before continuing.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/memory-test-save.yml" --env ascend-local
```

Step 2 — clear short-term chat again so the recall turn cannot leak from chat history. Run both commands and wait for them to return before continuing.

```bash
redis-cli -h localhost -p 6379 DEL chat:frosty
```

```bash
psql "postgresql://postgres:local@localhost:5432/ascend_ai" -c "DELETE FROM chat_history WHERE user_id = 'frosty';"
```

Step 3 — recall turn. Send the request and wait for the response before moving to the Expected section.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/memory-test-retrieve.yml" --env ascend-local
```

## Expected

After step 1 the Bruno output shows HTTP 200, and the AscendAgent log contains `Inserted N/N facts for user 'frosty'` with N ≥ 1.

After step 1 a Qdrant scroll on the active `ascend_memory_*` collection filtered by `user_id=frosty` returns at least one point whose payload mentions Luke and software engineer.

After step 3 the Bruno output shows HTTP 200, the AscendAgent log contains `SemanticMemory: YES (N items)` with N ≥ 1, and the response `content` mentions `Luke` and `software engineer`.

If recall says it doesn't know the name, verify the same `embeddingProvider` was used in both turns, that Qdrant contains a point for `frosty` in the active collection, and that AscendMemory is healthy.

## Fixtures

None.
