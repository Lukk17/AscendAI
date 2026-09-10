# Prompt cache: OpenAI: run tasks template

Spec: [8-prompt-cache-openai-test.md](8-prompt-cache-openai-test.md)

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
- [x] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold) — observed: 2462
- [x] Step 1: `usage.nativeUsage.prompt_tokens_details.cached_tokens == 0` (or absent on a fresh-cache run; non-zero acceptable when OpenAI's server-side TTL hasn't expired from a prior local run) — observed: 0
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.nativeUsage.prompt_tokens_details.cached_tokens > 0` — observed: 2688

### Verdict

- [x] Verdict: PASS

## Result summary

Both calls returned HTTP 200. Step 1 (cache-miss seed) reported `promptTokens = 2462`, clearing the 1024 threshold required for OpenAI automatic prefix caching to activate, with `cached_tokens = 0` confirming a clean cache miss after the state reset. Step 2 (cache hit, sent approximately 15 seconds after Step 1) returned `nativeUsage.prompt_tokens_details.cached_tokens = 2688`, confirming that OpenAI's prefix cache fired and the wiring of the `add-prompt-caching` change is functioning end-to-end. Both responses contained well-structured `usage` blocks with consistent field names (`snake_case` under `nativeUsage`).

Input tokens (call 1): 2462 prompt tokens (native OpenAI count)

Cached tokens (call 2): 2688

Output tokens: 259 (call 1), 247 (call 2)

Start (UTC): 2026-06-17T22:30:51Z

End (UTC): 2026-06-17T22:32:44Z

Duration: 00:01:53

---

## Additional tasks I did

- Read `prompt-cache-openai.yml` before running to confirm the user-id, provider, and model fields (gpt-4o via openai provider, X-User-Id: frostyPromptCacheOpenaiTest).
- Saved Step 1 and Step 2 JSON outputs to `runs/step1-cache-openai.json` and `runs/step2-cache-openai.json` for inline evidence. These are not spec-prescribed artifacts; they were written as diagnostic scratch files only.

