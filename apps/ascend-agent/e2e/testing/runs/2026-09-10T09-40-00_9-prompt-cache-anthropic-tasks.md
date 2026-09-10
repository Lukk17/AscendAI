# Prompt cache: Anthropic: run tasks template

Spec: [../9-prompt-cache-anthropic-test.md](../9-prompt-cache-anthropic-test.md)

Copy to `runs/<UTC-timestamp>_9-prompt-cache-anthropic-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] ascend-ai-agent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `ASCEND_ANTHROPIC_API_KEY` is configured for the ascend-ai-agent container

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `user:frostyPromptCacheAnthropicTest:instructions`

### Run

- [x] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [x] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.nativeUsage.cache_creation_input_tokens > 0` OR `usage.nativeUsage.cache_read_input_tokens > 0` (a true cold start pays a cache write, a warm cache from an identical prompt within the last ~5 minutes shows a read instead, either proves the `cache_control` directive was accepted) — observed cache_creation_input_tokens=3228, cache_read_input_tokens=0
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.nativeUsage.cache_read_input_tokens > 0` — observed cache_read_input_tokens=3228 (matches step-1's cache_creation_input_tokens=3228 exactly), cache_creation_input_tokens=0

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyPromptCacheAnthropicTest'` (4 rows)
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `user:frostyPromptCacheAnthropicTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyPromptCacheAnthropicTest` returned `{"status":"success","message":"All memories wiped for user frostyPromptCacheAnthropicTest"}`

### Verdict

- [x] Verdict: PASS

## Result summary

Both Run steps returned HTTP 200 with structurally valid bodies. Step 1 produced `cache_creation_input_tokens=3228` and `cache_read_input_tokens=0`, a true cold-start cache write, satisfying the step-1 Expected assertion (creation OR read > 0). Step 2, sent immediately after within the 5-minute Anthropic ephemeral-cache TTL, produced `cache_creation_input_tokens=0` and `cache_read_input_tokens=3228`, satisfying the step-2 Expected assertion (`cache_read_input_tokens > 0`) exactly, and the read count matches step 1's write count (3228 == 3228), confirming the cached chunk did not grow between calls. All three Expected assertions hold.

Cache creation tokens (call 1): 3228

Cache read tokens (call 2): 3228

Output tokens: 369 (call 1), 369 (call 2) — from response `metadata.usage.nativeUsage.output_tokens`, not LLM-runner token accounting

Start (UTC): 2026-09-10T08:05:12Z

End (UTC): 2026-09-10T08:07:24Z

Duration: 00:02:12

---

## Additional tasks I did

- Parsed the Bruno `--output --format json` captures with `/c/Python313/python` (system python3 not on PATH) to extract `metadata.usage.nativeUsage` fields precisely, since the embedded Bruno test script only asserts `cache_creation_input_tokens > 0 || cache_read_input_tokens > 0` on both calls rather than the spec's stricter step-2-only `cache_read_input_tokens > 0` assertion. The script passed on both steps, and the actual observed values also satisfy the spec's stricter assertion, but the script itself would not have caught a step-2 failure mode where `cache_creation_input_tokens > 0` and `cache_read_input_tokens == 0` (e.g. cache not actually reused). Script: `docs/api/request/AscendAI/ascend-agent/testing/prompt-cache-anthropic.yml`, test name `"cache_control was accepted (creation or read observed)"`.
- Deleted the two scratchpad JSON capture files (`step1.json`, `step2.json`) after extracting the needed fields.
