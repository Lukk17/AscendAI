## Context

See proposal.md for why. This section holds only the facts the design rests on.

The chat path today (`apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/`):

- `AscendChatService.prompt` resolves the request's embedding provider (the `embeddingProvider` request field, else the chat provider's `default-embedding`), assembles the system messages and the user message, loads history keyed by user id, calls `ChatExecutor.execute`, then saves history. There is no conversation id. A conversation is the history of one user id, and the unit that runs in one go is one chat request. The resolved embedding provider is not passed to `ChatExecutor` today.
- `ChatExecutor.execute` resolves a prompt cache strategy and calls `invoke`. When the provider rejects the cache settings, `execute` calls `invoke` a second time without them. Each `invoke` builds a new `ChatClient` in `buildChatClient`, which adds `toolCallbackProvider.getToolCallbacks()` as default tool callbacks, and passes `Map.of("user_id", userId)` as tool context.
- The only `ToolCallbackProvider` bean is `FilteredToolCallbackProvider` (or the no-op fallback when MCP is off). The `mcp-startup-resilience` spec requires it to stay the only such bean.
- `ToolCallTracker` keeps, per thread, the names of the tools the model asked for in the current request. `TrackingToolCallingManager` records each name before the tool runs. After `upgrade-spring-boot-4` (its D6) that manager is held by the `ToolCallingAdvisor` that `ChatExecutor` registers on its `ChatClient`, no longer by the chat models of `ChatModelResolver`. `ChatExecutor` reads the names with `drain()` at the end.
- `StartupLogConfig` prints the startup banner. `GlobalExceptionHandler` maps exceptions to the `ApiError` body today. `upgrade-spring-boot-4`, which is applied before this change, switches every handler to an RFC 7807 problem detail and deletes `ApiError` (its D19).
- The agent image runs as the non-root user `app` on `eclipse-temurin:21-jre-alpine`, which has no `git` binary.

The vector store setup the RAG pipeline already uses (`config/VectorStoreConfig.java`, `config/AppConfig.java`, `config/properties/EmbeddingProviderProperties.java`, `service/provider/VectorStoreResolver.java`, `service/rag/RagRetrievalService.java`):

- There is one `QdrantClient` bean. `VectorStoreConfig` builds, for every entry of `app.embedding.providers` (`lmstudio`, `openai`, `gemini`), one `OpenAiEmbeddingModel` from that entry's base URL, key, model and dimension count, and one `QdrantVectorStore` on the shared client with collection `ascendai-<dimensions>`. The embedding models are created inside that method and are not beans. `VectorStoreResolver` picks the store by embedding provider name.
- The collection name is chosen by embedding dimension only. `lmstudio` (`text-embedding-nomic-embed-text-v2-moe`) and `gemini` (`gemini-embedding-001`) both embed at 768 dimensions and share `ascendai-768`, and `openai` (`text-embedding-3-small`, 1536) uses `ascendai-1536`. AscendMemory follows the same rule with `ascend_memory_768` (shared by `lmstudio` and `gemini`) and `ascend_memory_1536` (`apps/ascend-memory/AGENTS.md`).
- `AppConfig.initVectorStore` creates every collection listed in `app.vectorstore.collections` with cosine distance when it is missing, at startup, and logs and continues when Qdrant is unreachable.
- `RagRetrievalService` asks for `top-k` candidates with no threshold in Qdrant, applies `app.rag.similarity-threshold` (0.4, chosen by manual testing) in Java, and treats a failed search as no result with a WARN line.

The library this change reuses, read at tag `v0.12.0` of `spring-ai-community/spring-ai-agent-utils` (its `SkillsTool.java` is byte-identical to `main` on 2026-10-02):

- `SkillsTool.builder()` offers `addSkillsDirectory`, `addSkillsDirectories`, `addSkillsResource`, `addSkillsResources`, `toolDescriptionTemplate` and `workspace`, and `build()` returns one `ToolCallback` named `Skill` taking `{"command": "<skill name>"}`.
- The builder reads skills through `Skills.loadDirectory`, which walks the whole tree with `Files.walk` and turns every file named `SKILL.md` at any depth into a skill. It throws a `RuntimeException` when the folder is missing or any file cannot be read.
- Front matter is parsed by `MarkdownParser`, which is not a YAML parser. It splits each line on its first colon. A multi-line value such as `description: |` in the repository skill `mongodb-search-and-ai` becomes the one character `|`, and the end of the front matter is the first `---` anywhere after the opening one.
- `build()` asserts that at least one skill exists and throws otherwise. Skills go into a `HashMap` by name, so a duplicate name silently replaces the earlier one. `Skill.name()` throws a `NullPointerException` when `name` is missing.
- `Skill.toXml()` writes every front matter key and value into the tool description without escaping.
- The whole body of every skill is read into memory at load time. "On demand" means only that the body reaches the model when the model calls the tool.
- The tool holds its skill map from the moment it is built. There is no reload, add or remove method.
- `SkillsTool.Skill` (a record of base path, front matter map and body), `SkillsTool.SkillsInput` and `SkillsTool.SkillsFunction` (public, constructed from a `Map<String, Skill>` and an optional `Workspace`) are all public.

The repository folder `.agents/skills` holds 62 skills, all with a folder name equal to their `name`, plus one plain file (`.openspec-target`) that is not a skill. Their descriptions add up to 22,264 characters (the longest is 728, the average 359), their `SKILL.md` files to 593,926 bytes (the largest is 16,643). Two skills carry a key outside the agentskills.io set (`user-invocable`).

Measured size of the skill list per request (2026-10-02, PyYAML over `.agents/skills`, markup escaped):

| What the model receives | Characters |
|---|---|
| Library `Skill` description with every skill listed (library template from tag `v0.12.0` plus 62 `<skill>` elements holding name and description) | 28,234 |
| This design: `Skill` description with an empty always-listed set plus the `skill_search` description and input schema (draft texts in D19) | 726 |
| This design with the three `ascend-*` skills always listed | 2,291 |
| One `skill_search` result of 5 entries, only in a request that calls it (5 times the measured average of 439 characters per entry) | about 2,200 |

Against the 22,000 characters measured before (descriptions alone), every request now carries 726 characters of skill text instead of the 28,234 the full list really costs, a saving of 27,508 characters (97 percent) per request with no always-listed skill. A request that searches once still saves about 25,300 characters.

The `type` parameter of `skill_search` (D19), added so `add-agent-subagents` can search its definitions with the same tool, came after this measurement and is not in the 726 characters. Task 5.8 measures the final length.

## Goals / Non-Goals

Goals:

- Reuse the library's `Skill` tool, its records and its function, and write only what the library lacks: safe loading from several folders, reload, the snapshot, the write path, git history, the file read tool, the REST surface and search.
- Offer the model only the skills that fit the task: index names and descriptions in the vector store the agent already runs and let the model search, instead of listing every skill in every request.
- Keep every request on one consistent skill list, and keep startup independent of the state of any skill folder and of the vector store.
- Make every change to the writable root validated, attributed and undoable.
- Keep skills written by the agent or the owner inside their tenant, with the shipped skills global, and let a tenant policy decide which skills a tenant is offered and which a search can return.
- Work the same with several agent instances (answer 87): every instance mounts the same agent home root, writes run one at a time across instances, and a write on one instance reaches the catalog of every other instance through shared invalidation (D24).
- Keep skills and the subagent definitions of `add-agent-subagents` in one catalog with one loader, snapshot, watcher, write path, git store and controller, and a validator per type (answer 89.5, D24).

Non-Goals:

- Deciding when the agent should write a skill. `add-self-improvement` (build group 4, position 13) decides it. This change gives it the hooks it asks for (D3, D6, D8, D9, D14).
- Running scripts from skill folders. No shell or code execution tool is added.
- Skills per user. A skill is either global (a read-only folder) or belongs to one tenant (the writable root). See D15.
- Writing files other than `SKILL.md` through the write path. Other files in a skill folder are loaded and readable, and they come from outside the agent.
- Honouring the `allowed-tools` or `model` keys. They are ignored and hidden from the model.
- Indexing skill bodies. Only the name and the description are indexed, because the description is the part written to say when a skill applies.
- An approval step before an agent-written skill goes live. By owner decision, skills the agent writes go live at once. The one exception belongs to `add-self-improvement`: a chat write made after outside content in the same request waits for one tap of the owner's approval (owner answer 38.1, D6).

## Decisions

### D1: Reuse the library's tool and records, not its loader or builder

The catalog builds `SkillsTool.Skill` records itself and wraps them in `new SkillsTool.SkillsFunction(map, workspace)` inside `FunctionToolCallback.builder("Skill", function)` with `SkillsTool.SkillsInput` as input type and a description built by the catalog. This keeps the library's tool name, input shape, lookup and "skill not found" answer.

The builder and `Skills` are not used, because against real files they fail in ways the spec forbids: the line-based parser breaks a repository skill, a missing folder or unreadable file throws, zero skills throws, duplicates are dropped silently, nested `SKILL.md` files become skills, and unescaped front matter goes into the tool description. The front matter map handed to each `Skill` holds only `name` and `description`, both escaped for markup, so the library's `toXml()` is safe to reuse.

The description template is the catalog's own text (the library keeps its template in a private constant). It tells the model what skills are, that the tool takes a skill name only, that `skill_search` finds the right one, and it lists only the always-listed skills (D22).

Alternatives considered: calling `addSkillsDirectory` once per already-validated skill folder (rejected: the parser still breaks `mongodb-search-and-ai` and extra keys still reach the model), copying the library source into the project (rejected: duplicates a maintained dependency).

### D2: Loader and validator, one rule set for loading and writing

`SkillLoader` lists the direct child folders of each configured folder in name order, resolves real paths, skips links that leave the folder, reads `SKILL.md` with a size check before reading, decodes UTF-8 strictly, and hands the text to `SkillValidator`. A child folder without `SKILL.md` and a plain file are not skills and are passed over without a log line. The validator parses front matter with SnakeYAML through `new Yaml(new SafeConstructor(loaderOptions))`, with `LoaderOptions` limiting aliases and code points, so `!!` type tags cannot build objects. The code point limit is derived from `max-skill-bytes` (a UTF-8 file of N bytes holds at most N code points), and the alias limit is a fixed security bound of the parser, not an operator value (answer 98). It applies the name, description, compatibility, metadata and limit rules from the spec and returns either a valid skill or a reason from the closed set. The write path calls the same validator, so a skill the owner or the agent can write is exactly a skill the loader accepts.

Unknown keys are ignored rather than refused, because two repository skills and many Claude Code skills carry such keys, and the goal is to load what other tools load.

SnakeYAML is used because Spring Boot already depends on it for YAML configuration. If `upgrade-spring-boot-4` leaves it off the runtime classpath, the version catalog adds it explicitly.

### D3: The catalog is an immutable snapshot swapped atomically, and keeps the last good version

Since answer 89.5 the snapshot and its holder are the type-generic `CatalogSnapshot` and `CatalogHolder` of the one catalog of D24, and `SkillCatalog` is the part of the snapshot for the type `skill`. `SkillCatalog` is an immutable record: list version, a fingerprint of the loaded files, the skills in name order, the skipped skills with reasons, the skills held at their last good version, and the ready tool callbacks. `CatalogHolder` keeps the current snapshot in an `AtomicReference`. A reload builds a complete new catalog off to the side and swaps it in one step. When the new fingerprint equals the current one, the current catalog stays and the version does not move.

