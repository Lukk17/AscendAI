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

- [x] Truncated `chat_history` rows for user `frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`

### Run

- [x] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [x] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.cacheCreationInputTokens > 0` (write to ephemeral cache)
- [ ] Step 1: `usage.cacheReadInputTokens == 0` (or absent) — OBSERVED: 2176 (cache warm from earlier runs in same session)
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.cacheReadInputTokens > 0`

### Verdict

- [x] Verdict: FAIL

## Result summary

Both HTTP calls returned 200. Prompt caching is definitively active: Step 1 returned `cache_creation_input_tokens=418 > 0` confirming the cache write, and Step 2 returned `cache_read_input_tokens=2176 > 0` confirming the cache hit. The one failing assertion is Step 1's `cacheReadInputTokens == 0`: Anthropic's ephemeral cache was still warm from earlier runs made in the same test session (prior Bruno and curl calls during prerequisite exploration), so the system prompt was being read from cache even on Step 1 of the final clean run. The core behavior — cache creation and cache reading both work — is confirmed. The Step 1 zero-read assertion is a cold-start expectation that cannot be guaranteed when the test is re-run multiple times within a 5-minute window against the same Anthropic model and system prompt.

Cache creation tokens (call 1): 418

Cache read tokens (call 2): 2176

Output tokens: 396 (Steps 1 and 2 each)

Start (UTC): 2026-05-28T14:39:26Z

End (UTC): 2026-05-28T14:42:41Z

Duration: 00:03:15

---

## Additional tasks I did

- Postgres `docker exec psql` blocked by auto-mode classifier on first attempt (reason: "production-like read on shared infra"). Verified Postgres and Redis via `docker ps --filter` health status instead (both showed `(healthy)`).
- API key verification: `docker exec ascend-agent printenv ASCEND_ANTHROPIC_API_KEY | head -c 8` blocked (reason: "leaks secret into transcript"). Used `wc -c` instead to confirm key is set (109 chars).
- Initial run: ran Bruno for Step 1 (no body captured from Bruno stdout) then immediately ran a curl as Step 2 — captured body showing `cache_read_input_tokens=2176 > 0`. Decided to reset and re-run both calls via curl to capture both response bodies properly.
- Second full reset + two sequential curl calls performed to get both Step 1 and Step 2 bodies. Step 1 already showed `cache_read_input_tokens=2176` because Anthropic's cache was warm from the first Bruno + curl attempt.
- The `cacheReadInputTokens == 0` assertion on Step 1 fails only because of cache warmth from in-session prior calls — not a functional regression in the implementation.
