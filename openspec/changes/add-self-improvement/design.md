## Context

See proposal.md for why. This section holds only the facts the design rests on.

What the earlier changes already give, read on 2026-10-02:

- `add-agent-skills`: one validated write path for tenant skills (`SkillWriteService`), one git repository per tenant at `<agent home>/tenants/<tenantId>/skills/`, commit trailers `Skill-Name`, `Skill-Operation`, `Skill-Origin` (`agent`, `owner`, `external`), `Skill-Request-Id`, `Skill-Tools-Seen`, history and revert, and the tool `skill_write {name, content}`. The agent may create a skill and update a skill whose newest commit has origin `agent`. It may not delete or revert. Shipped names are refused with `shipped_name`. A skill the agent writes goes live at once (owner decision). The composition point `ChatToolset` with `AgentNativeTool`, the tool context keys `user_id`, `request_id`, `tenant_id`, `embedding_provider`, `ToolCallTracker.peek()`, the capability index and `skill_search` are owned there. The tenant of every request comes from `TenantContext.currentTenantId()` of `add-keycloak-login`, which fails closed, and work without a request binds a tenant with `TenantContext.runAs` of the same change. Its Non-Goals say deciding when the agent writes a skill is this change.
- `add-agent-subagents`: definitions per tenant in `tenants/<tenantId>/.claude/agents/` with their own write path and git, the tool `subagent_definition_write {content, action}`, the agent rules (explicit `tools`, only tools the writing conversation has, never the write tool, model allowlist, never replace an owner definition), live at once. The run table `subagent_run` with a user controlled tool loop, checkpoints before every model and tool call, worker slots, per run cost and token limits, the price table `infra/pricing/pricing.yaml`, a restart sweep, and a kind neutral run path that `add-action-approvals` already extends with kind `approval`.
- `add-agent-soul`: one `RequestProvenance` value per request (its D15), `clean`, `retrieved` or `untrusted`, computed in code and never from the model, held in the `request_provenance` holder of the tool context together with the set of `ProvenanceSource` values seen (`retrieved_document`, `attachment`, `peer_bot_turn`, `finished_run_result`, `outside_tool_result`), and only ever moving towards `untrusted`. `user_facts_update {action, entry, match}` runs only when the value is `clean` or `retrieved`, and `personality_propose {content}` only when it is `clean`, with an `ADMIN` caller, never changes the file, and submits kind `personality_change` to `ApprovalService`. It also gives `SoulTextValidator` with the invisible character and reserved marker checks and `CustomMetadata.fileChanges`. This change reads that value instead of building its own provenance (D7). Its Non-Goals say deciding when the agent proposes a personality change or edits user facts on its own is this change. It ships no agent notes file, because semantic memory already holds learned facts.
- `add-action-approvals`: `ApprovalService.submit` with kinds and handlers, one decision path from REST, the app and Discord, expiry as denial, never rememberable categories, and the gate wrapper pattern in `ChatToolset`.
- Semantic memory today: `SemanticMemoryExtractor` runs after every chat turn on its own virtual thread, extracts facts from the user's text with the provider's `memory-extraction-model` and inserts them through `SemanticMemoryClient.insertMemory`. The client also has `search` and `deleteMemory`. Memories are per user id in AscendMemory.
- Chat history saves the joined user text (typed prompt, attachment text, RAG context) and the answer. Tool calls and tool results are not saved.
- The agent has no scheduling today (`@EnableScheduling` and `@Scheduled` appear nowhere in `apps/ascend-agent/src/main/java`). `add-shared-scheduler`, build group 3, position 7 of the owner build order of 2026-10-04, brings the one shared, persistent, cluster safe scheduler on db-scheduler 16.12.0 with the execution table `scheduler_execution`: a due execution runs on exactly one agent instance, a pending execution survives a restart, an overdue system task runs once and then follows its schedule, and every handler must be safe to run twice (its D1 to D6). System tasks are recurring task beans whose names sit in the closed enum `SchedulerTaskName`, with the schedule in `app.scheduler.system-tasks.<name>.cron` and `.time-zone`, and per record work is a one time execution keyed by the record id whose row and execution change in one transaction (its D2, D3 and D5). Its inventory (D2) already lists every execution and system task of this change. Every cron has five fields and is checked and evaluated by `CronRule` on Spring's `CronExpression`, always in a named zone (its D4). Every service that reads time takes the one injected `Clock`, and tests use the library's `ManualScheduler` with a `SettableClock` (its D6). The same change brings owner notifications in `core-chat`: the `owner_notification` table with the `subject_ids` column (this change inserts the pairs of the source `self_improvement` with the kinds `change` and `alert` into its table `owner_notification_kind` in its own migration, answer 93 of 2026-10-08, D12), the `owner_notification_delivery` table, `OwnerNotificationService`, the port `OwnerNotificationChannel` (`name`, `canReach`, `deliver`), delivery retries on the shared scheduler and `GET /api/v1/notifications` (its D7 to D11 and the `owner-notifications` spec). The Discord channel of that port is an edit it gave `add-openclaw-plugin-host`, made there in its D12 (service `ascend-openclaw-host`).
- `add-deployment-modules` has the catalog entry `self-improvement`, which requires `subagents`, and replaces `app.self-improvement.enabled` and the per tenant flag with the module list and the tenant module grant (its required edit to this change). `add-agent-subagents` owns the run kinds `subagent`, `approval`, `coding`, `scheduled`, `self_review` and `integration`.
- Owner answers of 2026-10-02 this design follows: 38.1, a skill or definition written during a chat right after outside content was read in the same request is held for one tap of approval (approval kind `self_change`). 38.2, there is no daily digest: every report is created and sent in real time, when the change happens, because the app may not run at a fixed hour. 38.3, there are no dollar limits for now, only count limits.

