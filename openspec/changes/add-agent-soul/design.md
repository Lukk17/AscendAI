## Context

See proposal.md for why. This section holds only the facts the design rests on.

The chat path today (`apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/`):

- `AscendChatService.prompt` calls `ChatContextAssembler.buildSystemMessages`, then `buildUserMessage`, then `ChatHistoryService.loadHistory(userId)` (the newest 100 messages from `PersistentChatMemory`), then `ChatExecutor.execute`, then saves history with `userMessage.text()`, which is the user's prompt plus attached document text plus the RAG context.
- `ChatContextAssembler.buildSystemMessages` returns `AssembledSystemMessages(staticPrefix, dynamicSuffix)`. The static prefix is `app.system-prompt` (2,674 characters, about 669 tokens at four characters per token). The dynamic suffix is `"User Instructions:\n"` plus the text from `UserInstructionService`, plus the semantic memory block. Because the heading is always there, `hasDynamic()` is always true today.
- `ChatExecutor.invoke` sends `SystemMessage(staticPrefix)`, `SystemMessage(dynamicSuffix)`, then the history, then the user message (with the image when there is one). On a cache configuration error `execute` calls `invoke` once more without the cache options.
- `UserInstructionService` reads `user_instructions` (Postgres, key `user_id`) through a Redis cache `user:{userId}:instructions` with a TTL from `app.memory.user-profile.ttl`. `updateInstructions` exists but nothing calls it: no controller, no tool. The table can only be filled by hand.
- There is no input budget. Nothing checks that the request fits the provider's window. `ChatHistoryCompactionService` keeps a private table `CONTEXT_WINDOW_DEFAULTS` (`openai` 128,000, `anthropic` 200,000, `gemini` 1,000,000, `minimax` 200,000, `lmstudio` 8,192, fallback 8,192) used only for its 50 percent token trigger, and compaction runs after the turn, asynchronously.
- The compaction summary is a `SystemMessage` that starts with `[Conversation summary]` and sits at the head of the history the executor sends.

How Spring AI 1.1.5 sends system messages to Anthropic, read from `AnthropicChatModel` in `spring-ai-anthropic-1.1.5-sources.jar`:

- `buildSystemContent` collects every message of type `SYSTEM` from the whole prompt, wherever it sits, into the top-level `system` field. `buildMessages` sends every other message in order.
- With `multiBlockSystemCaching(true)` and more than one system message, each system message becomes one block and `cache_control` goes on the block at index `size() - 2`, the second-to-last.
- Consequence today: a compacted conversation sends three system messages (static, dynamic, summary), the breakpoint lands on the dynamic block, which changes every request, and the static prompt is no longer cached for that conversation. This is a defect in the current code. It is in the exact area this change rebuilds, and the new layout fixes it (D4).
- Consequence for the reminder: a reminder sent as a `SystemMessage` at the end of the prompt would be moved into the `system` field by Spring AI and would also move the breakpoint. It must be part of the user message (D5).
- `upgrade-spring-boot-4` moves the agent to Spring AI 2. Task 3.1 checks the same two facts in the 2.0 sources before the layout code is written, and a test fails if they change.

What other agents do, checked on 2026-10-02:

| | OpenClaw | Hermes Agent |
|---|---|---|
| Personality file | `SOUL.md`, "Persona, tone, and boundaries. Loaded every session" | `SOUL.md`, "slot #1 in the system prompt", "the first thing in the system prompt" |
| Identity | separate `IDENTITY.md` (name, vibe, emoji) | inside `SOUL.md` |
| User file | `USER.md`, "stable preferences, communication style, relationships, and active-project context" | `USER.md`, written by the agent through its `memory` tool |
| Size limits | 20,000 characters per file (`agents.defaults.bootstrapMaxChars`), 60,000 in total (`bootstrapTotalMaxChars`), oversized files are truncated with a notice | `USER.md` 1,375 characters, `MEMORY.md` 2,200 characters, `SOUL.md` truncated when too large (no number in the docs) |
| Over the limit | truncation | the memory tool "returns an error instead of silently dropping entries", the agent consolidates in the same turn |
| Subagents | "Sub-agents only inject `AGENTS.md`" | built-in default identity when `skip_context_files` is set (subagent and delegation contexts) |
| Caching | stable files above an internal cache boundary, volatile sections below | "frozen snapshot" captured at session start, never changed mid-session, "to preserve the LLM's prefix cache" |
| Safety | not stated | `SOUL.md` and memory writes are scanned for injection and exfiltration patterns |
| Self edit | the shipped `SOUL.md` template: "If you change this file, tell the user", the docs say nothing more | the user writes `SOUL.md`, the agent writes `USER.md` and `MEMORY.md` |
| History | workspace kept in a private git repository | not stated |

Sources: https://docs.openclaw.ai/concepts/system-prompt, https://docs.openclaw.ai/concepts/agent-workspace, https://docs.openclaw.ai/reference/templates/SOUL, https://hermes-agent.nousresearch.com/docs/user-guide/features/memory, https://hermes-agent.nousresearch.com/docs/user-guide/features/personality, https://hermes-agent.nousresearch.com/docs/user-guide/which-file-does-what.

Reused from `add-agent-skills`: `VersionedFolder` (open or initialise a repository, commit with trailers, commit uncommitted changes as external, history for a path, read a path at a commit), `ChatToolset` with `AgentNativeTool`, the `TenantToolPolicy` port, the tool context keys `request_id`, `tenant_id`, `embedding_provider`, and the agent home root `app.agent-home` with its tenant folders (D1). Reused from `add-keycloak-login`: `TenantContext.currentTenantId()`, which answers the tenant of the request and fails closed. Reused from `add-deployment-modules`: `AuditEventPort` with its default. Reused from `upgrade-spring-boot-4`: the RFC 7807 problem detail of its D19 for every error (D7).

## Goals / Non-Goals

Goals:

- The personality file is whole and first in every request, however full the context is, and a fixed reminder ends every prompt.
- The cached prefix stays byte-stable while the personality file is unchanged, and nothing per user enters it.
- One validated, attributed and undoable write path per file, the same pattern as skills.
- The agent never changes the personality file alone. It proposes a change, and the change goes live only when the owner approves it.
- Every change or proposal made during a chat request is reported to the caller by the system, not only by the model.

Non-Goals:

- Deciding when the agent proposes a personality change or edits user facts on its own initiative. That is `add-self-improvement`.
- Deciding and storing a personality proposal. That is `add-action-approvals` (build group 4, position 5, right after this change), whose shared `ApprovalService` decides every proposal through `/api/v1/approvals`, from REST now and from the app and Discord later, and whose approval request is the only record of a proposal (owner answer 89.4 of 2026-10-08). This change has no approve or reject endpoint and no proposal table of its own. Until `add-action-approvals` lands, `personality_propose` is not offered (D7).
- Keeping existing data. The owner decided on 2026-10-02 (confirmed by owner answer 73.1 of 2026-10-06) that the project is under development and there is no data to keep, so this change copies nothing from `user_instructions` and drops the table (D10). This holds only until the first real customer deployment.
- A separate `IDENTITY.md`. Name and voice belong in `SOUL.md` (YAGNI, Hermes does the same).
- An agent notes file like Hermes' `MEMORY.md`. Semantic memory in AscendMemory already holds facts learned across sessions.
- Counting image tokens in the budget. Images are not estimated, the margin covers small images, and a provider error still surfaces as today.

## Decisions

### D1: Two files, two scopes

`SOUL.md` belongs to the tenant, because it describes the agent the tenant runs. `USER.md` belongs to one user, because it describes that user. Both live under the one agent home root `app.agent-home` of `add-agent-skills` (its D7 and D11: `${user.home}/.ascend-agent` for `bootRun`, `/app/agent-home` in the `docker` profile, on the named volume `agent-home`), in the tenant folder that already holds the tenant's skills and subagent definitions. This change adds no root property of its own. Layout:

```text
<root>/tenants/<tenantId>/skills/                    add-agent-skills, one git repository
<root>/tenants/<tenantId>/.claude/agents/            add-agent-subagents, one git repository
<root>/tenants/<tenantId>/soul/SOUL.md               this change, one git repository per tenant
<root>/tenants/<tenantId>/users/<userKey>/USER.md    this change, one git repository per user
```

`userKey` is the first 32 hex characters of SHA-256 of `<tenantId>:<userId>`. No user id appears in a path or a commit, and erasing one user deletes one folder without rewriting history, the same reason `add-agent-skills` keeps user ids out of git. Each of `soul/` and `users/<userKey>/` is its own repository through `VersionedFolder`. Neither the root, nor `tenants/`, nor a tenant folder, nor the `users/` folder is a git repository, so no repository contains another and each change commits only to its own folders. This change never reads or writes `skills/` or `.claude/agents/`, and the other two changes never read or write `soul/` or `users/`.

