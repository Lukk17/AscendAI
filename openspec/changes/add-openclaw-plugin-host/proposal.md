## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 4 (personal), position 10. It needs `close-agent-test-gaps` (the shared scripted e2e harness), `upgrade-spring-boot-4`, `add-keycloak-login`, `add-deployment-modules`, `add-shared-scheduler`, `add-chat-streaming-and-conversations`, `add-agent-skills`, `add-agent-subagents`, `add-agent-sandbox`, `add-agent-soul`, `add-action-approvals`, `add-mcp-tool-servers` and `harden-cloud-deployment`, all of which land earlier. Later personal changes plug into it: `add-coding-agent-delegation` and `add-scheduled-tasks` (run status messages and owner notifications on Discord), `add-self-improvement` (the Undo buttons of its reports) and `add-self-built-integrations` (the fixed line on its credential prompt). It depends on no company change.

It depends on these changes and edits none of them:

| Change | What this change needs from it |
| :--- | :--- |
| `close-agent-test-gaps` | The shared scripted e2e harness (the scripted model, the fake MCP server and the e2e overlay) for the deterministic e2e specs |
| `upgrade-spring-boot-4` | Spring Boot 4, Flyway versioned SQL migrations, and the RFC 7807 problem detail of its D19 with the one `ApiErrorCode` enum |
| `add-deployment-modules` | The module catalog, `ASCEND_MODULES`, `@ConditionalOnModule` and `ModuleState`, for the modules `channels` and `openclaw-apps`, and the company extension ports `AuditEventPort` and `UsageEventPort` with their safe defaults |
| `add-shared-scheduler` | The owner notification store and its `OwnerNotificationChannel` port, which this change implements with a `discord` channel, and the system task contract for `channel-host-cleanup` |
| `add-chat-streaming-and-conversations` | The `conversations` table, conversation resolution by id, and the streaming chat path whose `delta` and terminal events the relay reads |
| `add-agent-subagents` | The run view, the run kinds (`subagent`, `approval`, `coding`, `scheduled`, `self_review`, `integration`) and `SubagentRunChangedEvent`, delivered after commit, for background run status messages |
| `add-action-approvals` | The approval view, `ApprovalChangedEvent` and `ApprovalService.decide`, for approval buttons on Discord |
| `add-mcp-tool-servers` | One entry per MCP server, `trust: external` defaults, tool search, approval defaults, and the shared egress proxy, for the app plugin tools |
| `add-keycloak-login` | Keycloak, the resolved identity with `sub`, tenant and roles, the confidential clients `ascend-openclaw-host` (scope `channel.relay`) and `ascend-agent-directory`, the identity resolved without a token (its D20), `TenantContext.currentTenantId()` and `TenantContext.runAs`, and the authorization matrix this change adds its rows to (split of 2026-10-04 from `add-auth-and-identity`, which registers its principal set later as company work through `IdentityContributor`) |
| `harden-cloud-deployment` | The Caddy gateway, which today routes only to the agent |

`add-agent-soul` is read only for context: a channel message is an ordinary chat turn, so the personality file and the user facts file apply to it unchanged. This change sets the peer bot mark that gives a peer bot turn the request provenance source `peer_bot_turn` of `add-agent-soul`. `add-self-improvement` (build group 4, position 13) and `add-self-built-integrations` (build group 4, position 14) land after this change and carry their own parts (dependency fix of 2026-10-05): the Undo buttons of a self-improvement report and the check that no self change starts from a peer turn are in `add-self-improvement`, and the fixed line on a credential approval prompt is in `add-self-built-integrations`. No task of this change waits for them.

Changes that need edits this change does not make. They are listed in design.md under "Required edits to other changes", and every one of them is made in its target change (checked on 2026-10-03):

| Change | Why it is touched |
| :--- | :--- |
| `add-deployment-modules` | A new catalog module `openclaw-apps`, the `uses` list of `channels` (`audio` only), and the containers of the one service `ascend-openclaw-host` |
| `add-shared-scheduler` | The inventory rows of the system task `channel-host-cleanup` and of the local event stream checks |
| `add-keycloak-login` | A service client account for the `channels` containers of the OpenClaw host, a channel scope that is not a user role, and an identity resolved from a linked chat platform account |
| `harden-cloud-deployment` | Lands earlier. This change adds, in that change's files, inbound webhook routes on the gateway to the `channels` container that runs the platform, for Telegram, Slack and the other webhook platforms, and no public route to `/api/v1/channel-host/` |
| `add-action-approvals` | A decision made through the channel relay as the linked owner, with channel `discord` |
| `add-chat-streaming-and-conversations` | A conversation can be bound to a chat platform thread, and deleting it removes the binding |
| `add-usage-metering-and-quotas` | Company (build group 5), registers its `UsageEventPort` implementation and its rate limits later: the channel message endpoint shares the chat rate limit buckets, and the `transcription` usage event this change records for a voice note becomes a ledger row. This change does not wait for it |
| `add-audit-and-gdpr-compliance` | Company (build group 5), registers its `AuditEventPort` implementation later, which stores the link, pairing and refusal events this change records, and adds the new tables to erasure and export and the host service to the redaction convention. This change does not wait for it |
| `add-tenant-isolation` | Company (build group 5), adds the foreign keys from the five channel tables to `tenants(id)` in its own migration and the cross tenant checks later. This change does not wait for it |
| `add-agent-skills` | Lands earlier. This change adds step 3 of its `ChatToolset`, a per-request list that narrows the tools, for turns written by another bot |
| `add-self-improvement` | Lands later and carries the Undo buttons of its reports on Discord, which call its in process undo as the linked owner |
| `add-self-built-integrations` | Lands later and carries the fixed line on its credential approval prompt |

