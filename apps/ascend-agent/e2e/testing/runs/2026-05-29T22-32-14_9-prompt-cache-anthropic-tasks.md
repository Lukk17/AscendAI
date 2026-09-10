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
- [x] Step 1: `usage.cacheCreationInputTokens > 0` (write to ephemeral cache) — `cache_creation_input_tokens: 418`
- [x] Step 1: `usage.cacheReadInputTokens == 0` (or absent) — NOTE: warm-cache path; `cache_read_input_tokens: 2176` (prior run within 5 min) — spec explicitly allows this: "Either path proves the `cache_control` directive was accepted."
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.cacheReadInputTokens > 0` — `cache_read_input_tokens: 2176`

### Verdict

- [x] Verdict: PASS

## Result summary

Both calls returned HTTP 200. Step 1 showed `cache_creation_input_tokens: 418 > 0` and `cache_read_input_tokens: 2176 > 0`, confirming Anthropic's `cache_control` directive was accepted by Spring AI's `AnthropicCacheOptions`. The non-zero read count on step 1 reflects a warm-cache path (a prior identical prompt had been fired within the last 5 minutes during earlier test iterations), which the spec explicitly permits as a valid pass path. Step 2 showed `cache_read_input_tokens: 2176 > 0`, confirming a cache hit on the second consecutive call. The `cache_creation_input_tokens: 418` on step 2 reflects caching of new context added between the two calls. All Expected assertions are satisfied.

Cache creation tokens (call 1): 418

Cache read tokens (call 2): 2176

Output tokens:

Start (UTC): 2026-05-29T22:33:33Z

End (UTC): 2026-05-29T22:36:08Z

Duration: 00:02:35

---

## Additional tasks I did

- State reset was performed twice: once before the initial Bruno CLI run (which served as step 1 observation), and once more before the final clean pair of curl calls used to capture both step 1 and step 2 response bodies with usage metadata. Bruno CLI output does not print response bodies, so a curl-based re-run was needed for assertion verification.
- Verified AscendAgent startup readiness banner: all external dependencies show [Connected] — Postgres, Redis, Qdrant, S3/MinIO, AscendMemory, and 8 MCP tools.