Last good version, the same rule `add-agent-subagents` uses for its definitions: when a skill that is in the current catalog still has its `SKILL.md` but that file now fails validation (any file level reason: `invalid_front_matter`, `name_mismatch`, `too_large`, `not_utf8`, `unreadable`, `outside_folder`), the new catalog keeps the skill's previous name, description, body and base path, marks it as held at its last good version with the reason, and logs one WARN line naming the folder identifier, the path and the reason. The skill stays offered, searchable and loadable with its last good content until the file is valid again (then the new content replaces it) or the skill folder or its `SKILL.md` is removed (then the skill is removed). An instance keeps last good versions in memory. For a skill of a tenant skills folder, an instance that holds none in memory (it started after the broken edit, or restarted) takes the last good version from git: the newest commit touching the skill whose `SKILL.md` passes validation, read through `VersionedFolder`. So every agent instance serves the same version, before and after a restart (answer 87). A tenant skill with no valid commit in its history is skipped. A skill of a read-only folder has no history, so a shipped skill that is invalid at startup has no last good version and is skipped. A held skill is not counted as skipped. It is reported in the reload response and the list endpoint as `last_good` with its reason.

The skill tools reach the chat through one composition point that this change adds and owns. `add-agent-subagents` registers its tools there (its design D2) and `add-agent-sandbox` registers its sandbox tools there (its design D11), so no second one is ever added:

- `AgentNativeTool` is a small interface, not a `ToolCallbackProvider`, with one method that takes the tool context of one chat request or one subagent run of `add-agent-subagents` and returns the immutable list of `ToolCallback`s for it. The skill catalog implements it by returning the callbacks of the request's snapshot. An implementation may return no callback for a context, for example `subagent_definition_write` of `add-agent-subagents`, which returns none when the context holds a `subagent_run_id`, unless the run is of kind `self_review`. Other changes add their tools as more `AgentNativeTool` beans, for example `knowledge_add_download` of `add-download-ingestion`, the sandbox tools `shell`, `file_read` and `file_write` of `add-agent-sandbox` (offered to the main chat and to runs, each conversation and each run with its own sandbox workspace), and the tools of `add-agent-soul`.
- `ChatToolset` is a component of `core-chat` (`add-deployment-modules` D3) that, once per chat request (and once per run in `add-agent-subagents`), takes the filtered MCP callbacks from the existing `ToolCallbackProvider` and the callbacks of every `AgentNativeTool` bean, and returns one list. When an MCP tool has the name of an agent native tool, the MCP tool is left out for that request and a WARN line names it. It then applies, in this fixed order, the steps other changes add here, so every tool of every change is governed in this one place:
  1. Module filter (`add-deployment-modules` D10): a tool whose module is not effective for the request's tenant is left out. An agent native tool has the module of its bean class marking, an MCP tool the module of its connection.
  2. Tenant tool policy (D16): a tool that the `TenantToolPolicy` port of this change does not allow for the tenant is left out. Its default `ConfiguredTenantToolPolicy` denies only the tools listed in `app.tool-policy.denied-tools` (empty by default), and `add-tenant-policy` (company, build group 5) registers its allow-list implementation later.
  3. Per-request narrowing list (`add-openclaw-plugin-host`): when the request carries an allow list, for example `app.channels.peer-bots.allowed-tools` for a turn written by a peer bot, every tool not on it is left out. A request without the list is not narrowed.
  4. Self-change gate (`add-self-improvement`): the self-write tools that change names, `skill_write` among them, are wrapped in its `SelfChangeGate`.
  5. Approval gate (`add-action-approvals` D4): every tool whose mode is `requires_approval` is wrapped in its `ApprovalGatedToolCallback`. The wrapper keeps the tool definition, so the model and the prompt cache see the same tool list bytes.
  6. Always and deferred (`add-mcp-tool-servers`): the list is returned in two parts. An MCP tool goes to the part its server entry names. Every agent native tool is in the always part.
  This change builds steps 1 and 2 (step 1 on `ModuleState` of `add-deployment-modules`, which lands earlier). Steps 3 to 6 are added by the later changes named in each step, each in its own tasks (dependency fix of 2026-10-05), and do nothing before that change is applied. `ChatToolset` is built as this fixed pipeline so each later step plugs in without changing the order.
- `StreamingChatExecutor` of `add-chat-streaming-and-conversations`, the one chat executor of the agent (answer 89.1 of 2026-10-08, it replaced `ChatExecutor`), asks `ChatToolset` once per chat request, before the first model call, and uses that list for the model call and for its one undecorated cache retry, so the retry sees the same tools and no `ChatClient` calls the provider itself. `POST /api/v1/ai/prompt` collects the same executor's answer, so the blocking and the streamed endpoint get the same tools.
- The tool context keys this change adds are owned here and reused by the sibling changes: `StreamingChatExecutor` puts `request_id` (one id per chat request, D8), `tenant_id` (from `TenantContext.currentTenantId()` of `add-keycloak-login`, D15), `embedding_provider` (D19) and `user_message` (the text of the current user message, for the one paste rule of D8, answer 93) next to the existing `user_id`.

The skill tools are never exposed as a `ToolCallbackProvider` bean, so `mcp-startup-resilience` holds unchanged. The current `SkillCatalog` also offers a lookup by name, which `add-agent-subagents` uses to preload a skill into a subagent.

Because skills are scoped by tenant (D15), the holder keeps one global part, built from the read-only folders and shared by all tenants, and one tenant part per tenant, built from that tenant's skills folder under the writable root. The catalog a request receives is the global part filtered by the tenant's policy (D16) plus the tenant part, assembled once per request and cached per tenant until either part or the policy changes. This per-request catalog is the set every lookup of that request uses: the `Skill` tool, `skill_read_file` and `skill_search` (D19).

Because a request holds its own catalog reference and the `SkillsFunction` inside it holds its own map, nothing a reload does reaches a request already running. Bodies are kept in memory (about 0.6 MB for the repository folder today), which is the library's own model.

The `Skill` tool description holds only the always-listed skills (D22), so adding, changing or removing any other skill leaves the tool definitions byte for byte the same and the provider prompt cache stays warm.

Alternatives considered: rebuilding the callback on every request (rejected: rereads every folder per request and makes the tool description depend on timing), pinning one catalog version per user across turns (rejected for now: there is no conversation id, and a user's next turn seeing a new skill is the expected behaviour), dropping a skill that turns invalid (rejected by owner decision: one broken edit would make a working skill disappear, and the two changes must follow one rule).

### D4: Folder precedence and shipped names

`app.skills.sources` is an ordered list. The read-only folders come first in the order the owner lists them, and the writable root must be the last entry. `SkillProperties` refuses at startup a configuration whose writable source is not last. Between read-only folders, the first folder holding a name wins and later copies are skipped with `duplicate_name`. A tenant's own skills folder, `<writable root>/tenants/<tenantId>/skills/`, takes the writable root's place in that order.

The write path never accepts a skill whose name is the name of a shipped skill, that is any direct child folder of a read-only folder that holds a `SKILL.md`, valid or not, and whether or not the tenant's policy offers it. It refuses with reason `shipped_name` and a message naming the read-only folder that holds the name, for the agent and for the owner alike (D6 step 2). So a tenant skill and a shipped skill can share a name only when the shipped skill arrived after the tenant skill was written, or through a hand edit in the tenant skills folder. In that case the shipped skill wins, the tenant copy is skipped with `duplicate_name` and a WARN line naming both paths, and the owner can delete the tenant copy through `DELETE /api/v1/skills/{name}`, which acts on the tenant skills folder.

### D5: Watcher plus rescan plus endpoint, all funnelled into one debounced reload

`CatalogWatcher`, the one watcher of the catalog of D24, registers a `java.nio.file.WatchService` on each existing read-only folder and on each entry folder directly under it, and for the writable root on `tenants/`, on each tenant folder and on the folders each registered type keeps there: for the type `skill` the tenant skills folder and each skill folder directly under it, and for the type `subagent` of `add-agent-subagents` the `.claude/` and `.claude/agents/` folders (the JDK watch is not recursive). It re-registers after every reload. In a tenant folder only the entries of a registered type matter: an event for any other entry, such as `soul/` and `users/` of `add-agent-soul` or `integrations/` of `add-self-built-integrations`, is ignored and starts no reload. Any event, including `OVERFLOW`, schedules a reload of the type and scope it belongs to after the configured quiet period on one scheduler thread, so a burst of events gives one reload and two reloads never run at once. A hand edit is therefore live within the quiet period (500 milliseconds by default), under one second. The debounce thread, the rescan and the reaction to a `catalog_changed` notification (D24) are local work on Spring's `TaskScheduler`, never system tasks of the shared scheduler of `add-shared-scheduler`, because each agent instance refreshes its own in-memory snapshot (the rule of the shared scheduler: work that only refreshes one instance's memory stays local). A scheduled rescan computes the fingerprint (path, size and modification time of every entry file of every type and the set of entry folders) on the configured interval and reloads only the scopes that changed. `POST /api/v1/skills/reload`, `POST /api/v1/subagents/definitions/reload` of `add-agent-subagents` and the write path call the same reload directly. Every reload that publishes a new snapshot hands the change to the capability index (D20), and a reload caused by a write, a reload endpoint or a local file event also sends the `catalog_changed` notification (D24), so the other agent instances reload that scope too. The watcher has no on and off switch: it, the rescan and the notification always run while the module `skills` is active (answer 90 of 2026-10-08 removed `app.skills.watch.enabled`, which only a test used).

The rescan exists because file events are not guaranteed on every mount. Whether Docker Desktop on Windows delivers them for a bind mount of `.agents/skills` is not measured yet, so task 9.3 measures it. Spring Integration's file adapters, already on the classpath, were considered and rejected: they emit files into a message flow, and here the only output is "reload now".

### D6: One write path, serialised, atomic, committed before success

`CatalogWriteService` of the one catalog (D24) is the only class that changes the writable root, for every type. For the type `skill` every operation acts on the caller's tenant skills folder and runs in one Postgres transaction under the transaction advisory lock keyed by the type and the tenant, so writes of one tenant run one at a time across every agent instance (answer 87):

1. Check the tenant id against the tenant slug rule (`[a-z0-9-]{1,64}`), the skill name against the name rules and the Windows device names, then build the path and check the real path is a direct child of the tenant skills folder and not a link.
2. For create, update and revert, refuse `shipped_name` when any read-only folder holds a skill folder of that name (D4). For agent writes check `protected` against the newest commit touching the skill.
3. Check an `If-Match` commit id when one was given.
4. Validate the content with `SkillValidator`.
5. Write `SKILL.md` to a temporary file in the same folder and move it over the old file with `ATOMIC_MOVE`. The loader only reads files named exactly `SKILL.md`, so the temporary file is never loaded.
6. Commit with JGit. If the commit fails, restore the file from the last commit and report an error.
7. Run a reload of that tenant's part with trigger `write`, send the `catalog_changed` notification (D24), publish the audit event (D17), and return the commit id. The reload hands the change to the capability index (D20), and the write does not wait for the index: until the entry is indexed, `skill_search` finds it through the text match of D19.

Before step 1 of any operation, and at the start of every reload, uncommitted changes in the tenant skills folder are committed with origin `external`, under the same advisory lock, so two agent instances never commit in one repository at once. This keeps history complete when someone edits files by hand.

A skill the agent writes goes live at once, without an approval step (owner decision). The controls are the ones in D8 and the owner's revert. The one exception is set by `add-self-improvement` and settled by owner answer 38.1: a chat write made in a request whose `RequestProvenance` of `add-agent-soul` (its D15) is not `clean`, that is after retrieved documents, an attachment, a peer bot turn or an outside tool result, is held for one tap of the owner's approval. It is submitted as an approval request of kind `self_change` of `add-action-approvals`, the tool result tells the model that the change waits for the owner, and an approved change goes through this write path with its `If-Match` stale check. This is the default `stage` of that change's setting `app.self-improvement.provenance.chat-write-untrusted`, which the owner can still set to `apply` or `refuse`. The write path itself does not change for it: the `SelfChangeGate` in front of `skill_write` (D3 step 4) decides before the write path is called. Before `add-self-improvement` is applied every agent write is live at once.

