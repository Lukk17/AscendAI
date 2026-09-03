# Chat-history compaction: idempotency: e2e test

## What this verifies

When the chat history is already compacted (1 `[Conversation summary]` row + 8 raw turns = 9 rows total) and a new prompt is sent that doesn't push the user past the trigger, **compaction does NOT re-fire**. The row count grows from 9 → 11 (just the new user+assistant pair); no second `[Conversation summary]` row is written.

Hermetic: pre-seeds the post-compaction state via `seed-compaction-idempotency.{sql,redis}`.

## Prerequisites

Check Bruno CLI, AscendAgent `/actuator/health`, Postgres + Redis healthy.

Check the seed scripts exist.

```bash
ls AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-idempotency.sql AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-idempotency.redis
```

Check default config: turn-trigger=20, keep-recent-turns=8. With 9 pre-seeded rows + 2 new (= 11), we are well under the trigger past the existing summary (turns past summary = 10, < 20).

## Reset state

The Postgres seed pipes straight from the host because `psql` reads binary stdin cleanly across shells.

```bash
docker exec -i postgres psql -U postgres -d ascend_ai < AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-idempotency.sql
```

The Redis seed is delivered via `docker cp` + container-side stdin redirect instead of host-side `<`. Reason: PowerShell's `Get-Content | docker exec -i` (the implicit fallback when `<` isn't supported) prepends a UTF-8 BOM that `redis-cli` parses as part of the first command, silently dropping the `DEL` line. Copying the file in and redirecting inside the container's `sh` keeps the byte stream identical across host shells.

```bash
docker cp AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-idempotency.redis redis:/tmp/seed-compaction-idempotency.redis
```

```bash
docker exec redis sh -c "redis-cli < /tmp/seed-compaction-idempotency.redis"
```

```bash
docker exec redis rm /tmp/seed-compaction-idempotency.redis
```

Verify the seed worked.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT count(*) FROM chat_history WHERE user_id = 'frostyCompactionIdempotencyTest';"
```

Expect exactly `9`.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT count(*) FROM chat_history WHERE user_id = 'frostyCompactionIdempotencyTest' AND role = 'system' AND content LIKE '[Conversation summary]%';"
```

Expect exactly `1`.

The seed scripts only reset the two chat resources above; they never touch the Redis instructions-cache key. Drop it here so the pre-run reset and the Post-run cleanup stay symmetric, and a crashed prior run's stale marker cannot survive into this run.

```bash
docker exec redis redis-cli DEL user:frostyCompactionIdempotencyTest:instructions
```

## Run

Step 1. Send one prompt as `frostyCompactionIdempotencyTest`. The chat history grows from 9 → 11 rows (1 new user + 1 new assistant). The compaction trigger should NOT fire because turns past the existing summary (10) is less than the trigger (20).

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/compaction-idempotency-prompt.yml" --env ascend-local
```

Step 2. Wait long enough that any async compaction would have completed if it were going to.

```bash
sleep 5
```

Step 3. Assert no second compaction fired.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT count(*) FROM chat_history WHERE user_id = 'frostyCompactionIdempotencyTest';"
```

Expect exactly `11`.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT count(*) FROM chat_history WHERE user_id = 'frostyCompactionIdempotencyTest' AND role = 'system' AND content LIKE '[Conversation summary]%';"
```

Expect exactly `1` (still only the original seeded summary row, no new one).

## Post-run cleanup

The seed scripts write 9 rows into `chat_history` and the matching Redis list, the Run step adds the new turn pair, `UserInstructionService` writes a Redis instructions-cache entry on that prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions), and the background memory extractor may write semantic-memory points for the same prompt. The seeds only reset the two chat resources, so the Reset state section above also clears the instructions key explicitly. Remove all four pieces of state here too so a run that crashed before Post-run cleanup, or a run whose Reset state was skipped, still leaves the system exactly as it found it. Run these regardless of whether the Run steps passed or failed. Every command is idempotent.

Drop this spec's chat-history rows, the eleven left after the Run step.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyCompactionIdempotencyTest';"
```

Drop the Redis chat list the seed created.

```bash
docker exec redis redis-cli DEL chat:frostyCompactionIdempotencyTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostyCompactionIdempotencyTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. The agent runs the extractor after every prompt, whether or not it concerns memory. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyCompactionIdempotencyTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyCompactionIdempotencyTest"}`.

The seed file the Reset section copied into the `redis` container is already removed by that section's `docker exec redis rm` step, so nothing is left under `/tmp` in the container.

## Expected

- Step 1: HTTP 200. Normal chat completion. The model should reference the seeded facts (Rex the beagle, Warsaw, TechCorp, Spring Boot / Quarkus) since they're in the visible chat history (1 summary + 8 raw turns + the new user msg).
- Step 3: `chat_history` row count for `frostyCompactionIdempotencyTest` equals exactly **11**.
- Step 3: exactly **1** `[Conversation summary]` row exists (no second one was written).
- Latency: step 1's response time should NOT include a compaction-call window (no async LLM was dispatched for compaction).

## Fixtures

- `AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-idempotency.sql`
- `AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-idempotency.redis`

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyCompactionIdempotencyTest`); Redis keys `chat:frostyCompactionIdempotencyTest` and `user:frostyCompactionIdempotencyTest:instructions`; Qdrant collections `ascend_memory_*` (user-scoped: `frostyCompactionIdempotencyTest`, written by the background memory extractor on any prompt)
- **Conflicts with:** none
- **Serial:** false
- **Hermetic contract:** Self-cleaning. `Post-run cleanup` removes the seeded rows, the rows the Run step added and every Redis key the run touched.
