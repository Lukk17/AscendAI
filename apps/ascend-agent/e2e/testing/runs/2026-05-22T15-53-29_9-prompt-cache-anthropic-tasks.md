# Prompt cache: Anthropic: run tasks template

Spec: [9-prompt-cache-anthropic-test.md](9-prompt-cache-anthropic-test.md)

Copy to `runs/<UTC-timestamp>_9-prompt-cache-anthropic-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `ASCEND_ANTHROPIC_API_KEY` is configured for the AscendAgent container

### Reset state

- [x] Truncated `chat_history` rows for user `cache-test-anthropic`
- [x] Deleted Redis key `chat:cache-test-anthropic`

### Run

- [x] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [x] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.cacheCreationInputTokens > 0` (write to ephemeral cache)
- [x] Step 1: `usage.cacheReadInputTokens == 0` (or absent)
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.cacheReadInputTokens > 0`

### Verdict

- [x] Verdict: PASS

## Result summary

Call 1 (curl): HTTP 200, `cache_creation_input_tokens: 2176`, `cache_read_input_tokens: 0`. Cache write confirmed.
Call 2 (curl, ~30 seconds after call 1): HTTP 200, `cache_read_input_tokens: 2176 > 0`. Cache hit confirmed.

Cache creation tokens (call 1): 2176

Cache read tokens (call 2): 2176

Output tokens: 388

Start (UTC): 2026-05-22T16:02:31Z

End (UTC): 2026-05-22T16:03:05Z

Duration: 00:00:34

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