The write path accepts from its caller, and writes unchanged into the commit, the extra trailers `add-self-improvement` asks for: `Skill-Reason`, `Skill-Patch`, `Skill-Self-Change-Id` and `Self-Provenance`. Every trailer value is written as one line, with each line break replaced by a space, so a value can never add a trailer of its own. The guard of `add-self-improvement` reverts a skill through the write path with origin `guard` (D8), and no tool is ever offered that writes origin `guard`.

### D7: Git through JGit, one repository per tenant skills folder

JGit (`org.eclipse.jgit:org.eclipse.jgit:7.8.0.202609011348-r`, Eclipse Distribution License 1.0, Java 17 or later) runs inside the JVM, so the alpine image needs no `git` package and no process is started. There is one skills repository per tenant, at `<writable root>/tenants/<tenantId>/skills/`, so a tenant's history can be exported and erased whole without rewriting anyone else's history (D17).

Folder layout, the same in `add-agent-subagents` (its D4): the writable root is the agent home root, `app.agent-home` (D11). Each tenant has the tenant folder `<writable root>/tenants/<tenantId>/`. The tenant's skills live in its `skills/` folder and the tenant's subagent definitions of `add-agent-subagents` live in its `.claude/agents/` folder, and each of the two is its own git repository. Neither the root nor a tenant folder is a git repository, so the two repositories are never nested and each change commits only to its own. This change never reads or writes `.claude/agents/`, and `add-agent-subagents` never reads or writes `skills/`. `add-agent-soul` uses the same tenant folder for the personality repository `soul/` and for one repository per user under `users/<userKey>/`, and `add-self-built-integrations` adds the repository `integrations/`, read and written only by that change. None of these changes reads or writes another's folders. The read-only folders, including `.agents/skills` in the project repository, are never written and never committed to, and compose mounts that folder read-only to make this hold in the container too.

Commit messages carry trailers, for example:

```text
skills: update invoice-checks

Skill-Name: invoice-checks
Skill-Operation: update
Skill-Origin: agent
Skill-Request-Id: 6f1c2a9e-3b7d-4e0a-9a51-2c8f0d4b7e13
Skill-Tools-Seen: web_search, read_page
```

History is `git log` limited to the skill folder path, which still finds a deleted skill. Revert reads the skill folder's tree at the given commit, validates its `SKILL.md`, replaces the folder content with it (or deletes the folder when the skill did not exist at that commit), and commits it as a new `revert` commit. History is never rewritten.

### D8: Origin and the protection rule come from git, never from the file

The origin of a skill is the `Skill-Origin` trailer of the newest commit touching its folder: `agent`, `owner`, `external`, or `guard` for a revert made by the guard of `add-self-improvement`. The file content is not trusted for this, because the agent writes the content. The agent may update a skill only when that origin is `agent` or `guard` (the rule `add-self-improvement` asks for). It cannot delete or revert, and like the owner it cannot write a shipped name. No tool writes origin `guard`.

Every agent write is treated as coming from an untrusted source, because model output can be steered by anything in the prompt: a web page, an OCR result, a retrieved document, an uploaded file. The commit records the chat request id and the tools the model called earlier in the request, read through a new `ToolCallTracker.peek()` that returns the names without clearing them. The user id is not written into git, because git history cannot be edited when a user asks for erasure. The link from request id to user lives in the INFO log line of the write and in the audit event published through `AuditEventPort` (D17), which `add-audit-and-gdpr-compliance` pseudonymises on erasure once it registers its implementation. `StreamingChatExecutor` creates the request id once per chat request and puts it in the tool context as `request_id` next to `user_id`. Recording RAG or attached-document context as well would need the chat path to pass more into the tool context, and is left out because the untrusted label already applies to every agent write.

One rule for pasted content, the same for every catalog type (answer 93 of 2026-10-08, the paste check that `add-agent-subagents` D6 described first and that this change now owns): when the content passed to `skill_write`, with line endings normalised to `\n` and outer blank lines trimmed, appears in full in the `user_message` of the tool context (D3), the owner pasted it, and the write is recorded with origin `owner` and that chat request's id. Otherwise it is an agent write with origin `agent` and every agent rule applies. A model cannot pass the check by copying content the user did not paste, because the check is against the user's own message, not against anything the model says. The owner also gets origin `owner` by using the REST endpoint.

### D9: Tools offered to the model

- `Skill` (library function): returns the base location and body of a skill in the request's snapshot. Its description lists only the always-listed skills (D22) and points at `skill_search`, but it accepts any skill name in the request's snapshot. The catalog builds each `Skill` record with the base path `skills/<name>` and keeps the real folder path in its own record, so no host path reaches the model and the library's optional `Workspace` mapping is not needed.
- `skill_search`: `{query, type}`. Searches the request's snapshot through the capability index (D19), and with type `subagent` the request's subagent definitions of `add-agent-subagents`. Offered when search is turned on and `Skill` or the `Task` tool of `add-agent-subagents` is offered.
- `skill_read_file`: `{skill, path}`. Resolves the path inside the skill's folder from the snapshot, refuses absolute paths, `..` segments, links that leave the folder, directories, files over the configured size and text that is not UTF-8. Refusals are returned as text to the model.
- `skill_write`: `{name, content, reason}`. `reason` is optional, at most 300 characters, and is written into the `Skill-Reason` trailer (asked for by `add-self-improvement`). Pasted content follows the paste rule of D8. Offered only when the tenant skills folder is available and the tenant tool policy allows it (D16). Listing `skill_write` in `app.tool-policy.denied-tools` is the one switch that turns it off (answer 89.17). Reads `user_id`, `request_id` and `tenant_id` from the tool context. Refusals and failures are returned as text.

Tool names use only `[a-zA-Z0-9_-]`, which OpenAI and Anthropic require.

### D10: REST surface

`CatalogController`, the one controller of the catalog of D24, serves `/api/v1/skills` for the type `skill` (and `/api/v1/subagents/definitions` for the type `subagent` of `add-agent-subagents`), follows the existing controller style (`@Tag`, `@Operation`, the common response annotations) and answers every error with an RFC 7807 problem detail. `PUT` reads the body as bytes with a bounded read of the configured maximum plus one byte, so an oversized body answers 413 without being held in memory. `SkillWriteException` carries the reason, and `GlobalExceptionHandler` maps the validation reasons `invalid_name`, `invalid_front_matter`, `name_mismatch` and `not_utf8`, and a revert whose content fails validation, to 400 with code `validation` and the `errors` field described below, the body limit to 413 with code `content_too_large`, `shipped_name` and the read-only delete to 409 with code `shipped_name`, `not_found` to 404, a stale `If-Match` to 412 with code `conflict`, a caller without the `ADMIN` role to 403 with code `forbidden`, and an unavailable tenant skills folder to 503 with code `unavailable`. The 409 body for `shipped_name` has `code` `shipped_name` and a `detail` that names the read-only folder that holds the name and says to choose another name. Inside the write path and in the tool text the size refusal keeps its reason `too_large`, the reason the loader also uses, and only its REST code is `content_too_large`.

Error body (owner decision of 2026-10-02): every REST error body of the agent is an RFC 7807 problem detail. `upgrade-spring-boot-4` defines it (its D19) and owns the switch: it lands before this change, switches every handler of `GlobalExceptionHandler` to Spring's `ProblemDetail` sent as `application/problem+json`, deletes `ApiError`, and updates the existing endpoints and their tests. The body has the fields `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title` (the HTTP reason phrase), `status`, `detail` (one sentence for a person), `instance` (the request path), the extension field `code`, a stable snake case value at the top level of the body, and the extension field `traceId`, the trace id of the current trace (owner decision 51.3 of 2026-10-03), and no `timestamp`. `upgrade-spring-boot-4` keeps every code, status and type in one enum, `ApiErrorCode`, and builds every body in one factory method. This change only uses that body. A validation refusal answers code `validation` and lists every failed rule in the extension field `errors` that its D19 point 5 and its `agent-error-responses` spec require for code `validation`: one object with `field` and `message` per failed rule, sorted by `field`, where `field` is the front matter key or `name` or `content`, and `message` starts with the specific reason, for example `invalid_front_matter: description is missing`. The specific reasons `invalid_name`, `invalid_front_matter`, `name_mismatch` and `not_utf8` appear only inside each `errors` message and in the text the `skill_write` tool returns to the model. They are never the `code` of a body and never `ApiErrorCode` values.

