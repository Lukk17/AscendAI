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
- [x] Step 1: `usage.promptTokensDetails.cachedTokens == 0` (or absent)
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.promptTokensDetails.cachedTokens > 0`

### Verdict

- [x] Verdict: PASS

## Result summary

Both Expected assertions were met. Call 1 (cache-miss seed): HTTP 200, `promptTokens` = 1540 (exceeds the 1024 threshold required for OpenAI auto prefix cache), `nativeUsage.prompt_tokens_details.cached_tokens` = 0 — correct for a first call with a fresh chat history. Call 2 (cache-hit probe), sent ~51 seconds after call 1: HTTP 200, `promptTokens` = 1872, `nativeUsage.prompt_tokens_details.cached_tokens` = **1664** — strongly positive, confirming that OpenAI's automatic prefix cache fired. The `add-prompt-caching` change is wired correctly end-to-end: the `CustomMetadata` fix (removing the `extends ChatResponseMetadata` that caused duplicate JSON keys clobbering real values) allows `nativeUsage` to surface with real token counts, and the second call correctly reports 1664 cached tokens.

Input tokens (call 1): 1540

Cached tokens (call 2): 1664

Output tokens: 236 (call 1), 239 (call 2)

Start (UTC): 2026-05-28T15:43:42Z

End (UTC): 2026-05-28T15:46:21Z

Duration: 00:02:39

---

## Additional tasks I did