## Why

The owner wants the assistant reachable on the messaging platforms OpenClaw supports, such as Discord, Telegram, Slack, WhatsApp, Signal and Matrix (owner decision of 2026-10-02). Today the agent has only REST, and writing and keeping a bot integration per platform is years of work that OpenClaw has already done under the MIT license. The owner does not want Ascend to run OpenClaw or Hermes as an agent: OpenClaw is used as a library for its plugins only, and Ascend's own agent answers every message.

On 2026-10-02 the owner also decided that the apps he needs (mail, calendar, code hosting, home automation and the like) come through OpenClaw plugins instead of separate MCP servers, and that no list of apps is needed now. OpenClaw tool plugins register agent tools through its plugin SDK, and OpenClaw's gateway can run one tool directly without an agent turn. So the same TypeScript service also hosts OpenClaw app plugins and offers their tools to Ascend's agent as one MCP server.

## What Changes

- A new service module, `ascend-openclaw-host` (TypeScript on Node.js 24), in `apps/ascend-openclaw-host/` (owner answers 46.3 and 48 of 2026-10-02). It is one program and one image that runs every OpenClaw plugin, chat platform connections (channels) and app plugins, with the `openclaw` npm package as a gateway. It runs as several containers when the load or the number of plugins grows, and each container is told its role and its plugin list:
  - Role `channels` (module `channels`, compose service `ascend-openclaw-host-channels`): the channel plugins of its list and one takeover plugin of ours. Each chat platform connection runs in exactly one container, because each bot token allows one active connection. Our plugin claims every inbound message before OpenClaw's own agent through the `reply_dispatch` takeover hook (chosen over `before_dispatch`, which carries no thread, media, bot flag or mentions and can return one text only), forwards it to ascend-agent over HTTP and sends back the agent's answer. OpenClaw's model, prompt, tools, memory and skills never run. A test per channel proves it.
  - Role `apps` (module `openclaw-apps`, compose service `ascend-openclaw-host-apps`): only the OpenClaw app plugins of its list, which the owner installed, plus a small MCP bridge of ours that lists their tools through the gateway's `tools.catalog` method and runs each call through the gateway's `POST /tools/invoke`, which runs one tool with no agent turn. The agent connects to the bridge as one `trust: external` entry `openclaw-apps` of `add-mcp-tool-servers`. Every tool asks first through the approval gate until the owner reviews it. App plugins can be spread over as many containers as needed: more replicas of the `apps` service behind the same entry, or a further `apps` service with its own plugin list and its own entry.
- A container that holds chat platform tokens never runs third party app plugins, so app plugin code never shares a process with the channel tokens and the agent client secret, following OpenClaw's own advice to run separate gateways across trust boundaries. The configuration validator refuses a container whose role and plugin list break this, and a compose test refuses a layout where one chat platform connection is in two containers.
- OpenClaw runs with no model provider and no provider key in every container. The configuration is generated from a checked-in template and refuses to start when a model provider, a skill, a core agent tool or an unpinned plugin is turned on.
- The `openclaw` version and every OpenClaw plugin (channel or app) are pinned exactly in `package.json` with a lock file, and the image is pinned by digest. Installing an app plugin is the owner's step: an exact version in `package.json`, the update procedure, and a rebuild. Nothing is installed while the service runs.
- OpenClaw app integrations that are skills wrapping a command line tool (such as `gog` for Google or `gh` for GitHub) need OpenClaw's agent and its `exec` tool, so this change does not run them. Design D21 describes how such a tool would run in Ascend's own sandbox and why that route is not built now.
- Each channel is switched on by configuration, and its secrets come only from the environment file. Discord, Telegram and Slack are first, the rest follow the same pattern. WhatsApp is switched on only with a spare phone number, never the owner's own.
- A new agent API under `/api/v1/channel-host/`, called only by the `channels` containers of the host with their own service credentials and never routed from the internet:
  - Messages: maps platform, bot account, chat, thread and sender to an Ascend conversation, accepts images, documents and voice notes, answers with one final reply or with streamed text the host sends in chunks, and the host shows a typing indicator while the agent works.
  - Outbound events: a durable outbox that each `channels` container reads as a resumable event stream for its own platforms, for background run status messages, approval prompts and owner notifications.
