# Chat-history compaction: fires + replaces prefix: e2e test

## What this verifies

When a conversation crosses the configured turn-trigger (default 20), `ChatHistoryCompactionService` fires asynchronously after the next `add(...)`, calls the cheap compaction model, and replaces the oldest prefix with a single `[Conversation summary]` SystemMessage. After compaction completes, Postgres `chat_history` for the user contains exactly **9 rows**: 1 summary + 8 most-recent raw turns.

Hermetic: pre-seeds 21 deterministic rows for `frostyCompactionFiresTest` user via `seed-compaction-fires.{sql,redis}`. NO assertion on summary text quality. That's a manual spot-check.

## Prerequisites

Check Bruno CLI, ascend-ai-agent `/actuator/health`, Postgres + Redis healthy.

Check the seed scripts exist.

```bash
ls apps/ascend-ai-agent/e2e/fixtures/compaction-seeds/seed-compaction-fires.sql apps/ascend-ai-agent/e2e/fixtures/compaction-seeds/seed-compaction-fires.redis
```

Check default config: compaction enabled, turn-trigger=20, keep-recent-turns=8. (Defaults from `application.yaml`. Only check explicitly if overridden in your local config.)

```bash
curl -fsS http://localhost:9917/actuator/configprops 2>/dev/null | grep -A3 'chatHistoryCompaction' | head -10 || true
```

(Will return nothing useful unless actuator `configprops` is exposed; otherwise trust the defaults.)

## Reset state

The seed scripts include their own `DELETE` / `DEL` lines, so applying them is idempotent.

The Postgres seed pipes straight from the host because `psql` reads binary stdin cleanly across shells.

```bash
docker exec -i postgres psql -U postgres -d ascend_ai < apps/ascend-ai-agent/e2e/fixtures/compaction-seeds/seed-compaction-fires.sql
```

The Redis seed is delivered via `docker cp` + container-side stdin redirect instead of host-side `<`. Reason: PowerShell's `Get-Content | docker exec -i` (the implicit fallback when `<` isn't supported) prepends a UTF-8 BOM that `redis-cli` parses as part of the first command, silently dropping the `DEL` line. Copying the file in and redirecting inside the container's `sh` keeps the byte stream identical across host shells.

```bash
docker cp apps/ascend-ai-agent/e2e/fixtures/compaction-seeds/seed-compaction-fires.redis redis:/tmp/seed-compaction-fires.redis
```

```bash
docker exec redis sh -c "redis-cli < /tmp/seed-compaction-fires.redis"
```

The cleanup also wraps the container-side path in `sh -c` rather than passing it as a bare argument. Reason: on
Windows, Git Bash's MSYS layer rewrites a bare `/tmp/...` argument into a host path before `docker` ever sees it
(`rm: can't remove 'C:/Users/.../Temp/seed-compaction-fires.redis'`), while a path embedded inside a quoted `sh -c`
string is left alone. PowerShell has no such rewriting, so the same form works unchanged there too.

```bash
docker exec redis sh -c "rm /tmp/seed-compaction-fires.redis"
```

Verify the seed worked.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT count(*) FROM chat_history WHERE user_id = 'frostyCompactionFiresTest';"
```

Expect exactly `21`.

```bash
docker exec redis redis-cli LLEN chat:frostyCompactionFiresTest
```

Expect exactly `21`.

The seed scripts only reset the two chat resources above; they never touch the Redis instructions-cache key. Drop it here so the pre-run reset and the Post-run cleanup stay symmetric, and a crashed prior run's stale marker cannot survive into this run.

```bash
docker exec redis redis-cli DEL user:frostyCompactionFiresTest:instructions
```

## Run

Step 1. Send one prompt as `frostyCompactionFiresTest`. This adds 2 rows (1 user + 1 assistant), bringing the chat history to 23 rows. The compaction trigger fires async after the `add(...)`.

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "ascend-agent/testing/compaction-fires-prompt.yml" --env ascend-local
```

Step 2. Wait up to 5 seconds for the async compaction to complete.

```bash
sleep 5
```

Step 3. Assert the post-compaction state.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT count(*) FROM chat_history WHERE user_id = 'frostyCompactionFiresTest';"
```

Expect exactly `9`.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT role, left(content, 60) FROM chat_history WHERE user_id = 'frostyCompactionFiresTest' ORDER BY created_at DESC LIMIT 1;"
```

Expect: 1 row with `role = 'system'` and content beginning with `[Conversation summary]`.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT count(*) FROM chat_history WHERE user_id = 'frostyCompactionFiresTest' AND role = 'system' AND content LIKE '[Conversation summary]%';"
```

Expect exactly `1`.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "SELECT count(*) FROM chat_history WHERE user_id = 'frostyCompactionFiresTest' AND role IN ('user', 'assistant');"
```

Expect exactly `8`.

## Post-run cleanup

The seed scripts write 21 rows into `chat_history` and the matching Redis list, the Run step adds the new turn pair, `UserInstructionService` writes a Redis instructions-cache entry on that prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions), and the background memory extractor may write semantic-memory points for the same prompt. The seeds only reset the two chat resources, so the Reset state section above also clears the instructions key explicitly. Remove all four pieces of state here too so a run that crashed before Post-run cleanup, or a run whose Reset state was skipped, still leaves the system exactly as it found it. Run these regardless of whether the Run steps passed or failed. Every command is idempotent.

Drop this spec's chat-history rows, the nine that survive compaction.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyCompactionFiresTest';"
```

Drop the Redis chat list the seed created.

```bash
docker exec redis redis-cli DEL chat:frostyCompactionFiresTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostyCompactionFiresTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. The agent runs the extractor after every prompt, whether or not it concerns memory. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyCompactionFiresTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyCompactionFiresTest"}`.

The seed file the Reset section copied into the `redis` container is already removed by that section's `docker exec redis sh -c "rm ..."` step, so nothing is left under `/tmp` in the container.

## Expected

- Step 1: HTTP 200. The response is a normal chat completion (the user's turn doesn't wait for the async compaction).
- Step 3: `chat_history` row count for `frostyCompactionFiresTest` is exactly **9**.
- Step 3: exactly **1** row has `role='system'` and `content` starts with `[Conversation summary]`.
- Step 3: exactly **8** rows have `role IN ('user', 'assistant')`.
- The summary row's content (manually inspected) reasonably reflects the seeded conversation. Mentions Rex the beagle, Warsaw, TechCorp, Spring Boot. NOT asserted programmatically.
- Compaction completed within 5 seconds wall-clock (the cheap-model call typically takes 0.5–2 seconds; budget 5s for headroom).

## Fixtures

- `apps/ascend-ai-agent/e2e/fixtures/compaction-seeds/seed-compaction-fires.sql`
- `apps/ascend-ai-agent/e2e/fixtures/compaction-seeds/seed-compaction-fires.redis`

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyCompactionFiresTest`); Redis keys `chat:frostyCompactionFiresTest` and `user:frostyCompactionFiresTest:instructions`; Qdrant collections `ascend_memory_*` (user-scoped: `frostyCompactionFiresTest`, written by the background memory extractor on any prompt)
- **Conflicts with:** none
- **Serial:** false
- **Hermetic contract:** Self-cleaning. `Post-run cleanup` removes the seeded rows, the rows the Run step added and every Redis key the run touched.
