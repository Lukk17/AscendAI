# Semantic memory: e2e test

## What this verifies

- A fact stated in one turn is extracted and stored in Qdrant via AscendMemory.
- The fact is retrieved on a later, independent turn after chat history has been cleared.
- The response on the recall turn references the stored fact.

The reset between turns guarantees that recall cannot come from short-term chat history. Only from semantic memory.

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

Check Redis responds. Run inside the `redis` container because `redis-cli` is not on the host shell in this dev environment.

```bash
docker exec redis redis-cli ping
```

Expect `PONG`.

Check Postgres responds. Run inside the `postgres` container because `psql` is not on the host shell.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT 1"
```

Expect a row with `1` in the output.

The Bruno requests pin `X-User-Id: frostySemanticMemoryTest`. The reset commands below assume that user id.

## Reset state

Clear short-term chat for `frostySemanticMemoryTest` in Redis.

```bash
docker exec redis redis-cli DEL chat:frostySemanticMemoryTest
```

Clear archived chat history for `frostySemanticMemoryTest` in Postgres.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostySemanticMemoryTest';"
```

Wipe stored semantic memory points for `frostySemanticMemoryTest` in Qdrant.

```bash
curl -X POST http://localhost:6333/collections/ascend_memory_1536/points/delete -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"user_id","match":{"value":"frostySemanticMemoryTest"}}]}}'
```

## Run

Step 1. Save turn. Send the request and wait for HTTP 200 before continuing.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/memory-test-save.yml" --env ascend-local
```

Step 2. Clear short-term chat again so the recall turn cannot leak from chat history. Run both commands and wait for them to return before continuing.

```bash
docker exec redis redis-cli DEL chat:frostySemanticMemoryTest
```

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostySemanticMemoryTest';"
```

Step 3. Recall turn. Send the request and wait for the response before moving to the Expected section.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/memory-test-retrieve.yml" --env ascend-local
```

## Post-run cleanup

This spec writes four pieces of per-user state: `chat_history` rows in Postgres, the Redis `chat:` cache key, a Redis instructions-cache entry that `UserInstructionService` writes on every prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions), and the extracted facts that AscendMemory stores as Qdrant points. Remove all four so the run leaves the system exactly as it found it. Run these regardless of whether the Run steps passed or failed. Every command is idempotent.

Wipe the stored facts through AscendMemory rather than deleting from one Qdrant collection by hand. With no `provider` query parameter the endpoint clears the user across every provider collection (`ascend_memory`, `ascend_memory_768`, `ascend_memory_1536`), so it stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostySemanticMemoryTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostySemanticMemoryTest"}`.

Confirm nothing survived in the collection the Run steps asserted against.

```bash
curl -sS -X POST "http://localhost:6333/collections/ascend_memory_1536/points/scroll" -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"user_id","match":{"value":"frostySemanticMemoryTest"}}]},"limit":10,"with_payload":true,"with_vector":false}'
```

Expect an empty `result.points` array.

Drop this spec's chat-history rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostySemanticMemoryTest';"
```

Drop the Redis chat cache key.

```bash
docker exec redis redis-cli DEL chat:frostySemanticMemoryTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostySemanticMemoryTest:instructions
```

## Expected

After step 1 the Bruno output shows HTTP 200.

Wait ~5 seconds after step 1 returns before running the Qdrant scroll. Mem0 writes the extracted facts to Qdrant asynchronously after the `/api/v1/memory/insert` call returns, so an immediate scroll can race the writer and miss the new points.

```bash
sleep 5
```

After the wait, a Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` on the active `ascend_memory_*` collection returns at least one point whose payload mentions Luke and software engineer:

```bash
curl -sS -X POST http://localhost:6333/collections/ascend_memory_1536/points/scroll -H "Content-Type: application/json" -d '{"filter":{"must":[{"key":"user_id","match":{"value":"frostySemanticMemoryTest"}}]},"limit":5,"with_payload":true,"with_vector":false}'
```

The point count returned by that scroll is ≥ 1, and at least one point's `payload.data` (or equivalent payload field) contains `Luke` AND `software engineer`.

After step 3 the Bruno output shows HTTP 200.

After step 3 the response body's `content` field contains both `Luke` and `software engineer`. Because chat history was wiped between save and recall, the only way the recall response can know those facts is via semantic memory.

The response body's `content` field is NOT a refusal like "I don't know your name". That indicates the semantic-memory pipeline did not deliver the stored facts.

## Fixtures

None.

## Concurrency

- **Mutates:** Qdrant collections `ascend_memory_*` (user-scoped: `frostySemanticMemoryTest`); Postgres `chat_history` (user_id=`frostySemanticMemoryTest`); Redis keys `chat:frostySemanticMemoryTest` and `user:frostySemanticMemoryTest:instructions`
- **Conflicts with:** none
- **Serial:** false
- **Hermetic contract:** Self-cleaning. `Post-run cleanup` removes the stored facts through AscendMemory and drops every row and key the Run steps wrote.