Shared codes (owner decision of 2026-10-02): this change lands before `add-agent-soul` and `add-agent-subagents`, so it owns the codes that several of them need and adds them to `ApiErrorCode`: `conflict` (412) and `unavailable` (503). It reuses `forbidden` (403), which `add-keycloak-login` adds with the 403 body of every filter chain refusal (owner answer 76.9 of 2026-10-08), and does not introduce it again. It adds one code of its own, `shipped_name` (409). It reuses the codes `upgrade-spring-boot-4` already has, `validation` (400), `not_found` (404) and `content_too_large` (413), and adds no `too_large` code and no code for a validation reason. Later changes reuse these values for the same generic case and never add a second generic code for it. A later change may add a resource-named code for a not found or a forbidden case, in the pattern `<resource>_not_found` and `<resource>_forbidden` (for example `approval_not_found` or `download_not_found`), so a client knows which resource was missing or refused (owner decision 49.4 of 2026-10-03, following the owner's Pharmacy project). Such a code keeps the status of its generic code (404 or 403) and is added to `ApiErrorCode` by the change that owns the resource. The 403 body is written by the `AccessDeniedHandler` that `add-keycloak-login` adds to `SecurityConfig` (its D4 and task 2.10), through the `ProblemDetailWriter` of `upgrade-spring-boot-4`, with the code `forbidden`, so the `ADMIN` rows of this change answer the same body as every other 403 from that change on. `add-agent-subagents`, the runner of `add-agent-sandbox`, `add-agent-soul`, `add-chat-streaming-and-conversations`, `add-tenant-policy` and `add-flutter-chat-app` use the same body. The `ETag` of a skill read is its newest commit id, which the client sends back as `If-Match`.

Every endpoint acts on the caller's tenant: it lists the global skills the tenant's policy allows plus the tenant's own skills, and writes only to the tenant's skills folder.

Security: `add-keycloak-login` lands before this change (build group 3, right after `upgrade-spring-boot-4`, split of 2026-10-04, owner rule of 2026-10-04), so the agent is already an OAuth2 resource server with the roles `USER` and `ADMIN` and one authorization matrix that every later change extends with its own rows (its D4). This change adds its own rows to that matrix in `SecurityConfig`: `ADMIN` for `PUT` and `DELETE` on `/api/v1/skills/{name}`, for `POST /api/v1/skills/{name}/revert` and for `POST /api/v1/skills/reload`, and an authenticated caller for the list, read and history endpoints, with a security slice test per row. The owner decision of 2026-10-02 that the owner holds `ADMIN` for these write endpoints (the same decision `add-agent-subagents` D18 applies to its definition endpoints) now means the owner's Keycloak account holds the realm role `ADMIN`. The in-memory user and `app.security.enabled` no longer exist, because `add-keycloak-login` deleted them.

### D11: Configuration

```yaml
app:
  agent-home: ${user.home}/.ascend-agent
  capability-index:
    retry-interval: 60s
  tool-policy:
    denied-tools: []
    denied-global-skills: []
  skills:
    sources:
      - id: repo
        path: ${SKILLS_REPO_PATH:../../.agents/skills}
        writable: false
      - id: managed
        path: ${app.agent-home}
        writable: true
    watch:
      quiet-period: 500ms
      rescan-interval: 60s
    limits:
      max-skill-bytes: 65536
      max-description-chars: 1024
      max-skills: 200
      max-file-bytes: 262144
      max-reason-chars: 300
    search:
      enabled: true
      top-n: 5
      score-threshold: 0.4
      always-listed: []
    index:
      providers: []
    git:
      author-name: ascend-agent
      author-email: ascend-agent@localhost
  vectorstore:
    collections:
      - name: ascendai-768
        size: 768
      - name: ascendai-1536
        size: 1536
      - name: ascendai-capabilities-768
        size: 768
      - name: ascendai-capabilities-1536
        size: 1536
```

Every value above with a default is a setting under owner rule 98 of 2026-10-08 (CANON 31.11): `application.yaml` writes `key: ${ENV:default}`, `SkillProperties` (and, for the two `core-chat` blocks, their own properties records) carries the same default, and the `ascend-agent` service of `compose.yaml` passes `- ENV=${ENV:-default}`. ENV is Spring Boot's canonical environment form of the property, except `SKILLS_REPO_PATH`, which this plan already named. A list is passed as one comma separated value, empty by default.

| Property | Environment variable | Default |
|---|---|---|
| `app.agent-home` | `APP_AGENTHOME` | `${user.home}/.ascend-agent` (the `docker` profile sets `/app/agent-home`, see below) |
| `app.capability-index.retry-interval` | `APP_CAPABILITYINDEX_RETRYINTERVAL` | `60s` |
| `app.tool-policy.denied-tools` | `APP_TOOLPOLICY_DENIEDTOOLS` | empty |
| `app.tool-policy.denied-global-skills` | `APP_TOOLPOLICY_DENIEDGLOBALSKILLS` | empty |
| `app.skills.sources[0].path` (`repo`) | `SKILLS_REPO_PATH` | `../../.agents/skills` (the `docker` profile sets `/opt/ascend/skills/repo`, see below) |
| `app.skills.watch.quiet-period` | `APP_SKILLS_WATCH_QUIETPERIOD` | `500ms` |
| `app.skills.watch.rescan-interval` | `APP_SKILLS_WATCH_RESCANINTERVAL` | `60s` |
| `app.skills.limits.max-skill-bytes` | `APP_SKILLS_LIMITS_MAXSKILLBYTES` | `65536` |
| `app.skills.limits.max-description-chars` | `APP_SKILLS_LIMITS_MAXDESCRIPTIONCHARS` | `1024` |
| `app.skills.limits.max-skills` | `APP_SKILLS_LIMITS_MAXSKILLS` | `200` |
| `app.skills.limits.max-file-bytes` | `APP_SKILLS_LIMITS_MAXFILEBYTES` | `262144` |
| `app.skills.limits.max-reason-chars` | `APP_SKILLS_LIMITS_MAXREASONCHARS` | `300` |
| `app.skills.search.enabled` | `APP_SKILLS_SEARCH_ENABLED` | `true` |
| `app.skills.search.top-n` | `APP_SKILLS_SEARCH_TOPN` | `5` until task 5.7 sets the measured value |
| `app.skills.search.score-threshold` | `APP_SKILLS_SEARCH_SCORETHRESHOLD` | read at implementation time: task 5.7 measures it against the repository skills, `0.4` (the RAG threshold) is only its starting point |
| `app.skills.search.always-listed` | `APP_SKILLS_SEARCH_ALWAYSLISTED` | empty |
| `app.skills.index.providers` | `APP_SKILLS_INDEX_PROVIDERS` | empty (every provider of `app.embedding.providers`) |
| `app.skills.git.author-name` | `APP_SKILLS_GIT_AUTHORNAME` | `ascend-agent` |
| `app.skills.git.author-email` | `APP_SKILLS_GIT_AUTHOREMAIL` | `ascend-agent@localhost` |

`max-reason-chars` bounds the optional `reason` of the write tools of every catalog type (`skill_write` here, `subagent_definition_write` of `add-agent-subagents`), the way the watcher settings apply to every type (answer 98, it was the fixed 300 characters that `add-self-improvement` asked for).

The two container paths are not compose lines. `/app/agent-home` and `/opt/ascend/skills/repo` are the mount targets of the named volume and of the read-only bind mount (D12), and the Dockerfile creates `/app/agent-home` owned by `app`, so the `docker` profile writes them next to each other and a compose override of one without the mount would point at an empty folder. `APP_AGENTHOME` and `SKILLS_REPO_PATH` still override them, for example for `bootRun`. Where the agent home data lives is chosen through the volume (answer 98.8). The collection names and sizes of `app.vectorstore.collections` stay plain configuration with no variable, because a name is not an operator value and a size is fixed by the embedding model.

The relative default of the read-only source resolves from `apps/ascend-agent`, the working folder of `./gradlew bootRun`. `app.agent-home` is the one place the agent home root is set, and both the writable source here and `app.subagents.definitions.root` of `add-agent-subagents` default to it, so the two changes always share one root. `add-agent-soul` reads it directly for its files and adds no root property of its own. It defaults to `${user.home}/.ascend-agent` for `bootRun`, outside the project repository. The `docker` profile sets the read-only source to `/opt/ascend/skills/repo` and `app.agent-home` to `/app/agent-home`. The writable source is the root holding the tenant folders `tenants/<tenantId>/`, each with its skills repository `skills/` (D7). `index.providers` empty means every provider in `app.embedding.providers`. `SkillProperties` is a validated `@ConfigurationProperties` class that refuses zero or negative limits, a description limit above 1024, more than one writable source, a writable source that is not the last entry, a `top-n` below 1, a `score-threshold` outside 0 to 1, and an `index.providers` entry that is not in `app.embedding.providers`.

The `search.score-threshold` default is the RAG pipeline's measured 0.4 as a starting point. Task 5.7 measures it against the repository skills and sets the shipped default from that measurement.

There is no `app.skills.enabled` flag. The whole feature is the module `skills` of the catalog of `add-deployment-modules` (its D3): it is active when `skills` is in `app.modules.active`, bound from `ASCEND_MODULES`, which compose fills from `COMPOSE_PROFILES`. The skill registry, the catalog of D24 (`CatalogLoader`, `CatalogHolder`, `CatalogWatcher`, `CatalogWriteService`, `CatalogChangeNotifier` and `CatalogController`), the tools `Skill`, `skill_search`, `skill_read_file` and `skill_write`, and `SkillProperties` carry `@ConditionalOnModule("skills")`, so with the module off none of them is a bean, `/api/v1/skills` answers the normal 404 problem detail, and no skill folder is read. A tenant whose policy does not grant `skills` gets no skill tool (the module filter of D3) and 403 with code `module_denied` on `/api/v1/skills` (`add-deployment-modules` D8). The capability index, `CapabilitySource`, `CapabilityIndexSync`, `ChatToolset`, `AgentNativeTool`, `TenantToolPolicy`, `VersionedFolder` and `app.agent-home` belong to `core-chat` and carry no marking, because `add-mcp-tool-servers` finds tools through the index and `add-agent-soul` uses the folder component and the agent home root with `skills` off. The one setting that switches a part inside the module is `app.skills.search.enabled`. Agent writes are turned off by listing `skill_write` in `app.tool-policy.denied-tools`, the one switch for a tool (answer 89.17), and the watcher has no switch (answer 90). The watcher settings `app.skills.watch.quiet-period` and `app.skills.watch.rescan-interval` apply to every catalog type, because the catalog is part of the module `skills`, which `subagents` requires (D24).

### D12: Compose and image

The `ascend-agent` service mounts `./.agents/skills:/opt/ascend/skills/repo:ro` and a named volume `agent-home:/app/agent-home`, the agent home root that `add-agent-subagents` reuses for its definitions and `add-agent-soul` for its personality and user facts files, neither with a volume of its own. A new named volume is created owned by root unless the image already holds that folder, so the Dockerfile creates `/app/agent-home` owned by `app` before `USER app`, and Docker copies that ownership into the volume on first use. The capability index lives in the existing Qdrant prerequisite, so compose gains no new service. The service also gains one `- ENV=${ENV:-default}` line for every setting of D11 that has one (answer 98).

One machine or several (answer 98.8 of 2026-10-08): on one machine every agent copy mounts the named volume `agent-home`. On several machines the volume `agent-home` is declared as an NFS-backed named volume (the `local` volume driver with `driver_opts` of `type: nfs`, the NFS server address and the exported path), which every machine mounts at the same `/app/agent-home`. That is a compose and host setup only, with no code change, and `docs/DEPLOYMENT.md` documents it (task 9.4). The NFS server, its address and its export path are chosen by the operator and are written in the document as placeholders. The catalog stays correct on NFS because every write, revert and commit runs under the Postgres advisory lock of D6, so JGit never writes one repository from two machines at once, and because a file event on one machine does not reach the watcher of another, the `catalog_changed` notification and the rescan of D24 bring every other machine in step.

### D13: Pieces shared with add-agent-subagents

`add-agent-subagents`, which lands right after this change, needs the same two libraries and its own JGit backed folder with a validated write path, origin trailers, history and revert. To keep one way of doing each thing, this change writes the git part as a small generic component, `VersionedFolder` (open or initialise a repository, commit with given trailers, commit uncommitted changes as external, history for a path, read a path at a commit), with nothing skill specific in it. `SkillRepository` uses it with the `Skill-*` trailers. The capability index (D18 to D21) is written the same way: nothing in it is skill specific except the `skill` type value, the subagent definitions register through `CapabilitySource` as type `subagent`, and the MCP tools of `add-mcp-tool-servers` as type `tool`. Since answer 89.5 of 2026-10-08 the catalog itself is shared too: `add-agent-subagents` adds its definitions as the type `subagent` of the one catalog of D24 and writes no loader, snapshot, watcher, write path or controller of its own.

This change is build group 4, position 1 of the owner build order of 2026-10-04, the first personal change. It therefore owns and creates the two library entries in the version catalog, `ChatToolset`, `AgentNativeTool`, the tool context keys of D3, `VersionedFolder`, the one catalog of D24 with `CatalogType`, `CatalogLoader`, `CatalogHolder`, `CatalogWatcher`, `CatalogWriteService`, `CatalogChangeNotifier` and `CatalogController`, the policy ports `TenantToolPolicy` and `GlobalSkillPolicy` (D16) and the capability index with `CapabilitySource`, `CapabilityIndexSync` and `skill_search`. The later changes reuse them and add none of their own. The tenant comes from `TenantContext.currentTenantId()` of `add-keycloak-login` (build group 3, position 3), so this change adds no tenant seam (D15).

### D14: Metrics and logs

Names follow `add-observability` D2 (lowercase, dot separated) and D5 (cardinality), the same rule `add-agent-subagents` and `add-agent-sandbox` follow. The first segment is the singular name of the domain, as in the metrics the agent already has (`mcp.tool.duration`, `rag.retrieval.duration`, `memory.search.duration`, `chat.history.size`), so this change uses `skill.` and `capability.`, `add-agent-subagents` uses `subagent.` and `add-agent-sandbox` uses `sandbox.`:

| Metric | Type | Tags |
|---|---|---|
| `skill.catalog.size` | gauge | `source` |
| `skill.catalog.version` | gauge | none |
| `skill.catalog.last_good` | gauge | none |
| `skill.load.skipped` | counter | `reason` |
| `skill.reload` | timer | `trigger`, `outcome` |
| `skill.tool.calls` | counter | `skill`, `outcome` |
| `skill.search` | timer | `outcome` |
| `skill.write` | counter | `origin`, `operation`, `outcome` |
| `capability.index.sync` | timer | `type`, `provider`, `trigger`, `outcome` |
| `capability.index.pending` | gauge | `type`, `provider` |

No metric carries a tenant tag, following `add-observability` D5. Tenant level detail goes to the log lines and the audit log. The `provider` tag is bounded by `app.embedding.providers` (three today) and `type` by its three values, `skill`, `subagent` and `tool`. The two `capability.index.*` metrics are the only index metrics: `add-agent-subagents` measures its definition syncs through them with type `subagent` and `add-mcp-tool-servers` its tool syncs with type `tool`, and neither adds one of its own.

`SkillUsedEvent(tenant, name, requestId)`, which `add-self-improvement` asked for, is not published by this change, because nothing here listens to it (answer 93 of 2026-10-08). `add-self-improvement`, its only listener, publishes it from the `Skill` function in its own task.

The `skill` tag is bounded by `max-skills`. The `trigger` tag of `skill.reload` is one of `startup`, `watcher`, `rescan`, `notify` (a `catalog_changed` notification of another instance, D24), `endpoint` and `write`. The per-request saving of D22 is measured once by task 5.8 and kept in the decision record, so no gauge repeats that one-off measurement (answer 93). `skill.search` outcomes are `hit`, `no_match`, `text_match` (the fallback of D19 answered) and `error`. The `Skill`, `skill_search`, `skill_read_file` and `skill_write` calls also appear in the existing `mcp.tool.duration` timer and in the response's tools-used list through `ToolCallTracker`, with no extra code. Log lines are the ones the specs name. Bodies are never logged, and a search log line holds the query length, the result names and scores, never the query text, because the query can carry user data. `StartupLogConfig` gains one block listing each folder, its path, writable flag and loaded count, the skipped count, the indexed providers with their collection names, and the always-listed names.

### D15: Skills are global or tenant keyed, and the personal deployment is tenant `default`

Every store of the platform is keyed by tenant. Skills follow the same rule:

- Skills in the read-only folders (the repository folder and any shipped folder) are global. They are the same for every tenant and are never written.
- Skills written by the agent or by an owner belong to the caller's tenant and live in `<writable root>/tenants/<tenantId>/skills/<skill>/`. A tenant never sees, reads, writes, reverts, deletes or finds through search another tenant's skills.
- In the personal deployment every request runs as tenant `default`, so the first start creates `<writable root>/tenants/default/skills/`. No migration is needed later, because the folder layout and the index entries are tenant keyed from the first day.
- The tenant comes from the one tenant seam of the platform, `TenantContext.currentTenantId()` in `com.lukk.ascend.ai.agent.security`, defined by `add-keycloak-login` (its D3 and task 3.9, owner decision 65.23 of 2026-10-04), which lands earlier. It answers the tenant of the resolved identity of the current request (`default` in the personal deployment) and throws when no identity is resolved, so a skill read, write or search with no tenant fails closed and never falls back to `default`. This change adds no tenant seam of its own, and `add-agent-subagents`, `add-agent-sandbox` and `add-agent-soul` read the same accessor. `StreamingChatExecutor` puts its value into the tool context as `tenant_id` (D3). A background thread that acts for a stored row binds that row's tenant with `TenantContext.runAs(tenantId, action)` of the same change.

### D16: A tenant policy decides which skills a tenant is offered and can find

Which global skills and which tools a tenant is offered is decided by two small ports this change owns, both `core-chat` beans registered with `@ConditionalOnMissingBean`, so a later implementation replaces the default with no edit here (owner rule of 2026-10-04: company work only plugs in through extension points with safe defaults):

- `GlobalSkillPolicy.isOffered(tenantId, skillName)` decides whether a global skill is offered to a tenant. Its default `ConfiguredGlobalSkillPolicy` hides only the global skills listed in `app.tool-policy.denied-global-skills` (empty by default), so the personal deployment offers every shipped skill until the owner lists one. It is applied when the per-request catalog is assembled (D3). This change also gives `SkillCatalog.globalSkillNames()`, the names of the global catalog after its first load at each startup, for an implementation that needs to seed a list from them.
- `TenantToolPolicy.allows(tenantId, toolName)` decides whether a tool is offered at all. `ChatToolset` applies it in step 2 (D3) to every MCP tool and every agent native tool, `Skill`, `skill_read_file` and `skill_write` here, and `ToolPermission` of `add-agent-subagents` applies the same port again when a run starts. Its default `ConfiguredTenantToolPolicy` denies only the tools listed in `app.tool-policy.denied-tools` (empty by default), for every tenant alike, and `skill_search` follows `app.skills.search.enabled` here. The deny list is the only switch that turns one of these tools off, and no tool has a second switch of its own (answer 89.17). Both lists live in the block `app.tool-policy`, outside `app.skills`, because the two ports are `core-chat` and exist with the `skills` module off (ruling 13.2 of 2026-10-05). A name in either list that matches no tool or skill is logged once at WARN at startup and otherwise ignored. `skill_search` is not a separate entry: it is offered when `Skill` or the `Task` tool of `add-agent-subagents` is offered.

A tenant's own skills are always offered to that tenant when `Skill` is allowed, because the tenant wrote them. `skill_search` searches only the per-request catalog (D19), so a search never returns a skill the policy hides and a policy change reaches the next request with no reload and no reindex.

`add-tenant-policy` (company, build group 5) registers its implementations of both ports later: a skill allow-list of global skill names per tenant (empty for a new tenant, every global skill for tenant `default`, seeded at agent startup from `SkillCatalog.globalSkillNames()` because skills are files on disk), and its tool allow-list, where `skill_write` ships switched off for a new tenant. This change does not wait for it.

### D17: Audit, erasure and export

Audit, in this change:

- Every accepted or refused write, delete and revert, from the agent or the owner, and every call of the reload endpoint, is published as one `AuditEvent` through `AuditEventPort.record` of `add-deployment-modules` (its decision "Company extension ports"), with actor, tenant, action (`SKILL_CREATED`, `SKILL_UPDATED`, `SKILL_DELETED`, `SKILL_REVERTED`, `SKILL_RELOADED`, the upper case past tense names of the closed vocabulary of `add-audit-and-gdpr-compliance` D3), target (kind `skill`, id the skill name), outcome, request id, and origin and commit id in `details`. The body is never in the event. The default `LogAuditEventPort` writes one structured INFO line per event. `add-audit-and-gdpr-compliance` (company, build group 5) registers its `AuditRecorder` backed implementation later. This change does not wait for it.

Erasure and export, added later by `add-audit-and-gdpr-compliance` in its own tasks (dependency fix of 2026-10-05), on the layout this change keeps:

- Tenant erasure deletes the tenant's skills folder `<writable root>/tenants/<tenantId>/skills/`, git history included, then removes the tenant folder `tenants/<tenantId>/` when nothing else is left in it, and every capability index entry of that tenant in every collection, of every type (`skill`, `subagent`, and `tool` for a tenant-scoped server), and reports the number of skills removed. The step that `add-audit-and-gdpr-compliance` writes for `add-agent-subagents` relies on this for the index and deletes only the definitions folder and run rows. Because each tenant has its own repository (D7) and every tenant entry carries its tenant id (D18), this needs no history rewrite and touches no other tenant.
- Tenant export adds the tenant's skill folders at their newest commit plus a `git bundle` of the tenant repository to the archive. The index entries are derived data rebuilt from the folders and are not exported.
- Per user erasure deletes no skill. Tenant skills are shared within the tenant and are not attributed to one user, like the document registry in that change. Git and the index hold no user id (D8, D18), and the audit rows that link a request to a user are pseudonymised by that change.

This change provides the audit publishing call through `AuditEventPort`. `SkillTenantStore.deleteTenant(tenantId)` and `SkillTenantStore.exportTenant(tenantId, sink)` are written by `add-audit-and-gdpr-compliance`, which owns erasure and export.

### D18: One capability index in the existing Qdrant, shared by skills and subagents

`CapabilityIndex` stores one entry per offered capability and embedding provider. It is not skill specific: an entry has a `type` (`skill` here, `subagent` from the definitions of `add-agent-subagents`, `tool` from the MCP tools of `add-mcp-tool-servers`), a name, a description, a scope and an embedding provider. A search of one type never returns an entry of another type.

Capabilities reach the index through one small interface, `CapabilitySource`. A source has one type and gives, for the tool context of one chat request or run, the list of entries that request may see (name, description and entry key). It also reports every snapshot it publishes to `CapabilityIndexSync` (D20). The skill catalog is the source of type `skill`. The subagent definition registry of `add-agent-subagents` is the source of type `subagent`, and the tool registry of `add-mcp-tool-servers` the source of type `tool`. Neither adds index code of its own. A `tool` entry is global in scope and holds no tenant, except a tool of a tenant-scoped server entry (the integrations of `add-self-built-integrations`), which is a tenant entry keyed by that tenant like a tenant skill.

Reuse of the existing setup, never a second client:

- `VectorStoreConfig` stops creating embedding models inline and exposes them as one bean, `Map<String, EmbeddingModel> embeddingProviderModelMap`, built from `app.embedding.providers` exactly as today. The RAG stores in `embeddingProviderStoreMap` are built from that map, so RAG behaviour does not change. The capability index builds one `QdrantVectorStore` per indexed provider on the same `QdrantClient` bean and the same embedding model, with collection `ascendai-capabilities-<dimensions>`.
- The two collections are added to `app.vectorstore.collections`, so the existing `AppConfig.initVectorStore` creates them with cosine distance like the RAG collections.
- The per-provider capability stores are one bean, `Map<String, VectorStore> capabilityStoreMap` keyed by embedding provider, next to `embeddingProviderStoreMap`. `CapabilityIndex` writes, deletes and searches through it, and the tenant-filtered search method that `add-tenant-isolation` adds later picks the store from the same map for the target `CAPABILITIES` (D19), so no caller hands that method a store.

Collections and models: the collection is chosen by embedding dimension, the rule the RAG collections and AscendMemory already follow, so `lmstudio` and `gemini` share `ascendai-capabilities-768` and `openai` uses `ascendai-capabilities-1536`. Unlike RAG, the index writes entries for several providers into one collection, and vectors of two different models are not comparable even at the same dimension. So every entry carries `embedding_provider` in its payload, and every search and every delete filters on it. A search never compares a `gemini` query vector with an `lmstudio` entry vector.

Entry content: the embedded text is `<name>: <description>`. The payload holds `type`, `name`, `scope` (`global` or `tenant`), `tenant` (the tenant id, or empty for global), `entry_key` (`<scope>/<tenant>/<name>`), `source` (the folder identifier), `embedding_provider` and `content_hash` (SHA-256 of the embedded text). The point id is a name-based UUID of `<embedding_provider>|<type>|<entry_key>`, so writing the same entry again replaces it. No user id and no body is stored. Global entries are written once, not once per tenant.

Embedded text leaves the process when an indexed provider is remote (`openai`, `gemini`), as RAG chunks already do. A tenant that must not send skill descriptions to a remote provider is served by leaving that provider out of `index.providers`.

### D19: The skill_search tool

`skill_search` takes `{query, type}`: a short description of the task, and the type to search, `skill` (the default) or `subagent`. It embeds the query with the request's embedding provider, which `AscendChatService` already resolves and which `StreamingChatExecutor` now puts into the tool context as `embedding_provider` next to `user_id`, `request_id` and `tenant_id` (D3). It then calls `CapabilityIndex.search` with:

- the type,
- the request's embedding provider,
- the allowed entry keys: the `entry_key` of every entry the `CapabilitySource` of that type gives for this request (D18). For type `skill` that is every skill in the request's per-request catalog (D3), which is already filtered by tenant and policy (D15, D16). For type `subagent` it is every definition in the tenant snapshot the request or run started with (`add-agent-subagents` D3),
- `top-n` and `score-threshold` from configuration.

The Qdrant filter is `type == '<type>' && embedding_provider == '<provider>' && entry_key in [<allowed keys>]`, built as one `FilterExpressionBuilder` expression, so tenant scoping and policy are applied by the vector store before ranking and the top N are the best of what this request may see.

One search call site: `CapabilityIndex.search` is the only class of this change that searches the capability collections, and `skill_search` and the `toolSearchTool` of `add-mcp-tool-servers` both search through it. In this change `CapabilityIndex.search` calls the store from `capabilityStoreMap` (D18) itself with the filter above, which is safe because the allowed entry keys already hold only the request tenant's entries and the global ones, and the tenant is read from `TenantContext.currentTenantId()`, which fails closed (D15). `add-tenant-isolation` (company, build group 5) later moves this one call onto its tenant-filtered search method `TenantFilteredVectorSearch.search` with the target `CAPABILITIES` and the filter above as the narrowing conjunct, in its own tasks. This change does not wait for it, and keeping the call in one method is what lets that later change move it without touching any caller. A failed search, a fail closed refusal included, gets the text match below. The result is checked again in Java against the source's list, and the name and description returned to the model come from that list, never from the index payload, so an index entry that lags a reload can never show stale or hidden text. Hits below the threshold are dropped, as `RagRetrievalService` does.

A type with no registered source, or whose tool is not offered in this request (`Skill` for type `skill`, `Task` for type `subagent`), is answered with a message that no capability of that type is available, and nothing is searched. The input schema always holds both values, so the tool definition does not change with the tenant or the request.

Text match fallback: the index for a provider is not ready until its first rebuild finished (D20), and an entry is pending until it is written. When the provider is not indexed, not ready, or the search call fails, `skill_search` answers with a text match over the source's list for this request instead: the query is split into lower-case words, each skill scores the number of distinct query words found in its name or description, skills with no match are dropped, and the top N by score then name are returned. When the vector search succeeds but some entries of the source's list are still pending for that provider, the text match is run over those entries only and its hits fill the places left after the vector hits, up to N. The answer says which method produced each hit. So a new skill or definition is findable from the moment its write succeeds, and an embedding outage degrades search instead of breaking it.

Draft texts used for the size measurement in Context, final wording set at implementation:

```text
Search the skills available in this conversation by what you need to do. Pass a short description of the task as query. Returns up to 5 skills, best match first, each with its name, description and match score. Load a returned skill with the Skill tool. Call this before starting a task that may have a stored procedure, format or checklist.
```

The sentence for the `type` parameter (set `type` to `subagent` to find a subagent to start with the `Task` tool) is added to this text at implementation and is not in the measurement of Context. So is one more sentence that `add-mcp-tool-servers` asks for: tools are found with `toolSearchTool`, not with `skill_search`. The `type` parameter of `skill_search` therefore takes only `skill` and `subagent`, and entries of type `tool` are searched by `toolSearchTool` of that change through the same index.

```text
Load a skill: stored instructions for one kind of task. Pass the skill name only. Find the right skill with the skill_search tool first. Only a name returned by skill_search or listed below is valid.

<available_skills>
%s
</available_skills>
```

The result lists each hit as name, description and score rounded to two decimals, best first, then one line saying to load a skill with `Skill` (or, for type `subagent`, to start a subagent with `Task`). With no hit it says nothing matches and the task can go on without one. A failure is returned as text and never fails the chat request.

When `search.enabled` is false, `skill_search` is not offered and the `Skill` description lists every skill of the request's catalog, the library's own model. The `Task` tool of `add-agent-subagents` follows the same rule and then lists every subagent definition of the request's tenant in its description (its D6a). This is the rollback switch.

### D20: The index follows the catalog

`CapabilityIndexSync` keeps the index in step with the catalogs. Every `CapabilitySource` (D18: the skill catalog here, the subagent definition registry in `add-agent-subagents`) reports, for one type and one scope (global, or one tenant), the full list of entries after each published snapshot, with the trigger that published it. The sync runs on its own single thread, after the snapshot swap, so a reload and a chat request never wait for embedding calls.

- Startup: for each indexed provider, the global scope and every tenant skills folder found are rebuilt: write all current entries, then delete the entries of that type, provider and scope that are not in the current list, so two agent instances rebuilding at once never leave a scope empty (answer 87). The provider is marked ready when its rebuild finishes.
- `POST /api/v1/skills/reload`: the same full rebuild for the global scope and the caller's tenant. `POST /api/v1/subagents/definitions/reload` of `add-agent-subagents` asks for the same full rebuild for type `subagent` and the caller's tenant.
- Watcher, rescan, notification and write: an incremental update against the last snapshot the sync saw for that scope. An added entry or an entry whose `content_hash` changed is written, a removed entry is deleted by point id. A skill or definition held at its last good version keeps its last good text in the index, because the source reports its snapshot with that text.
- Failure: an embedding or Qdrant failure leaves the affected entries pending and logs one WARN line per provider and scope with the cause. The one retry trigger below retries them. The agent keeps running and search uses the fallback of D19 for pending entries.
- A provider that is not reachable at startup (for example LM Studio not running) stays not ready, and every retry tick retries its rebuild until it succeeds.
- Retry, one trigger only (answer 93 of 2026-10-08): `CapabilityIndexSync`, which is `core-chat`, retries the pending entries of every type and the providers that are not ready on its own local timer, a `@Scheduled` method on Spring's `TaskScheduler`, every `app.capability-index.retry-interval` (default `60s`), whether the `skills` module is on or off, for the types whose sources are active. The catalog rescan and a published snapshot do not retry. Each instance retries the entries it saw, and every write is keyed by a name-based point id, so it does not matter that every instance runs this timer (answer 87). This property sits outside `app.skills` because the sync is not part of the `skills` module.

Every sync logs one INFO line with type, provider, scope (the tenant id for a tenant scope), trigger, entries written, entries deleted, pending count and duration.

### D21: Embedding providers for the index

`index.providers` lists the embedding providers the index is built for, empty meaning every entry of `app.embedding.providers`. A request whose embedding provider is not indexed always gets the text match. Indexing all three providers by default keeps search working whatever chat provider a request picks, at the cost of three embedding calls per changed skill. Today's full rebuild is 62 entries per provider, 186 embedding calls in all, which the embedding models send in batches.

### D22: A small always-listed set

`search.always-listed` names skills whose name and description stay in the `Skill` description of every request, so the model sees them without a search. A listed name that is not in a request's catalog (unknown, or hidden by the tenant's policy) is left out of that request and logged once at WARN at startup and on change. The default is empty.