Erasure and export are company work of `add-audit-and-gdpr-compliance` (ruling 13.3 of 2026-10-05), which writes the erasure and export step of these stores. This change keeps the layout that makes them simple. Erasure deletes only this change's own folders. Per user erasure deletes `users/<userKey>/`, then `users/` when nothing else is left in it. Tenant erasure deletes `soul/` and `users/` of the tenant, then the tenant folder `tenants/<tenantId>/` when nothing else is left in it, the same rule `add-agent-skills` and `add-agent-subagents` follow for their folders. It never deletes `skills/` or `.claude/agents/`, which their own erasure removes.

Alternatives considered: user facts in Postgres (rejected: the owner asked for the same folder layout and git history as skills, and one folder per user gives erasure for free), one repository per tenant holding every user's file (rejected: erasing one user would need a history rewrite).

### D2: Reuse `VersionedFolder`, one store per file kind

`PersonalityStore` and `UserFactsStore` sit on `VersionedFolder` with their own trailers (`Soul-File`, `Soul-Operation`, `Soul-Origin`, `Soul-Request-Id`, and `Soul-Reason` when a tool call gave a reason). Each keeps an in-memory snapshot per tenant or per user (content, newest commit id, file size and modification time, validity). At the start of a chat request the store checks size and modification time with one file status call and reloads only when they changed, so a hand edit on the volume is seen at the next request without a watcher. The check reads only the store's own file, `soul/SOUL.md` or `users/<userKey>/USER.md`, never the tenant folder or the root. The skills watcher of `add-agent-skills` (its D5) and the definitions watcher of `add-agent-subagents` (its D5) are scoped to their own subfolders, so a change under `soul/` or `users/` never reloads skills or definitions, and a skill or definition change never touches these snapshots. A hand edit is committed with origin `external` before the next write, as skills do.

Invalid file on disk: the store walks the file's history newest first and uses the first committed version that passes validation, logs one WARN line, and sets the `soul.personality.fallback` gauge. Unlike skills, this survives a restart, because git already holds the last valid version. With no valid version the shipped default is used and one ERROR line is logged.

The shipped default is a classpath resource `soul/default-SOUL.md`. The owner writes the real `SOUL.md` content himself through `PUT /api/v1/personality` (owner decision of 2026-10-02), so the shipped default is only a minimal placeholder with no rules of its own:

```text
# Personality

No personality has been written for this agent yet. Follow the system prompt.
```

### D2a: Several agent instances on one agent home

Several agent containers run at once (owner answer 87 of 2026-10-08, CANON 26.1), and every one of them mounts the same `agent-home` volume. The per-folder lock of every write, revert and seed is a transaction-level Postgres advisory lock keyed on the repository path (`soul/` of a tenant, `users/<userKey>/` of a user), taken before the local lock, so writes of two instances to one repository run one at a time and never interleave two git commits. The in-memory snapshot of each instance is checked against the file's size and modification time at the start of every chat request (D2), so a write made on another instance is used from the next request on, with no cache to invalidate. The stale check of a proposal approval (D7) runs under the same lock.

### D3: Size limits

| File | Default | Hard cap | Why |
|---|---|---|---|
| `SOUL.md` | 8,000 characters (about 2,000 tokens) | 20,000 (`app.soul.hard-cap-chars`) | OpenClaw's per-file cap is the upper bound. The default is set by the smallest window the agent supports |
| `USER.md` | 4,000 characters (about 1,000 tokens) | 20,000 (`app.soul.hard-cap-chars`) | larger than Hermes' 1,375 because it also takes over user instructions |
| one `USER.md` entry written by the agent | 500 characters | none | keeps entries short so `replace` and `remove` can target one |
| reminder | 139 characters, fixed in code | none | a short sentence only, written by this change (D5) |

The smallest window is `lmstudio` at 8,192 tokens. At the defaults the fixed parts take: global prompt 669 tokens, personality 2,000, user facts 1,000, reminder and headings about 70, a total of about 3,740 tokens, which is 46 percent of 8,192. Output reserve (1,024) and margin (819) leave about 2,600 tokens for the user's text, tool definitions and everything else on LM Studio. Every remote provider has at least 128,000 tokens, where the same parts take under 3 percent. The startup WARN of the budget spec fires when the fixed parts pass `app.chat.context-budget.warn-fraction` (default 0.5, one half) of a window, so an owner who raises a limit sees the cost on the small model at once.

Over the limit a write is refused with the size and the limit in the message (Hermes' rule), never truncated (OpenClaw's rule), because cutting a rules file can drop the rule that matters most.

### D4: Three system messages, fixed order

`AssembledSystemMessages` becomes `(personalityBlock, globalPrompt, dynamicBlock)`, all three always non-empty:

1. `personalityBlock`: the fixed heading `# Personality file (mandatory for every reply)` then the file text.
2. `globalPrompt`: `app.system-prompt`, unchanged.
3. `dynamicBlock`: fixed headings, each always present in this order: user facts (or the fixed `none` line), conversation summary when there is one, the finished runs block of `add-agent-subagents` (its D16) when there are finished runs to report, semantic memory.

A new `PromptLayout` component builds the final message list from the assembled parts, the trimmed history and the user message, and is the only place that creates `SystemMessage` instances for a chat request. It takes a leading `[Conversation summary]` message out of history and into the dynamic block, and moves any other system message found in history there too. It is used by `ChatExecutor`, by the streaming path of `add-chat-streaming-and-conversations` and by subagent runs, so all three follow one layout.

Why the personality comes before the global prompt: the owner decided it is always the first system message. The global prompt is then cached per tenant instead of once for all tenants. Provider caches are per account and keyed on exact bytes, so this costs one cache entry per tenant and nothing else.

Why three and never two or four: with Anthropic multi-block caching the breakpoint is the second-to-last system block. Three blocks put it on the global prompt, so the cached prefix is personality plus global prompt (plus the tool definitions, which Anthropic places before the system field). With two blocks it would land on the personality and the global prompt would not be cached. With four it would land on the dynamic block and nothing would be cached. The summary move in item 3 is what fixes the defect described in Context.

### D5: The reminder sits right before the user's typed text

The final user message holds, in this order: the attached document text when a document is attached, the retrieved document context when there is any, the reminder, one blank line, and then the user's typed prompt. Attached text and retrieved context come first, each under its fixed heading and separated by one blank line, so the reminder and the user's own words are the very last thing in the prompt (owner decision of 2026-10-02). Today `BuiltUserMessage` puts the typed prompt first and the attachment text and RAG context after it. Because this changes how retrieved text is presented, task 3.7 measures answer quality on the old and the new order before the new order ships. The measurement runs on the hosted provider and model the existing AI-run agent specs whose documents it reuses answer on: provider `minimax` with model `MiniMax-M2.7` and embedding provider `openai`, read on 2026-10-08 in the enabled rows of `docs/api/request/AscendAI/ascend-agent/testing/rag-prompt-*.yml` (spec 5, RAG) and `doc-summarization-prompt.yml` (spec 3, the attached PDF). It never runs on LM Studio (owner answers 98.10 and 99.2 of 2026-10-08).

The reminder text is written by this change, not by the owner (owner decision of 2026-10-02), so it is a constant in code with no setting (answer 93 of 2026-10-08). It is only a short reference that tells the model to read and follow the personality file again, and carries no rules of its own:

```text
<personality-reminder>Read the personality file at the start of this conversation again and follow it in this reply.</personality-reminder>
```

It is added inside `PromptLayout`, after history has been loaded and after `AscendChatService` has taken the text it saves, so history never stores it. It sits after every cache breakpoint on every provider (after the `system` field on Anthropic, after all earlier messages on OpenAI and Gemini prefix caching), so it can never break a cached prefix. It is not a `SystemMessage` because Spring AI would move it into the `system` field (Context). It also avoids a mid-conversation system message, which some local chat templates in LM Studio refuse.

Placement limit, stated honestly: during a tool loop the tool calls and results come after the user message, so in later model calls of the same request the reminder is near the end but not last.

The text saved to chat history stays the joined text `BuiltUserMessage` builds today (typed prompt, attachment text, RAG context), without the reminder. Only the order sent to the provider changes.

### D6: The context budget

`ContextBudget` runs once per request in the one chat executor `StreamingChatExecutor` of `add-chat-streaming-and-conversations` (owner answer 89.1 of 2026-10-08), before the first model call, after `ChatToolset` has given the tool list, and its result is reused by the cache retry.

