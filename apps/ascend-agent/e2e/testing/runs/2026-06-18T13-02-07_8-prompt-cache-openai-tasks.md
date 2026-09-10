# Prompt cache: OpenAI: run tasks template

Spec: [8-prompt-cache-openai-test.md](8-prompt-cache-openai-test.md)

Copy to `runs/<UTC-timestamp>_8-prompt-cache-openai-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `OPENAI_API_KEY` is configured for the AscendAgent container

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheOpenaiTest`
- [x] Deleted Redis key `chat:frostyPromptCacheOpenaiTest`

### Run

- [x] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [x] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold)
- [x] Step 1: `usage.nativeUsage.prompt_tokens_details.cached_tokens == 0` (or absent on a fresh-cache run; non-zero acceptable when OpenAI's server-side TTL hasn't expired from a prior local run)
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.nativeUsage.prompt_tokens_details.cached_tokens > 0`

### Verdict

- [x] Verdict: PASS

## Result summary

Both steps returned HTTP 200. Step 1 (clean seed call after state reset) reported `promptTokens: 2462` — well above the 1024-token threshold required for OpenAI's automatic prefix cache to activate — and `cached_tokens: 1920`, which is non-zero because OpenAI's server-side cache TTL had not yet expired from earlier test-session calls; this is explicitly acceptable per the spec. Step 2, run immediately after (within ~30 seconds), reported `promptTokens: 2801` and `cached_tokens: 2688`, confirming a large prefix cache hit. The cached portion (2688 tokens out of 2801 prompt tokens, approximately 96%) matches the expected "high hundreds at minimum" wording in the spec. Both calls produced well-formed responses with complete `usage` and `nativeUsage` blocks. The `add-prompt-caching` change is correctly wired end-to-end for the OpenAI provider.

Input tokens (call 1): 2462 (promptTokens); 1920 cached (server-side TTL not expired from prior runs)

Cached tokens (call 2): 2688 out of 2801 prompt tokens

Output tokens: 243 (call 1), 265 (call 2)

Start (UTC): 2026-06-18T13:02:07Z

End (UTC): 2026-06-18T13:05:17Z

Duration: 00:03:10

---

## Additional tasks I did

- Before the final clean two-call sequence, ran additional seed calls (one Bruno + one curl) to verify the response body shape and confirm the `nativeUsage.prompt_tokens_details.cached_tokens` field path. These were not spec-prescribed but provided the exact field-path evidence needed to complete the assertions with confidence.
- Reset state twice: once at the start of the test (per spec) and once before the final clean two-step sequence to eliminate chat-history accumulation from the intermediate exploratory calls.
- Deleted the Bruno JSON output file `docs/api/request/AscendAI/json` (a side-effect of an `--output json` invocation without a path; Bruno wrote to a file named `json` in the collection root). This file is outside `e2e/testing/runs/` and was not intended; noted here for transparency but no action taken beyond noting it.
