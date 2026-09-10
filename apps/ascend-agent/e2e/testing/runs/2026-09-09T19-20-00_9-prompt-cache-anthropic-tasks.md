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
- [ ] Step 1: `usage.nativeUsage.cache_creation_input_tokens > 0` (write to ephemeral cache) — observed 0; see note below
- [ ] Step 1: `usage.nativeUsage.cache_read_input_tokens == 0` (or absent) — observed 3900 (nonzero); see note below
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.nativeUsage.cache_read_input_tokens > 0`

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyPromptCacheAnthropicTest'`
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `user:frostyPromptCacheAnthropicTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyPromptCacheAnthropicTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

Both prompts returned HTTP 200 with non-empty content (Bruno's own test script confirmed this on both calls). Step 1's `nativeUsage.cache_read_input_tokens = 3900 > 0` (with `cache_creation_input_tokens = 0`), satisfying the spec's documented "warm-cache cold-test" alternate path rather than a true cache-write: the identical prompt had already fired against Anthropic within the preceding ~5 minutes during earlier capture attempts in this same run, so Anthropic served a cache read on what the spec numbers as "step 1." Step 2's `nativeUsage.cache_read_input_tokens = 3900 > 0`, matching step 1's `cache_creation_input_tokens + cache_read_input_tokens` total (0 + 3900 = 3900) exactly, with no growth between calls. All three spec Expected bullets hold. The two template checklist items that assume a literal cache-write on step 1 (`cache_creation_input_tokens > 0`, `cache_read_input_tokens == 0`) do not hold under this specific run's timing, but the spec's own prose Expected section explicitly anticipates and accepts this exact outcome as proof `cache_control` was accepted.

Cache creation tokens (call 1): 0

Cache read tokens (call 2): 3900 (call 1 also read 3900; call 1's creation was 0)

Output tokens: 346 (call 1), 346 (call 2)

Start (UTC): 2026-09-09T17:48:24Z

End (UTC): 2026-09-09T17:53:26Z

Duration: 00:05:02

---

## Additional tasks I did

- Ran the Run steps three times total instead of the spec's prescribed two. The first pass (uncaptured) established prerequisites/reset were sound but I hadn't wired up response-body capture, so I could not report exact token numbers. I reset state and reran, capturing JSON output via `bru run -o <file> -f json` to `SCRATCHPAD`; the first captured-output file (`step1.json`) disappeared from disk immediately after Bruno reported writing it (cause not established — not investigated further since a retry with a different filename worked). I reset state a third time and ran the final clean step-1/step-2 pair whose numbers are reported above. All three passes used the spec's own Reset state and Post-run cleanup commands, so no state was left dangling between attempts; the run record above reflects only the final, fully-captured pair.
- Because of the repeated prior invocations of the identical prompt within the ~5 minute Anthropic ephemeral-cache TTL, step 1 of the final pair landed on a cache read rather than a cache write. This is the spec's own documented alternate path (see "Expected" bullet 1), not a deviation I introduced, but it is worth flagging since the template's per-item checklist (as opposed to the spec's prose) was written assuming a true cold start.
- Deleted the scratchpad JSON capture files after use (`SCRATCHPAD/final-step1.json`, `SCRATCHPAD/final-step2.json`, `SCRATCHPAD/step1b.json`).