1. Window `W` from `app.chat.context-budget.windows[provider]`, available `A = W - outputReserve - ceil(margin * W)`.
2. Protected `P` = personality block + global prompt + reminder + typed prompt + tool definitions (the JSON of each `ToolCallback` definition, measured in characters). If `P > A`, throw `ContextTooLargeException` (HTTP 413, a problem detail with `code` `context_too_large`, see D7).
3. Add the remaining parts and, while the estimate is over `A`, drop in the spec's order: oldest history pair, summary, finished runs block, memory entries (least relevant first, the order `SemanticMemoryClient` returns), RAG chunks (lowest score first), attachment text (cut at the end with the fixed marker line), user facts (replaced by the `none` line).
4. Return the kept parts and a `TrimReport` that goes into `CustomMetadata.contextTrimmed` and one INFO line.

To trim chunks one by one and to place them before the reminder (D5), `RagRetrievalResult` and `BuiltUserMessage` keep the chunks and the attachment text as separate fields next to the joined text they hold today. The text saved to history is still today's joined text, so history does not change.

`ChatHistoryCompactionService.contextWindow` reads the same table. Its private map is deleted (DRY). The estimator is the existing characters divided by four, extracted to one `TokenEstimator` both use.

The budget does not replace compaction. Compaction shrinks history for the next turns. The budget makes this turn fit when compaction has not caught up or the window is small.

### D7: Write path and tools

`PersonalityWriteService` and `UserFactsWriteService` follow the steps of `add-agent-skills` D6: check the tenant slug (and compute the user key), take the per-folder lock (D2a), commit any hand edit as `external`, check `If-Match`, validate with `SoulTextValidator`, write to a temporary file and move it over `SOUL.md` or `USER.md` with `ATOMIC_MOVE`, commit, refresh the snapshot, publish one `AuditEvent` through `AuditEventPort.record` of `add-deployment-modules` (its default writes one structured log line, and `add-audit-and-gdpr-compliance` registers its implementation later), return the commit id. A failed commit restores the file from the newest commit.

`SoulTextValidator` is shared by both files and by load: strict UTF-8, no NUL, not blank (personality only), length in code points, the invisible and direction control characters of the spec, and the reserved markers `<personality-reminder>`, `</personality-reminder>`, `[Conversation summary]` and the fixed headings of D4. This is a narrow check that stops a write from imitating the prompt's own structure or hiding text. It is not a general prompt-injection filter and the design does not claim it is one. The clean-request rule (D8) is the main control.

Personality proposals (owner decision of 2026-10-02). The agent never writes the personality file itself. A proposal is stored in one place only, as an approval request of kind `personality_change` of `add-action-approvals` (owner answer 89.4 of 2026-10-08): this change has no proposal table. A proposal is the value `PersonalityProposal` with the newest commit of `soul/` when it was made (`baseCommit`), the proposed content (`proposedContent`, passed `SoulTextValidator`) and the optional reason (`reason`, at most `app.soul.reason-max-chars` characters, default 300). `PersonalityProposalService` validates it and hands it to the port `PersonalityProposalPort` of this change:

- `submit(tenantId, proposal, requestContext)` stores the proposal for the owner's decision and returns its id.
- `page(tenantId, status, cursor, limit)` and `find(tenantId, id)` return stored proposals with their id, payload, status (`pending`, `approved`, `stale`, `rejected`, `expired` or `cancelled`), approval id, creation time and decision time.
- `isAvailable()` says whether an implementation that can store proposals exists.

This change registers no implementation that stores anything: its default `UnavailablePersonalityProposalPort`, registered with `@ConditionalOnMissingBean`, answers `isAvailable()` false, an empty page and no proposal. `add-action-approvals` (build group 4, position 5) registers `ApprovalPersonalityProposalPort`, which stores each proposal as an approval request of kind `personality_change` with the proposal as its payload, so the proposal id is the approval id, and reads the requests of that kind as the proposal screen's filtered approval view. A personality change is never rememberable, so each proposal is decided on its own.

The before view is the file at the base commit, read from git, so it is never stored twice. The after view is the proposed content. `PersonalityProposalService.diff(baseCommit, content)` computes the unified diff between them, used for the approval's preview and when a proposal is read.

Every decision goes through the shared `ApprovalService` of `add-action-approvals`. This change has no decision endpoint of its own. `PersonalityProposalService` offers three methods that only the approval handler of that change calls (its `PersonalityChangeApprovalHandler` for kind `personality_change`):

- `approve(approvalId, proposal)` runs through `PersonalityWriteService` under the tenant's lock (D2a). The base commit must still be the newest commit, otherwise the call is refused with `stale_proposal` and the approval execution fails with that reason, so the proposal reads `stale`. An accepted approval validates the content again and commits it with origin `agent`, the request id and the trailer `Soul-Proposal-Id` holding the approval id. The approval service claims the execution once, so it can never run twice.
- `reject(approvalId)` when the owner denies the approval, and `expire(approvalId)` when it times out. Neither changes a file. Each counts the outcome and records its audit event (D13, task 8.6). An expired proposal is never applied.

The `stale_proposal` refusal goes back to the approval handler as the reason of a failed execution. It has no HTTP status in this change, because no endpoint of this change decides. A proposal changes nothing on disk until it is approved. Tenant erasure of the proposals is the erasure of the approval requests of `add-action-approvals`.

Before `add-action-approvals` lands, `personality_propose` is not offered, because `PersonalityProposalPort.isAvailable()` is false, and the read endpoints answer an empty list and 404. Nothing would be lost by storing proposals earlier, because nothing could decide them before that change lands (owner decision 65.25 of 2026-10-04), and storing them only in the approval record removes the second record and the bridge at the first start (owner answer 89.4 of 2026-10-08).

Tools, both `AgentNativeTool` beans through `ChatToolset`:

