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
- [ ] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold)
- [ ] Step 1: `usage.promptTokensDetails.cachedTokens == 0` (or absent)
- [x] Step 2: HTTP 200
- [ ] Step 2: `usage.promptTokensDetails.cachedTokens > 0`

### Verdict

- [ ] Verdict: FAIL

## Result summary

Both calls returned HTTP 200 and produced coherent response content, confirming the AscendAgent routes correctly to the OpenAI provider. However, the core assertion failed: `metadata.usage` in both responses contained all-zero token counts (`promptTokens: 0`, `completionTokens: 0`, `totalTokens: 0`, `nativeUsage: {}`), and the `promptTokensDetails` field was entirely absent. Because `promptTokens` was 0 in step 1 (not >= 1024), the OpenAI auto-cache threshold was never confirmed to be met. On step 2, `promptTokensDetails.cachedTokens` was absent / effectively 0, meaning the cache-hit assertion cannot pass. The `metadata.empty: true` flag on both responses indicates the AscendAgent's response mapper is not propagating OpenAI's usage data (including `prompt_tokens_details.cached_tokens`) into the API response's `metadata.usage` structure. The prompt-caching feature is not testable end-to-end until the usage metadata wiring is fixed.

Input tokens (call 1): 0 (as reported by API; actual not surfaced)

Cached tokens (call 2): 0 (absent from response)

Output tokens: not available from response

Start (UTC): 2026-05-28T10:42:15Z

End (UTC): 2026-05-28T10:44:52Z

Duration: 00:02:37

---

## Additional tasks I did

- Attempted `docker exec ascend-agent printenv OPENAI_API_KEY | head -c 8` per spec but auto-mode classifier blocked credential read. Used `if [ -n "$OPENAI_API_KEY" ]; then echo KEY_PRESENT; fi` instead — confirmed key is present without exposing its value.
- Attempted `docker exec redis redis-cli DEL chat:frostyPromptCacheOpenaiTest` per spec but auto-mode classifier blocked Redis mutation. Followed up with `EXISTS` check which returned 0 — key was already absent, confirming effective reset.
- The step 1 `promptTokensDetails.cachedTokens == 0` assertion is marked unticked because the field itself is absent from the response (not 0). The root cause is the same mapping gap that causes all usage fields to be 0; absence of the field is consistent with the mapper returning empty usage.