Decision (owner, 2026-10-02): the always-listed set is a configurable list that ships empty. None of the 62 repository skills is written for the chat agent: they are coding, document and service skills for coding agents, and the three `ascend-*` skills describe the REST interfaces of services the agent already reaches through its MCP tools, so listing them would cost 1,565 characters per request and point the model at an interface it cannot call. The owner fills the list in configuration once there are skills written for this agent.

### D23: The shared end-to-end harness is not used by this change

The shared end-to-end harness of owner answer 67.1 of 2026-10-04 (the scripted model `e2e-scripted-model`, the fake MCP server `e2e-fake-mcp`, the overlay `apps/ascend-agent/e2e/overlay/application-e2e.yaml` with the provider `scripted`, its lifecycle, which since answer 98.1 of 2026-10-08 copies the overlay into the running agent instead of an `e2e` profile (`close-agent-test-gaps` D7), and its allowlist entries) belongs to `close-agent-test-gaps` (build group 3, position 1). This change used it for one deterministic spec in which the scripted model wrote skills through the chat (task 12.7). Answer 91.3 of 2026-10-08 removed that spec, because `StreamingChatExecutorSkillWriteTest` (task 7.2) and `CatalogWriteServiceSkillTest` (task 7.1) already prove the agent write, its trailers and its `protected` and `shipped_name` refusals with a stub model. So this change adds no script rule to the shared Mockoon environment file, no reply file and no overlay user for a scripted spec, and none of its specs needs the harness. The deterministic spec of task 12.2 calls no model, and the AI-run spec of task 11.2 runs against the agent with the shipped profile and the real AscendMemory, with neither harness container running (owner answer 70.4 of 2026-10-04).