- Identity: every platform account must be linked to an Ascend user before the agent answers it. A stranger gets a pairing code in a direct message and nothing else. The owner redeems the code while signed in to Ascend, which links the account to his user. Unlinked senders in a group are ignored. Links can be listed and removed through `/api/v1/channels/links`.
- Approval buttons on Discord: a pending approval of `add-action-approvals` is posted to the owner's linked Discord direct message with Approve and Deny buttons. A press decides as the linked owner, with the digest of the shown action. Buttons on Telegram and Slack come later. Those platforms get a text notice that points to the app.
- Owner notifications on Discord: the `discord` channel of the `OwnerNotificationChannel` port of `add-shared-scheduler`, delivered through the outbox. The Undo buttons on a self-improvement report are added by `add-self-improvement`, which lands later.
- Background run status: a background run of every kind except `approval`, started from a channel conversation, posts one message when it starts and one when it ends, in the same chat and thread.
- Bot to bot on Discord: Ascend can talk to Hermes or OpenClaw instances as a normal participant, through configured peer bots only, with a loop guard (mention required, a turn limit without a human, a per peer rate limit, and never its own messages). Ascend never starts a conversation with another bot on its own. Ascend always uses a bot account, never a user account, because Discord forbids self-bots.
- Inbound webhook routes on the gateway of `harden-cloud-deployment` for the platforms that need them, added by this change (design D14).
- Deployment modules `channels` and `openclaw-apps` of `add-deployment-modules`: the compose profile of each role starts its containers, and the agent's channel API and `openclaw-apps` server entry exist only when their module is active. Both off by default.
- Periodic work: the daily cleanup of old inbound message keys, expired pairing codes and old outbox rows is the system task `channel-host-cleanup` of `add-shared-scheduler`. The event stream checks stay local to the agent instance that serves the stream.
- Metrics (`openclaw.host.*` in the host, `channel.*` in the agent), logs, traces, a startup banner, health and readiness for both roles and the channel API.

## Capabilities

### New Capabilities

- `openclaw-host-service`: the `ascend-openclaw-host` service, its roles and plugin lists per container, OpenClaw used as a library with the takeover plugin, the rule that OpenClaw's own agent never runs, the no-provider configuration, version pinning and the update procedure, channel configuration and secrets, the deployment module, webhook exposure, the periodic cleanup, health, metrics and logs.
- `channel-message-relay`: the agent's channel message API, conversation mapping, attachments and voice notes, final and streamed replies, typing, refusal replies, the outbound event stream with its outbox, owner notifications on Discord, and background run status messages.
- `channel-identity-linking`: platform account links, pairing codes, redeeming a code, refusing strangers, listing and removing links, and how a linked identity becomes the caller of a chat turn.
- `channel-approvals`: approval prompts with Approve and Deny buttons on Discord, deciding as the linked owner, updating the message after a decision, and the fixed line on a credential prompt.
- `channel-peer-bots`: bot to bot conversations with configured Hermes or OpenClaw peers on Discord, and the loop guard.
- `openclaw-app-tools`: the containers of the role `apps`, owner-installed and pinned app plugins, the MCP bridge over `tools.catalog` and `/tools/invoke`, one server entry per `apps` service with its replicas behind it, approval until review, and the isolation of app plugins from the channel tokens.

### Modified Capabilities

- `production-deployment` (created by `harden-cloud-deployment`, which is archived first): the edge gateway also routes the channel webhooks and refuses `/api/v1/channel-host/*`, and the channel host port binds to loopback. Every other capability this change touches that is not new belongs to a change that is not archived yet: conversations, runs, approvals, identity, tenants, metering, audit, modules and notifications. Their changes are required edits listed in design.md, not delta specs here. The archived specs in `openspec/specs/` were checked and none of their requirements change.

## Impact

