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

## Expected

- Step 1: HTTP 200. Normal chat completion. The model should reference the seeded facts (Rex the beagle, Warsaw, TechCorp, Spring Boot / Quarkus) since they're in the visible chat history (1 summary + 8 raw turns + the new user msg).
- Step 3: `chat_history` row count for `frostyCompactionIdempotencyTest` equals exactly **11**.
- Step 3: exactly **1** `[Conversation summary]` row exists (no second one was written).
- Latency: step 1's response time should NOT include a compaction-call window (no async LLM was dispatched for compaction).

## Fixtures

- `AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-idempotency.sql`
- `AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-idempotency.redis`

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyCompactionIdempotencyTest`); Redis key `chat:frostyCompactionIdempotencyTest`
- **Conflicts with:** none
- **Serial:** false