What Hermes Agent does (MIT, github.com/nousresearch/hermes-agent), read from its documentation on 2026-10-02 (https://hermes-agent.nousresearch.com/docs/user-guide/features/skills and https://hermes-agent.nousresearch.com/docs/user-guide/features/memory):

| Hermes | Taken over here | Not taken over, and why |
| :--- | :--- | :--- |
| The prompt tells the agent to save a skill after a non trivial multi step workflow, after errors or dead ends that led to a working path, and after the user corrected its approach. Skills hold "lessons, not logs" | The same three triggers, the same wording in the review instructions and the learning section of the prompt | None |
| `skill_manage` actions `create`, `patch` (find and replace, preferred), full rewrite, `delete`, `write_file`, `remove_file` | `create` (existing `skill_write`), `patch` (new `skill_patch`, exactly one match) | Full rewrite by the review (a patch is reviewable and small), delete (the agent may not delete in `add-agent-skills`, `GET /api/v1/self-improvement/stats` lists unused skills for the owner instead), supporting files (`add-agent-skills` writes only `SKILL.md`) |
| `skills.write_approval` defaults to `false`, writes are staged under `pending/` when it is `true`, background review follows the same gate | Changes apply without approval by default. Staging exists for one case only, a chat write after outside content was read (D7) | A global staging switch, because the owner wants autonomy |
| Advisory linter (`incident-log-shape`, `references-sprawl`, `oversized-body` above about 24k characters) and `skills.guard_agent_created` pattern scanner | A blocking content scan for self-written text (D8) and a lower size limit for self-written skills (D10) | An advisory only linter, because a self-written skill reaches every user of the tenant |
| Memory entries scanned for prompt injection, credential exfiltration and invisible Unicode | The content scan, plus the `SoulTextValidator` checks the user facts already have | None |
| `MEMORY.md` 2,200 characters, `USER.md` 1,375 characters, frozen snapshot per session | User facts and semantic memory, as `add-agent-soul` already decided | An agent notes file, which `add-agent-soul` left out on purpose |
| `session_search` over past sessions with SQLite full text search | None | Conversations belong to `add-chat-streaming-and-conversations`. The review reads captured evidence instead (D3) |
| Background self-improvement review after a session | The review run (D2) | None |

## Goals / Non-Goals

Goals:

- The agent learns on its own from the three Hermes triggers and a daily review, and needs no approval for skills, definitions, memories and user facts.
- Every self-written change is small, checked, reported and undoable in one step.
- Text from a web page, a document, an attachment or another bot can never become a standing instruction for the tenant without a check, a mark and a report, and a chat write right after such text needs one tap.
- Work is bounded by counts per review, per check and per tenant and day. There is no dollar limit (owner answer 38.3), and cost is measured and shown.

Non-Goals:

- Changing the personality file without approval. The agent only proposes, as `add-agent-soul` decided.
- Fine tuning, prompt optimisation of the global system prompt, or changes to configuration, policy or limits by the agent.
- Deleting skills or definitions on its own. `add-agent-skills` gives the agent no delete. `GET /api/v1/self-improvement/stats` lists unused self-written skills, and the owner deletes them.
- A search over past conversations. The review reads evidence captured at the end of a request.
- A scheduler, a lock or a notification store of its own. Every timed piece of this change runs on the shared scheduler of `add-shared-scheduler`, and every report is an owner notification of that change (D9, D11).
- A daily digest or any report sent at a fixed hour (owner answer 38.2).
- Any mechanism that works with one agent instance only. Several agent instances run at once (answer 87 of 2026-10-08, CANON 26.1): the shared scheduler runs each review, each tenant review and each system task on one instance, the review slot is a pool of the one slot pool in Postgres (D2), the daily limits are counted under a Postgres advisory lock (D10), a chat change's check is claimed in its row (D6), and nothing of this change keeps a lock, counter, queue or cache in memory only.

## Decisions

### D1: Triggers and the merged, delayed review

A trigger is a reason to review one conversation. There are four kinds:

| Kind | How it is detected | Cost when nothing comes of it |
| :--- | :--- | :--- |
| `task_finished` | Code, at the end of a chat request: the request made at least `triggers.min-tool-steps` tool calls (default 4), or a subagent run started by the request finished `done` | none until the review runs |
| `error_solved` | Code: in one request a tool call ended in error and a later call of the same tool, or the final answer, succeeded | none until the review runs |
| `owner_correction` | The model calls `request_self_review` with trigger `owner_correction` when the user corrects its approach. Language independent, which matters because the owner writes Polish and English | one short tool call |
| `periodic` | The daily review task (D9) | bounded by `daily-review.max-conversations` and the daily limits |

The model also may call `request_self_review` with `workflow` or `error_solved` and a one line `lesson` (at most 300 characters) when it notices one of the Hermes triggers itself. The tool is offered to the main chat only, at most once per request (a second call answers that a review is already requested), and never to a run. Its description and a short learning section added to `app.system-prompt` carry the Hermes wording: save lessons, not logs, and do not write a skill during the chat unless the user asks, flag the lesson instead. This keeps most learning in the background review, where the evidence boundary (D3), the check before keep (D5) and the cost limits apply.

All triggers of one conversation are merged into one `self_review` row in state `pending`, with `not_before = last trigger + review.quiet-period` (default 10 minutes), moved forward by every new trigger. A partial unique index on `(tenant_id, conversation_id) WHERE status = 'pending'` makes this one row per conversation. Each pending row has one one time execution `self-review/<reviewId>` on the shared scheduler at `not_before`. The trigger recorder creates the row and the execution together, and moves both to the new `not_before`, in one transaction, the pattern of `add-shared-scheduler` D3 and D5. The quiet period lets the review see the whole task and a correction that comes in the next message, instead of reviewing half a task. The conversation id is the conversation id of `add-chat-streaming-and-conversations` (build group 3, position 9), which lands earlier.

A request that is itself a self-review run, a guard check or an approval run never records a trigger, so the agent cannot start a loop of reviews about its reviews.

Alternatives considered: a code heuristic for corrections (rejected: phrases like "no, do it like this" depend on the language, and a false positive costs a review), a review after every request (rejected: cost, and most requests teach nothing), a review inside the user's request like Hermes' foreground `skill_manage` (kept only as an explicit user request, because it adds latency to the chat and the chat model has just read raw tool output).

### D2: The review run

The custom task `self-review` of the shared scheduler runs `SelfReviewHandler.start(reviewId)` when the execution comes due. The shared scheduler gives the at most one instance guarantee, so this change has no poll loop and no lock of its own. The handler must be safe to run twice (`add-shared-scheduler` D2), so it moves the row with `UPDATE self_review SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'` and stops when zero rows change, because an earlier execution of the same review already started it. A trigger that arrives after the row left `pending` opens a new pending row with its own execution. A review that was due while every agent instance was down runs once when one starts, by the overdue rule of the shared scheduler. Before it starts, it checks in this order and ends the row `skipped` with the reason when one fails: the tenant's grant for the module `self-improvement` (D12), the daily limits (D10), `QuotaGate` of `add-deployment-modules` (default `AllowAllQuotaGate` allows every call, and `add-usage-metering-and-quotas` registers the real one later), and a free review slot: the review run takes a start-now slot of the pool `self_review` of the one slot pool `RunSlots` of `add-agent-subagents` (its D10, answer 89.7 of 2026-10-08), which this change registers for the run kind `self_review` with one `RunPoolRegistration` bean, running limit `review.max-concurrent` (default 1) and waiting bound 0, separate from the subagent worker slots so a review never takes a slot from the owner's work. The slot count lives in the `subagent_run` rows in Postgres, so `max-concurrent` holds across every agent instance (answer 87). When no slot is free the row ends `skipped` with the slot reason. A skipped row for limits stays visible in the report (D11).

The review runs as a run of the kind `self_review` that `add-agent-subagents` owns, in `subagent_run`, on the same user controlled tool loop: checkpoints, cancel, deadline, cost counters, usage recording, restart sweep. A `self_review` run has no cost limit (owner answer 38.3, made in `add-agent-subagents`, its D13): its cost is counted and recorded, and only its count limits stop it. Its tool set is fixed by this change and is not computed from a caller, because it has none. Its model is `review.model` per provider, default the provider's entry in `app.memory.chat-history.compaction.provider-defaults` of `application.yaml` (`gpt-4o-mini`, `claude-haiku-4-5`, `gemini-flash-lite-latest`, `MiniMax-M2.7`, and `meta-llama-3.1-8b-instruct` for `lmstudio`). The provider is the provider of the newest trigger request. Its system instructions are the classpath resource `self-improvement/review-instructions.md`, which nothing at runtime can write. The personality file is not sent, because the review is an internal step like the compaction summariser in `add-agent-soul` D9.

Tools of a review run:

| Tool | Purpose | Writes |
| :--- | :--- | :--- |
| `skill_search`, `Skill`, `skill_read_file` | find and read the tenant's skills before writing a near duplicate | no |
| `skill_write` | create a new skill only, an update is refused in a review with a message to use `skill_patch` | yes |
| `skill_patch` | change one text of a skill whose newest origin is `agent` or `guard` | yes |
| `subagent_definition_write` | create a new definition only | yes |
| `subagent_definition_patch` | change one text of an agent definition | yes |
| `user_facts_update` | add, replace or remove a user facts entry of the conversation's user | yes |
| `memory_search`, `memory_update` | search, add or remove semantic memories of the conversation's user | yes |
| `personality_propose` | propose a personality change, only from a `clean` source (D7) | no, a proposal |
| `self_review_finish` | end the review with a short summary, required as the last call | no |

No MCP tool, no sandbox tool, no `Task` and no integration tool of `add-self-built-integrations` is ever offered to a review run, so the review cannot read a web page, a file or any other outside content, and it never starts an integration build. A review may suggest an integration in its `self_review_finish` summary, which `GET /api/v1/self-improvement/reviews/{id}` shows as text (owner decision 40.3 of 2026-10-02). Every write tool of the table takes an extra `reason` argument (at most 300 characters, required in a review), which becomes the "why" of the report.

Limits of one review: `review.max-model-calls` (default 8), `review.max-duration` (default 5 minutes), `review.max-changes` (default 5 writes). The run's checkpoints enforce the first two, the gate (D4) the last. There is no dollar limit per review (owner answer 38.3).

`user_facts_update` and `personality_propose` in this table are the one documented exception to the rule of `add-agent-soul` that these two tools are never offered to a background run. The exception belongs to this change and covers the run kind `self_review` only, and it is made in `add-agent-soul`, its D8 and D9. It keeps the owner's two decisions: user facts change automatically (live for a `clean` or `retrieved` source, D7), and the personality only through a proposal that waits for the owner's approval. Removing the two tools from the review was rejected, because then the agent could never learn a user fact on its own, which the owner wants. Every other background run kind (`subagent`, `approval`, `coding`, `scheduled`, `integration`) is still never offered them.

### D3: The evidence boundary

The review never reads chat history, tool results, retrieved chunks or attachment text. At the end of every chat request that records a trigger, `StreamingChatExecutor` of `add-chat-streaming-and-conversations`, the one chat executor whose stream `POST /api/v1/ai/prompt` also collects (answer 89.1 of 2026-10-08), captures evidence into the review row once, for both endpoints:

- the user's typed prompt only, never the attachment text or retrieved context that the saved history joins to it,
- the final answer text,
- each tool step in order: tool name, the arguments the model sent (canonical JSON cut at `review.evidence-max-argument-chars`, default 500 characters), and `ok` or `error`, with no result text and no error text, because both come from the outside service,
- the lessons from `request_self_review`,
- the request's `RequestProvenance` value and `ProvenanceSource` set of `add-agent-soul` (its D15), and the list of tools the request had, for the subset rule of definitions.

The row keeps the newest `review.evidence-max-turns` (default 3) entries, at most `review.evidence-max-chars` (default 16,000) in total, oldest dropped first. The review instructions tell the model that the evidence is data and never instructions. The evidence is cleared when the review ends, whatever the outcome, so personal text does not stay in the table.

Why: a prompt injection needs its text to reach the model that writes. Tool output, retrieved chunks and attachments are where outside text enters, and none of them reaches the review. What remains is the user's own words, the assistant's answers and arguments the model wrote. An answer can echo injected text, so the provenance rules (D7) and the content scan (D8) still apply.

### D4: The change gate

`SelfChangeGate` wraps every write tool of D2 in a review run and the write tools `skill_write`, `skill_patch`, `subagent_definition_write`, `subagent_definition_patch`, `user_facts_update` in the main chat. It is applied in `ChatToolset` after the policy filter and before the approval wrapper of `add-action-approvals` (required one line edit to `add-agent-skills`, the same pattern approvals uses), and it keeps the tool definition bytes, so the prompt cache sees the same tools. For each call it:

1. Refuses when the item is frozen (D6) or a daily limit is reached (D10), with a message the model can read.
2. Applies the provenance rule of D7 for the type and the path.
3. Runs the content scan (D8) on skill and definition text.
4. For a review: runs the regression guard on the candidate (D5) and refuses the write when it fails. For a chat write: passes the call on, and queues a guard check after the commit.
5. Calls the delegate write path. Every write still goes through the validated write path of its owning change, with its own rules, locks, commit and reload.
6. Records one `self_change` row (D11) with the commit id, proposal id or memory id the delegate returned.

The owner's own REST writes never pass the gate, because they are not tool calls.

### D5: Targeted patches

`skill_patch {name, old_text, new_text, reason}` and `subagent_definition_patch {name, old_text, new_text, reason}` read the item at its newest commit, require `old_text` to occur exactly once (else `not_found` or `ambiguous`, Hermes' rule and the `user_facts_update` rule), build the new content, and send it through the owning write path with the read commit id as `If-Match`, so a write that happened in between fails with `conflict` instead of being overwritten. A patch whose changed text is longer than `limits.max-patch-chars` (default 2,000 characters, counted as the larger of the removed and the added text) is refused with `patch_too_large`. The commit carries `Skill-Operation: update` and the trailer `Skill-Patch: true` (or `origin`, `request` and the new `reason` trailer of a definition commit). Both tools are `AgentNativeTool` beans of this change that call the existing write services, so no write path is duplicated.

In a review, `skill_write` and `subagent_definition_write` create only. In the main chat they keep the update behaviour `add-agent-skills` and `add-agent-subagents` define, and the learning section of the prompt prefers `skill_patch`.

Why a patch and not a rewrite: a rewrite can silently drop a rule the owner relied on, a patch shows exactly one change in the report, and the guard compares one before and one after.

### D6: The regression guard, and why it runs where it runs

Test cases. Each self-written skill and agent definition has two or three cases in `self_check_case`: a prompt and a rubric of one to three checkable statements (for example "names the invoice number field", "asks before sending"). The first case is the replay case: the typed prompt from the evidence that taught the lesson, with a rubric written from the corrected or final accepted answer. The review writes the cases with the item (an extra `test_cases` argument of `skill_write`, `subagent_definition_write` and the patch tools in a review). When an item has no case, for example after a chat write, the guard asks the review model once to write two cases from the item's description and the request's typed prompt. The owner can list, add, change and delete cases through REST, and an owner case is never replaced by the agent.

A check. For each case, one model call runs the case prompt with the item loaded (the skill body as `Skill` would return it, or the definition body as a run's instructions), with no tools offered, at temperature 0 and at most `guard.max-output-tokens` (default 800). A second call, the judge, gets the rubric and the answer and returns `{"pass": true|false, "failed": [...]}`. A failed case is run once more, and only a second fail counts, because a single judge answer can be noise. No tool is ever executed during a check, so a check has no side effect.

Decision rule. For a new item, it is kept when at least two of its cases pass, or both when it has two. For a changed item, it is kept when every case that passed on the version before still passes on the new version. Results are stored per case and per content hash, so the version before is not run again when its result is already known.

Where it runs:

- A change from a review is checked before it is kept. A failed check refuses the write, nothing goes live, and the review is told why so it can try a smaller patch within its limits.
- A change written during a chat goes live at once, which is the owner decision of `add-agent-skills` and `add-agent-subagents`, and is checked right after on a background thread. A failed check reverts it with a new commit of origin `guard` (made in `add-agent-skills` and `add-agent-subagents`), never by rewriting history, and the revert is reported at once. With several agent instances (answer 87 of 2026-10-08) the change record is written with guard outcome `not_run` in the transaction of the write, and the background thread and the retry task of D9 each claim the check with one conditional update of that row (`check_claimed_at` set to now where the outcome is `not_run` and no claim younger than `review.max-duration` exists, because one check makes at most the few model calls of this section and ends well inside the time a whole review may take) before they run it. So one instance checks a change at a time, and a change whose instance stopped before its check ended is checked by the retry task on any instance.
- When a check cannot run (provider down, quota reached), a review change is not applied and the review row says why. A chat change stays live, is retried by the system task `self-improvement-check-retry` (D9) up to `guard.max-retries` (default 3), and is then reported as `unchecked`.
- An item the guard reverted twice within `guard.freeze-window` (default 7 days) is frozen for agent writes until the window ends, and the freeze is reported.

Cost estimate, for information only, because there is no dollar limit (owner answer 38.3). It is measured from the shipped price table `infra/pricing/pricing.yaml`, which prices each provider's default chat model and is therefore an upper bound for the cheaper review model. One case run is about 2,400 input and 800 output tokens (skill body up to the 8,000 character limit of D10, case prompt, answer), and one judge call about 1,400 input and 60 output tokens. A patch with three cases runs only the new version, because the result of the version before is stored: 11,400 input and 2,580 output tokens. That costs at most $0.073 on `anthropic` (0.003 and 0.015 per 1,000), $0.054 on `openai` (0.0025 and 0.01), $0.0016 on `gemini` and nothing on `lmstudio`. The retry of a failed case adds at most one case pair. Task 4.6 measures the real token counts on the repository fixtures before the defaults ship.

Alternatives considered: no guard, as in Hermes (rejected: the owner asked for one), replaying the whole conversation with real tools (rejected: tools have side effects and outside costs, and a replay of a web search sees a different page), checking chat writes before they go live (rejected: it adds two to six model calls to the user's chat, and it contradicts the owner decision that chat writes go live at once), reverting on any single failed case (rejected: one noisy judge answer would revert a good change).

### D7: Provenance and untrusted sources

This change builds no provenance of its own. `add-agent-soul` defines one `RequestProvenance` value per request (its D15), computed in code from the request itself and never from the model, with the three values `clean`, `retrieved` and `untrusted`, and the `ProvenanceSource` values that lowered it: `retrieved_document` gives `retrieved`, and `attachment`, `peer_bot_turn` of `add-openclaw-plugin-host`, `finished_run_result` (the finished runs block of `add-agent-subagents` added a result of a finished background run, owner decision 49.3 of 2026-10-03) and `outside_tool_result` give `untrusted`. Which tools count as outside content is that value's rule, not this change's. The closed list of trusted tools in `add-agent-soul` D15 names the three tools of this change, `skill_patch`, `subagent_definition_patch` and `request_self_review`, because they return only stored text or a status (owner decision 49.3 of 2026-10-03), so calling one of them never lowers the value. This change has no trusted tools setting of its own, and neither has `add-agent-soul`: the closed list in code of its D15 is the only list (answer 93 of 2026-10-08).

The trigger recorder reads the `request_provenance` holder at the end of the trigger request and stores its value and its `ProvenanceSource` set with the trigger in the review row, and the evidence carries both (D3). `SelfChangeGate` reads the same holder before a chat self-write. This change uses `RequestProvenance` directly, with no mapping and no level type of its own. A review takes the least trusted value of its merged triggers and the union of their source sets, and its run starts at that value, which the review's own tool calls never change (`add-agent-soul` D15).

A call the rules below refuse answers the model with reason `unclean_source`. Rules, fixed in code so configuration cannot loosen them except where named:

| What | `clean` | `retrieved` | `untrusted` |
| :--- | :--- | :--- | :--- |
| Skill or definition, from a review | live | live, marked, reported at once (default of `provenance.review-not-clean`) | live, marked, reported at once (default of `provenance.review-not-clean`) |
| Skill or definition, written during the chat | live | staged (owner answer 38.1) | staged (owner answer 38.1) |
| User fact | live | live | refused (`add-agent-soul` already refuses it during the chat) |
| Semantic memory | live | live | refused |
| Personality proposal | proposed | refused | refused |

Why a review may apply live from an untrusted source: the review never saw the outside text (D3), its change passed the content scan and the guard, and it is marked and reported at once with an undo button. Most useful lessons come from tasks that used tools, so blocking them would stop most of the learning the owner asked for.

Why a chat write after outside content is staged: the chat model has the raw page or document in its context at that moment, which is exactly the injection path. A staged change is submitted to `ApprovalService` as kind `self_change` (made in `add-action-approvals`, its D3 and D9), never rememberable as an allow, and the tool result tells the model the change waits for the owner. Approval applies the stored content through the write path with an `If-Match` stale check. This changes the "live at once" decision of `add-agent-skills` and `add-agent-subagents` for this one case, so it is made there, decided by owner answer 38.1. The setting `provenance.chat-write-untrusted` takes `stage` (the default, owner answer 38.1), `apply` (live, marked, reported at once) or `refuse`.

The setting `provenance.review-not-clean` takes `apply` (default) or `stage`, so the owner can make review changes from a source that is not clean wait for one tap too, without a code change.

Every self-written change from a source that is not `clean` carries `untrusted_source = true` in its record and the trailer `Self-Provenance: retrieved|untrusted` in its commit.

### D8: The content scan

`SelfChangeContentScanner` runs on every self-written skill and definition text, after the owning validator and before the guard, and refuses with reason `content_scan` and the rule name when the text:

- holds an invisible or direction control character, or a reserved marker of `add-agent-soul` (it reuses `SoulTextValidator`'s character and marker checks, not a copy),
- holds a web address or host name that is in neither the user's typed text of the evidence nor the version before,
- holds a run of more than 200 characters of base64 or hex,
- names an environment variable, a secret file path or a credential header (a fixed list: `Authorization`, `api_key`, `API_KEY`, `.env`, `id_rsa`, `password=` and the names of the agent's own secret variables in `.env.example`),
- tells the reader to send, upload or forward data to an address, matched by a short fixed list of verbs next to an address.

It is a narrow check against the most common exfiltration shapes, not a general injection filter, and the design does not claim it is one. Text written by the owner through REST is never scanned.

### D9: Timed work on the shared scheduler

This change brings no scheduler, no `@Scheduled` method, no poll loop, no claim row and no lock. Every timed piece runs on the shared scheduler of `add-shared-scheduler` through that change's registration contract (its D2): each name below is a value of `SchedulerTaskName`, each schedule is a five field cron checked by `CronRule` and evaluated in a named zone, and each handler is safe to run twice (owner decision of 2026-10-02). The inventory of `add-shared-scheduler` D2 lists each of them. Every task bean carries `@ConditionalOnModule("self-improvement")`, so with the module off none is registered.

| Work | Shape on the shared scheduler | Name | Default schedule |
| :--- | :--- | :--- | :--- |
| The review of one conversation | one time execution per review | `self-review/<reviewId>` | the review's `not_before` (D1, D2) |
| The daily review | system task | `self-improvement-review` | `30 3 * * *` in `Europe/Warsaw` |
| The daily review of one tenant, also started through REST | one time execution per tenant | `self-improvement-tenant-review/<tenantId>` | due at once when the daily review or `POST /reviews/run` creates it |
| Retry of guard checks that could not run (D6) | system task | `self-improvement-check-retry` | `0 * * * *` in `Europe/Warsaw` |

Retention is not a task of this change (answer 89.7 of 2026-10-08). This change registers two `RetentionEntry` beans with the one retention task `record-retention` of `add-shared-scheduler` (its D15), which runs on that task's schedule: `self-review` (the table `self_review`, the time column `created_at`, the age `retention.reviews`, default 90 days) and `self-change` (the table `self_change`, the time column `created_at`, the age `retention.changes`, default 365 days). Both entry beans carry `@ConditionalOnModule("self-improvement")` (D16).

The system task schedules live in `app.scheduler.system-tasks.<name>.cron` and `.time-zone`, the keys `add-shared-scheduler` owns. Each `.time-zone` defaults to `${app.self-improvement.zone}` (default `Europe/Warsaw`, the owner's zone, owner decision of 2026-10-02), so the daily review, the check retry and the day of the daily limits (D10) use one zone unless the owner sets a task's zone on purpose.

The daily review creates, for each tenant with the grant for the module `self-improvement` (D12), the execution `self-improvement-tenant-review/<tenantId>` due at once. The execution table's primary key `(task_name, task_instance)` refuses a second one while one is pending or running, and the daily review treats that refusal as already scheduled. This replaces the per tenant per day claim row of the earlier design: the shared scheduler runs the daily task once per due time across instances and restarts, an overdue daily task runs once and then follows its schedule, and the per tenant execution allows at most one daily review of a tenant at a time. The tenant review binds the tenant on the scheduler thread, the way a firing does in `add-scheduled-tasks` D9, and then takes the newest `daily-review.max-conversations` (default 10) conversations of the last day that recorded a lesson but whose review was skipped for limits, in the order of the next day's budget. Each one gets the trigger `periodic` through the same merge as every other trigger (D1) with `not_before` set to now, and its skipped row is marked `requeued` in the same transaction, so a second run of the same day finds nothing to queue.

Reviews that came due while every agent instance was down need no step here, because their own `self-review` executions are overdue and run once at start. The check retry task claims each `not_run` change with the conditional update of D6 before it runs the check, so a second run of the same due time, or the background check of another instance, never checks one change twice. The retention entries delete by age, which is safe to repeat.

### D10: Limits

All under `app.self-improvement.limits`, per tenant and calendar day in `app.self-improvement.zone` (default `Europe/Warsaw`, the owner's zone), counted from the tables with indexed queries. The day starts at local midnight in that zone, computed from the one injected `Clock` of `add-shared-scheduler` D6. Every limit is a count. There is no dollar limit per review or per day (owner answer 38.3):

| Key | Default | Why |
| :--- | :--- | :--- |
| `max-reviews-per-day` | 20 | about one review per busy hour of one owner |
| `max-changes-per-day` | 20 | applied skill, definition, user fact and memory changes together |
| `max-patch-chars` | 2000 | D5 |
| `max-new-skill-chars` | 8000 | a self-written skill is one procedure. The 65,536 byte limit of `add-agent-skills` stays for the owner |
| `max-self-written-skills` | 50 | per tenant, below the 200 skill limit of `add-agent-skills`, so self-written skills can never crowd out the owner's |
| `max-self-written-definitions` | 20 | per tenant, below the 100 definition limit |
| `max-user-fact-changes-per-user-per-day` | 10 | |
| `max-memory-changes-per-user-per-day` | 20 | |

With several agent instances (answer 87 of 2026-10-08) two reviews or a review and a chat write of one tenant can run on two instances at once, so `SelfChangeGate` and the review start count and write in one transaction under a Postgres transaction advisory lock keyed by the tenant (and by the tenant and the user for the per user limits), and never from a counter in memory. A refused call answers the model with the limit's name, and the first refusal of a day is reported at once. Usage is recorded through `UsageEventPort` of `add-deployment-modules`: the run loop of `add-agent-subagents` records the model calls of a review run with the request type `self-review` of its kind mapping, and this change records each guard call as one `UsageEvent` of request type `self-check`. The run loop asks `QuotaGate` of `add-deployment-modules` before each model call of a review run, and this change asks it before each guard call. `add-usage-metering-and-quotas` (company, build group 5) registers its ledger behind `UsageEventPort` and its quota gate behind `QuotaGate` later (request types made there).

### D11: The change record and the report

`self_change` holds one row per self-written change, staged change, guard revert, refused change of a review and integration event: tenant, user (only for user facts and memories), review id, request id, conversation id, type (`skill`, `subagent_definition`, `user_fact`, `memory`, `personality_proposal`, `integration`), operation (`create`, `patch`, `update`, `add`, `replace`, `remove`, `propose`, `guard_revert`, `register`, `activate`, `disable`, `auto_disable`, and `update` is also the operation of an integration update), target name, commit id and the commit id before it, memory id and memory text (for undo of a removed memory), proposal id, approval id, integration id and version, reason, trigger kinds, provenance (the `RequestProvenance` value of D7, null when no request is behind the change), guard outcome (`passed`, `failed`, `not_run`, `unchecked`, `not_applicable`), status (`kept`, `staged`, `reverted_by_guard`, `undone`, `refused`), size before and after, check retry count, the claim time `check_claimed_at` of D6, created and reported times, and the id of the owner notification that first reported it. There is no seen time (answer 89.6 of 2026-10-08): the only seen marker is `read_at` of the owner notification that reported the change to a user (D14).

The report shows per change:

- what: type, name, operation, size before and after, and the unified diff for skills, definitions and user facts,
- why: the reason the agent gave,
- trigger: the trigger kinds, the conversation id and the time,
- check: the guard outcome and the failed rubric lines when it failed,
- mark: `untrusted source` when the source was not clean,
- undo: the button, and the command `curl -X POST <base>/api/v1/self-improvement/changes/<id>/undo` with the caller's authentication.

Integration events (asked by `add-self-built-integrations`, which calls these seams in its D26). `add-self-built-integrations` lands after this change, so this change offers it two seams and depends on nothing of it: `SelfChangeRecorder.recordIntegrationEvent(...)`, which that change calls after commit when an integration is registered (its first version goes active), activated (a version that waited for the owner's approvals goes active), updated (a new version replaces the active one at once), disabled by the model through `integration_disable`, or disabled automatically by its failure rule, and the undo handler port of D13, which that change implements for type `integration`. Each event becomes one `self_change` row of type `integration` with the operation `register`, `activate`, `update`, `disable` or `auto_disable`, the integration id and version, the reason text that change gives, status `kept`, guard outcome `not_applicable`, and the `RequestProvenance` value of the request that started the action, or null for an automatic disable. These rows pass no gate, scan, guard or limit of this change, because the integration change has its own owner gates, and they do not count toward `max-changes-per-day`. They are reported like every other change, with kind `alert` for `auto_disable` and `change` for the others. With the module `self-improvement` off, the recorder bean does not exist and that change records nothing. The two seams are, by these exact names: `SelfChangeRecorder.recordIntegrationEvent(...)` with the five events `register`, `activate`, `update`, `disable` and `auto_disable`, and one `SelfChangeUndoHandler` bean with `type()` returning `integration`, provided by `add-self-built-integrations` and registered only while the module `self-improvement` is active, because the undo endpoint and its dispatch exist only then.

When (owner answer 38.2): every report is created and sent at once, in the same transaction as the event it reports, because the owner's app may not run at a fixed hour, so a report waiting for a fixed time could be missed or arrive late. There is no daily digest and no report system task. A report is sent for each change record that reaches `kept`, `staged` or `reverted_by_guard`, for a chat change whose check ends `unchecked`, for a freeze, and for the first limit refusal of a day. A change a review tried and the gate refused (status `refused`) writes nothing live and sends no report, and it stays readable through `GET /api/v1/self-improvement/changes`. The kind is `alert` for a staged change, a guard revert, a change from a source that is not clean, an `unchecked` change, a freeze and a limit refusal, and `change` for every other kept change. Self-written skills and definitions with no use in `stats.unused-after` (default 30 days) are listed by `GET /api/v1/self-improvement/stats` (D14) with a delete link, not in a report.

How: this change has no report port, no adapter and no delivery code of its own. A report is an owner notification of `add-shared-scheduler`. `SelfImprovementReporter` builds the text and calls `OwnerNotificationService.create(...)` once for each `ADMIN` of the tenant, because a notification is addressed to one user. The notification has source `self_improvement`, kind `change` or `alert`, a fixed title (`I changed something` or `I changed something that needs a look`), the report text as the body, and the id of the reported change in `subject_ids`. In the same transaction the reported rows get `reported_at` and the notification id. The notification service offers it, in the same transaction, to every switched on channel of the port `OwnerNotificationChannel` that can reach the user, and each channel accepts it into its own queue, which is the one retry layer (for Discord the `channel_outbox` of `add-openclaw-plugin-host`, owner answer 89.6 of 2026-10-08). So:

- The report is always readable through `GET /api/v1/notifications` of `add-shared-scheduler`, and each change stays readable with its full diff through `GET /api/v1/self-improvement/changes/{id}` (D14). A body above the notification limit of 4,000 characters is cut with the visible note of `add-shared-scheduler`, and the note points at `GET /api/v1/self-improvement/changes`.
- Discord delivery is the `discord` channel that `add-openclaw-plugin-host` implements for that port. The report notification carries one entry of action type `self_improvement_undo` per id in `subject_ids` in its `actions` list (`add-shared-scheduler` D7 and D8), so the channel renders one Undo button per changed record. This change registers the `ChannelActionHandler` bean of `add-shared-scheduler` for the action type `self_improvement_undo`. A press reaches the one action endpoint `POST /api/v1/channel-host/actions` of `add-openclaw-plugin-host`, which resolves the presser through the channel link, binds the tenant of the outbox row and calls the handler with the change id from the button. The handler checks `ADMIN` of the change's tenant and calls `SelfImprovementService.undo(changeId, identity, channel)` in process as the linked user with channel `discord` (D13). This change adds no endpoint, no host namespace and no host code for the button (owner answer 89.6 of 2026-10-08). The namespace `ascend-notify`, the custom id `ascend-notify:<outbox id>:<index>` and `POST /api/v1/channel-host/notifications/actions` are gone.
- The app shows the notification in the notification list that `add-shared-scheduler` asks `add-flutter-chat-app` for, and the "What I learned" screen reads this change's REST (made there, its D11).
- A failed delivery on one channel never stops another, because each channel has its own delivery row and retry.

The `ADMIN` users of a tenant come from an offline lookup that `add-keycloak-login` provides next to the offline identity resolution `add-scheduled-tasks` already asks it for (made there, its D20 and task 3.8). In a personal deployment every user is in tenant `default`.

### D12: Tenant scoping and the module

Every row carries `tenant_id VARCHAR(64) NOT NULL` from `TenantContext.currentTenantId()` of `add-keycloak-login` (`default` in the personal deployment), and every query filters on it. The scheduler threads of `self-review/<reviewId>`, `self-improvement-tenant-review/<tenantId>` and the system tasks bind the row's tenant with `TenantContext.runAs` before any other step, and the review run binds the tenant on its thread like a subagent run does. With no tenant bound, the accessor throws and the work stops (fail closed).

Foreign keys: the migration `V<n>__create_self_improvement.sql` adds no foreign key to `tenants(id)`. `add-tenant-isolation` (company, build group 5) creates the `tenants` table and adds the foreign keys from `self_review.tenant_id`, `self_change.tenant_id`, `self_check_case.tenant_id` and `self_capability_use.tenant_id` in its own migration later (dependency fix of 2026-10-05). The owner decision of 2026-10-03 that put them in this migration is kept as a record (superseded by the owner build order of 2026-10-04). The migration adds the one foreign key between its own tables, `self_change.review_id` to `self_review(id)` `ON DELETE SET NULL`, because a review is deleted after 90 days while its change records stay 365 days (D16). The ids that point into other changes' rows (commit ids, memory id, proposal id, approval id, integration id, notification id) stay plain values without a foreign key, because those rows follow the retention and erasure of their own changes, and the change record must outlive them for the report and the audit trail. Every constraint and index is named. The same migration adds this change's notification pairs to the owner notification store of `add-shared-scheduler` (answer 93 of 2026-10-08, review item S3-8), which keeps the allowed pairs in the table `owner_notification_kind (source, kind)` referred to by the foreign key `owner_notification_kind_fk`: `INSERT INTO owner_notification_kind (source, kind) VALUES ('self_improvement', 'change'), ('self_improvement', 'alert') ON CONFLICT DO NOTHING`. User facts and memory changes act only on the user of the reviewed conversation. A tenant never sees another tenant's changes, cases or reviews.

The module: the whole feature is the catalog entry `self-improvement` of `add-deployment-modules`, which requires `subagents`. Every bean of this change carries `@ConditionalOnModule("self-improvement")`. There is no `app.self-improvement.enabled` flag and no per tenant flag of this change: the deployment switches the module on with `ASCEND_MODULES`, and a tenant uses it only with the tenant module grant of `add-deployment-modules`. The new tools are offered through the tool policy port `TenantToolPolicy` of `add-agent-subagents`, whose default allows every tool. `add-tenant-policy` (company, build group 5) registers later its implementation with the allow-list entries `request_self_review`, `skill_patch` and `subagent_definition_patch` (made there, its D2). With the module off, none of the new tools is offered, no trigger is recorded, no execution is created, no task of D9 is registered, and the earlier write tools work as their own changes define. A tenant without the grant gets no trigger, no review and no daily review.

### D13: Undo

`POST /api/v1/self-improvement/changes/{id}/undo`, `ADMIN` only, and the same undo in process as `SelfImprovementService.undo(changeId, identity, channel)` (required edit asked by `add-openclaw-plugin-host`, its D12): the REST endpoint calls it with the caller's identity and channel `rest`, and the plugin host calls it for a Discord Undo press with the identity resolved from the linked account and channel `discord`. The method checks that the identity has the `ADMIN` role in the change's tenant before anything else, with the same refusals as REST, and the channel goes into the audit event of the undo. Undo dispatches on the record's type to one `SelfChangeUndoHandler` bean (`type()`, `undo(change, identity)`). This change provides the handlers of its own types, and `add-self-built-integrations` provides the one of type `integration`:

| Type | Undo |
| :--- | :--- |
| skill, definition | revert to the commit before the change through the owning revert path, origin `owner`, only when the change is still the newest commit of that item, else 409 `newer_change_exists` naming the newer change ids, newest first |
| user fact | revert `USER.md` to the commit before through the user facts revert path, same newest rule |
| memory added | delete the memory id |
| memory removed | insert the stored text again |
| personality proposal | deny the pending approval, or revert the applied commit through the personality revert path |
| staged change | deny the pending approval |
| integration `register` or `activate` | disable the integration through its disable path, only when no newer integration record of that integration exists, else 409 `newer_change_exists` |
| integration `update` | roll the integration back to its previous version through its rollback path, same newest rule |
| integration `disable` or `auto_disable` | enable the integration through its enable path, same newest rule |

Undo is idempotent: a second call on an `undone` change answers 409 `already_undone`. An undone skill or definition counts as an owner commit, so the agent cannot change it again without the owner, the protection rule `add-agent-skills` already has.

### D14: REST

`SelfImprovementController` under `/api/v1/self-improvement`, `ADMIN` only, in the style of `SkillController`, every error an RFC 7807 problem detail of `upgrade-spring-boot-4` with codes added to `ApiErrorCode`:

- `GET /changes` (filters `since`, `type`, `status`, `unseen`, cursor page), `GET /changes/{id}` (with diff), `POST /changes/{id}/undo`. `unseen=true` keeps a change while the caller's own report notification of it (source `self_improvement`, the change id in `subject_ids`) has no `read_at`. There is no `POST /changes/seen`: a client marks a report as seen with `POST /api/v1/notifications/{id}/read` of `add-shared-scheduler`, so the notification `read_at` is the one seen marker (answer 89.6 of 2026-10-08).
- `GET /reviews`, `GET /reviews/{id}` (status, triggers, provenance, cost, skip reason, never the evidence), `POST /reviews/run` (creates the execution `self-improvement-tenant-review/<tenantId>` for the caller's tenant due at once and answers 202, 409 `job_running` when that execution is already pending or running)
- `GET /cases?type=&name=`, `POST /cases`, `PUT /cases/{id}`, `DELETE /cases/{id}`
- `GET /stats` (per type: written, kept, reverted by the guard, undone by the owner, used afterwards, unused for `stats.unused-after`, with the names of the unused self-written items and a delete link for each)

Role rules. `add-keycloak-login` lands before this change and says that a later change adds its own rows to its authorization matrix (its D4), with a security slice test per row, and its coverage test `SecurityMatrixCoverageTest` fails the build for an endpoint with no row. This change adds these rows to that matrix in `SecurityConfig`, written the same way:

| Path | Rule |
|---|---|
| `GET /api/v1/self-improvement/changes`, `GET /api/v1/self-improvement/changes/*`, `POST /api/v1/self-improvement/changes/*/undo` (`add-self-improvement`) | tenant `ADMIN` only |
| `GET /api/v1/self-improvement/reviews`, `GET /api/v1/self-improvement/reviews/*`, `POST /api/v1/self-improvement/reviews/run` (`add-self-improvement`) | tenant `ADMIN` only |
| `/api/v1/self-improvement/cases/**`, `GET /api/v1/self-improvement/stats` (`add-self-improvement`) | tenant `ADMIN` only |

The Discord Undo press reaches the agent through `POST /api/v1/channel-host/actions` of `add-openclaw-plugin-host` under its `/api/v1/channel-host/**` row with the scope `channel.relay`, and `SelfImprovementService.undo` checks `ADMIN` of the change's tenant again itself (D13). This change adds no agent endpoint for it. The controller scopes every call to the caller's tenant.

### D15: Use afterwards

`self_capability_use` counts uses of self-written items per tenant: `use_count` and `last_used_at`. A `Skill` load is reported by a `SkillUsedEvent` that this change publishes from the `Skill` function of `add-agent-skills` (moved here by answer 93 of 2026-10-08, because this change is its only listener), a definition start by the existing `SubagentRunChangedEvent`. Only items with a `self_change` row are counted. These counts feed `/stats` with its unused list and the metric of D17.

### D16: Audit, erasure, export and retention

Audit events are recorded through `AuditEventPort` of `add-deployment-modules`, whose default writes one structured INFO log line, and `add-audit-and-gdpr-compliance` (company, build group 5) registers its implementation later. The actions are `SELF_IMPROVEMENT_REVIEWED`, `SELF_IMPROVEMENT_CHANGED`, `SELF_IMPROVEMENT_STAGED`, `SELF_IMPROVEMENT_GUARD_REVERTED`, `SELF_IMPROVEMENT_FROZEN`, `SELF_IMPROVEMENT_UNDONE` and `SELF_IMPROVEMENT_CASE_WRITTEN`, in the one naming style of `add-audit-and-gdpr-compliance` D3 (actor `agent` or the owner, tenant, resource type and name, outcome, review id, request id, and for an undo the channel `rest` or `discord`, never content). Erasure and export are added by `add-audit-and-gdpr-compliance` later, which owns them (dependency fix of 2026-10-05): per user erasure deletes the user's `self_review` rows and, in `self_change`, clears the memory text and replaces the reason with a fixed erased text in that user's rows, tenant erasure deletes all four tables' rows of the tenant, and tenant export adds `self_change` and `self_check_case` as JSON. Retention: `self_review` rows 90 days, `self_change` rows 365 days (`retention.reviews`, `retention.changes`), deleted by the shared retention task `record-retention` of `add-shared-scheduler` through two entries this change registers with `@ConditionalOnModule("self-improvement")`: `self-review` (table `self_review`, its creation time column, age `retention.reviews`, default 90 days) and `self-change` (table `self_change`, its creation time column, age `retention.changes`, default 365 days) (D9, owner answer 89.7 of 2026-10-08). The owner notifications that carried the reports follow the notification retention of `add-shared-scheduler` (30 days) and its erasure and export, so this change adds nothing for them.

### D17: Metrics and logs

Names follow `add-observability` D2 and D5, domain first, dotted and lower case, as `add-agent-skills` D14 does, with no tenant tag. The domain segment is `improvement`, one word, because an underscore in the domain (`self_improvement.`) turns into `self_improvement_` in Prometheus and reads as two domains:

| Metric | Type | Tags |
| :--- | :--- | :--- |
| `improvement.trigger` | counter | `kind` |
| `improvement.review` | timer | `outcome` (`done`, `skipped`, `failed`, `cancelled`) |
| `improvement.change` | counter | `type`, `operation`, `status` |
| `improvement.guard` | timer | `path` (`review`, `chat`), `outcome` |
| `improvement.undo` | counter | `type` |
| `improvement.use` | counter | `type` |
| `improvement.check.cost.usd` | counter | none |

`improvement.check.cost.usd` measures the cost of the guard checks and never limits it (owner answer 38.3). The cost of a review run is not counted again here: it is the run cost counter `subagent.cost.usd` of `add-agent-subagents`, which counts every model call of the run loop, the `self_review` runs included, and the review's own row and `GET /reviews/{id}` carry it (answer 93 of 2026-10-08).

Log lines: one INFO per trigger (kind, conversation id, request id) and per review end (review id, outcome, changes, cost, duration), and one WARN per guard revert, freeze and limit refusal. A change and an undo write no log line of their own, because their audit events (D16) already are one structured INFO line through the default `LogAuditEventPort` of `add-deployment-modules` (answer 93 of 2026-10-08). The audit event of a change carries the change id, type, name, status and provenance for that reason. Content, evidence, reasons and diffs never reach a log line or a metric. `StartupLogConfig` gains one block, only when the module is active, with the review model per provider, the limits and the zone. The schedules of the system tasks and the switched on notification channels are already in the scheduler block of `add-shared-scheduler` D12, so they are not repeated.

### D18: Configuration

```yaml
app:
  self-improvement:
    zone: Europe/Warsaw
    triggers:
      min-tool-steps: 4
    review:
      quiet-period: 10m
      max-concurrent: 1
      max-model-calls: 8
      max-duration: 5m
      max-changes: 5
      evidence-max-turns: 3
      evidence-max-chars: 16000
      evidence-max-argument-chars: 500
      model: {}
    guard:
      max-output-tokens: 800
      max-retries: 3
      freeze-window: 7d
    provenance:
      chat-write-untrusted: stage
      review-not-clean: apply
    limits:
      max-reviews-per-day: 20
      max-changes-per-day: 20
      max-patch-chars: 2000
      max-new-skill-chars: 8000
      max-self-written-skills: 50
      max-self-written-definitions: 20
      max-user-fact-changes-per-user-per-day: 10
      max-memory-changes-per-user-per-day: 20
    daily-review:
      max-conversations: 10
    stats:
      unused-after: 30d
    retention:
      reviews: 90d
      changes: 365d
  scheduler:
    system-tasks:
      self-improvement-review:
        cron: "30 3 * * *"
        time-zone: ${app.self-improvement.zone}
      self-improvement-check-retry:
        cron: "0 * * * *"
        time-zone: ${app.self-improvement.zone}
```

The `app.scheduler.system-tasks` keys belong to `add-shared-scheduler`, which binds and checks them (five field cron and known zone through `CronRule`, startup refusal for a missing key). This change only adds the defaults of its two system tasks. `retention.reviews` and `retention.changes` are the ages of its two entries `self-review` and `self-change` in the one retention task `record-retention` of `add-shared-scheduler`, which owns that task's schedule. There is no `enabled` key and no dollar limit key. `review.model` empty means the provider's compaction default. `SelfImprovementProperties` refuses zero or negative values, a `max-new-skill-chars` above `app.skills.limits.max-skill-bytes`, a `max-self-written-skills` at or above `app.skills.limits.max-skills`, a `chat-write-untrusted` value outside the three, a `review-not-clean` value other than `apply` or `stage`, and a `zone` that `CronRule` does not accept. `SelfImprovementProperties` and every bean of this change exist only when the module `self-improvement` is active (D12).

Every value with a default is a setting (owner rule 98 of 2026-10-08): `application.yaml` writes each key above as `key: ${ENV:default}`, `SelfImprovementProperties` carries the same default in code, and the `ascend-agent` service of `compose.yaml` writes `- ENV=${ENV:-default}`. The environment variable is Spring Boot's canonical form of the property:

| Property | Environment variable | Default |
| :--- | :--- | :--- |
| `app.self-improvement.zone` | `APP_SELFIMPROVEMENT_ZONE` | `Europe/Warsaw` |
| `app.self-improvement.triggers.min-tool-steps` | `APP_SELFIMPROVEMENT_TRIGGERS_MINTOOLSTEPS` | `4` |
| `app.self-improvement.review.quiet-period` | `APP_SELFIMPROVEMENT_REVIEW_QUIETPERIOD` | `10m` |
| `app.self-improvement.review.max-concurrent` | `APP_SELFIMPROVEMENT_REVIEW_MAXCONCURRENT` | `1` |
| `app.self-improvement.review.max-model-calls` | `APP_SELFIMPROVEMENT_REVIEW_MAXMODELCALLS` | `8` |
| `app.self-improvement.review.max-duration` | `APP_SELFIMPROVEMENT_REVIEW_MAXDURATION` | `5m` |
| `app.self-improvement.review.max-changes` | `APP_SELFIMPROVEMENT_REVIEW_MAXCHANGES` | `5` |
| `app.self-improvement.review.evidence-max-turns` | `APP_SELFIMPROVEMENT_REVIEW_EVIDENCEMAXTURNS` | `3` |
| `app.self-improvement.review.evidence-max-chars` | `APP_SELFIMPROVEMENT_REVIEW_EVIDENCEMAXCHARS` | `16000` |
| `app.self-improvement.review.evidence-max-argument-chars` | `APP_SELFIMPROVEMENT_REVIEW_EVIDENCEMAXARGUMENTCHARS` | `500` |
| `app.self-improvement.review.model.<provider>` | `APP_SELFIMPROVEMENT_REVIEW_MODEL_<PROVIDER>`, one per provider of the agent (`OPENAI`, `ANTHROPIC`, `GEMINI`, `MINIMAX`, `LMSTUDIO`) | empty, which means the provider's compaction default. A blank value counts as empty |
| `app.self-improvement.guard.max-output-tokens` | `APP_SELFIMPROVEMENT_GUARD_MAXOUTPUTTOKENS` | `800` |
| `app.self-improvement.guard.max-retries` | `APP_SELFIMPROVEMENT_GUARD_MAXRETRIES` | `3` |
| `app.self-improvement.guard.freeze-window` | `APP_SELFIMPROVEMENT_GUARD_FREEZEWINDOW` | `7d` |
| `app.self-improvement.provenance.chat-write-untrusted` | `APP_SELFIMPROVEMENT_PROVENANCE_CHATWRITEUNTRUSTED` | `stage` |
| `app.self-improvement.provenance.review-not-clean` | `APP_SELFIMPROVEMENT_PROVENANCE_REVIEWNOTCLEAN` | `apply` |
| `app.self-improvement.limits.max-reviews-per-day` | `APP_SELFIMPROVEMENT_LIMITS_MAXREVIEWSPERDAY` | `20` |
| `app.self-improvement.limits.max-changes-per-day` | `APP_SELFIMPROVEMENT_LIMITS_MAXCHANGESPERDAY` | `20` |
| `app.self-improvement.limits.max-patch-chars` | `APP_SELFIMPROVEMENT_LIMITS_MAXPATCHCHARS` | `2000` |
| `app.self-improvement.limits.max-new-skill-chars` | `APP_SELFIMPROVEMENT_LIMITS_MAXNEWSKILLCHARS` | `8000` |
| `app.self-improvement.limits.max-self-written-skills` | `APP_SELFIMPROVEMENT_LIMITS_MAXSELFWRITTENSKILLS` | `50` |
| `app.self-improvement.limits.max-self-written-definitions` | `APP_SELFIMPROVEMENT_LIMITS_MAXSELFWRITTENDEFINITIONS` | `20` |
| `app.self-improvement.limits.max-user-fact-changes-per-user-per-day` | `APP_SELFIMPROVEMENT_LIMITS_MAXUSERFACTCHANGESPERUSERPERDAY` | `10` |
| `app.self-improvement.limits.max-memory-changes-per-user-per-day` | `APP_SELFIMPROVEMENT_LIMITS_MAXMEMORYCHANGESPERUSERPERDAY` | `20` |
| `app.self-improvement.daily-review.max-conversations` | `APP_SELFIMPROVEMENT_DAILYREVIEW_MAXCONVERSATIONS` | `10` |
| `app.self-improvement.stats.unused-after` | `APP_SELFIMPROVEMENT_STATS_UNUSEDAFTER` | `30d` |
| `app.self-improvement.retention.reviews` | `APP_SELFIMPROVEMENT_RETENTION_REVIEWS` | `90d` |
| `app.self-improvement.retention.changes` | `APP_SELFIMPROVEMENT_RETENTION_CHANGES` | `365d` |
| `app.scheduler.system-tasks.self-improvement-review.cron` | `APP_SCHEDULER_SYSTEMTASKS_SELFIMPROVEMENTREVIEW_CRON` | `30 3 * * *` |
| `app.scheduler.system-tasks.self-improvement-review.time-zone` | `APP_SCHEDULER_SYSTEMTASKS_SELFIMPROVEMENTREVIEW_TIMEZONE` | `${app.self-improvement.zone}` |
| `app.scheduler.system-tasks.self-improvement-check-retry.cron` | `APP_SCHEDULER_SYSTEMTASKS_SELFIMPROVEMENTCHECKRETRY_CRON` | `0 * * * *` |
| `app.scheduler.system-tasks.self-improvement-check-retry.time-zone` | `APP_SCHEDULER_SYSTEMTASKS_SELFIMPROVEMENTCHECKRETRY_TIMEZONE` | `${app.self-improvement.zone}` |

The two task zones stay derived from the zone: `application.yaml` writes `${APP_SCHEDULER_SYSTEMTASKS_SELFIMPROVEMENTREVIEW_TIMEZONE:${app.self-improvement.zone}}`, and the compose line nests the zone's variable, `- APP_SCHEDULER_SYSTEMTASKS_SELFIMPROVEMENTREVIEW_TIMEZONE=${APP_SCHEDULER_SYSTEMTASKS_SELFIMPROVEMENTREVIEW_TIMEZONE:-${APP_SELFIMPROVEMENT_ZONE:-Europe/Warsaw}}`, the same for the check retry task, so both follow `APP_SELFIMPROVEMENT_ZONE` unless the owner sets a task's zone on purpose. The two cron values are quoted in the compose lines, because they hold spaces and `*`. No `.env.example` line is added. The rows of every setting of this table go into `apps/ascend-agent/docs/CONFIGURATION.md` (task 8.4).

Values that stay constants, because they are not operational: the 300 character caps of a `lesson` and a `reason` argument (part of the fixed tool definitions, whose bytes must not change between requests for the prompt cache), the content scan rules of D8, the 200 character run of base64 or hex among them (security rules that configuration must not loosen, as D7 says of its own rules), the guard's temperature 0, its one confirming rerun and its keep rules of D6 (decision rules, not tuning), the startup refusals above, which compare with the limits of `add-agent-skills`, and every task name, retention entry name, notification source and kind, error code, metric name and enum value. The cost estimate of D6 is information, not a value the code reads.

## Risks / Trade-offs

- [A review applies a change from an untrusted source that the scan and the guard miss] → The review never saw the outside text, the change is marked and reported at once with an undo button, and `provenance.review-not-clean: stage` makes such changes wait for one tap. Residual risk accepted for autonomy.
- [The judge model is noisy and reverts a good change, or keeps a bad one] → Temperature 0, a confirming rerun before a fail counts, a comparison against the version before instead of an absolute score, the freeze after two reverts, and the owner can edit the cases.
- [Reviews cost money every day, and there is no dollar limit] → Count limits bound the work: at most 20 reviews per tenant and day, 8 model calls per review, 5 writes per review and 20 applied changes per day, plus `QuotaGate`, whose real implementation `add-usage-metering-and-quotas` (company) registers later, the cheap model, and no review without a trigger. `improvement.check.cost.usd`, the run cost counter `subagent.cost.usd` and the usage ledger show the cost, so the owner can add a dollar limit later if he wants one (owner answer 38.3).
- [Self-written skills crowd the index and the search] → A cap of 50 per tenant, the unused list, and patches instead of near duplicates because the review searches first.
- [A lesson is wrong and spreads to every user of the tenant] → Report, undo, guard, and the owner case editing. A wrong user fact reaches only one user.
- [The review sees only typed text and tool names, so it misses lessons hidden in tool results] → Accepted. The arguments the model sent and the ok or error status carry most of a working path, and the safety gain is large.
- [Staging chat writes after a tool ran asks the owner more often] → Only for writes the user asked for during the chat, which the prompt now discourages. The review path stays automatic.
- [A timed task runs twice, after the shared scheduler revives a dead execution] → Every handler of D9 acts only on rows in a state it then changes in the same transaction (a review moves from `pending`, a check from `not_run`, a skipped review to `requeued`, a reported change gets `reported_at`), so a second run does no work twice.
- [A report per change can be many messages on a busy day] → At most 20 applied changes per tenant and day, so at most about 20 reports plus a few alerts. The owner decided that real time reports matter more than fewer messages (owner answer 38.2).
- [`add-shared-scheduler` is late] → This change cannot ship before it. It is build group 3, position 7 of the owner build order of 2026-10-04 and lands earlier, and nothing here builds a stopgap scheduler or report path.
- [The quiet period delays learning by ten minutes] → Accepted, a lesson is for future conversations.

## Required edits to other changes

This change does not edit the changes below. Each edit was asked of the named change, and every one of them is now made there, checked on 2026-10-03 and noted in its row. A task here that uses an edit of an earlier change uses it as applied, and tasks.md names that change. An edit that a later change or a company change carries is that change's own work, and no task here waits for it (owner rule of 2026-10-04, dependency fix of 2026-10-05).

| Change | Required edit |
| :--- | :--- |
| `add-agent-skills` | Made in that change, checked on 2026-10-03 (its D3, D6, D8, D9, D14, its Non-Goals and its row for this change). D3 (`ChatToolset`): wrap the self-write tools in `SelfChangeGate` after the policy filter and before the approval wrapper. D6 and D8: accept the extra trailers `Skill-Reason`, `Skill-Patch`, `Skill-Self-Change-Id` and `Self-Provenance` from the caller, add origin `guard` for the guard's revert (offered to no tool), and let the agent update a skill whose newest origin is `agent` or `guard`. D9: `skill_write` gains the optional argument `reason` (at most 300 characters). D14: publish `SkillUsedEvent(tenant, name, requestId)` on each successful `Skill` load (since answer 93 of 2026-10-08 published by this change, task 6.4). The "live at once" rule gains one exception: a chat write after outside content follows `app.self-improvement.provenance.chat-write-untrusted`, default `stage` (owner answer 38.1). Its Non-Goals line on deciding when to write names this change as decided. `add-agent-skills` lands earlier (build group 4, position 1), so step 4 of its `ChatToolset` (the `SelfChangeGate` wrap) moved here from its task 10.8 by the dependency fix of 2026-10-05 and is this change's task 3.4. |
| `add-agent-subagents` | Made in that change, checked on 2026-10-03 (its D4, D6, D7, D9, D10, D13 and its row for this change). D13: for its run kind `self_review`, the fixed tool set of this change, no definition, no caller, no parent, no cost limit (owner answer 38.3, the cost is still counted and recorded), and never listed in a conversation's finished runs block. D9: the computed tool set and the exclusion of `subagent_definition_write` apply to kind `subagent` only, and in a `self_review` run the subset rule of agent definitions is checked against the tools the reviewed request had, read from the evidence. D4: origin `guard` for the guard's revert, the commit trailers `reason` and `self-change`, and `subagent_definition_write` gains the optional argument `reason`. D7: the same chat write exception as skills. `add-agent-subagents` lands earlier (build group 4, position 2), so the wiring of the gate into subagent definitions moved here from its task 3.11 by the dependency fix of 2026-10-05 and is this change's task 3.8. |
| `add-agent-soul` | Made in that change on 2026-10-02 and checked on 2026-10-03 (its D8, D9, D15 and its row for this change). D8 and D9: the run kind `self_review` is the one documented exception, owned by this change, to its rule that `user_facts_update` and `personality_propose` are never offered to background runs. Both may be offered to a `self_review` run, and to no other background run kind. There the `RequestProvenance` rule is evaluated on the review's recorded value (user facts: `clean` or `retrieved`, personality: `clean` only) instead of on the run's own tool calls, and the `ADMIN` caller check is replaced by the tenant's grant for the module `self-improvement`, because the review has no caller and the proposal still waits for the owner. Both tools gain the optional argument `reason`, stored in the `Soul-Reason` trailer and on the proposal row. D15: one `RequestProvenance` value per request with the values `clean`, `retrieved` and `untrusted` and the `ProvenanceSource` set, which this change reads from the `request_provenance` holder and builds none of its own (D7). `retrieved_document` gives `retrieved`, so a review can tell it from `untrusted`, and `finished_run_result` gives `untrusted` (owner decision 49.3). Its closed list of trusted tools names `skill_patch`, `subagent_definition_patch` and `request_self_review` of this change, and that closed list replaces a trusted tools setting of this change (answer 93 of 2026-10-08 removed the setting `app.soul.provenance.trusted-tools` there). `add-agent-soul` lands earlier (build group 4, position 4), so the two `self_review` checks of its tools moved here from its task 5.3 by the dependency fix of 2026-10-05 and are this change's task 3.7. |
| `add-action-approvals` | Made in that change, checked on 2026-10-03 (its D3, D9 and its list of kinds other changes register). D3: register kind `self_change` with category `self_change`, never rememberable as an allow, rememberable as a deny, preview the unified diff, execute the stored write through the owning write path with its stale check, and deny or expiry marking the change `refused`. D9 table: add the category row. |
| `add-tenant-policy` | Company, build group 5, registers its `TenantToolPolicy` implementation (the port of `add-agent-subagents`) later, and no task here waits for it. Made in that change, checked on 2026-10-03 (its D2 tool table). Add the tool allow-list entries `request_self_review`, `skill_patch` and `subagent_definition_patch` (off for a new tenant, on in the deployment default policy). The per tenant switch is the tenant module grant of `add-deployment-modules`, not a flag of this change. |
| `add-shared-scheduler` | Its inventory (D2) lists, with owning change `add-self-improvement` and home shared, the one time executions `self-review/<reviewId>` and `self-improvement-tenant-review/<tenantId>` and the system tasks `self-improvement-review` and `self-improvement-check-retry` (the system task `self-improvement-retention` is replaced by the entries `self-review` and `self-change` of its one retention task `record-retention`, answer 89.7 of 2026-10-08). Its `owner_notification` table and `owner-notifications` spec allow source `self_improvement` with the kinds `change` and `alert` (since answer 93 of 2026-10-08 this change inserts the two pairs into its table `owner_notification_kind` in its own migration, D12), a fixed title of the source, the `subject_ids` column in the table and the notification view, and a cut body note that points at `GET /api/v1/self-improvement/changes`, and `notification.created` has the tags `source` and `kind`. Made in that change on 2026-10-02, so both sides agree. The `SchedulerTaskName` values and handlers are added by this change under the registration contract. |
| `add-deployment-modules` | Its catalog entry `self-improvement` requires `subagents`, and its required edit to this change removes `app.self-improvement.enabled` and the per tenant flag. Made in this change on 2026-10-02 (D12), so no further edit is needed. |
| `add-keycloak-login` (split out of `add-auth-and-identity` on 2026-10-04) | Made in that change, checked on 2026-10-04 (its D20, its task 3.8, its D4 table of later changes and its `user-identity` spec). Its matrix leaves the rows of this change's endpoints to this change, which adds them (D14). Next to the offline identity resolution that `add-scheduled-tasks` asks for: an offline lookup of the enabled users with the `ADMIN` role of a tenant, with no token, so a report reaches each of them (D11). It lands before this change (build group 3), so this change uses that lookup from its first day. |
| `add-tenant-isolation` | Company, build group 5, lands after this change, and no task here waits for it. Made in that change, checked on 2026-10-03 (its decisions 13 and 14 and `specs/tenant-isolation/spec.md`). Its decision 14 states the rule of the owner decision of 2026-10-03 that a change landing after it adds its own foreign keys (superseded by the owner build order of 2026-10-04): this change lands first, so that change adds the foreign keys of `self_review`, `self_change`, `self_check_case` and `self_capability_use` to `tenants(id)` in its own migration and carries the cross tenant check (D12, its inbox files of the dependency fix of 2026-10-05). The four tables carry `tenant_id`, and `TenantContext` of `add-keycloak-login` fails closed for them. The scheduler threads of `self-review/<reviewId>` and `self-improvement-tenant-review/<tenantId>` bind the row's tenant with `TenantContext.runAs` before any other step and fail closed when they cannot, which this change already does (D12). |
| `add-usage-metering-and-quotas` | Company, build group 5, registers its ledger behind `UsageEventPort` and its quota gate behind `QuotaGate` of `add-deployment-modules` later, and no task here waits for it (D10). Made in that change, checked on 2026-10-03 (its request type table, its run quota rule and its `quota-enforcement` spec). D2 and D12: add the request types `self-review` (every model call of a review run) and `self-check` (every guard call) to the closed set, with the run id on review rows. The quota gate applies before each of these calls. |
| `add-audit-and-gdpr-compliance` | Company, build group 5, registers its `AuditEventPort` implementation and carries the erasure and export of the four tables later, and no task here waits for it (D16, the erasure part of task 7.3 moved there by the dependency fix of 2026-10-05). Made in that change, checked on 2026-10-03 (its D3 action table with the names of D16, its erasure table and its retention matrix). Add the audit actions of D16, the four tables to per user and tenant erasure and to tenant export as D16 describes, and list the retention of `self_review` (90 days) and `self_change` (365 days) in the retention matrix of `docs/COMPLIANCE.md`. The deletion itself is the two entries `self-review` and `self-change` of the one retention task `record-retention` of `add-shared-scheduler` (answer 89.7 of 2026-10-08), not a task of that change. The report notifications fall under the erasure and export of `owner_notification` that `add-shared-scheduler` already asks for. |
| `add-chat-streaming-and-conversations` | Made in that change, checked on 2026-10-03 (its streaming design and `specs/chat-streaming/spec.md`). D3: the streaming executor captures the evidence and triggers at stream end, and `request_self_review` is offered on the streaming path. Since answer 89.1 of 2026-10-08 it is the one chat executor, so the capture is added once. The conversation id becomes the review's conversation key. That change lands earlier (build group 3), so the capture at stream end moved here from its task 9.5 by the dependency fix of 2026-10-05 and is this change's task 2.5. |
| `add-openclaw-plugin-host` | The `discord` channel of the `OwnerNotificationChannel` port, which `add-shared-scheduler` already asks for, renders one Undo button per id in `subject_ids` for a notification of source `self_improvement`, and a press calls `SelfImprovementService.undo(changeId, identity, channel)` in process as the linked owner with channel `discord`. Since answer 89.6 of 2026-10-08 the buttons are entries of action type `self_improvement_undo` in the notification's `actions` list, a press goes through the one action endpoint `POST /api/v1/channel-host/actions` of that change, and this change registers only the `ChannelActionHandler` for that action type. No outbox event kind of this change is needed. A turn started by a peer bot is marked so that the `RequestProvenance` of `add-agent-soul` names it as an untrusted source. Applied in that change on 2026-10-02 (its D12 and D13), and its own edit to this change, the in process undo, is applied here (D13). `add-openclaw-plugin-host` lands earlier (build group 4, position 10), so the Undo buttons and the check that no self change starts from a peer turn moved from that change to this one (dependency fix of 2026-10-05). Their own endpoint and host handler are gone since answer 89.6 of 2026-10-08. |
| `add-self-built-integrations` | Made in that change, checked on 2026-10-03 (its D26). Call `SelfChangeRecorder.recordIntegrationEvent(...)` after commit with the event `register`, `activate`, `update`, `disable` or `auto_disable` when an integration is registered, activated, updated, disabled by the model or disabled automatically, only when the module `self-improvement` is active, and provide the `SelfChangeUndoHandler` of type `integration`, registered only while that module is active, that disables, rolls back or enables through its own paths as the deciding identity (D11, D13). Its review rule needs nothing more here: a review has no integration tool and never starts a build, and may suggest an integration in its summary (D2). Its own edits to this change, the change records with their undo and the review rule, are applied here. |
| `add-flutter-chat-app` | Made in that change, checked on 2026-10-03 (its D11, its `specs/flutter-chat/self-improvement-report/spec.md` and its task group 18). A "What I learned" screen listing `GET /api/v1/self-improvement/changes` with what, why, trigger, check, the untrusted mark and an Undo button, a badge for unseen changes, counted from the `subjectIds` of the caller's unread notifications of source `self_improvement`, and opening the screen marks those notifications read with `POST /api/v1/notifications/{id}/read` (answer 89.6 of 2026-10-08), and the staged changes in the approvals list that `add-action-approvals` already asks for. A notification of source `self_improvement` in the notification list that `add-shared-scheduler` asks for opens this screen. |
| `upgrade-spring-boot-4` | None. This change adds its codes to `ApiErrorCode` and uses its Flyway setup. |

## Decision record numbering

The decision record of this change takes the next free ADR number in `apps/ascend-agent/docs/architecture/decisions/` at implementation time, after the records of every change applied before it. The e2e spec takes the next free spec number the same way.

## Migration Plan

1. Apply the changes before this one in the build order first, at least `upgrade-spring-boot-4`, `add-deployment-modules`, `add-shared-scheduler`, `add-agent-skills`, `add-agent-subagents`, `add-agent-soul` and `add-action-approvals`, with the required edits above, which are all made.
2. Deploy. Flyway creates the four tables. The shared scheduler starts the two system tasks of D9 from their task beans, and its one retention task picks up the two entries of D9. There is no data to keep (the project is under development). Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.
3. Rollback: removing `self-improvement` from `ASCEND_MODULES` stops triggers, reviews, the timed work of D9 and the new tools. Self-written skills and definitions stay in git and can be reverted by the owner. Going back to the previous image leaves the four tables unused, and pending executions of this change's task names fall under the unresolved task rule that `add-shared-scheduler` task 1.6 records in `docs/SCHEDULING.md`.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. Its four tables start empty, and it needs none of today's data.

## Owner decisions of 2026-10-07

Answer 75.1 (review of the group 3, 4 and 5 changes of 2026-10-07, fix of all 75 items approved): items 35, 36, 62 and 68 are fixed here. Item 35: the AI-run spec of task 9.1 lives at `apps/ascend-agent/e2e/testing/<N>-self-improvement-test.md`. Item 36: `add-shared-scheduler` is build group 3, position 7, not fifth. Item 62: D9 has three system tasks, and the migration plan says three. Item 68: the conversation id is the one of `add-chat-streaming-and-conversations`, which lands earlier, not the user id.

## Owner decisions of 2026-10-08

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/self-improvement/` (task 10.6). Every check that read the request journal now reads the scripted model's request log, `GET /mockoon-admin/logs` of the Mockoon admin API, and clears it with `POST /mockoon-admin/state/purge`.

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (task 10.6).

Answer 85.1: no plan text of this change exports a key or a secret in a shell. The AI-run spec of task 9.1 takes its tokens from the shared token module of `add-keycloak-login` and its provider key from the repository `.env`. Nothing changes here.

Answer 87 (rule R1, several agent instances, CANON 26.1): checked for every mechanism of this change. Kept: the one time execution per review and per tenant review on the shared scheduler, the conditional moves of review rows, the partial unique index of one pending review per conversation and the reports written in the transaction of the change. Changed: the review slot is the pool `self_review` of the one slot pool in Postgres (D2), the daily limits are counted under a Postgres transaction advisory lock in the transaction that writes (D10, task 3.9), and the check of a chat change is claimed in its row with `check_claimed_at`, so the background check and the retry task on any instance never check one change twice and a change whose instance stopped is still checked (D6, task 4.4). The Non-Goal that accepted in-memory parts for one instance is replaced (Goals and Non-Goals, the `self-improvement-review` spec).

Answer 89.1: `StreamingChatExecutor` of `add-chat-streaming-and-conversations` is the one chat executor, and this change adds its evidence capture and trigger recording to it once (D3, tasks 2.3 and 2.5).

Answer 89.6: owner notifications have one retry layer, the queue of each channel (`channel_outbox` for Discord), and this change keeps none (D11). The Discord Undo buttons are entries of action type `self_improvement_undo` in the report's `actions`, a press goes through the one action endpoint `POST /api/v1/channel-host/actions` of `add-openclaw-plugin-host`, and this change registers only the `ChannelActionHandler` for that type. The namespace `ascend-notify`, `POST /api/v1/channel-host/notifications/actions` and the request of task 10.7 are removed (D11, D14, the required edit rows, task 6.5, the `self-improvement-reports` spec). The notification `read_at` is the only seen marker: `self_change` has no seen time, `POST /changes/seen` is removed, and `unseen=true` keeps a change while the caller's report notification of it is unread (D11, D14, task 6.3, the `self-improvement-reports` spec).

Answer 89.7: the review slot is the pool `self_review` of `RunSlots` of `add-agent-subagents`, registered with a `RunPoolRegistration` bean from `review.max-concurrent` and waiting bound 0 (D2, task 5.3). Retention is the two `RetentionEntry` beans `self-review` and `self-change` of the one retention task `record-retention` of `add-shared-scheduler`, and the system task `self-improvement-retention` is removed (D9, D16, D18, task 7.5, the specs).

Answer 91.1: in the deterministic phase AscendMemory is faked in the one Mockoon container under `/ascend-memory/`, only the agent restarts, and no deterministic spec wipes memories. This change no longer has a deterministic spec that runs a scripted chat turn (answer 91.3), so the approved fix above no longer applies to any of its specs. The AI-run spec of task 9.1 uses the real AscendMemory and keeps its cleanup of the spec user's semantic memory.

Answer 91.3: the scripted spec of task 10.6 is removed, because the guard revert, the freeze and their reports are proven by `GuardAfterChatWriteIT`, `GuardFreezeTest` and `SelfImprovementReporterIT`. With it go this change's scripted model rules and reply files and the dependency on the harness of `close-agent-test-gaps`. The deterministic API spec of task 10.2 stays, because it alone proves the endpoints with real Keycloak tokens on the live stack, and the AI-run spec of task 9.1 stays, because it runs with real AI answers. The company check of another tenant moves from the removed spec to the spec of task 10.2 (inbox to `add-tenant-isolation`, its task 12.10).

Answer 93: the two pairs of the source `self_improvement` are inserted into `owner_notification_kind` of `add-shared-scheduler` by this change's own migration (review item S3-8, D12, task 1.2). A change and an undo write no log line of their own, because their audit event already is one structured INFO line (D17, task 8.1, the `self-improvement-reports` spec). The cost metric counts only the guard checks (`improvement.check.cost.usd`), because the review run's cost is already the run cost counter of `add-agent-subagents` (D17). Not applied, because each would cut a capability or a setting the owner may rely on (rule R3): the settings of D18 stay settings, because which of them the owner wants as fixed values is his call, the report to every `ADMIN` of the tenant through the offline lookup stays, because it is a company feature (rule R2), and `self_capability_use` stays, because the used and unused counts of `/stats` need it.

Answer 93 (from `add-agent-skills` and `add-agent-soul`): `SkillUsedEvent` is published by this change, its only listener, from the `Skill` function of `add-agent-skills` (D15, task 6.4), not by `add-agent-skills`. The setting `app.soul.provenance.trusted-tools` is removed in `add-agent-soul`, and the closed list in code of its D15, which names `skill_patch`, `subagent_definition_patch` and `request_self_review`, is the only list of trusted tools (D7). Answer 89.4 (from `add-agent-soul`): a personality proposal of a review is an approval request of kind `personality_change` of `add-action-approvals`, so the proposal id this change records is that approval id, and its undo denies the pending approval or reverts the applied commit (D13).

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 98 (owner rule 98, every value with a default is a setting): every key of D18 is made external, each as `${ENV:default}` in `application.yaml`, the same default in `SelfImprovementProperties`, and `- ENV=${ENV:-default}` on the `ascend-agent` service of `compose.yaml` (D18 table, task 1.1): `APP_SELFIMPROVEMENT_ZONE` (`Europe/Warsaw`), the trigger, review, guard, provenance, limit, daily review, statistics and retention keys with the defaults of the D18 table, the per provider review models `APP_SELFIMPROVEMENT_REVIEW_MODEL_<PROVIDER>` (empty), and the crons and zones of the system tasks `self-improvement-review` (`30 3 * * *`) and `self-improvement-check-retry` (`0 * * * *`), whose zones follow `APP_SELFIMPROVEMENT_ZONE` through a nested compose default. No `.env.example` line is added. Kept as constants, because they are not operational (D18): the 300 character caps of `lesson` and `reason` (fixed tool definitions that keep the prompt cache warm), the content scan rules of D8 with the 200 character run of base64 or hex (security rules configuration must not loosen), the guard's temperature 0, its one confirming rerun and its keep rules (decision rules), the startup refusals that compare with the limits of `add-agent-skills`, and every name, code and enum value. The 4000 character notification body limit and the 30 day notification retention belong to `add-shared-scheduler`. The rows go into `apps/ascend-agent/docs/CONFIGURATION.md` (task 8.4). LM Studio: no test or measurement of this change uses it as a default, the AI-run spec of task 9.1 names a hosted provider and the deterministic spec of task 10.2 calls no model. Stale text: no plan text of this change names the old `e2e` profile, the overlay mount or `SPRING_CONFIG_ADDITIONAL_LOCATION`, and the AI-run spec runs against the shipped configuration, never the test settings the deterministic phase copies into the running agent (`close-agent-test-gaps` D7, task group 10 intro). Fixed in the same pass: a stray backtick in the D18 row of the per provider review models, and the required edit row of `add-audit-and-gdpr-compliance`, which still named the removed system task `self-improvement-retention` instead of the two retention entries of answer 89.7.
