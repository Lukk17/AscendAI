# AI traffic observability: e2e test

## What this verifies

- One OpenAI prompt and two identical Anthropic prompts produce model answers through the agent.
- `gen_ai_client_token_usage_total` holds a series for the `openai` provider and a series for the `anthropic` provider.
- `prompt_cache_tokens_read_total{provider="anthropic"}` grew after the second Anthropic prompt, because the second prompt repeats the first one and reads the cache.
- The trace of the weather prompt, found through the Tempo search for `service.name=ascend-agent`, holds a span whose name starts with `chat` or `spring_ai` and a span for the MCP tool call.
- Every panel query of the six dashboards of task 13, run against `http://localhost:7077/api/v1/query`, returns at least one series, or the panel names a provider this spec did not use in `docs/OBSERVABILITY.md`.

## Prerequisites

Bruno CLI installed, the always-on stack running, Prometheus ready, Grafana healthy, Tempo reachable, and the agent able to reach the OpenAI and Anthropic providers.

```bash
bru --version
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7077/-/ready
```

The second command prints `200`.

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7078/api/health
```

The third command prints `200`.

```bash
docker compose exec grafana wget -qO- "http://tempo:3200/api/search?tags=service.name%3Dascend-agent&limit=1"
```

The fourth command answers with a Tempo search body.

```bash
docker compose exec ascend-agent printenv OPENAI_API_KEY
```

The fifth command prints a key, not `not-set`.

```bash
docker compose exec ascend-agent printenv ASCEND_ANTHROPIC_API_KEY
```

The sixth command prints a key, not `not-set`.

## Reset state

Clear this spec's per-user state before the run. Post-run cleanup removes the same pieces of state, but a run that crashed before reaching that section leaves them behind, and stale `chat_history` rows change the prompt the model sees on the next run. Every command is idempotent.

Drop this spec's chat-history rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyAiTrafficTest';"
```

Drop the Redis chat cache key.

```bash
docker exec redis redis-cli DEL chat:frostyAiTrafficTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostyAiTrafficTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user. With no `provider` query parameter the endpoint clears the user across every provider collection, which stays correct if the embedding provider changes.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyAiTrafficTest"
```

## Run

```bash
cd docs/api/request/AscendAI
```

Record the current Anthropic cache-read counter, so the Expected section can prove it grew.

```bash
curl -s --get "http://localhost:7077/api/v1/query" --data-urlencode "query=prompt_cache_tokens_read_total"
```

Send the OpenAI prompt and wait for the response before continuing.

```bash
bru run "platform/observability/openai-prompt.yml" --env ascend-local
```

Send the first Anthropic prompt and wait for the response before continuing.

```bash
bru run "platform/observability/anthropic-prompt-1.yml" --env ascend-local
```

Send the second Anthropic prompt. It repeats the first one exactly, so it reads the cache.

```bash
bru run "platform/observability/anthropic-prompt-2.yml" --env ascend-local
```

Send the weather prompt and wait for the response before continuing.

```bash
bru run "platform/observability/weather-tool-prompt.yml" --env ascend-local
```

Wait 30 seconds so Prometheus scrapes the new series (the scrape interval is 15 seconds per task 1.1) and the weather trace reaches Tempo (task 9.7 waits 10 seconds for the same hop).

```bash
sleep 30
```

Read back the token-usage series.

```bash
curl -s --get "http://localhost:7077/api/v1/query" --data-urlencode "query=gen_ai_client_token_usage_total"
```

Read back the Anthropic cache-read counter and compare it with the value recorded before the prompts.

```bash
curl -s --get "http://localhost:7077/api/v1/query" --data-urlencode "query=prompt_cache_tokens_read_total"
```

Search Tempo for recent agent traces.

```bash
docker compose exec grafana wget -qO- "http://tempo:3200/api/search?tags=service.name%3Dascend-agent&limit=5"
```

Fetch the trace of the weather prompt with the id the search returned. The weather prompt is the most recent model call of this run, so on a quiet stack it is the first listed trace. When the stack carried other traffic, fetch each listed trace in order until one holds both spans the Expected section names.

```bash
docker compose exec grafana wget -qO- http://tempo:3200/api/traces/<traceID>
```

For each of the six dashboards of task 13 (`platform-overview.json`, `ai-pipeline.json`, `infrastructure.json`, `token-cost.json`, `rag-quality.json`, `cache-hit-rate.json` in `infra/observability/grafana/dashboards/`), take every panel query and run it against the instant-query API.

```bash
curl -s --get "http://localhost:7077/api/v1/query" --data-urlencode "query=<panel query>"
```

## Post-run cleanup

Every prompt this spec sends writes three pieces of per-user state: a `chat_history` row pair in Postgres, the same turns cached under the Redis `chat:` key, and a Redis instructions-cache entry that `UserInstructionService` writes on every prompt (an `EMPTY` marker with a 24 hour TTL when the user has no stored instructions). The agent also runs its semantic-memory extractor after every prompt, whether or not the prompt itself concerns memory, so a fourth cleanup step wipes any fact AscendMemory happened to extract from this prompt. Remove all four so the run leaves the system exactly as it found it. Run these regardless of whether the Run step passed or failed. Every command is idempotent.

Drop this spec's chat-history rows.

```bash
docker exec postgres psql -U postgres -d ascend_ai -c "DELETE FROM chat_history WHERE user_id = 'frostyAiTrafficTest';"
```

Drop the Redis chat cache key.

```bash
docker exec redis redis-cli DEL chat:frostyAiTrafficTest
```

Drop the Redis instructions cache key.

```bash
docker exec redis redis-cli DEL user:frostyAiTrafficTest:instructions
```

Wipe any semantic-memory points AscendMemory's background extractor stored for this user.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyAiTrafficTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyAiTrafficTest"}`.

## Expected

- Each Bruno request answers HTTP 200 with a non-empty `content` field, and the weather answer carries a numeric temperature and a weather condition word, never a live-data refusal.
- The `gen_ai_client_token_usage_total` answer holds at least one series for the `openai` provider and at least one series for the `anthropic` provider.
- The `prompt_cache_tokens_read_total` value with `provider="anthropic"` after the second Anthropic prompt is greater than the value recorded before the prompts.
- The fetched Tempo trace holds a span whose name starts with `chat` or `spring_ai` and a span for the MCP tool call.
- Every panel query of the six dashboards, run against `http://localhost:7077/api/v1/query`, returns at least one series, or the panel names a provider this spec did not use in `docs/OBSERVABILITY.md` (task 13.7).
- No expected line matches the text of a log line.

## Fixtures

None.

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyAiTrafficTest`); Redis keys `chat:frostyAiTrafficTest` and `user:frostyAiTrafficTest:instructions`; Qdrant collections `ascend_memory_*` (user-scoped: `frostyAiTrafficTest`, written by the background memory extractor on any prompt)
- **Conflicts with:** specs that send Anthropic prompts while this run measures the cache-read growth (they move the same provider-scoped counter)
- **Serial:** false
- **Hermetic contract:** Self-cleaning. `Reset state` (pre) and `Post-run cleanup` (post) both remove every row, key and vector point this spec's user id could carry. Nothing else survives the run.
