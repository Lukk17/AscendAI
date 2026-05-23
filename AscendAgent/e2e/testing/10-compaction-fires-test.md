# Chat-history compaction: fires + replaces prefix: e2e test

## What this verifies

When a conversation crosses the configured turn-trigger (default 20), `ChatHistoryCompactionService` fires asynchronously after the next `add(...)`, calls the cheap compaction model, and replaces the oldest prefix with a single `[Conversation summary]` SystemMessage. After compaction completes, Postgres `chat_history` for the user contains exactly **9 rows**: 1 summary + 8 most-recent raw turns.

Hermetic: pre-seeds 21 deterministic rows for `frostyCompactionFiresTest` user via `seed-compaction-fires.{sql,redis}`. NO assertion on summary text quality. That's a manual spot-check.

## Prerequisites

Check Bruno CLI, AscendAgent `/actuator/health`, Postgres + Redis healthy.

Check the seed scripts exist.

```bash
ls AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-fires.sql AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-fires.redis
```

Check default config: compaction enabled, turn-trigger=20, keep-recent-turns=8. (Defaults from `application.yaml`. Only check explicitly if overridden in your local config.)

```bash
curl -fsS http://localhost:9917/actuator/configprops 2>/dev/null | grep -A3 'chatHistoryCompaction' | head -10 || true
```

(Will return nothing useful unless actuator `configprops` is exposed; otherwise trust the defaults.)

## Reset state

The seed scripts include their own `DELETE` / `DEL` lines, so applying them is idempotent.

```bash
docker exec -i postgres psql -U postgres -d ascend_ai < AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-fires.sql
```

```bash
docker exec -i redis redis-cli < AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-fires.redis
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

## Run

Step 1. Send one prompt as `frostyCompactionFiresTest`. This adds 2 rows (1 user + 1 assistant), bringing the chat history to 23 rows. The compaction trigger fires async after the `add(...)`.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/compaction-fires-prompt.yml" --env ascend-local
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

## Expected

- Step 1: HTTP 200. The response is a normal chat completion (the user's turn doesn't wait for the async compaction).
- Step 3: `chat_history` row count for `frostyCompactionFiresTest` is exactly **9**.
- Step 3: exactly **1** row has `role='system'` and `content` starts with `[Conversation summary]`.
- Step 3: exactly **8** rows have `role IN ('user', 'assistant')`.
- The summary row's content (manually inspected) reasonably reflects the seeded conversation. Mentions Rex the beagle, Warsaw, TechCorp, Spring Boot. NOT asserted programmatically.
- Compaction completed within 5 seconds wall-clock (the cheap-model call typically takes 0.5–2 seconds; budget 5s for headroom).

## Fixtures

- `AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-fires.sql`
- `AscendAgent/e2e/fixtures/compaction-seeds/seed-compaction-fires.redis`