### D24: One catalog for skills and subagent definitions

Skills and the subagent definitions of `add-agent-subagents` are one catalog with two types, `skill` and `subagent`, not two copies of the same machinery (answer 89.5 of 2026-10-08). This change lands first, so it builds the catalog with the type `skill`, and `add-agent-subagents` adds the type `subagent` as one more `CatalogType` bean. Every part below exists once:

- Loader: `CatalogLoader` lists the entries of every read-only folder of a type and of every tenant folder of that type under the agent home root, with the real path, link and size checks of D2, and hands each entry to the type's validator. The type says how an entry is laid out: a skill is a direct child folder holding `SKILL.md` (D2), a subagent definition is one `<name>.md` file in `tenants/<tenantId>/.claude/agents/`.
- Validator per type: `SkillValidator` for `skill` (D2) and `SubagentDefinitionValidator` of `add-agent-subagents` for `subagent`. The loader and the write path call the same validator of the type.
- Snapshot: `CatalogHolder` keeps one immutable `CatalogSnapshot` that holds, per type, the global part and one part per tenant, with the last good rule of D3 for every type. A chat request or a run takes the snapshot once and keeps it (D3), so its skills and its subagent definitions come from the same moment.
- Watcher: `CatalogWatcher` (D5), one watch of the read-only folders and of the agent home tree for every type, with one quiet period and one fingerprint rescan.
- Write path: `CatalogWriteService` (D6), the only class that changes an entry of any type, with the type's own rules (the shipped name rule and the `protected` rule here, the agent-written rules of `add-agent-subagents` D7 there) and one rule for pasted content (D8).
- Git store: `VersionedFolder` (D13), one repository per tenant and type, as D7 lays it out. The type gives its commit trailers (`Skill-*` here, the lower case trailers of `add-agent-subagents` D4 there), because other changes read them.
- Controller: `CatalogController`, one controller with list, read, write, delete, history, revert and reload. The existing URL paths stay as routes onto it: `/api/v1/skills/**` for the type `skill` and `/api/v1/subagents/definitions/**` for the type `subagent`. A route of a type with no registered `CatalogType` bean answers the normal 404 problem detail, so with the module `subagents` off the definition paths answer 404 as before. The type gives its list and read views, so each path keeps its response fields, status codes and error codes.
- Audit, metrics and the capability index: the catalog publishes the audit actions, the metric names and the `CapabilitySource` snapshots that the type names (`SKILL_*`, `skill.*` and the index type `skill` here, `SUBAGENT_DEFINITION_*`, `subagent.definitions.*` and the index type `subagent` there), so the audit vocabulary, dashboards and the index keep their names.

Every feature of both types stays: a hand edit live within the quiet period, under one second, the rescan, both reload endpoints, the last good version, history, revert, the shipped name rule, the agent rules and the index entries. The catalog is part of the module `skills`, which `subagents` requires (`add-deployment-modules` D3). The type `subagent` and its routes are part of the module `subagents`. `VersionedFolder` stays `core-chat` for `add-agent-soul`.

Several agent instances (answer 87, CANON 26.1): every agent instance mounts the same agent home root (the named volume `agent-home` when the instances run on one Docker host), so they read and write the same files and repositories. A write, revert or delete of one tenant and type, and the commit of hand edits with origin `external`, run in one Postgres transaction under the transaction advisory lock keyed by the type and the tenant (D6), so they run one at a time across every instance and two instances never commit in one repository at once. After a reload that publishes a changed scope because of a write, a reload endpoint or a local file event, the instance sends a Postgres `NOTIFY` on the channel `catalog_changed` with the type and the scope (`global`, or the tenant id). The notification is sent with `pg_notify` in the transaction of the write or reload, so it goes out only when that transaction commits, and its payload holds only the type and the scope. `CatalogChangeNotifier` is a `PostgresNotificationHandler` of the one Postgres `LISTEN` connection of the agent, `PostgresNotificationListener` of `add-keycloak-login` D20, registered for the channel `catalog_changed`, and opens no connection of its own. On every instance it schedules a reload of the notified scope with the quiet period of a file event (trigger `notify`), so a write on one instance reaches the snapshot of every other instance without depending on its folder watcher. A reload with trigger `notify` sends no notification of its own. Its `onReconnect()` schedules a reload of every scope, because notifications sent while the connection was down are lost. The rescan of D5 is the fallback for a missed notification. Last good versions of tenant entries come from git when an instance holds none in memory (D3), so every instance serves the same version. The capability index is written by the sync of every instance, which is harmless because every entry is keyed by a name-based point id (D18). Instances on several machines share the agent home root through an NFS-backed named volume `agent-home`, documented in `docs/DEPLOYMENT.md` with no code change (D12, answer 98.8 of 2026-10-08).

