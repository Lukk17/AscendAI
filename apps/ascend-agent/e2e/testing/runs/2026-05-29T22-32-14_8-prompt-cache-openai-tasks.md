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
- [x] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold) — observed 1536
- [x] Step 1: `usage.promptTokensDetails.cachedTokens == 0` (or absent) — observed 0
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.promptTokensDetails.cachedTokens > 0` — observed 1792

### Verdict

- [x] Verdict: PASS

## Result summary

Both calls returned HTTP 200. Step 1 (cache-miss seed): `promptTokens = 1536` (above the 1024 threshold required for OpenAI auto-caching to activate) and `cached_tokens = 0`, confirming a cache miss as expected. Step 2 (cache-hit): `promptTokens = 1899` and `cached_tokens = 1792`, confirming that OpenAI's prefix cache fired and the majority of the prompt prefix was served from cache. The `add-prompt-caching` wiring is confirmed end-to-end against the live OpenAI provider. Both responses contained structurally consistent `usage` blocks.

Input tokens (call 1): promptTokens=1536, completionTokens=271, totalTokens=1807

Cached tokens (call 2): cached_tokens=1792 (of promptTokens=1899)

Output tokens: completionTokens=266 (call 2)

Start (UTC): 2026-05-29T22:33:33Z

End (UTC): 2026-05-29T22:35:24Z

Duration: 00:01:51

---

## Additional tasks I did

- The Bruno CLI run (Step 1 via `bru run`) does not surface the response body in its summary output. To capture the `usage` block needed for the Expected assertions, I ran both steps via direct `curl` invocations replicating the same form fields as the Bruno request file. The Bruno run itself returned HTTP 200 (verified in its Execution Summary), confirming the endpoint reachable; the curl runs provided the assertion-bearing response bodies.
- State was reset a second time before the clean two-step run because the initial Bruno execution + one exploratory curl call had seeded 4 chat-history rows for the test user, which would have caused the "Step 1 seed" to include prior-turn content in the system prefix (altering the prefix and potentially inflating cached_tokens on Step 1). The second reset returned a clean slate.
