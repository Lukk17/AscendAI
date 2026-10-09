## Purpose

Gives ascend-agent one searchable index of the capabilities it can offer the model, skills, the subagent definitions of `add-agent-subagents` and the MCP tools of `add-mcp-tool-servers`, stored in the Qdrant vector store the RAG pipeline already uses, kept in step with the folders the capabilities come from, and searched only within what the request's tenant and tenant policy allow.

## ADDED Requirements

### Requirement: The capability index reuses the existing vector store setup

The capability index SHALL be stored in Qdrant through the Qdrant client bean the agent already has and through the embedding models built from `app.embedding.providers`, and SHALL NOT create a second Qdrant client or a second embedding configuration. It SHALL use one collection per embedding dimension, `ascendai-capabilities-768` and `ascendai-capabilities-1536`, listed in `app.vectorstore.collections` so the existing collection initializer creates them with cosine distance at startup. It SHALL NOT write to the RAG collections, and RAG retrieval SHALL behave as before.

#### Scenario: Collections are created at startup

- **WHEN** the agent starts against a Qdrant that has neither capability collection
- **THEN** `ascendai-capabilities-768` with vector size 768 and `ascendai-capabilities-1536` with vector size 1536 exist afterwards

#### Scenario: Qdrant is unreachable at startup

- **WHEN** the agent starts and Qdrant cannot be reached
- **THEN** the agent starts and loads skills
- **AND** `skill_search` answers through the text match

### Requirement: Each entry records its type, scope and embedding provider and never mixes models

Every entry SHALL hold a type (`skill`, `subagent` or `tool`), a name, a scope (`global` or `tenant`), the tenant id for a tenant entry, an entry key made of scope, tenant and name, the source folder identifier, the embedding provider that produced its vector, and a hash of the embedded text. The embedded text SHALL be the name and the description. No entry SHALL hold a body or a user id. A global entry SHALL be stored once per embedding provider, never once per tenant. Every search and every delete SHALL filter on the embedding provider, so a query vector of one provider is never compared with an entry vector of another, even when both share a collection.

#### Scenario: Two providers in one collection stay apart

- **WHEN** `lmstudio` and `gemini` are both indexed into `ascendai-capabilities-768` and a search runs with embedding provider `gemini`
- **THEN** every hit is an entry whose embedding provider is `gemini`

#### Scenario: No body in the index

- **WHEN** the skill `api-design` is indexed
- **THEN** its entry holds the name and description of `api-design` and no text of its body

### Requirement: The index stays in step with the catalogs

The index SHALL be rebuilt for the global scope and every tenant scope at startup, and for the global scope and the caller's tenant on `POST /api/v1/skills/reload`, by writing all current entries of that type and provider and then deleting the scope's entries that are not current, so two agent instances rebuilding at once never leave a scope empty. After every other published snapshot (watcher, rescan, notification, write) it SHALL write each added entry and each entry whose text changed and delete each removed entry. A skill held at its last good version SHALL keep its last good text in the index. Index updates SHALL run after the snapshot swap on their own thread, so no reload and no chat request waits for an embedding call. An embedding or Qdrant failure SHALL leave the affected entries pending, SHALL be logged at WARN once per provider and scope, and SHALL be retried, for every type, by one trigger only, a local timer of the index at its configured retry interval, whether the skills module is active or not. An embedding provider SHALL count as ready for search only after its first rebuild has finished.

#### Scenario: Added, changed and deleted skills

- **WHEN** a skill is added, another one's description is changed and a third is deleted, and the watcher reloads
- **THEN** the index holds an entry for the added skill, the changed skill's entry has the new text hash, and the deleted skill has no entry left for any provider

#### Scenario: Unchanged skill is not embedded again

- **WHEN** a rescan finds a change in one skill only
- **THEN** only that skill's entries are written

#### Scenario: Provider down during a sync

- **WHEN** the embedding provider `lmstudio` cannot be reached when a new skill is added
- **THEN** the agent keeps running, the new skill's `lmstudio` entry is pending and one WARN line names the provider and scope
- **AND** after `lmstudio` is reachable again, the next retry of the index writes the entry

### Requirement: Search returns only what the request is allowed to see

A search SHALL take a type, a query, the request's embedding provider, the entry keys of the request's own capability list (already filtered by tenant and tenant policy), a top N and a score threshold. The vector store query SHALL be filtered by type, embedding provider and those entry keys before ranking, so tenant scoping and policy apply before the top N is chosen. The result SHALL hold at most N entries at or above the threshold, best first, and every hit SHALL be checked again against the request's list. The name and description returned SHALL come from the request's list, never from the index. When the provider is not indexed, not ready or the query fails, the search SHALL answer with a text match over the request's list, scoring each entry by the number of distinct query words found in its name or description, dropping entries with no match and ordering by score then name. When the vector search succeeds and some entries of the request's list are still pending for that provider, the text match over those entries SHALL fill the places left, up to N. The answer SHALL say which method produced each hit.

`CapabilityIndex.search` SHALL be the only place that searches the capability collections. It SHALL read the request's tenant from the tenant context of the login capability, which refuses when no tenant is resolved. That refusal SHALL count as a failed query and SHALL never widen the search.

#### Scenario: Another tenant's entry is never returned

- **WHEN** tenant `acme` has the skill `invoice-checks` indexed and a request of tenant `globex` searches for "invoice checks"
- **THEN** no hit is `invoice-checks`

#### Scenario: Policy filtering before ranking

- **WHEN** the policy of tenant `acme` allows only the global skill `api-design` and an `acme` request searches with top N 5
- **THEN** every hit is `api-design` or a skill of `acme`'s own folder

#### Scenario: Threshold applied

- **WHEN** the score threshold is 0.4 and a search finds entries scoring 0.62, 0.41 and 0.39
- **THEN** the result holds the first two only

#### Scenario: Provider not indexed

- **WHEN** the index is built for `lmstudio` only and a request whose embedding provider is `openai` searches
- **THEN** the answer is produced by the text match and no embedding call is made for the query

### Requirement: The index is shared with subagent definitions and MCP tools

The index SHALL accept entries of type `subagent` and of type `tool` from any capability source that reports its snapshots the same way the skill catalog does, and a search SHALL return only entries of the type it asks for. A search of one type SHALL never return an entry of another type. A `tool` entry SHALL be global, except a tool of a server entry scoped to one tenant, which SHALL be a tenant entry of that tenant. The model SHALL search subagent entries with the same `skill_search` tool and the type `subagent`, and the subagent definitions SHALL use the entry format, the sync, the text match fallback and the metrics of this capability, with no second index component.

#### Scenario: Types stay apart

- **WHEN** a skill `code-reviewer` and a subagent definition `code-reviewer` are both indexed and a skill search for "review my code" runs
- **THEN** every hit has type `skill`

#### Scenario: Tool entries stay out of skill searches

- **WHEN** a global `tool` entry `web_search_query` is indexed and a skill search for "search the web" runs
- **THEN** no hit has type `tool`

### Requirement: Index work is visible in metrics and logs

The agent SHALL publish a timer of index syncs tagged by `type`, `provider`, `trigger` and `outcome`, and a gauge of pending entries tagged by `type` and `provider`, with no tenant tag. Every sync SHALL log one INFO line with type, provider, scope, trigger, entries written, entries deleted, pending count and duration. The startup banner SHALL name each indexed provider with its collection. No log line SHALL contain a body or a search query text.

#### Scenario: Pending entries are visible

- **WHEN** two entries are pending for provider `lmstudio`
- **THEN** the pending gauge tagged `type="skill"`, `provider="lmstudio"` reads 2