Alternatives considered: two copies, one per type (rejected by answer 89.5: two loaders, watchers, write paths and controllers that differ only by accident), and a per-process lock with the folder watcher as the only way a write reaches another instance (rejected by answer 87: a second instance would write and commit at the same time and could miss a write on a file system that drops events).

## Risks / Trade-offs

- [An agent-written skill reaches every user of the same tenant at once, so text from a web page or a document can become standing instructions for everyone] → Shipped names cannot be written at all, owner skills are protected, every agent write is labelled untrusted with the tools seen, the owner can revert any commit, and agent writes can be switched off. Skills the agent writes go live at once by owner decision.
- [The model may not search, or a search may miss the skill that fits] → The `Skill` and `skill_search` descriptions tell the model to search first, the threshold is measured against the repository skills (task 5.7), the always-listed set covers skills that must always be visible, and `search.enabled=false` brings back the full list.
- [The embedding provider of a request is down or not indexed] → Search falls back to a text match over the request's catalog, which needs no network call.
- [Two embedding models share one 768 dimension collection] → Every entry carries its provider and every search and delete filters on it.
- [Index entries lag the catalog after a reload] → The allowed keys come from the request's catalog, returned text comes from the catalog, and pending entries are found by the text match.
- [Skill descriptions written by a tenant are sent to a remote embedding provider] → The same as RAG chunks today, and `index.providers` can leave remote providers out.
- [A change to the always-listed set changes the tool definitions and starts a new provider prompt cache entry] → Any other skill change leaves the definitions unchanged, which is a large improvement on listing every skill.
- [The library is at version 0.x and its public records may change] → Only `SkillsTool.Skill`, `SkillsInput` and `SkillsFunction` are used, the version is pinned, and the catalog tests exercise them directly so an upgrade that breaks them fails the build.
- [Tool calls may run on another thread after the Spring AI 2 upgrade, which would break the per-thread `ToolCallTracker` and the tools-seen record] → Task 7.2 tests the tools-seen value through a real `StreamingChatExecutor` call, so a threading change fails a test rather than silently recording nothing.
- [File events may not arrive for a Docker Desktop bind mount] → The rescan picks the change up within its interval, and task 9.3 measures the real behaviour.
- [A hand edit in a tenant skills folder is committed as `external` even when it is invalid] → History stays complete, the skill keeps its last good version and a WARN line names the file, so the owner sees it and can revert.
- [A last good version hides a broken file from users] → The WARN line, the `skill.catalog.last_good` gauge and the `last_good` entry in the list and reload responses make it visible. A tenant skill keeps its last good version across a restart because it comes from git (D3), so the owner fixes the file or reverts it.
- [Several agent instances write to one agent home root] → One advisory lock per tenant and type across instances, and the `catalog_changed` notification with the rescan as fallback keep every snapshot current (D24). On several machines the agent home root is an NFS-backed named volume (answer 98.8, D12, task 9.4): writes stay serialised by the advisory lock, and a file event that does not cross machines is covered by the notification and the rescan. The NFS server is the operator's to run, and an NFS outage stops writes and reloads until it is back, while the in-memory snapshot keeps serving.
- [JGit adds a dependency of several megabytes] → Accepted in exchange for no `git` binary in the image and no process spawning.

## Required edits to other changes

This change does not edit the changes below. The company changes (build group 5) plug into this change later through the ports and the one search call site named here, and their tasks are in their own tasks.md (dependency fix of 2026-10-05). No task of this change waits for them. The last column records whether the named change reflects the edit, checked against its text on 2026-10-03. The rows for the company changes are restated on 2026-10-05 for the ports, and each company change adapts its own text in the same fix. The second table lists the edits other changes asked of this change, made here on 2026-10-02.

| Change | Required edit | Status |
|---|---|---|
| `add-tenant-isolation` | Add skills to the tenant scoped stores: skills written by the agent or an owner live under `<writable root>/tenants/<tenantId>/skills/`, read-only skills stay global, capability index entries carry the tenant id, and the personal deployment runs as tenant `default`. The tenant comes from `TenantContext.currentTenantId()` of `add-keycloak-login`, which already fails closed, so no seam needs replacing (D15). Its one tenant-filtered search method `TenantFilteredVectorSearch.search` serves the capability index with the target `CAPABILITIES`, whose mandatory filter admits global entries and entries of the caller's tenant, and it moves the one call of `CapabilityIndex.search` onto that method in its own tasks (D19). | Made for the stores and the search method (its decisions 10 and 12, its `rag-retrieval` and `tenant-isolation` specs and its tasks 1.9, 5.11 and 7.2). The move of the call and its test come from this change in the fix of 2026-10-05 |
| `add-tenant-policy` | Register its implementations of `TenantToolPolicy` and `GlobalSkillPolicy` of this change (D16) in place of the defaults: a skill allow-list of global skill names per tenant, empty for a new tenant, and for tenant `default` seeded at agent startup from `SkillCatalog.globalSkillNames()` (not by its Flyway migration, because skills are files on disk), recording the added names (a column such as `seeded_global_skills`) so a later shipped global skill reaches tenant `default` and a name an `ADMIN` removed stays removed. `Skill`, `skill_read_file` and `skill_write` join its tool allow-list, with `skill_write` off for a new tenant. `skill_search` follows `Skill` or `Task` and needs no entry of its own. A policy denial of a skill tool emits its normal audit event. | Made for the allow-lists and the seed (its D4, D7 and D8, its `tool-policy` spec and its tasks 1.1, 1.5, 3.3, 3.4 and 3.7). Registering them as implementations of the two ports comes from this change in the fix of 2026-10-05 |
| `add-audit-and-gdpr-compliance` | Register its `AuditRecorder` backed implementation of `AuditEventPort` of `add-deployment-modules`, which receives the actions `SKILL_CREATED`, `SKILL_UPDATED`, `SKILL_DELETED`, `SKILL_REVERTED` and `SKILL_RELOADED` that this change publishes (D17). Write `SkillTenantStore.deleteTenant` (the tenant skills folder with its history, then the tenant folder when nothing else is left, plus every capability index entry with that tenant id) and `SkillTenantStore.exportTenant` (folders at the newest commit plus a git bundle) and register them with its erasure and export jobs. State that per user erasure removes no skill and that git and the index hold no user id. | Made for the vocabulary and the inventory (its D3 vocabulary, its `audit-logging` spec, its D9 erasure and export inventory and its tasks 5.3b and 8b.2). The two store operations and their tests come from this change in the fix of 2026-10-05 |
| `add-agent-subagents` | Made in that change on 2026-10-02. It uses the `ChatToolset` and `AgentNativeTool` composition point, the tool context keys of D3, `TenantContext` of `add-keycloak-login`, the `TenantToolPolicy` port, the `VersionedFolder` git component and the two library entries in the version catalog from this change instead of adding its own, and uses the same folder layout (D7): its definitions live in `<writable root>/tenants/<tenantId>/.claude/agents/` under the same agent home root `app.agent-home`, as their own git repository next to the tenant's `skills/` repository. Its definition registry is the `CapabilitySource` of type `subagent` (D18), reports every published tenant snapshot to `CapabilityIndexSync` (D20), and the model finds definitions with `skill_search` and type `subagent` (D19). Its index syncs are measured by the `capability.index.*` metrics of D14. Since answer 89.5 of 2026-10-08 its definitions are the type `subagent` of the one catalog of D24, so it adds no loader, snapshot, watcher, write path or controller of its own, and its definition paths are routes of `CatalogController`. | Made |
| `add-chat-streaming-and-conversations`, `add-agent-soul`, `add-tenant-policy`, `add-flutter-chat-app` | Made in those changes on 2026-10-02. Each describes its agent error bodies as the RFC 7807 problem detail that `upgrade-spring-boot-4` defines (the fields of D10) instead of `ApiError`, and depends on `upgrade-spring-boot-4` for it. | Made |
| `upgrade-spring-boot-4` | None. Its D19 and its `agent-error-responses` spec define the problem detail this change uses, including the extension field `errors` (its D19 point 5). The shared codes and `shipped_name` of D10 are added to its `ApiErrorCode` enum by task 8.1 here, and the validation reasons answer its code `validation` with the `errors` field. | Nothing to edit |
| `add-keycloak-login` | None. It lands before this change, and this change adds its own matrix rows for the skill endpoints (D10, task 8.3) and its rows to the role matrix spec of that change's task 10.7 (task 12.5), the rule of its D4. | Nothing to edit |

Edits other changes asked of this change, made here on 2026-10-02. The design text below stays in this change. The code that adds a step to `ChatToolset` or a type to the capability index belongs to the later change that asked for it, in its own tasks, because a change may only depend on changes that land earlier (dependency fix of 2026-10-05):

| Asked by | Edit made in this change |
|---|---|
| `add-deployment-modules` | `app.skills.enabled` is removed. The module `skills` covers the registry, the skill tools, `skill_search` and `/api/v1/skills`, with `@ConditionalOnModule("skills")` (D11). The capability index, `CapabilitySource`, `CapabilityIndexSync`, `ChatToolset`, `AgentNativeTool`, `TenantToolPolicy` and `app.agent-home` are `core-chat` with no marking. `ChatToolset` drops tools of modules not effective for the tenant (D3 step 1). |
| `add-action-approvals` | `ChatToolset` wraps every tool whose mode is `requires_approval` in the approval gate, after the policy filter, so the gate covers every MCP and agent native tool in one place (D3 step 5). |
| `add-mcp-tool-servers` | The entry type set is `skill`, `subagent` and `tool`, a `tool` entry is global except a tool of a tenant-scoped server entry (the self-built integrations of `add-self-built-integrations`), which is a tenant entry keyed by that tenant, and a search of one type never returns another (D18). The `type` tag of the two `capability.index.*` metrics has three values (D14). `ChatToolset` returns the tools in two parts, always and deferred, and every agent native tool is always (D3 step 6). The `skill_search` description says that tools are found with `toolSearchTool` (D19). |
| `add-openclaw-plugin-host` | `ChatToolset` takes an optional per-request allow list that narrows the tool list after the policy filter and before the approval wrapping, so a peer bot turn gets only `app.channels.peer-bots.allowed-tools` (D3 step 3). Without the list nothing changes. |
| `add-download-ingestion` | `knowledge_add_download` is one more `AgentNativeTool`, governed by the tenant tool allow-list like the others (D3). |
| `add-self-improvement` | `ChatToolset` wraps the self-write tools in `SelfChangeGate` after the policy filter and before the approval wrapper (D3 step 4). The write path accepts the trailers `Skill-Reason`, `Skill-Patch`, `Skill-Self-Change-Id` and `Self-Provenance` from its caller and the origin `guard` for the guard's revert, which no tool can write, and the agent may update a skill whose newest origin is `agent` or `guard` (D6, D8). `skill_write` gains the optional argument `reason` of at most 300 characters (D9). `SkillUsedEvent(tenant, name, requestId)` is no longer published here: by answer 93 of 2026-10-08 that change, its only listener, publishes it from the `Skill` function in its own task (D14). The "live at once" rule gains one exception: a chat write in a request whose request provenance is not `clean` waits for one tap of approval of kind `self_change` (owner answer 38.1, default `stage` of `app.self-improvement.provenance.chat-write-untrusted`), and the Non-Goals line names that change as the one that decides when to write (D6). |
| `add-self-built-integrations` | The tenant folder gains the repository `integrations/`, read and written only by that change, and the skills watcher ignores it (D5, D7). A `tool` entry of a tenant-scoped server is tenant keyed (D18). |
| `add-scheduled-tasks` | Nothing asked. The skill folder rescan stays local work (D5). |

## Decision record numbering

The decision record of this change (task 2.4) takes the next free ADR number in `apps/ascend-agent/docs/architecture/decisions/` at implementation time, never a number fixed now. `upgrade-spring-boot-4`, which lands earlier, adds its own record in that folder, and `add-agent-subagents`, which lands after this change, takes the next free number after this one, so no number is predicted here. The new e2e spec (task 11.2) takes the next free spec number the same way.