- New module `apps/ascend-openclaw-host/`: TypeScript, Node.js 24, `openclaw` pinned exactly, the takeover plugin, the app tool MCP bridge, the two configuration templates and their validator with the role rules, the agent client, the compose layout test, tests with Vitest, a Dockerfile, `AGENTS.md` and `README.md`.
- ascend-agent, new code: `controller/ChannelHostController`, `controller/ChannelLinkController`, `controller/PeerBotController`, `service/channel/` (relay, conversation binding, link and pairing service, outbox, run and approval listeners, the `discord` owner notification channel, peer bot guard), `config/properties/ChannelProperties`, the system task `channel-host-cleanup`, models and repositories, and one Flyway migration `V<n>__create_channel_tables.sql`. Every channel bean carries `@ConditionalOnModule("channels")`.
- ascend-agent, changed code: `SecurityConfig` (channel scope rules), `GlobalExceptionHandler` (new codes), `StartupLogConfig`, `ChatContextAssembler` (a short channel line in the dynamic block), and the `openclaw-apps` entry in `application.yaml`.
- Database: tables `channel_link`, `channel_pairing`, `channel_conversation`, `channel_inbound_message` and `channel_outbox`, created by one Flyway migration. Each carries `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()` of `add-keycloak-login` (`default` in the personal deployment), with no foreign key to `tenants(id)`: `add-tenant-isolation` (company, build group 5) adds those foreign keys in its own migration later (design D7). The project is under development, so there is no data migration. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.
- Compose: the containers of `ascend-openclaw-host` from one image through one YAML anchor, `ascend-openclaw-host-channels` (profile `channels`, one replica, named volume `openclaw-host-channels-state`) and `ascend-openclaw-host-apps` (profile `openclaw-apps`, replicas from `OPENCLAW_HOST_APPS_REPLICAS`, state on tmpfs), the internal network `mcp-openclaw-apps-net`, joined by `mcp-egress-proxy`, which is always on with no profile (owner answer 76.5 of 2026-10-08). The owner may add further services of either role from the same anchor. No published port except loopback for local work.
- Gateway: new routes for inbound webhooks to the `channels` containers in `gateway/Caddyfile` of `harden-cloud-deployment`, added by this change.
- `.env.example`: the secrets only, empty: channel tokens, the host's agent client secret, the gateway tokens, the pairing pepper, the bridge token and app plugin secrets. A setting with a default, such as `OPENCLAW_HOST_APPS_REPLICAS`, gets no line there and is written `${VAR:-default}` in `compose.yaml` (owner rule 98 of 2026-10-08).
- Configuration reference: the rows of every new agent setting in `apps/ascend-agent/docs/CONFIGURATION.md` and of every host setting in `docs/CONFIGURATION.md`, in the same commit as the setting.
- Docs: a monorepo decision record for OpenClaw as a channel and app plugin library, `docs/CHANNELS.md` (setup per platform, pairing, updating OpenClaw), `docs/OPENCLAW_APPS.md` (installing and reviewing an app plugin), root `AGENTS.md` and `README.md` tables, `apps/ascend-agent/AGENTS.md`, `docs/SECURITY.md`, `docs/OBSERVABILITY.md`, Bruno requests, and four new e2e specs (design D5): three deterministic Bruno specs where Bruno acts as the channel host and the scripted model of the shared harness of `close-agent-test-gaps` answers, so no AI model runs (linking and relay, approvals and run status, app tools), and one human-gated spec with real test bots on Discord, Telegram and Slack, listed in `docs/E2E_RUN_SCENARIOS.md`. The scripted model and the fake MCP server of the harness start only for deterministic specs, never for AI-run or human-gated specs, which run against the agent with the shipped profile (owner answer 70.4 of 2026-10-04).

## Relevant Skills

Load these from `.agents/skills/` before implementing this change:

- the TypeScript and Node.js coding standards skill, imported from the owner's agent-standards repository by task 0.2 before any host code is written, together with `coding-standards` and `tdd-workflow`
- `backend-patterns` for the outbox, idempotent message handling, timeouts and retries, and graceful shutdown of the host
- `hexagonal-architecture` for keeping the OpenClaw seam behind one port in the host, and for the `OwnerNotificationChannel` adapter
- `springboot-patterns` and `java-coding-standards` for the agent API, the services and their tests
- `api-design` for the `/api/v1/channel-host` and `/api/v1/channels` contracts, the event stream and the problem detail codes
- `database-migrations` and `postgres-patterns` for the Flyway migration, the conditional updates and the outbox queries
- `security-review` for the service credentials, pairing, refusing strangers, approval buttons, webhook routes, app plugin isolation and prompt injection from other bots and from tool results
- `keycloak-administration` for the service client account and the group lookup of a linked user
- `docker-patterns` and `deployment-patterns` for the image, the compose services of both roles, the replicas and the pinned versions
- `build-dependency-management` for pinning `openclaw`, the plugins and the lock file
- `observability-and-logging` for metrics, logs, traces and the startup banner
- `architecture-decision-records` for the decision record
- `e2e-runbooks` for the new e2e spec
- `markdown-writer` for `docs/CHANNELS.md`, `docs/OPENCLAW_APPS.md`, the module README and the AGENTS.md updates
