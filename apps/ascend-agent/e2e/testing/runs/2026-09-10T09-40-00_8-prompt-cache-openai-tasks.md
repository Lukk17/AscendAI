# Prompt cache: OpenAI: run tasks template

Spec: [../8-prompt-cache-openai-test.md](../8-prompt-cache-openai-test.md)

Copy to `runs/<UTC-timestamp>_8-prompt-cache-openai-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] ascend-ai-agent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `OPENAI_API_KEY` is configured for the ascend-ai-agent container

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheOpenaiTest`
- [x] Deleted Redis key `chat:frostyPromptCacheOpenaiTest`
- [x] Deleted Redis key `user:frostyPromptCacheOpenaiTest:instructions`

### Run

- [x] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [x] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold) — observed 2213
- [x] Step 1: `usage.nativeUsage.prompt_tokens_details.cached_tokens == 0` (or absent on a fresh-cache run; non-zero acceptable when OpenAI's server-side TTL hasn't expired from a prior local run) — observed 0
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.nativeUsage.prompt_tokens_details.cached_tokens > 0` — observed 2304

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyPromptCacheOpenaiTest'` (4 rows)
- [x] Deleted Redis key `chat:frostyPromptCacheOpenaiTest`
- [x] Deleted Redis key `user:frostyPromptCacheOpenaiTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyPromptCacheOpenaiTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

Both Run steps returned HTTP 200 with a well-formed `usage` block. Step 1 (fresh cache, `chat_history` and Redis
keys reset immediately before): `promptTokens = 2213` (>= 1024), `nativeUsage.prompt_tokens_details.cached_tokens =
0` — a genuine cache miss, matching the fresh-cache expectation. Step 2, run immediately after step 1 (well within
the ~5 minute OpenAI prefix-cache TTL, same exact prompt/provider/model/user): `nativeUsage.prompt_tokens_details.
cached_tokens = 2304 > 0`, comfortably above the spec's "high hundreds at minimum" bar and in fact covering nearly
all of step 2's `promptTokens = 2556`. Both Bruno-embedded test scripts (`Status code is 200`, `usage block is
present with a cacheable prompt size`) passed on both invocations and assert no more than the spec's own Expected
section. All three Expected assertions hold.

Input tokens (call 1): 2213 (promptTokens)

Cached tokens (call 2): 2304

Output tokens: 247 (call 1 completionTokens), 241 (call 2 completionTokens)

Start (UTC): 2026-09-10T08:03:20Z

End (UTC): 2026-09-10T08:05:43Z

Duration: 00:02:23

---

## Additional tasks I did

- None off-spec. Ran the spec's Prerequisites, Reset state, both Run steps, and Post-run cleanup exactly as written,
  in order, and verified the response bodies directly (not just the Bruno test-script pass/fail) by inspecting the
  JSON output Bruno wrote to the scratchpad directory, which was deleted after use.