## Migration Plan

1. Apply build group 3 first, in particular `close-agent-test-gaps`, `upgrade-spring-boot-4`, `add-keycloak-login` and `add-deployment-modules` (build group 3, positions 1, 2, 3 and 6). This change is build group 4, position 1, and `add-agent-subagents` and then `add-agent-sandbox` are applied after it.
2. Add `skills` to `COMPOSE_PROFILES` (the module list of `add-deployment-modules`) and deploy with the default configuration. The writable root, the skills folder of tenant `default` and its repository are created on first start, the two capability collections are created by the existing collection initializer, and the index is built in the background. Nothing existing changes, and RAG keeps its collections and behaviour.
3. Rollback: remove `skills` from `COMPOSE_PROFILES` (and so from `ASCEND_MODULES`), and remove the modules that require it, because the selection check of `add-deployment-modules` (its D4) refuses at startup a list that keeps `subagents` without `skills`, or deploy the previous image. The writable volume and its git history stay for a later return. The capability collections hold only derived data and can be left or deleted. To keep skills but drop search, set `app.skills.search.enabled=false`.

## Owner decisions of 2026-10-07

Answer 75.1: the owner approved the fix of every item of the review of the group 3, 4 and 5 changes of 2026-10-07. Fixed here: item 19 (`add-deployment-modules` is build group 3, position 6), item 20 (the in-memory user is gone from the proposal), item 21 (the `ADMIN` rows of `add-keycloak-login` D4 already answer 403, this change adds the problem body with code `forbidden`), item 22 (tenant erasure of the capability index is written by `add-audit-and-gdpr-compliance`), item 25 (the overlay user `frostyAgentSkillsScriptedTest` is added by task 12.7), item 60 (the tenant comes from `TenantContext.currentTenantId()`, no wording about missing tenant resolution), item 62 (three specs), item 64 (`traceId` in the problem body field list of D10) and item 66 (the audit event names its `target`).

## Owner decisions of 2026-10-08

Answer 76.9: the problem body with the code `forbidden` for a 403 moves into `add-keycloak-login` (its D4 and task 2.10), so every 403 has that body from that change on. This change reuses the code and the `AccessDeniedHandler` and no longer introduces them (D10, tasks 8.1 and 8.3). It still owns the shared codes `conflict` and `unavailable`. The record of item 21 under 2026-10-07, which said this change adds the body, is replaced by this answer.

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/skills/` (D23, task 12.7). (Superseded by answer 91.3 of 2026-10-08: task 12.7 is removed and this change adds no script rule.)

Answer 78.2: the deterministic phase has two restarts of AscendMemory and the agent, each followed by a check (`close-agent-test-gaps` D7). The start restart sets the scripted model's address as AscendMemory's `OPENAI_BASE_URL`, a non-blank `OPENAI_API_KEY` and the agent's `e2e` profile, and the end restart, which runs even when a spec fails, brings back the real address and settings. The deterministic spec of task 12.7 runs between them, and the AI-run spec of task 11.2 starts only after the end check has passed (task 11.3). (Superseded by answers 91.1 and 91.3 of 2026-10-08: this change has no spec in the harness phase. Since answer 98.1 of 2026-10-08 there is no `e2e` profile at all: the deterministic phase copies the overlay into the running agent and recreates it at the end, with the steps of `close-agent-test-gaps` D7.)

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (task 12.7). (Superseded by answers 91.1 and 91.3 of 2026-10-08: task 12.7 is removed, and no deterministic spec wipes memories.)

Answer 79.1 and 79.2: the start restart of `close-agent-test-gaps` D7 sets AscendMemory's `OPENAI_BASE_URL` to `http://e2e-scripted-model:3000/v1` and the dummy `OPENAI_API_KEY` `e2e-scripted-not-a-real-key` in the shell of that one command, and the end check confirms the key is no longer this value. The harness containers on the stack's network are `e2e-scripted-model` (the scripted model, at `http://e2e-scripted-model:3000`) and `e2e-fake-mcp` (the fake MCP server). (Superseded by answers 85.1, 91.1 and 91.3 of 2026-10-08: this change has no spec in the harness phase.)

Answer 87: several agent instances run at once, so the catalog is made safe for it (D24): every instance mounts the same agent home root, a write takes a Postgres transaction advisory lock per tenant and type, a write or reload on one instance reaches every other instance through the Postgres notification `catalog_changed` with the rescan as fallback, last good versions of tenant skills come from git so every instance serves the same one (D3), and the capability index rebuild writes before it deletes so two instances never leave a scope empty (D20). The retry timer of the index is local work that every instance may run, because writes are keyed by point id. The Non-Goal that kept the writable root to one instance is removed. Which shared storage serves the agent home root for instances on several hosts was not decided then (decided by answer 98.8 of 2026-10-08: an NFS-backed named volume).

Answer 89.5: skills and subagent definitions are one catalog (D24): one loader `CatalogLoader`, one snapshot `CatalogSnapshot` in `CatalogHolder`, one watcher `CatalogWatcher`, one write path `CatalogWriteService`, one git store `VersionedFolder`, a validator per type, and one controller `CatalogController` with history, revert and reload. The URL paths `/api/v1/skills/**` and `/api/v1/subagents/definitions/**` stay as routes onto it. This change builds the catalog with the type `skill`, and `add-agent-subagents` adds the type `subagent`. Every feature stays, including a hand edit live within the quiet period of 500 milliseconds. Changed: Goals, D3, D5, D6, D10, D11, D13, D24, tasks 1.4, 3.1, 3.8, 4.1, 4.2, 4.7, 7.1 and 8.1, and the catalog and authoring specs.

Answer 89.17: `app.skills.agent-write.enabled` is removed. Listing `skill_write` in `app.tool-policy.denied-tools` is the one switch that turns the tool off (D9, D11, D16, task 7.2 and the authoring spec).

Answer 90: `app.skills.watch.enabled` is removed, because only a test used it. The rescan test of task 4.3 now drops file events through a test watch service (D5, D11).

Answer 91.1: AscendMemory is faked in the one Mockoon container under `/ascend-memory/` for the deterministic phase, only the agent restarts, and no deterministic spec wipes memories (`close-agent-test-gaps` D7). This change has no spec in that phase any more (answer 91.3), so none of its specs restarts anything or wipes memories in a deterministic spec. The AI-run spec of task 11.2 runs against the real AscendMemory and keeps its memory wipe.

Answer 91.2: the fake MCP server `e2e-fake-mcp` is the one fake MCP server class of the agent's test sources (`close-agent-test-gaps` D5). This change writes no fake MCP server of its own and no spec of it uses one.

Answer 91.3: the deterministic spec `<N>-agent-skills-scripted` of task 12.7 is removed, because `StreamingChatExecutorSkillWriteTest` (task 7.2) and `CatalogWriteServiceSkillTest` (task 7.1) prove the agent write, its trailers and its `protected` and `shipped_name` refusals with a stub model. Its overlay user, script rules and reply files are not added, and tasks 11.3, 12.3 and 12.4 and the catalog spec name two specs. The deterministic API spec of task 12.2 stays, because it proves the live mounts, the volume and the last good version after a hand edit inside the container, which no lower test proves. The AI-run spec of task 11.2 stays.

Answer 93: applied here: `SkillUsedEvent` has no listener in this change and is published by `add-self-improvement`, its only listener (D14, task 3.7), the one-off gauge `skill.tool.description.chars` is removed and task 5.8 keeps the measurement (D14, task 3.4), the capability index has one retry trigger, its own timer (D20, tasks 4.3 and 5.3), and pasted content follows one rule for both catalog types, the paste check of D8, so an owner paste in chat is recorded with origin `owner` (D3, D8, task 7.2). Not applied, because it would cut a feature: removing the vector search of the capability index (review item A5).

Answer 89.1: `StreamingChatExecutor` of `add-chat-streaming-and-conversations` is the one chat executor, and this change adds its steps to it once: the one `ChatToolset` call per request and the tool context keys of D3 (D3, D8, D19, tasks 3.3 and 7.2).

Answer 85.1: no plan text of this change tells the owner to export a key or a secret in the shell. The dummy key of answer 79.1 left with task 12.7 (answer 91.3).

Answer 89.4: the `self_change` approval of D6 is one kind of the one approval record `approval_request` of `add-action-approvals`. Nothing else in this change records an approval, so nothing changes here.

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 98: every value of this change with a default is a setting (CANON 31.11): `application.yaml` writes `key: ${ENV:default}`, the properties record carries the same default and the `ascend-agent` service of `compose.yaml` passes `- ENV=${ENV:-default}` (D11, D12, tasks 1.2, 1.3 and 9.1). Made external, with their defaults: `APP_AGENTHOME` (`${user.home}/.ascend-agent`), `APP_CAPABILITYINDEX_RETRYINTERVAL` (`60s`), `APP_TOOLPOLICY_DENIEDTOOLS` (empty), `APP_TOOLPOLICY_DENIEDGLOBALSKILLS` (empty), `SKILLS_REPO_PATH` (`../../.agents/skills`), `APP_SKILLS_WATCH_QUIETPERIOD` (`500ms`), `APP_SKILLS_WATCH_RESCANINTERVAL` (`60s`), `APP_SKILLS_LIMITS_MAXSKILLBYTES` (`65536`), `APP_SKILLS_LIMITS_MAXDESCRIPTIONCHARS` (`1024`), `APP_SKILLS_LIMITS_MAXSKILLS` (`200`), `APP_SKILLS_LIMITS_MAXFILEBYTES` (`262144`), the new `APP_SKILLS_LIMITS_MAXREASONCHARS` (`300`, the reason limit of both write tools, which was a fixed number), `APP_SKILLS_SEARCH_ENABLED` (`true`), `APP_SKILLS_SEARCH_TOPN` (`5`), `APP_SKILLS_SEARCH_SCORETHRESHOLD` (read at implementation time by task 5.7, CANON 31.13), `APP_SKILLS_SEARCH_ALWAYSLISTED` (empty), `APP_SKILLS_INDEX_PROVIDERS` (empty), `APP_SKILLS_GIT_AUTHORNAME` (`ascend-agent`) and `APP_SKILLS_GIT_AUTHOREMAIL` (`ascend-agent@localhost`). The two container paths `/app/agent-home` and `/opt/ascend/skills/repo` stay in the `docker` profile beside their mounts, with no compose line, because they are mount targets of the image and of `compose.yaml`, not operator values (D11). Kept as constants, because they are not operational: the tool names, the collection names `ascendai-capabilities-768` and `ascendai-capabilities-1536` and their sizes (fixed by the embedding models), the tenant slug rule `[a-z0-9-]{1,64}`, the Windows device names, the closed reason, trailer, audit action, metric and channel names, the `skills/<name>` base path, the YAML alias limit (a security bound) and the code point limit (derived from `max-skill-bytes`). Every new or changed setting gets its row in `apps/ascend-agent/docs/CONFIGURATION.md` ending with "Added by `add-agent-skills`." in the same commit (task 1.3).

Answer 98.8: the agent home root on one machine is the named volume `agent-home`. On several machines `docs/DEPLOYMENT.md` documents an NFS-backed named volume `agent-home`, with no code change (D12, D24, Risks, new task 9.4). The open point of D24 and of the Risks is closed.

## Owner decisions of 2026-10-09

Answer 101: LM Studio is used only in tests that test LM Studio support. The search quality measurement of task 5.7 runs with the `openai` embedding provider only, the hosted provider the other AI-run specs use, and `lmstudio` is dropped from it, so the shipped `search.score-threshold` and `search.top-n` come from the `openai` measurement. The capability index scenarios and unit tests that name the `lmstudio` provider entry (pending entries, the shared 768 collection) test the index's provider handling with no running LM Studio and stay.

## Open Questions

None. The owner decided on 2026-10-02 that the always-listed set stays a configurable list that ships empty (D22).
