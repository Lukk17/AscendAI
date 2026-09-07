# ADR-006: Upgrade mem0ai 1.0.3 → 2.0.4, Drop OpenAILLM Monkey-Patch

**Date**: 2026-06-01
**Status**: Accepted
**Deciders**: Łukasz Sarna

---

## Context

mem0ai 1.0.3 had two structural problems that the service worked around with patches:

1. `Memory.delete_all(user_id=...)` ran a per-id `delete` loop and then called `vector_store.reset()`, which wiped
   every other user's memories sharing the Qdrant collection. The service compensated by reimplementing wipe as a
   manual per-id loop, never calling `delete_all`.
2. mem0 1.x had no native `lmstudio` LLM provider. LM Studio rejects `response_format={"type": "json_object"}` on
   models that don't support structured output, so the service monkey-patched `OpenAILLM.generate_response` at import
   time to strip the field before forwarding to LM Studio. This survived as long as mem0 didn't refactor the
   `OpenAILLM` class.

mem0ai 2.0.4 fixed both issues upstream (`delete_all` no longer calls `reset()`; a first-class `lmstudio` LLM
provider ships with the package) and broke the call signature of `Memory.search` as a side effect:
`(query, user_id, limit, ...)` became `(query, top_k, filters={"user_id": ...}, threshold, rerank, ...)` with
keyword-only arguments.

---

## Decision

Upgrade mem0ai to 2.0.4. Remove the OpenAILLM monkey-patch entirely. Drop the manual delete loop in
`AscendMemoryClient.wipe_user` and call `self.memory.delete_all(user_id=...)` directly. Update `AscendMemoryClient.search`
to the 2.x signature (`top_k=`, `filters={"user_id": ...}`).

For LM Studio specifically, the service now constructs the mem0 LLM config with `provider="lmstudio"` and
`lmstudio_base_url=<settings.LMSTUDIO_BASE_URL>`. For OpenAI and Gemini (OpenAI-compatible), the config uses
`provider="openai"` with `openai_base_url=<...>`. The choice is driven by `PROVIDER_CONFIGS[provider]["llm_provider"]`
so adding a new backend stays a config-file edit. (`src/service/memory_client.py`, `src/config/config.py`)

---

## Alternatives Considered

### Alternative 1: Stay on mem0ai 1.0.3, keep both patches

- **Pros**: No call-site changes to `search`.
- **Cons**: Both patches are load-bearing. The `delete_all` workaround spins through Qdrant for every wipe; the
  OpenAILLM monkey-patch silently breaks the day a mem0 patch release refactors `generate_response`.
- **Why not**: We are accumulating risk by staying on a version with known defects we patch around.

### Alternative 2: Fork mem0ai

- **Pros**: We control the cadence.
- **Cons**: Forks rot. Maintaining a fork of an active upstream is more work than tracking releases.
- **Why not**: Upstream fixed both issues; we don't need a fork.

---

## Consequences

### Positive

- The wipe path is now one Qdrant call (filter delete inside `delete_all`) instead of N calls plus a `reset`.
- The LM Studio path no longer depends on a private method of an external package.
- The provider routing config is now the single source of truth for which LLM backend mem0 instantiates.

### Negative

- The `search` API is now keyword-only and uses `top_k` / `filters` instead of `limit` / `user_id`. Any external
  caller that imports `AscendMemoryClient` directly must update.
- mem0ai 2.x has tightened input validation; some payloads that 1.x silently accepted now raise. Tests cover the
  current shapes; new shapes need verification before adoption.

### Risks

- **mem0ai 2.x is recent**: The release is weeks old as of this ADR. Patches may break the contract again. Pin the
  exact version (`mem0ai==2.0.4`) and bump deliberately.
- **lmstudio LLM provider behaviour drift**: mem0's `LmstudioLLM` makes assumptions about LM Studio's OpenAI-compat
  endpoint. If LM Studio's API surface changes, the integration breaks without a mem0 release. Mitigated by the
  cold-boot warmup loop in `src/main.py` that surfaces the breakage on startup.