- `personality_propose` `{content, reason}`: proposes a full replacement, submits it for approval through `PersonalityProposalPort` as above, and returns the proposal id (which is the approval id), the size before and after and a short diff, and tells the model to tell the user that the change waits for the owner's approval. `reason` is optional, at most `app.soul.reason-max-chars` characters (default 300), and is stored in the proposal and in the `Soul-Reason` trailer of the commit an approval makes (asked for by `add-self-improvement`). Offered when proposals are on, `PersonalityProposalPort.isAvailable()` is true, the tenant folder is writable and the caller has `ADMIN` when security is on. Never offered to a run, except a run of kind `self_review` (D9).
- `user_facts_update` `{action, entry, match, reason}`: `add`, `replace`, `remove` on lines starting with `- `, matched by plain substring on exactly one entry (Hermes' substring matching). `reason` is optional, at most `app.soul.reason-max-chars` characters (default 300), and is stored in the `Soul-Reason` trailer. Never offered to a run, except a run of kind `self_review` (D9).

`StreamingChatExecutor` adds one tool context key owned by this change, `request_provenance`, which holds the request's one `RequestProvenance` value (D15). Both tools read the current value from it when they are called.

REST: `PersonalityController` under `/api/v1/personality` (with the read only proposal endpoints `GET /api/v1/personality/proposals` and `GET /api/v1/personality/proposals/{id}` with the status, the approval id, the before text, the after text and a unified diff, both `ADMIN` only and both reading through `PersonalityProposalPort`, so they are the filtered approval view of kind `personality_change` once `add-action-approvals` is applied, and no approve or reject endpoint, because the owner decides through `/api/v1/approvals/{id}/approve` and `/deny` of `add-action-approvals`) and `UserFactsController` under `/api/v1/user-facts`, in the style of `CatalogController` of `add-agent-skills` (its D24, owner answer 89.5 of 2026-10-08) (`@Tag`, `@Operation`, bounded body read, `ETag` as the newest commit id, `If-Match`). The user is resolved like `PromptController` does, from the resolved identity of `add-keycloak-login`, which lands before this change (the token's `sub`, and the dev identity under the `dev` profile). The personality write and proposal endpoints are this change's own rows in the authorization matrix of that change (its D4), `ADMIN` only. `GlobalExceptionHandler` maps the refusal reason `too_large` to 413 with the code `content_too_large` on REST, the validation reasons `blank`, `not_utf8`, `invisible_character` and `reserved_marker` (and a revert whose content fails validation) to 400 with the code `validation` and the `errors` field of `upgrade-spring-boot-4` D19 point 5, `conflict` to 412, `not_found` to 404, `forbidden` to 403, and `unavailable` to 503. Inside the write services, in the tool text and in the `soul.write` counter the reason stays `too_large`, and only its REST code is `content_too_large`.

Error body (owner decision of 2026-10-02): every error is the RFC 7807 problem detail that `upgrade-spring-boot-4` defines for every agent error (its D19) and builds in one factory method. It is sent as `application/problem+json` with `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title` (the HTTP reason phrase), `status`, `detail` (one sentence for a person, never file content), `instance` (the request path) and a top-level `code`, and has no `timestamp`. A validation refusal answers code `validation` with the extension field `errors` that `upgrade-spring-boot-4` requires for that code (its D19 point 5 and its `agent-error-responses` spec): one object with `field` (`content`) and `message` per failed rule, sorted by `field`, where `message` starts with the specific reason, for example `reserved_marker: the content holds the reminder tag`. The specific reasons `blank`, `not_utf8`, `invisible_character` and `reserved_marker` appear only inside each `errors` message and in the tool text, never as the `code` of a body. This change adds no error body of its own.

Codes (owner decision of 2026-10-02): `add-agent-skills` lands first and owns the shared codes `conflict` and `unavailable`, `add-keycloak-login` owns `forbidden` (owner answer 76.9 of 2026-10-08), and `upgrade-spring-boot-4` already has `validation`, `not_found` and `content_too_large`. This change reuses those six and adds no `too_large` code and no code for a validation reason. It adds to `ApiErrorCode` only its own code `context_too_large` (413), with type `https://ascend.ai/errors/context-too-large`.

### D8: Who may change what

- Owner through REST: both files, always, with origin `owner`.
- Agent through chat, `user_facts_update`: on by default, on its own initiative, only while the request's `RequestProvenance` (D15) is `clean` or `retrieved`, so not after an attachment, a peer bot turn or an outside tool result. RAG context alone does not block it. This matches Hermes, where the agent writes `USER.md`, and replaces user instructions that nobody could write.
- Agent through chat, `personality_propose`: on by default, only for an `ADMIN` caller, only while the request's `RequestProvenance` is `clean` (no retrieved context, no attachment, no peer bot turn, no outside tool result). It never changes the file. It creates a proposal with a before and after view that the owner approves once (owner decision of 2026-10-02) through the shared `ApprovalService` of `add-action-approvals` (build group 4, position 5), as kind `personality_change`, from `/api/v1/approvals` now and from the app and Discord later. A denied approval rejects the proposal and a timed out approval sets it `expired`. Until `add-action-approvals` lands the tool is not offered (D7). The approved commit is recorded as origin `agent` with the request id and the proposal id. A personality change reaches every user of the tenant, and small unreviewed edits over many sessions could wear away the rules the owner wrote, which is why the agent may only propose.
- The clean-request rule exists because model output can be steered by any text in the prompt (`add-agent-skills` D8). A tool that ran earlier may have returned a web page, an OCR result or a file, and that text must not become standing instructions for everyone. The rule reads the one `RequestProvenance` value of D15, the same value `add-self-improvement` uses, so the two changes can never disagree on whether a request was clean. Earlier drafts refused after any other tool. With D15 only a tool whose result can carry outside content counts, so the agent's own read tools such as `skill_search` no longer block a user facts write.
- User facts stay fully automatic (owner decision of 2026-10-02): `user_facts_update` needs no approval.
- The one exception for runs (asked for by `add-self-improvement`, documented here): a run of kind `self_review` may be offered `user_facts_update` and `personality_propose`, and `personality_propose` there only stores a proposal that waits for the owner's approval like any other. A review has no caller and its own tool calls are not the source of what it writes, so for that run the `RequestProvenance` rule of D15 is evaluated on the review's provenance as `add-self-improvement` records it, a `RequestProvenance` value of D15 that the review run starts with (user facts: `clean` or `retrieved`, personality: `clean` only), instead of on the run's own tool calls, and the `ADMIN` caller check of `personality_propose` is replaced by the tenant's grant of the `self-improvement` module. No other kind of run (`subagent`, `coding`, `scheduled`, `integration`) is ever offered either tool.
- Every change or proposal in a chat request is in `CustomMetadata.fileChanges` (file, operation, commit id for a change or proposal id for a proposal, size before and after), and the tool result tells the model to tell the user. This is the "tell the user" line of OpenClaw's template made deterministic, and it is the report the owner wants for `add-self-improvement`.

### D9: Subagents get the personality file, not the user facts

OpenClaw gives subagents only `AGENTS.md` and Hermes gives them a built-in default identity. Here the owner defines the personality file as how the AI must always behave, which includes boundaries, and a subagent acts for the tenant with tools of its own. So a run sends the personality block first, then the definition body, preloaded skills and footer of `add-agent-subagents` D8 in its dynamic part, and begins its first user message with the reminder, through `PromptLayout`. This holds for every kind of run in the run table of `add-agent-subagents` (`subagent`, `coding`, `scheduled`, `self_review`, `integration`) that calls a model through the run loop: a run without a definition puts the instructions its kind's change provides where the definition body would be, for example the fixed footer of a `scheduled` run of `add-scheduled-tasks`. `add-agent-subagents` lands before this change (build group 4, position 2), so this change builds the run prompt itself (task 7.3), and that change's D8 already describes the result. The run's budget follows D6 with the run's provider. The user facts are left out of every run (least data to a delegated task, the same choice OpenClaw makes with its minimal mode). `personality_propose` and `user_facts_update` are never offered to a run, with the one documented exception of D8: a run of kind `self_review` may be offered both, and `personality_propose` there only proposes. `app.soul.personality.subagents.enabled=false` turns the personality block for runs off if run token cost matters more.

The compaction summariser and the memory extractor are internal steps with their own fixed instruction, not the agent speaking, and get neither file.

### D10: Replace `UserInstructionService` and drop its table

Replace, do not keep both. Both hold per-user standing text for the dynamic block, and two places for the same knowledge break DRY and would leave the model guessing which one wins. `USER.md` has everything the table lacks: a write path, history, limits, the agent tool and the REST endpoints.

Steps in this change (owner decision of 2026-10-02, confirmed by owner answer 73.1 of 2026-10-06, no data to keep):

1. `ChatContextAssembler` stops calling `UserInstructionService`. The service, its Redis key, its test, `UserInstruction`, `UserInstructionRepository` and `app.memory.user-profile.ttl` are deleted.
2. The versioned Flyway migration `V<n>__drop_user_instructions.sql` drops `user_instructions` in this change. No row is copied into user facts and there is no wait of a release before the drop.

This holds only until the first real customer deployment. After that, removing a table that holds customer data needs a copy step and a plan of its own.

### D11: Configuration

```yaml
app:
  soul:
    enabled: true
    hard-cap-chars: 20000
    reason-max-chars: 300
    personality:
      max-chars: 8000
      proposals:
        enabled: true
      subagents:
        enabled: true
    user-facts:
      max-chars: 4000
      max-entry-chars: 500
      agent-write:
        enabled: true
    git:
      author-name: ascend-agent
      author-email: ascend-agent@localhost
  chat:
    context-budget:
      windows:
        openai: 128000
        anthropic: 200000
        gemini: 1000000
        minimax: 200000
        lmstudio: 8192
      fallback-window: 8192
      output-reserve-tokens: 1024
      margin-fraction: 0.1
      warn-fraction: 0.5
```

`SoulProperties` refuses a `max-chars` above `hard-cap-chars` or below 1 and an entry limit above the file limit. The reminder is a constant in code (D5) and the trusted tools are a closed list in code (D15), so neither has a setting (answer 93 of 2026-10-08). There is no `app.soul.root`: the stores build their paths from `app.agent-home` of `add-agent-skills` (D1), which the `docker` profile already sets to `/app/agent-home`, so this change adds nothing to `application-docker.yaml`. `app.soul.enabled=false` sends the shipped default as the personality, keeps the reminder and the three-message layout, and offers neither `personality_propose` nor `user_facts_update`, so the cache layout never depends on the switch.

Settings (owner rule 98 of 2026-10-08). Every key above with a default is a setting: `application.yaml` writes `key: ${ENV:default}`, `SoulProperties` and `ContextBudgetProperties` carry the same default, the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`, and each gets one row in `apps/ascend-agent/docs/CONFIGURATION.md` whose description ends "Added by `add-agent-soul`." (tasks 1.1 and 1.2). ENV is Spring Boot's canonical environment form of the property:

| Property | Environment variable | Default |
|---|---|---|
| `app.soul.enabled` | `APP_SOUL_ENABLED` | `true` |
| `app.soul.hard-cap-chars` | `APP_SOUL_HARDCAPCHARS` | `20000` |
| `app.soul.reason-max-chars` | `APP_SOUL_REASONMAXCHARS` | `300` |
| `app.soul.personality.max-chars` | `APP_SOUL_PERSONALITY_MAXCHARS` | `8000` |
| `app.soul.personality.proposals.enabled` | `APP_SOUL_PERSONALITY_PROPOSALS_ENABLED` | `true` |
| `app.soul.personality.subagents.enabled` | `APP_SOUL_PERSONALITY_SUBAGENTS_ENABLED` | `true` |
| `app.soul.user-facts.max-chars` | `APP_SOUL_USERFACTS_MAXCHARS` | `4000` |
| `app.soul.user-facts.max-entry-chars` | `APP_SOUL_USERFACTS_MAXENTRYCHARS` | `500` |
| `app.soul.user-facts.agent-write.enabled` | `APP_SOUL_USERFACTS_AGENTWRITE_ENABLED` | `true` |
| `app.soul.git.author-name` | `APP_SOUL_GIT_AUTHORNAME` | `ascend-agent` |
| `app.soul.git.author-email` | `APP_SOUL_GIT_AUTHOREMAIL` | `ascend-agent@localhost` |
| `app.chat.context-budget.windows.openai` | `APP_CHAT_CONTEXTBUDGET_WINDOWS_OPENAI` | `128000` |
| `app.chat.context-budget.windows.anthropic` | `APP_CHAT_CONTEXTBUDGET_WINDOWS_ANTHROPIC` | `200000` |
| `app.chat.context-budget.windows.gemini` | `APP_CHAT_CONTEXTBUDGET_WINDOWS_GEMINI` | `1000000` |
| `app.chat.context-budget.windows.minimax` | `APP_CHAT_CONTEXTBUDGET_WINDOWS_MINIMAX` | `200000` |
| `app.chat.context-budget.windows.lmstudio` | `APP_CHAT_CONTEXTBUDGET_WINDOWS_LMSTUDIO` | `8192` |
| `app.chat.context-budget.fallback-window` | `APP_CHAT_CONTEXTBUDGET_FALLBACKWINDOW` | `8192` |
| `app.chat.context-budget.output-reserve-tokens` | `APP_CHAT_CONTEXTBUDGET_OUTPUTRESERVETOKENS` | `1024` |
| `app.chat.context-budget.margin-fraction` | `APP_CHAT_CONTEXTBUDGET_MARGINFRACTION` | `0.1` |
| `app.chat.context-budget.warn-fraction` | `APP_CHAT_CONTEXTBUDGET_WARNFRACTION` | `0.5` |

A window for a provider added later is one more map entry with the same form. Removed with `UserInstructionService` (D10): `app.memory.user-profile.ttl`, whose row in the configuration reference and any compose line for it go in the same commit.

Kept as constants, because they are not operational: the reminder text (written by this change by owner decision, D5, answer 93 of 2026-10-08), the closed trusted tool list (D15, answer 93), the fixed headings and reserved markers of D4 and D7 (prompt format), the `Soul-*` trailer names, the user key format of D1 (32 hex characters of SHA-256, a path format), the token estimate of four characters per token (the estimation rule compaction already uses, whose error the margin setting covers), the sanity bounds that guard the budget settings themselves (a window of at least 1024, a margin from 0 to 0.5), the error codes and the metric names.

### D12: Compose and image

No new volume and no Dockerfile change. The files live on the named volume `agent-home`, mounted at `/app/agent-home` in the `ascend-agent` service by `add-agent-skills` (its D12), whose Dockerfile line already creates `/app/agent-home` owned by `app` before `USER app`. On one machine every agent copy shares that named volume. On several machines `docs/DEPLOYMENT.md` documents an NFS-backed named volume, with no code change (owner answer 98.8 of 2026-10-08, `add-agent-skills` D24), so the advisory lock and the per-request file check of D2a work the same way there. The stores create `tenants/<tenantId>/soul/` and `tenants/<tenantId>/users/<userKey>/` themselves as the `app` user, so they get the right owner.

### D13: Metrics and logs

| Metric | Type | Tags |
|---|---|---|
| `soul.write` | counter | `file`, `origin`, `operation`, `outcome` |
| `soul.personality.proposal` | counter | `outcome` (`proposed`, `approved`, `rejected`, `stale`, `expired`, `refused`) |
| `soul.personality.fallback` | gauge | none |
| `chat.context.trimmed` | counter | `part` |
| `chat.context.refused` | counter | `provider` |
| `chat.context.fill` | distribution summary (fraction of the window used) | `provider` |

No tenant or user tag (`add-observability` D5). `part` has the seven values of the trim order and `provider` is bounded by `app.ai.providers`. Content of either file never reaches a log line or a metric.

### D14: Tests that prove the rules with a near-full context

All with a stub `ChatModel` that captures the `Prompt`, plus one Anthropic request body capture:

- `PromptLayoutTest`: three system messages in order, personality block byte for byte, the final user message holding attachment text, then RAG context, then the reminder and then the typed prompt last, a summary in history moved into the dynamic block, any other history system message moved too, image requests keep the reminder in the text part.
- `ContextBudgetTest`: for `lmstudio` (8,192) with the personality at its 8,000 character limit, user facts at 4,000, ten tool definitions and 60 history turns: the request fits, the oldest turns are dropped first, the personality is intact, the trim report counts the dropped turns. Then the order: memory before RAG before attachment before user facts. Then refusal with 413 when the typed prompt alone is too large, and no call reaches the model.
- `NearFullContextExecutorTest`: through the real `StreamingChatExecutor`, on both `POST /api/v1/ai/prompt` and `POST /api/v1/ai/prompt/stream`, with a history at 99 percent of the window, the captured prompt has the personality first and the reminder directly before the user's typed text at the end, and the cache retry sends the same prompt.
- `PersonalityProposalServiceTest` with a capturing test `PersonalityProposalPort`: a proposal changes nothing on disk and reaches the port with its base commit, content and reason, approval commits once with origin `agent` and the approval id in `Soul-Proposal-Id`, an approval after another write is refused with `stale_proposal`, rejection and expiry leave the file unchanged, and with the default port the tool is not offered and the read endpoints answer an empty list and 404.
- `AnthropicCacheLayoutTest`: builds the Anthropic request with the real `AnthropicChatModel` request builder for a compacted conversation, and asserts `cache_control` is on the second of three `system` blocks and the reminder is not in `system`. This test is also the guard on the Spring AI 2 behaviour from Context.
- `PromptPrefixStabilityTest`: two users of one tenant with different facts, memory and history give byte-identical first and second system messages.
- `CompactionKeepsPersonalityTest`: after a real compaction run on a stub summariser, the summariser input has no personality text and no reminder, and the next request still starts with the personality block.
- `HistoryNeverStoresSoulTest`: after a turn, Redis and Postgres hold no personality text and no reminder.
- E2E spec: on the live stack, set a personality with a rule that leaves a visible trace (every reply ends with a fixed word), fill a conversation on the hosted provider `minimax` (model `MiniMax-M2.7`) past its 200,000 token window, and assert the reply still ends with the word and `contextTrimmed` reports dropped turns (owner answer 101 of 2026-10-09, never LM Studio). Behaviour only, as the e2e contract requires.

### D14a: Removed

The scripted spec `<N>-soul-scripted` of task 10.6 and its offline retrieved context layout check (owner answer 72.8 of 2026-10-06) are removed by owner answer 91.3 of 2026-10-08, because `PromptLayoutTest`, `AnthropicCacheLayoutTest`, `RequestProvenanceTest` and the tool tests of task 5.3 already prove the layout and the provenance rules it repeated.

### D15: One request provenance value per request

Every chat request has one provenance value, computed in code from the request and never from the model. This change owns it because its two tools are the first to need it, and `add-self-improvement` reuses the same value for its change gate and its reviews instead of computing its own (required edit there).

- `RequestProvenance` is an enum with three values, ordered from most to least trusted, written in lower case wherever it is stored, logged or sent: `clean` (`CLEAN`), `retrieved` (`RETRIEVED`) and `untrusted` (`UNTRUSTED`).
- `ProvenanceSource` is an enum of the five things that lower it, written in lower case the same way: `retrieved_document` (retrieved document context from RAG was added to the request, gives `retrieved`), `attachment` (a document was attached to the prompt, gives `untrusted`), `peer_bot_turn` (the turn was written by a peer bot of `add-openclaw-plugin-host`, gives `untrusted`), `finished_run_result` (the finished runs block of `add-agent-subagents`, its D16, added the result of a finished run of any kind to the request, for example an approval, a subagent or a coding run, gives `untrusted`, owner decision 49.3 of 2026-10-03) and `outside_tool_result` (a tool that can return outside content was called, gives `untrusted`).
- `RequestProvenanceHolder` is the one mutable object per request: it holds the current `RequestProvenance` and the set of `ProvenanceSource` values seen. Its value only moves towards `untrusted` and never back.
- `StreamingChatExecutor` computes the value once, before the first model call, from the request: `retrieved_document` when `BuiltUserMessage` holds retrieved chunks (D6), `attachment` when it holds attachment text, `finished_run_result` when the dynamic block (D4) holds the finished runs block with at least one run result, and `peer_bot_turn` when the request carries the peer bot mark that only the agent API of `add-openclaw-plugin-host` sets (its `channel-peer-bots` capability, required edit there). It creates the holder with that value, puts it into the tool context under `request_provenance`, and reuses it for the cache retry. The streaming path of `add-chat-streaming-and-conversations` computes it the same way (required edit there).
- The only later change during the request: the `TrackingToolCallingManager` that the chat executor registers (`upgrade-spring-boot-4` D6) adds `outside_tool_result` and moves the holder to `untrusted` when it records a tool call, before the tool runs, unless the tool is one whose result holds only the agent's own stored text or a status. That list is closed and kept in code: `Skill`, `skill_search`, `skill_read_file`, `skill_write`, `subagent_definition_write`, `personality_propose`, `user_facts_update`, and the three self-improvement tools `skill_patch`, `subagent_definition_patch` and `request_self_review`, which `add-self-improvement` owns and which are named here because they return only stored text or a status (owner decision 49.3 of 2026-10-03). A later change that adds such a tool adds its name to this list in its own design. This closed list in code is the only list: there is no setting that adds names (answer 93 of 2026-10-08 removed `app.soul.provenance.trusted-tools`, which repeated the list in configuration), and the setting `provenance.trusted-tools` of `add-self-improvement` stays replaced by it. Every other tool counts: every MCP tool, every sandbox tool, `Task` and `TaskOutput`, because their results can carry a web page, a file or a subagent's answer.
- Runs of `add-agent-subagents` (its D2): a run started by `Task` gets a holder of its own that starts at the caller's current value and is raised by the run's own tool calls the same way. A run with no caller starts at the value its starter gives. A run of kind `self_review` starts at the review's provenance that `add-self-improvement` records, and its own tool calls do not change it, because the review never sees the outside text of the request it reviews (D8).
- Readers: `personality_propose` needs `clean`, `user_facts_update` needs `clean` or `retrieved` (D8), and `add-self-improvement` reads the value at the end of the request for its trigger and in its `SelfChangeGate` before a self-write. A refusal names the sources seen, so the model can tell the user why.

Why one value: two changes computing "was this request clean" in two places would drift, and a write could pass one check and fail the other. Why the tool call is counted before the tool runs: it is the safe side. A write that the model put in the same response after that tool call is refused even though the model had not yet seen the result, which costs at most one refusal, and no write can ever slip in after an outside result.

## Risks / Trade-offs

- [The personality costs tokens in every request, and in every subagent run] → 8,000 characters by default, the share of each window is shown at startup with a WARN above one half, and the subagent switch turns it off for runs.
- [On LM Studio at 8,192 tokens, tool definitions may leave little room] → Task 4.6 measures the real tool definition size with all MCP servers up on the hosted provider and computes the fit for every configured window, `lmstudio` included, without running LM Studio (owner answer 101 of 2026-10-09). If the protected parts do not fit, requests get a clear 413 instead of a provider error, and the owner can raise the window to the context the model was loaded with.
- [The cached global prompt is no longer shared across tenants] → One cache entry per tenant, on a per-account cache, keyed on exact bytes. Accepted by the owner's first-position decision.
- [The clean-request rule blocks some legitimate user facts writes] → The refusal tells the model the user can confirm the fact in a new message, which is then a clean request.
- [A personality proposal waits until the owner acts] → The tool result tells the user it waits for approval, and `GET /api/v1/personality/proposals` lists every pending one. An approval nobody decides expires after its timeout and the proposal becomes `expired`, so an unseen change never applies.
- [Until `add-action-approvals` lands the agent cannot propose] → Accepted, because nothing could decide a proposal before that change lands, and it lands right after this one. The owner can still change the file himself through `PUT /api/v1/personality` (D7).
- [Moving retrieved text before the reminder could change answer quality] → Task 3.7 measures it on the old and the new order before the new order ships, and stops for the owner if quality drops.
- [A model may still ignore the personality file] → First position plus the end reminder is the strongest placement available without fine-tuning. The e2e spec measures it on the weakest model in use.
- [A trimmed turn may hold context the user expects] → The trim report in the response makes it visible, and compaction keeps the summary of older turns in the dynamic block.
- [Hand edits on the volume are trusted as `external`] → They pass the same validation before use, and history shows them.
- [Spring AI 2 may change where it puts the breakpoint] → `AnthropicCacheLayoutTest` fails if it does.

## Required edits to other changes

This change does not edit these changes. Each edit must be made in the named change. No task of this change waits for a later change: the company changes register their implementations of the ports this change uses later, and a later personal change wires itself in its own tasks (dependency fix of 2026-10-05). On 2026-10-03 every edit below was checked against the named change and is made there: `add-chat-streaming-and-conversations` (its design section on the agent changes, its `chat-streaming` spec and its task 9.4), `add-tenant-isolation` (its design decision 12, its `chat-history-persistence` spec and its tasks 7.2 and 7.3, which drop the `user_instructions` rekeying and list `personality_proposal`, `soul/` and `users/<userKey>/`), `add-tenant-policy` (its D8 rows for `personality_propose` and `user_facts_update`), and `add-audit-and-gdpr-compliance` (its D3 vocabulary with the ten actions below, its D9 row for this change, its retention text and its `data-erasure` and `data-portability` specs). The rows for `add-self-improvement` and `add-scheduled-tasks` list what those changes asked of this change, made here on 2026-10-02.

| Change | Required edit |
|---|---|
| `add-agent-skills` | Made in that change on 2026-10-02: its D7, D11 and D12 name the `soul/` and `users/<userKey>/` folders of this change in the same tenant folder under `app.agent-home` and the same `agent-home` volume, and its D5 watcher ignores them. Nothing else in its text changes. This change uses `VersionedFolder`, `ChatToolset`, `AgentNativeTool`, the `TenantToolPolicy` port, the tool context keys as they are, and adds one key of its own, `request_provenance` (D15). Its `ChatExecutorSkillsTest` must keep passing with the new layout. |
| `add-agent-subagents` | Made in that change on 2026-10-02. Its D8: once this change is applied, a run's system instructions become three system messages through `PromptLayout`: the tenant's personality block first, the global prompt second, then the definition body, preloaded skills and footer in the dynamic block, and the run's first user message starts with the personality reminder, with no user facts. Its D9: `personality_propose` and `user_facts_update` are always subtracted from a run's tools, like `subagent_definition_write`, except in a run of kind `self_review`. Its D16: the finished-runs block is one section of the dynamic block and is trimmed by the context budget after the conversation summary. Its D5 watcher ignores the `soul/` and `users/` folders of a tenant folder. Its D2: every run carries a `RequestProvenance` holder of D15 under `request_provenance`, started from the caller's value or the starter's value. Task 7.3 here builds the run prompt, because that change lands first. |
| `add-chat-streaming-and-conversations` | That change lands before this one (build group 3, position 9), so its one chat executor `StreamingChatExecutor` (its D3, owner answer 89.1 of 2026-10-08, which removed `ChatExecutor`) is changed by this change itself (tasks 3.4, 4.4 and 7.2), and the text of that change that describes it is a note of what this change does there. Design D3: the executor builds its prompt through `PromptLayout` and `ContextBudget` once, for the blocking and the streaming endpoint alike, computes the request's `RequestProvenance` and puts its holder into the tool context under `request_provenance` (D15), refuses `context_too_large` before any SSE bytes like its other boundary refusals, and its terminal `done` event carries `fileChanges` and `contextTrimmed`, which the blocking endpoint returns in its one answer. The compaction delta spec there keeps its requirement, and the summary of a conversation moves into the dynamic block. |
| `add-tenant-isolation` | Proposal line 21 and tasks 7.2 and 7.3: this change lands first (build group 4 before build group 5), so `UserInstructionService`, the Redis key `user:{userId}:instructions` and the table `user_instructions` no longer exist, so the rekeying to `user:{tenantId}:{userId}:instructions` and the `tenant_id` column and composite key on `user_instructions` are dropped. Owner answer 89.4 of 2026-10-08: there is no `personality_proposal` table any more (sent through `inbox93/add-tenant-isolation__from__add-action-approvals.md`), so it is not added to the tenant-scoped tables. Add the personality repository `<root>/tenants/<tenantId>/soul/` and the user repositories `<root>/tenants/<tenantId>/users/<userKey>/` under the agent home root `app.agent-home` to the tenant-scoped stores, No seam needs replacing: both stores read `TenantContext.currentTenantId()` of `add-keycloak-login`, which already fails closed. |
| `add-tenant-policy` | Register its allow-list as the implementation of the `TenantToolPolicy` port of `add-agent-skills`, whose default offers both tools, and add `personality_propose` and `user_facts_update` to the tool allow-list governed in `ChatToolset`. `personality_propose` ships off for a new tenant. `user_facts_update` ships on, because it touches only the caller's own file. The deployment default policy for the personal deployment lists both. |
| `add-audit-and-gdpr-compliance` | Proposal lines 12, 13 and 15 and design line 7: replace `user_instructions` and the Redis key `user:{tenantId}:{userId}:instructions` with the user facts folder `<root>/tenants/<tenantId>/users/<userKey>/` in the per-user erasure and export inventory (erasure deletes the folder, export adds `USER.md` at its newest commit), add the tenant's `soul/` and `users/` folders to tenant erasure (its proposals are approval requests of kind `personality_change`, erased with the approval requests, owner answer 89.4 of 2026-10-08) (the tenant folder itself is removed only when nothing else is left in it, D1) and the personality file with a git bundle to tenant export, remove `user_instructions` from the erasure, export and retention inventory because this change drops the table (user facts are a profile kept until the user deletes them, not chat history), and record the audit actions this change publishes through `AuditEventPort` with its registered implementation, `PERSONALITY_REPLACED`, `PERSONALITY_REVERTED`, `PERSONALITY_PROPOSED`, `PERSONALITY_APPROVED`, `PERSONALITY_REJECTED`, `PERSONALITY_EXPIRED`, `USER_FACTS_UPDATED`, `USER_FACTS_REPLACED`, `USER_FACTS_DELETED`, `USER_FACTS_REVERTED`, the upper case past tense names of its closed vocabulary (its D3). That change writes `SoulTenantStore.deleteTenant`, `deleteUser`, `exportTenant` and `exportUser` on the layout of D1, in its own tasks (ruling 13.3 of 2026-10-05). |
| `add-action-approvals` | Made in that change on 2026-10-02 and changed there on 2026-10-08 for owner answer 89.4 (both changes are planned by the same worker). Its approval request of kind `personality_change` is the only record of a proposal, with the base commit, the content and the reason as payload. It registers `ApprovalPersonalityProposalPort`, the implementation of this change's `PersonalityProposalPort` (its D3 and task 3.7), its `PersonalityChangeApprovalHandler` calls `diff`, `approve(approvalId, proposal)`, `reject(approvalId)` and `expire(approvalId)`, its retention keeps proposals, and its task 7.6 adds the requests `soul-ai-propose-personality` and `soul-ai-approve-proposal` to the AI-run spec of task 9.5. The approve and reject endpoints are gone. Nothing is left to edit there. |
| `add-self-improvement` | Asked of this change and made here on 2026-10-02 (D7, D8, D9): `user_facts_update` and `personality_propose` may be offered to a run of kind `self_review`, and to no other kind of run. There the clean-request rule is evaluated on the review's provenance (user facts: `clean` or `retrieved`, personality: `clean` only), and the `ADMIN` caller check is replaced by the tenant's grant of the `self-improvement` module. Both tools gain the optional argument `reason`, stored in the `Soul-Reason` trailer and on the proposal row. Required of that change and made there, checked on 2026-10-03 (its D3 and D7): its D7 provenance becomes the `RequestProvenance` value of D15 with its values `clean`, `retrieved` and `untrusted`, read from the `request_provenance` holder instead of being computed a second time, its trigger records the value and the `ProvenanceSource` set at the end of the request, its `SelfChangeGate` reads the holder before a self-write, a review run starts at the review's recorded value, and its setting `provenance.trusted-tools` is replaced by the closed list of D15 (answer 93 of 2026-10-08 removed `app.soul.provenance.trusted-tools`, sent through `inbox93/add-self-improvement__from__add-agent-soul.md`). |
| `add-openclaw-plugin-host` | Its `channel-peer-bots` capability: a turn written by a peer bot reaches the chat with a peer bot mark that only the plugin host's own agent API can set, and `StreamingChatExecutor` turns that mark into the source `peer_bot_turn`, so the request's `RequestProvenance` is `untrusted` (D15). Made in that change, checked on 2026-10-03 (its D13, its `channel-peer-bots` spec and its task 6.5). |
| `add-scheduled-tasks` | Asked of this change and made here on 2026-10-02 (D9): runs of kind `scheduled` get the personality block and the reminder like every run, never the user facts file, and are never offered `personality_propose` or `user_facts_update`. |
| `upgrade-spring-boot-4` | None. Its `prompt-caching` delta and this change's delta modify the same requirement. This change's text is written on top of that change's text and must be archived after it. Its D19 and its `agent-error-responses` spec define the problem detail every error of this change uses (D7), and this change adds its codes to its `ApiErrorCode` enum. |

## Decision record numbering

The decision record of this change takes the next free ADR number in `apps/ascend-agent/docs/architecture/decisions/` at implementation time, after the records of `upgrade-spring-boot-4`, `add-agent-skills` and any change applied before it. The e2e spec takes the next free spec number the same way.

## Migration Plan

1. Apply build group 3 and build group 4, positions 1 to 3, first: in particular `close-agent-test-gaps`, `upgrade-spring-boot-4`, `add-keycloak-login`, `add-deployment-modules`, `add-chat-streaming-and-conversations`, `add-agent-skills`, `add-agent-subagents` and `add-agent-sandbox`. This change is build group 4, position 4 of the owner build order of 2026-10-04.
2. Deploy. Flyway drops `user_instructions` when the agent starts. The personality repository `tenants/default/soul/` with the placeholder `SOUL.md` is created under `app.agent-home` on first start. Requests now carry three system messages and the reminder. The first Anthropic request per tenant writes a new cache entry.
3. The owner writes the personality with `PUT /api/v1/personality`.
4. `personality_propose` is offered once `add-action-approvals` is applied, and from then on the owner decides each proposal through `/api/v1/approvals`.
5. Rollback: switch the files and tools off with `app.soul.enabled=false`. Going back to the previous image is not supported, because that image reads the dropped `user_instructions` table. There is no data to keep (owner decision of 2026-10-02, confirmed by owner answer 73.1 of 2026-10-06), so a return to the previous image also means a fresh database. This holds only until the first real customer deployment.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. This change keeps its drop of the `user_instructions` table with no copy of its rows (D10), and it needs none of today's data.

## Owner decisions of 2026-10-07

Answer 75.1: the owner approved the fix of every item of the review of the group 3, 4 and 5 changes of 2026-10-07. Fixed here: item 25 (the overlay users `frostySoulToolsTest`, `frostySoulFactsTest`, `frostySoulFactsOtherTest`, `frostySoulBudgetTest` and `frostySoulScriptedTest` are added by the tasks that use them), item 26 (one rule for the e2e users, stated once in task 10.2) and item 62 (four specs).

## Owner decisions of 2026-10-08

Answer 76.9: the code `forbidden` and the 403 problem body come from `add-keycloak-login`, not from `add-agent-skills`. This change reuses them as before and adds neither (the codes paragraph, the proposal and task 0.1).

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/soul/`, its vector file in `apps/ascend-agent/e2e/fixtures/scripted-model/embeddings/soul/` (tasks 10.5 and 10.6, spec `agent-personality`). Every check that read the request journal now reads the scripted model's request log, `GET /mockoon-admin/logs` of the Mockoon admin API, and clears it with `POST /mockoon-admin/state/purge`. Answer 77.1: every scripted vector is 1536 long, because the provider `scripted` sends the embedding provider name `openai`, which the e2e overlay points at the scripted model, so the retrieved-context check writes to `ascendai-1536`.

Answer 78.1: the provider `scripted` uses `default-embedding: openai`, and the deterministic phase overlay points the agent's own embedding entry `openai` at Mockoon. There is no separate scripted embedding entry, and every vector file of this change is 1536 long (`ascendai-1536` and `ascend_memory_1536`).

Answer 78.2: the deterministic phase has two restarts of AscendMemory and the agent, each followed by a check (`close-agent-test-gaps` D7). The start restart sets the scripted model's address as AscendMemory's `OPENAI_BASE_URL`, a non-blank `OPENAI_API_KEY` and the agent's `e2e` profile, and the end restart, which runs even when a spec fails, brings back the real address and settings. The deterministic spec of task 10.6 runs between them, and the AI-run specs of tasks 9.4 and 9.5 start only after the end check has passed (task 9.6). (Superseded by answer 91.1 below: AscendMemory is never restarted, and the spec of task 10.6 is removed by answer 91.3.)

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (task 10.6). (Superseded by answers 91.1 and 91.3 below.)

Answer 79.1 and 79.2: the start restart of `close-agent-test-gaps` D7 sets AscendMemory's `OPENAI_BASE_URL` to `http://e2e-scripted-model:3000/v1` and the dummy `OPENAI_API_KEY` `e2e-scripted-not-a-real-key` in the shell of that one command, and the end check confirms the key is no longer this value. The harness containers on the stack's network are `e2e-scripted-model` (the scripted model, at `http://e2e-scripted-model:3000`) and `e2e-fake-mcp` (the fake MCP server). (Superseded by answer 91.1 below: no dummy key and no AscendMemory restart.)

Answer 89.1: `StreamingChatExecutor` of `add-chat-streaming-and-conversations` is the one chat executor, and this change adds its steps to it once: the prompt layout, the context budget, the request provenance and the `fileChanges` and `contextTrimmed` metadata (D6, D7, D15, tasks 3.4, 3.8, 4.4 and 7.2). The blocking endpoint collects the same answer, so no step is added twice.

Answer 89.5: the personality and user facts controllers follow the style of `CatalogController`, the one controller of the skills and subagent definitions catalog of `add-agent-skills` (D7).

Answer 85.1: every key and secret lives in the repository `.env`, never in the shell. No plan text of this change exports a secret any more: the start restart with the dummy key of answers 78.2 and 79.1 is gone (answer 91.1), and the AI-run specs use the keys of `.env`.

Answer 87 (rule R1, CANON 26.1): several agent instances run at once on the same `agent-home` volume. The Non-Goal that limited this change to one instance is removed. Every write, revert, seed and proposal approval takes a transaction-level Postgres advisory lock keyed on its repository path before the local lock, so two instances never interleave commits, and the snapshot check at the start of every request (D2) makes a write of another instance visible from the next request, with no cache to invalidate (D2a, D7, tasks 2.1 and 5.1).

Answer 88 (rule R2): every company plug-in point stays: the per-user git repository that makes per-user erasure a folder delete (D1), `AuditEventPort`, the `TenantToolPolicy` port and `TenantContext`.

Answer 89.4: a personality proposal is one approval request of kind `personality_change` of `add-action-approvals`, whose payload holds the base commit, the proposed content and the reason. The table `personality_proposal`, its five states, its migration and the bridge at the first start of `add-action-approvals` are gone. This change keeps `personality_propose`, the read endpoints (now the filtered approval view through the port `PersonalityProposalPort`, which `add-action-approvals` implements), `PersonalityProposalService` with `diff`, `approve`, `reject` and `expire`, the stale check, the `Soul-Proposal-Id` trailer (now the approval id) and the counter. The tool is offered once `add-action-approvals` is applied, which lands right after this change, so the proposal request of the AI-run spec of task 9.5 moved to its task 7.6 (D7, D8, D13, D14, tasks 5.2, 5.3 and 9.5). The text for `add-tenant-isolation` and `add-audit-and-gdpr-compliance` was sent through `inbox93`.

Answer 89.7: this change has no retention of its own. Decided proposals are kept by the approval retention entry, which excludes kind `personality_change` (`add-action-approvals` D10).

Answer 90: checked, no test-only setting or branch of this change is in real logic or service configuration. The overlay users `frostySoul*` live only in the development overlay of `add-keycloak-login`, and the removed scripted spec took its rules and vector file with it (answer 91.3).

Answer 91.1: this change has no deterministic spec that runs a scripted chat turn any more, so it has no memory wipe in a deterministic spec and no AscendMemory restart. The deterministic spec of task 10.2 calls no model. The AI-run specs of tasks 9.4 and 9.5 use the real AscendMemory and keep their memory deletes (task 9.6). Answer 91.2: this change uses no fake MCP server any more.

Answer 91.3: the deterministic spec `<N>-soul-scripted` of task 10.6 is removed, because `PromptLayoutTest`, `NearFullContextExecutorTest`, `AnthropicCacheLayoutTest`, `RequestProvenanceTest` and the tool tests of task 5.3 prove the layout and provenance rules it repeated, and it needed a restart of two services. D14a is removed with it, and so are its README rows, its run in task 9.6 and its scenario lines (tasks 10.3 to 10.5, `agent-personality` spec). The one deterministic API spec of task 10.2 and both AI-run specs stay.

Answer 93: removed with no feature cut: the setting `app.soul.provenance.trusted-tools`, because the same list is the closed list in code of D15, which stays the only list (sent to `add-self-improvement` through `inbox93/add-self-improvement__from__add-agent-soul.md`), and the setting `app.soul.personality.reminder`, because the owner decided that this change writes the reminder, so it is a constant in code (D3, D5, D11). Not applied, because each would cut a capability: the switches `app.soul.enabled` (the rollback path of the Migration Plan), `proposals.enabled`, `subagents.enabled` (the mitigation of the run token cost) and `agent-write.enabled`, and the per-user git repository (R2).

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 98: every value of this change that has a default is a setting with an environment variable, the same default in code and a compose line `${VAR:-default}` on `ascend-agent`, listed in D11, with its row in `apps/ascend-agent/docs/CONFIGURATION.md` in the same commit (tasks 1.1 and 1.2). Made external beside the keys D11 already had: the hard cap of both files `app.soul.hard-cap-chars` (20000), the reason limit of both tools `app.soul.reason-max-chars` (300) and the startup warning share `app.chat.context-budget.warn-fraction` (0.5). Every key D11 already had (the four switches, the file and entry limits, the git author, the five windows, the fallback window, the output reserve and the margin) gets its environment variable and compose line. Kept as constants, with the reason in D11: the reminder text and the trusted tool list (answer 93), the prompt headings and reserved markers, the trailer names, the user key format, the four characters per token estimate, the sanity bounds of the budget settings, the codes and the metric names. The removed `app.memory.user-profile.ttl` leaves the configuration reference in the same commit.

Answer 98.8: the files of this change live on the agent home. On one machine it is the named volume `agent-home`, on several machines `docs/DEPLOYMENT.md` documents an NFS-backed named volume, with no code change (`add-agent-skills` D24). This change adds nothing for it (D12).

Answer 99.2: the ordering measurement of task 3.7 runs on provider `minimax` with model `MiniMax-M2.7` and embedding provider `openai`, the hosted provider and model of the existing AI-run agent specs whose documents it reuses (read on 2026-10-08 in the enabled rows of `docs/api/request/AscendAI/ascend-agent/testing/rag-prompt-*.yml` and `doc-summarization-prompt.yml`), never on LM Studio, because the owner rejects LM Studio as a test default (answer 98.10, D5, task 3.7). Listed for the owner and not changed: task 4.6 measures the tool definition size on `lmstudio`, task 9.4 runs its AI-run spec on provider `lmstudio` because only its 8,192 token window can be filled at a sensible cost (D14), and the request `chat-context-too-large` of task 10.1 names provider `lmstudio` but calls no model.

## Owner decisions of 2026-10-09

Answer 101: LM Studio is used only in tests that test LM Studio support. The tests of this change do not, so every test or measurement that ran on LM Studio uses the hosted provider and model the other AI-run agent specs use, the same one task 3.7 names: provider `minimax` with model `MiniMax-M2.7`. Task 4.6 measures the tool definition size on it and computes the fit of every configured window, `lmstudio` included, by arithmetic. The near-full context spec of task 9.4 (D14, the `agent-personality` scenario "The personality survives a near-full context end to end") fills the history past the `minimax` window of 200,000 tokens, about 0.14 USD of input per run at the `pricing.yaml` row, so it runs in Scenarios 1 to 4 (tasks 9.6 and 10.4) and no scenario needs LM Studio. This replaces owner answer 67.6 of 2026-10-04 for this spec. The window of `minimax` is not lowered for the test, because an AI-run spec runs against the agent with its shipped configuration (owner answer 70.4). The unit tests and the deterministic request that only use the `lmstudio` window number of 8,192 tokens (`ContextBudgetTest`, the compaction trigger test, the `chat-context-too-large` request of task 10.1, which is refused before any model call with LM Studio stopped) stay.

## Open Questions

Owner decision of 2026-10-06: answer 72.8, the retrieved context layout check stays fully offline through the scripted embeddings of `close-agent-test-gaps` (D14a). (Superseded by answer 91.3 of 2026-10-08: the check and its spec are removed.)

None. The owner answered every open question on 2026-10-02: the agent only proposes personality changes and the owner approves each one once through the shared approval service of `add-action-approvals` (D7, D8), retrieved context and attachment text move before the reminder with a quality measurement (D5), `user_instructions` is dropped in this change with no copy (D10), and the owner writes `SOUL.md` himself while this change ships a placeholder and the reminder text (D2, D5).

Closed (owner decision 65.25 of 2026-10-04): a personality proposal cannot be decided before `add-action-approvals` lands, so the proposal stays `pending` with the file unchanged until then, and the first start with `add-action-approvals` submits it for approval, as written in D7. (Superseded by owner answer 89.4 of 2026-10-08: the proposal is stored only as an approval request, so `personality_propose` is offered only once `add-action-approvals` lands, and there is nothing to submit at its first start.)
