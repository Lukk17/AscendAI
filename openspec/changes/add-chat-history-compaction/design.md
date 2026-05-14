## Context

Today `PersistentChatMemory` retains the last `app.memory.chat-history.max-size` turns (default 5) per conversation. The hard cap keeps Redis memory and per-turn input cost bounded, but it also throws away everything past the window. That works for short Q&A. It breaks down for the longer working sessions AscendAI is increasingly used for: a 40-turn debugging conversation either loses its early framing entirely (current behaviour with `max-size=5`) or, if `max-size` is bumped to 50, costs 10× more input tokens per turn and starts to suffer from documented mid-context attention drop on every supported provider.

The modern best practice across hosted assistants (Claude Code's `/compact`, OpenAI Assistants' built-in summarisation, LangChain's `ConversationSummaryBufferMemory`, every production RAG stack we have looked at) is the same shape:

1. **Keep recent turns raw** (recency dominates relevance for follow-ups).
2. **Summarise older turns** into a short, structured paragraph using a cheaper / faster model than the primary chat model.
3. **Trigger by token budget** (preferred) or turn count (fallback), not by wall-clock or message-count alone.
4. **Make it idempotent** — replaying compaction without new turns must not produce a "summary of the summary of the summary".
5. **Make it async** — never block the user's turn on the compaction call.

We have all the prerequisites in place: per-provider chat clients via `ChatModelResolver`, a cheap variant for every provider already named in `application.yaml` (`memory-extraction-model` — Haiku, gpt-4o-mini, gemini-flash-lite-latest, etc.), an `@Async`-wired executor already used by `PersistentChatMemory.persistToDb`, both backends (Redis hot cache + Postgres archive) accessible from `PersistentChatMemory`, and a working REST DTO at `/api/v1/ai/prompt` that already accepts per-call provider/model overrides for the primary chat call.

The change reuses every one of those. It introduces one new service, one new properties class, two new REST fields, and one new YAML block.

## Goals / Non-Goals

**Goals:**

- Compaction fires automatically once a conversation crosses a sensible threshold, with safe defaults for first-time operators.
- Operators tune trigger thresholds, recency window, and per-provider compaction model via `application.yaml` without code changes.
- Callers override the compaction model per request via two optional fields on `/api/v1/ai/prompt`.
- Compaction is idempotent — running it twice in a row on the same conversation state produces the same end state.
- Compaction never increases latency on the user's turn (async after persistence).
- Compaction is safe under the existing chat-history toggles — when both backends are off, compaction is a no-op (there is nothing to compact).
- Per-provider cheap-model defaults are documented and conservative (Haiku, mini, flash-lite, etc.).

**Non-Goals:**

- A second-tier "summary of summaries" recursive compaction. One summary per compaction window is sufficient for the conversation lengths we expect (a single 800-token summary covers ~30 typical turns); recursive summarisation is a future change once we see real conversations that exceed that.
- Per-user or per-tenant compaction toggles. Global config is enough for now.
- Eviction or pruning of Postgres `chat_history` rows beyond the compaction replace. Long-term archive retention is a separate concern.
- Compaction quality metrics (BLEU, ROUGE, etc.). Subjective evaluation by operator + occasional manual spot-check is the bar; we are not building an LLM-judge harness in this change.
- Using a separate "summariser" provider stack (e.g. always routing compaction through OpenAI even when the chat is on Anthropic). The default is same-provider, cheap-model — keeps secrets and rate-limit pools aligned. Operators who want cross-provider compaction set `compactionProvider` per request.
- Streaming the compaction. It's an internal background job; a single `String` summary is fine.

## Decisions

### D1 — Trigger heuristic: token-budget preferred, turn-count fallback

The trigger fires when **either** of two conditions is true:

1. `tokens(history) ≥ token-trigger-fraction × resolved-context-window-for-provider` (default `0.5`).
2. `turns(history) ≥ turn-trigger` (default `20`).

Token-budget is the modern correct signal — a 20-turn conversation full of one-liners is cheap, a 20-turn conversation with pasted stack traces is not. We fall back on turn-count because we don't always have a reliable tokenizer for every provider in-process (LM Studio's local models, MiniMax's variant tier), and "20 turns is too many" is a safe bet across providers. Both have to be configurable; either one tripping is enough.

We estimate tokens with `(string-length / 4)` as the lightweight default — it's the rule-of-thumb every Spring AI sample uses and it is good to within ~15 % for English. When a provider exposes a real tokenizer through its Spring AI client we use that; otherwise the estimate is fine for a decision that only needs to be order-of-magnitude right.

**Alternative considered**: time-based ("compact after 24 h of inactivity"). Rejected — orthogonal to cost, and conversations going stale is what Redis TTL already handles.

### D2 — Recency window: keep 8 raw turns

Default `keep-recent-turns: 8` — that is roughly 4 user/assistant exchanges, which industry-wide is the empirical floor below which follow-up coherence breaks down ("can you do that thing you mentioned earlier?" stops working below ~3 raw exchanges). 8 keeps every typical multi-turn fix-up alive while still squeezing the cost out of the tail.

**Alternative considered**: `keep-recent-tokens` instead of turn count. Rejected for now because turn count is what users intuit and what `max-size` already configures. Token-keep-recent can be added if 8 turns proves too coarse.

### D3 — Compaction model: per-provider defaults, REST override

Default map in `application.yaml`:

```yaml
app:
  memory:
    chat-history:
      compaction:
        provider-defaults:
          openai:    gpt-4o-mini
          anthropic: claude-haiku-4-5
          gemini:    gemini-flash-lite-latest
          minimax:   ${MINIMAX_MODEL:MiniMax-M2.7}   # no published "mini" tier — same as main
          lmstudio:  ${LMSTUDIO_MODEL:meta-llama-3.1-8b-instruct}
```

A caller can override either field per request:

```json
{
  "message": "...",
  "userId": "frosty",
  "provider": "anthropic",
  "model": "claude-sonnet-4-5",
  "compactionProvider": "openai",
  "compactionModel": "gpt-4o-mini"
}
```

If both are unset, compaction uses (`requestProvider`, `provider-defaults[requestProvider]`). If `compactionProvider` is set but `compactionModel` is unset, we use `provider-defaults[compactionProvider]`. If `compactionModel` is set but `compactionProvider` is unset, the model runs on the request's primary provider.

**Alternative considered**: reuse `memory-extraction-model` from `AiProviderProperties` and skip the new field. Rejected — extraction models are tuned for short, strict JSON output (mem0 needs that). Compaction wants longer-form prose at ~800 tokens. They will diverge over time; better to keep them parallel from day one.

### D4 — Summary format and idempotency marker

The compaction call returns a single SystemMessage whose text starts with the literal marker `[Conversation summary]`. The marker is the idempotency hinge: when the read path assembles history, any message whose text starts with `[Conversation summary]` is treated as already-compacted and is **not** itself eligible for compaction. The compaction service detects this same marker in the *current* history and decides whether the existing summary already covers the prefix; if it does and no new turns have accumulated past `keep-recent-turns`, the call short-circuits.

The summary prompt template (lives as a private constant on `ChatHistoryCompactionService`, mirroring `SemanticMemoryExtractor`'s `EXTRACTOR_INSTRUCTION`):

```
You are compacting an older portion of a chat between a USER and the AscendAI ASSISTANT.
Produce a single paragraph of at most {maxSummaryTokens} tokens that preserves:
  - Facts the user shared about themselves or their work.
  - Decisions the assistant proposed and the user accepted or rejected.
  - Open threads the user wanted to return to.
Discard: small talk, restated questions, anything already captured in a prior [Conversation summary] block.
Do not invent details. If the older portion already begins with "[Conversation summary]", treat it as authoritative and merge.
Output one paragraph. Begin with the exact literal "[Conversation summary]".
```

**Alternative considered**: structured JSON output. Rejected — extra fragility (parse failures, schema drift), and downstream consumers (the next model turn) prefer prose.

### D5 — Write path: replace the prefix in both backends atomically-enough

When compaction completes:

1. Compute `prefixCount = totalTurns - keepRecentTurns`.
2. In Postgres: `repository.replacePrefixWithSummary(conversationId, summaryText, prefixCount)` — a single transactional method that deletes the oldest `prefixCount` rows and inserts one new row with `role='system'` and `content=summaryText`. This is the new repository method introduced by the change.
3. In Redis: `LTRIM key prefixCount -1` to drop the oldest `prefixCount`, then `LPUSH key <jsonForSummary>` to prepend the summary, then refresh `EXPIRE` with the configured `ttl`. The two Redis ops are not strictly atomic, but the worst-case interleave is "history briefly has summary AND original prefix" — which a follow-up read tolerates because compaction is idempotent (the marker prevents double-counting on the next compaction tick).
4. The whole sequence is gated on each backend's toggle (`redis.enabled`, `postgres.enabled`). If both are off, compaction never gets called (see `PersistentChatMemory.add(...)` short-circuit) — when only one is on, only that side is touched.

**Alternative considered**: a write-ahead "compaction journal" table to make the swap fully durable across crashes. Rejected — overkill for a derived view. Loss of a compaction summary at worst means the next turn pays for one extra raw prefix before compaction runs again.

### D6 — Async, fire-and-forget, never fails the user's turn

`ChatHistoryCompactionService.maybeCompact(conversationId, requestPrimaryProvider, compactionOverride)` is annotated `@Async` and dispatched **after** `persistToDb`. The user's HTTP response has already been written. Any exception inside compaction is logged at WARN with the conversation id and swallowed. The next turn will see the un-compacted history; the compaction will simply retry on the next `add(...)`.

We rely on the same `TaskExecutor` Spring AI already wires for `@Async`. No new thread pool.

**Alternative considered**: synchronous compaction inside the user's turn. Rejected — would add a full cheap-model round-trip (~300-1500 ms) to every Nth turn. Async is invisible to the user.

### D7 — REST DTO shape

Existing `PromptRequest` (multipart form / JSON, depending on endpoint) gains two optional fields:

| Field | Type | Default | Validation |
|---|---|---|---|
| `compactionProvider` | string | (request `provider`) | must match a configured provider key in `app.ai.providers.*` |
| `compactionModel` | string | (resolved via D3) | non-empty if present |

`PromptController` reads both, builds a `CompactionOverride` value object (immutable record), and threads it to `PersistentChatMemory.add(...)` → `ChatHistoryCompactionService`. The existing primary-chat `provider` / `model` flow is unchanged.

### D8 — Banner visibility

`StartupLogConfig` gains one new line in the Infrastructure block, directly under the `Chat History:` toggle line:

```
Chat History Compaction:  [Enabled] (trigger: 20 turns / 50% context, keep: 8 turns, defaults: openai=gpt-4o-mini, ...)
```

When `enabled: false` the suffix is just `[Disabled]`. Operators see at a glance whether their cost-savings knob is on and what models it routes to.

### D9 — Behaviour when the toggle path turns chat history off entirely

If both `app.memory.chat-history.redis.enabled` and `app.memory.chat-history.postgres.enabled` are `false`, there is no history to compact. `PersistentChatMemory.add(...)` early-returns before reaching the compaction call, so `ChatHistoryCompactionService` is never invoked. The banner still shows whether compaction *would* fire if backends were enabled — making the configuration legible without needing to mentally compose two flags.

## Risks / Trade-offs

- **[Risk] Compaction summary loses important detail.** The cheap model is, by definition, less capable. A 50-turn debugging session might end with a summary that drops a critical exception trace. → Mitigation: defaults are conservative (only fires past 20 turns, summary capped at 800 tokens which is roomy). REST override lets a high-stakes caller use a stronger model on demand. Operators can disable globally via `app.memory.chat-history.compaction.enabled: false` if they hit quality issues. We will spot-check summaries during the implementation tasks before declaring the feature ready.
- **[Risk] Cheap model returns malformed output (no `[Conversation summary]` marker, off-target paragraph).** → Mitigation: post-call validation — if the output does not start with the marker, the service prepends it and logs at INFO. If the output is empty or longer than `max-summary-tokens × 1.5`, the compaction is skipped (the original turns remain) and a WARN is logged.
- **[Risk] Per-provider rate limits.** A long burst of new conversations all hitting the compaction trigger at the same time could amplify outbound rate-limit pressure on the cheap model. → Mitigation: compaction is async on the existing executor, so it queues naturally. If pressure becomes a real problem we add a per-provider semaphore — out of scope for this change.
- **[Risk] Redis / Postgres divergence during the replace.** Crash between the Postgres replace and the Redis trim+push could leave Redis ahead of Postgres for one read. → Mitigation: the idempotency marker handles it — next compaction call detects the prefix already starts with a summary and decides to merge / skip. Worst case is one stale read until the next compaction tick.
- **[Trade-off] Compaction is per-conversation, not per-tenant.** A noisy power user with 50 active conversations and a default trigger of 20 turns can move significant load through the compaction model. Acceptable; we already use the same per-provider cost defaults that the rest of the agent uses, so the failure mode is "operator's monthly bill went up", not "system fell over".
- **[Trade-off] Two parallel "cheap model" config knobs** (`memory-extraction-model` and now `compaction-model`). Operators have to set both. Mitigation: documented inline in `application.yaml`; the banner reports the active compaction model so the configuration is legible.

## Migration Plan

Pure additive. Deploy the binary, optionally tune the new yaml block, restart. No data migration: existing chat history is compatible as-is; the first time a long-enough conversation gets `add()`-ed, compaction fires once and the resulting summary lands in both backends. No back-fill of historic conversations — they'll compact naturally on next activity, or stay raw if dormant.

Rollback: set `app.memory.chat-history.compaction.enabled: false` and redeploy (no restart of dependent services needed). Any `[Conversation summary]` rows already written to Postgres remain — they are valid SystemMessages and continue to be returned by `get(...)`. To fully purge summaries, an operator runs `DELETE FROM chat_history WHERE content LIKE '[Conversation summary]%'`; this is documented in the rollback section of `tasks.md`.

## Open Questions

- Should the summary prompt be parameterised by user / locale? For now: no — one English prompt, the agent answers in the user's language regardless. Revisit if non-English transcripts produce noticeably worse summaries.
- Should `compactionModel` validation accept an arbitrary string, or must it match a known model for the provider? Decision deferred to implementation: start permissive (provider-side error surfaces back to the caller), tighten if it causes confusion.
- For MiniMax we currently default to the same primary model since there is no clear "mini" tier in `application.yaml`. If MiniMax adds a cheaper tier, the default flips with no code change (it's just a yaml entry).
