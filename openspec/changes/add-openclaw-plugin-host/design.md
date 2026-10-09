## Context

See proposal.md for why. This section holds only the facts that shape the approach. Facts about OpenClaw were read on 2026-10-02 from the npm package `openclaw@2026.9.7` (published 2026-10-02, which ships the same `docs/` tree that docs.openclaw.ai serves), from `@openclaw/discord@2026.9.7`, and from GitHub `openclaw/openclaw` main at commit `eb978fd6`. Facts about Hermes were read from GitHub `NousResearch/hermes-agent` main at commit `4e3fcd5c`. No gateway was started, so every statement about runtime behaviour below is proved by a task before code depends on it.

OpenClaw:

- MIT, TypeScript on Node.js. The npm package is about 389 MB unpacked. Channel plugins import 352 `openclaw/plugin-sdk/*` subpaths of the `openclaw` package (the separate `@openclaw/plugin-sdk` package is private). The Discord plugin alone imports 149 subpaths across about 75,000 lines. Core owns the shared message tool, prompt wiring, session keys, dispatch and threading.
- Node.js 24.16 or later, or 26.1 or later. Node 22, 23 and 25 are not supported (`package.json` engines, `docs/install/node.md` line 10). Versions are calendar versions `YYYY.M.PATCH` (`docs/install/development-channels.md` lines 147-181).
- Configuration is JSON5 at `~/.openclaw/openclaw.json`, moved with `OPENCLAW_CONFIG_PATH`, `OPENCLAW_STATE_DIR` and `OPENCLAW_HOME` (`docs/gateway/configuration.md` line 10, `docs/help/environment.md` lines 23-50). Local plugins load from `plugins.load.paths` and need an `openclaw.plugin.json` manifest with `id` and `configSchema` (`docs/gateway/config-extensions.md` lines 185-210, `docs/plugins/manifest.md` lines 20 and 221). A plugin is `definePluginEntry({ id, name, register(api) })` from `openclaw/plugin-sdk/plugin-entry` and registers hooks with `api.on(name, handler, { priority, timeoutMs })` (`docs/plugins/hooks.md` lines 14-27 and 59-75).
- Bundled channels: Telegram, A2A, Reef and WebChat. Discord, Slack, WhatsApp, Signal, Matrix, LINE, Google Chat, Microsoft Teams, Mattermost, SMS through Twilio, IRC and more are official plugins installed as `@openclaw/<id>` (`docs/channels/index.md`).
- The gateway serves WebSocket and HTTP on one port, default 18789, with `/health`, `/healthz`, `/ready`, `/readyz` (readiness includes channel checks) and `/startupz` (`docs/gateway/config-gateway.md` line 132, `docs/gateway/health.md` lines 81-93). It starts unconfigured only with `gateway.mode=local` or `--allow-unconfigured`, and onboarding can skip connecting any model (`docs/cli/gateway/running.md` lines 22-26 and 59-60, `docs/cli/onboard.md` lines 149-152). A missing provider key fails only when a model is called (`docs/help/faq-models.md` lines 326-330). There is no setting that switches the agent off and no production stub provider.
- Two claiming hooks exist (`docs/plugins/hooks/messages.md`, types in `src/plugins/hook-types.ts` lines 448-530):
  - `before_dispatch` gets `messageId`, `content`, `body`, `channel`, `sessionKey`, `senderId`, the reply-to fields, `isGroup` and `timestamp`, plus `channelId`, `accountId` and `conversationId` in its context. It has no thread id, no media, no bot flag and no mentions. It returns `{ handled, text? }`, which core sends as one final payload (dist `dispatch-from-config-BfxY-Rlw.mjs` lines 929-950).
  - `reply_dispatch` gets the finalized message context (with `SenderIsBot`, `WasMentioned`, `MentionedUserIds`, `MessageThreadId`, `ChatId`, `media`, `OriginatingTo`, `originatingThreadId`) and a dispatcher with `sendToolResult`, `sendBlockReply` and `sendFinalReply`, each taking text, media, attachments, `interactive` and `presentation`, callable many times. It returns `{ handled, queuedFinal, counts }`.
  - Both run in priority order, the first `handled: true` wins, an error moves on to the next handler, and there is no timeout unless one is registered (`src/plugins/hooks.ts` around lines 800-830). `before_dispatch` runs before `reply_dispatch` and before the agent run, so a claim by `before_dispatch` means `reply_dispatch` never runs. A handled claim ends dispatch with no agent run (`dispatch-from-config.choose-route.ts` lines 561-580).
  - They run in the shared dispatch path of every channel. Heartbeat turns, restricted admitted sessions, fast commands and abort are handled before them, and channel access control (`dmPolicy`, pairing, mention gating) runs earlier, inside each channel plugin.
- Access control: `dmPolicy` is `pairing` (default), `allowlist`, `open` (needs `"*"` in `allowFrom`) or `disabled`. `groupPolicy` defaults to `allowlist`. OpenClaw's own pairing codes are 8 uppercase characters, expire after 1 hour, and at most 3 are pending per channel account (`docs/channels/pairing.md`, `docs/channels/discord/access-control.md` lines 19-28).
- Discord: `channels.discord.allowBots` is `true`, `false` or `"mentions"`, default `true` (`extensions/discord/src/monitor/message-handler.preflight.ts` line 238). Own messages are dropped when the author is the bot (line 241). `botLoopProtection` is on by default, 20 events per 60 seconds per bot pair, then a 60 second pause (`docs/channels/bot-loop-protection.md`). Components v2 buttons are supported, and button callbacks live `channels.discord.agentComponents.ttlMs`, default 30 minutes, at most 24 hours (`docs/channels/discord/rich-messages.md` lines 12-31 and 104-120). Native slash commands follow `commands.native` (`docs/channels/discord/access-control.md` lines 296-298).
- Plugins register button handlers with `api.registerInteractiveHandler({ channel, namespace, handler })` (`docs/plugins/sdk-overview/infrastructure.md` line 26, type in dist `channel-core-BrH0n2qr.d.ts` around line 33626), and send without an inbound message through `api.runtime.channel.outbound.loadAdapter(channelId)` with `sendText`, `sendMedia` and `sendPayload`. The gateway also has a `send` RPC.
- Transports: Discord keeps an outbound gateway WebSocket. Telegram polls by default and can use a webhook at `/telegram-webhook`. Slack uses Socket Mode by default and can use HTTP request URLs. WhatsApp (Baileys), Signal (signal-cli) and Matrix are outbound. LINE (`/line/webhook`), Google Chat (`/googlechat`), Microsoft Teams (Bot Framework) and SMS (`/webhooks/sms`) need a public HTTPS URL.
- Sessions are kept in the state directory and pruned by `session.maintenance.pruneAfter`, default 30 days (`docs/concepts/session.md` lines 263 and 328).
- `openclaw mcp serve` is a stdio MCP server over an existing gateway that lists conversations and sends text only along routes a session already recorded (`docs/cli/mcp/serve.md` lines 29-160). OpenClaw's own agent still answers inbound messages.

OpenClaw app integrations, read on 2026-10-02 from the same `openclaw@2026.9.7` package (MIT, `npm view openclaw license`) and checked against docs.openclaw.ai:

- Three kinds of app integration exist:
  - Tool plugins. A plugin registers agent tools with `api.registerTool({ name, description, parameters, execute })` inside `definePluginEntry` (`docs/plugins/building-plugins.md` lines 130-170), and every registered tool is declared in the manifest under `contracts.tools` (same file, lines 317-330). `defineToolPlugin` from `openclaw/plugin-sdk/tool-plugin` (since `openclaw` 2026.5.17) builds a plugin that only adds tools, with TypeBox parameter schemas, a typed plugin config and an optional `optional: true` flag per tool (`docs/plugins/tool-plugins.md` lines 10-140). Plugins install from npm or ClawHub (`openclaw plugins install clawhub:<package>`, `docs/plugins/manage-plugins.md` lines 120-150, `docs/plugins/plugin-inventory.md`).
  - Skills. A skill is a folder with `SKILL.md` that teaches OpenClaw's agent when and how to use tools (`docs/tools/skills.md` lines 10-15). The package ships 49 bundled skills (`package/skills/*/SKILL.md`), and most app skills wrap a command line tool that the skill lists under `requires.bins`: `gog` for Gmail, Calendar, Drive, Contacts, Sheets and Docs (`skills/gog/SKILL.md`, homepage https://gogcli.sh), `gh` for GitHub (`skills/github/SKILL.md`), and `himalaya`, `notion`, `trello`, `openhue`, `obsidian`, `1password` and others. OpenClaw's agent runs these tools through its `exec` shell tool (`docs/tools/exec.md` line 9, and `docs/tools/skills.md` lines 111 and 797, which say skills are executed with `exec`). Community skills come from ClawHub (https://clawhub.ai, `docs/tools/skills.md` lines 323-363). The bundled `github` plugin is only link previews in the Control UI, not an agent tool (`docs/plugins/github.md` lines 10-15).
  - MCP servers. OpenClaw is itself an MCP client: servers configured under `mcp.servers` (Streamable HTTP, SSE or stdio) give their tools to OpenClaw's agent (`docs/tools/mcp.md` lines 9-35). The bundled `mcporter` skill lists and calls MCP servers through the `mcporter` command line tool.
- An outside program can run a tool without an agent turn:
  - `POST /tools/invoke` on the gateway port runs one tool and is "always enabled", authenticated with the gateway token (`docs/gateway/tools-invoke-http-api.md` lines 9-31). The request is `{ tool, args, sessionKey, idempotencyKey }` and the answer `{ ok: true, result }` or `{ ok: false, error }` with 400, 403, 404 or 500 (lines 51-150). Tool availability follows the gateway tool policy (`tools.allow` and the other lists, line 77), and a tool not allowed answers 404. A hard deny list blocks `exec`, `spawn`, `shell`, `fs_write`, `fs_delete`, `fs_move`, `apply_patch`, `sessions_spawn`, `sessions_send`, `cron`, `gateway` and `nodes` over HTTP (lines 93-110). The gateway token is a full operator credential and must stay on loopback or a private network (lines 33-42). Approval prompts of OpenClaw are not added on this path (line 89).
  - The gateway WebSocket methods `tools.catalog` (`operator.read`, the runtime tool catalog with `source` `core` or `plugin` and the `pluginId`) and `tools.invoke` (`operator.write`, the same policy path as `/tools/invoke`) give the same over RPC (`docs/gateway/protocol/operator-methods.md` lines 28-63).
  - OpenClaw's docs advise separate gateways, ideally on separate OS users or hosts, when callers sit across a trust boundary (`docs/gateway/tools-invoke-http-api.md` line 91).

Hermes (`gateway/authz_mixin.py` lines 38-46 and 554-565, `website/docs/user-guide/messaging/discord.md` lines 304-345): `DISCORD_ALLOW_BOTS` is `none` (default), `mentions` or `all`. `DISCORD_REQUIRE_MENTION` defaults to true, `DISCORD_BOTS_REQUIRE_INLINE_MENTION` defaults to true, so a bot must write a literal `<@BOT_ID>`. Hermes drops bot messages in a channel for 10 minutes after 20 bot messages in 5 minutes.

Discord forbids self-bots: "Automating normal user accounts (generally called "self-bots") outside of the OAuth2/bot API is forbidden, and can result in an account termination if found." (support.discord.com article 115002192352, read through its Zendesk API on 2026-10-02, because the page itself answered HTTP 403.)

Ascend: the chat pipeline, conversations and streaming come from `add-chat-streaming-and-conversations`, runs and `SubagentRunChangedEvent` from `add-agent-subagents` (its D17), the approval view, `ApprovalChangedEvent` and the decision rules from `add-action-approvals` (its D11 and D12), identity from `add-keycloak-login` (Keycloak realm `ascend-ai`, `sub` as user id, the tenant `default` through its extension point of D22, two roles, freshness bounded by the access token lifetime, its D3, D4 and D20), with the `tenant` claim and a principal set from Keycloak groups registered later by `add-auth-and-identity` (company, build group 5, split of 2026-10-04, owner rule of 2026-10-04), the tenant seam `TenantContext.currentTenantId()` and `TenantContext.runAs` from `add-keycloak-login` (its D3 and task 3.9), with the tenant foreign keys and cross tenant checks of `add-tenant-isolation` (company, build group 5) plugging in later, the company extension ports `AuditEventPort` and `UsageEventPort` with their safe defaults from `add-deployment-modules`, the gateway from `harden-cloud-deployment` (D2: one upstream, the agent), the deployment modules from `add-deployment-modules` (`COMPOSE_PROFILES` starts the containers, the agent reads the same list as `ASCEND_MODULES`, and beans carry `@ConditionalOnModule`), the owner notification store and its `OwnerNotificationChannel` port from `add-shared-scheduler` (`String name()`, `boolean canReach(String tenantId, String userId)`, `DeliveryResult deliver(OwnerNotificationView notification)`), the MCP server entries from `add-mcp-tool-servers`, and the error body from `upgrade-spring-boot-4` D19. The repository has no Node.js module and no TypeScript skill today. The owner's agent-standards repository has a TypeScript and Node.js coding standards skill, which task 0.2 imports before implementation.

## Goals / Non-Goals

Goals:

- Every OpenClaw channel can reach Ascend's agent, and OpenClaw's own agent never runs.
- One identity store: Ascend decides who is answered. OpenClaw's pairing and allow lists are not a second store.
- Nothing about OpenClaw leaks into the agent. The agent sees a platform neutral message API, so the host could be replaced without changing the agent.
- Updating OpenClaw is a routine, tested step the owner can do alone.
- Approvals, owner notifications, background runs and bot to bot talk work on Discord.
- Apps the owner needs reach Ascend's agent as OpenClaw tool plugins, through one MCP server entry, with every tool asking first until the owner reviews it.

Non-Goals:

- Running OpenClaw or Hermes as an agent, or calling OpenClaw's model, memory, skills, cron or heartbeat. The only OpenClaw tools that run are the tools of app plugins the owner installed, called one at a time through `/tools/invoke` with no agent turn.
- Running OpenClaw skills, including skills that wrap a command line tool (D21).
- A list of apps. The owner installs an app plugin when he needs one.
- Forking or rewriting OpenClaw. The host never patches OpenClaw code.
- A tool that lets the model send a message to any chat on its own, and any conversation with another bot that Ascend starts on its own (owner decision of 2026-10-02). Replies go only to the chat that wrote, and outbound messages are only the fixed kinds of this change.
- Approval buttons on Telegram and Slack. They come later through the same outbox kind (owner decision of 2026-10-02). Until then those platforms get a text notice that points to the app.
- Voice calls and voice channels.
- More than one container holding the same chat platform connection, and a container that holds chat platform tokens and also runs app plugins (D18).

## Decisions

### D1: OpenClaw runs as a library inside a gateway process of our own

The host is a small Node.js service whose process is OpenClaw's gateway, started from the `openclaw` package with our configuration and our plugin. Our code is the plugin, the configuration generator, the agent client and, in containers of the role `apps`, the MCP bridge of D19. The service is `ascend-openclaw-host`, one program and one image that runs as several containers, each with a role (`channels` or `apps`) and a plugin list (D18). D1 to D17 describe the role `channels`. D18 describes the roles and the containers, D19 to D21 the role `apps` and the skills that are not run, and D22 the periodic work.

Alternatives considered:

- Rewrite the host on top of the channel plugins without OpenClaw core (rejected: the Discord plugin alone imports 149 core subpaths, so this is a rewrite of OpenClaw core, and it would have to be redone on every OpenClaw release).
- Use one bot library per platform, such as discord.js and grammY (rejected: the owner wants every platform OpenClaw supports, and each library would be our own integration to keep).
- `openclaw mcp serve` with Ascend as the MCP client (rejected: OpenClaw's own agent would still answer every inbound message, and it can only send along routes a session already recorded).
- Run Hermes as the host (rejected by the owner: Ascend talks to Hermes only as a participant on Discord).

### D2: The takeover seam is `reply_dispatch`, not `before_dispatch`

The plugin registers one `reply_dispatch` handler with the highest priority and no `eligibleDispatchKinds` limit, so it is eligible for both `agent` and `acp` dispatch. It always returns `handled: true`, also when the agent refuses the message or cannot be reached, so OpenClaw's agent dispatch never runs.

Why not `before_dispatch`: its event has no thread id, no media, no bot flag and no mentions, and it can send only one text. The relay needs all of them: the thread for the conversation binding, media for attachments, the bot flag and mentions for the peer rules, several messages for long answers and blocks, and buttons for approvals. `reply_dispatch` has them and is the documented "advanced takeover seam". The two hooks cannot be combined as a safety net, because a `before_dispatch` claim stops `reply_dispatch` from running.

Defence in depth, because the docs do not promise that every channel reaches the hook:

1. No model provider is configured (D3), so an agent run that starts anyway cannot reach a model.
2. The plugin also observes OpenClaw's agent run lifecycle (the agent event stream or the run start hook of the pinned version, chosen in task 1.3). Any agent run start is an ERROR log line, a `openclaw.host.openclaw.agent.runs` counter and a failed readiness check, so a regression is visible at once.
3. The per-channel takeover tests (D5) assert that every message is claimed and that the counter stays zero.

The plugin does not forward `ctx.userTurnTranscriptRecorder` or `ctx.onAgentRunStart`, because no OpenClaw runtime runs. What OpenClaw still writes to its own session store after a takeover is measured in task 1.5 and handled by D16.

### D3: OpenClaw configuration with no model, generated and checked at startup

`config/openclaw.channels.template.json5` is checked in for containers of the role `channels` (the role `apps` has its own template, D18). At startup `src/config/generate.ts` fills in the channels of the container's `OPENCLAW_HOST_CHANNELS`, their non-secret settings and environment variable references, writes the file to the state volume with mode `0600`, and `src/config/validate.ts` checks the result before the gateway starts. The template sets:

- `gateway.mode: "local"`, the gateway auth token from `OPENCLAW_GATEWAY_TOKEN`, the Control UI off, and the gateway bound to the container network.
- No `models`, no provider, no auth profile, no agent model default, no tools allowed, no skills, no memory plugin, no heartbeat, no cron, no hooks other than our plugin's.
- `commands.native: false` and `commands.text: false`, so `/new`, `/model` and every other command text reaches our plugin.
- Every enabled channel with `dmPolicy: "open"` and `allowFrom: ["*"]`, so OpenClaw's own pairing never answers and Ascend decides (D8).
- `groupPolicy: "allowlist"` with the groups, guilds and channels of `OPENCLAW_HOST_GROUPS_<PLATFORM>` (empty by default, so the bot answers only direct messages until the owner lists groups), and mention required in groups.
- Discord `allowBots: "mentions"` and `botLoopProtection` left on.
- `channels.discord.agentComponents.ttlMs: 86400000`, the 24 hour maximum, for approval buttons (D12).
- `session.maintenance.pruneAfter` at its shortest accepted value (D16).

The validator refuses to start, naming the setting, when the generated file enables any provider, model, tool, skill, memory, cron or heartbeat, when a group policy is open, or when a known provider key variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MINIMAX_API_KEY` and the other names in OpenClaw's provider docs, listed once in `src/config/forbidden-env.ts`) is set in the container. The exact key names are checked against the configuration schema of the pinned version in task 2.2, because OpenClaw's own startup validation is the authority for its keys.

Alternatives considered: a hand-written static configuration file (rejected: secrets and enabled channels vary per deployment, and a static file cannot refuse a provider key that sits in the environment), and OpenClaw's own pairing in front of Ascend's (rejected: two identity stores that can disagree).

### D4: Module layout and runtime

`apps/ascend-openclaw-host/`:

- `package.json` with exact versions and `package-lock.json`. Runtime dependencies: `openclaw`, the `@openclaw/<channel>` plugins that are not bundled (Discord and Slack first, each pinned to the same version as `openclaw`), the app plugins the owner installed (D18), `@modelcontextprotocol/sdk` (MIT) for the bridge of D19, and the OpenTelemetry API. Dev dependencies: TypeScript, Vitest and ESLint.
- `src/plugin/`: `openclaw.plugin.json` and the plugin entry that registers the `reply_dispatch` handler, the Discord interactive handlers, the agent run observer and the readiness route.
- `src/agent/`: the `AgentRelay` port and its HTTP adapter (service token, SSE parsing, timeouts, retries only for the event stream).
- `src/outbound/`: the outbox consumer that reads the agent's event stream and delivers through OpenClaw's outbound adapters.
- `src/apps/`: the MCP bridge of D19 (`OpenClawToolGateway` port, its adapter over `tools.catalog` and `/tools/invoke`, and the Streamable HTTP MCP server).
- `src/config/`: the two templates, generator, validator, the role rules of D18 and the forbidden variable list.
- `src/main.ts`: reads `OPENCLAW_HOST_ROLE` (`channels` or `apps`) and the container's plugin list, generates and checks the configuration of that role, and starts the gateway and, for the role `apps`, the bridge.
- `Dockerfile`: `node:24` slim pinned by version and digest, `npm ci --omit=dev`, non-root user, read-only root file system with the state volume and a tmpfs, entrypoint `node dist/main.js`.
- `test/compose/OpenClawHostComposeTest`: the layout check of D18 over `docker compose config --format json`.
- `AGENTS.md`, `README.md`.

Only `src/plugin/`, `src/outbound/` and the adapter in `src/apps/` import `openclaw/plugin-sdk/*` or call the gateway. Everything else talks to the `AgentRelay` and `OpenClawToolGateway` ports, so an OpenClaw update touches at most three folders. Node.js 24 is the owner's decision of 2026-10-02: it is the long-term support line that OpenClaw supports (24.16 or later), and moving to Node 26 is a later update through the same procedure as D5.

The official image `ghcr.io/openclaw/openclaw` is not used as the base: it bundles parts this host must not run (browser variant, diagnostics, onboarding defaults), and installing from our own lock file is what makes the pin exact.

### D5: Pinning and the owner's update procedure

`openclaw` and every `@openclaw/*` plugin are pinned to one exact calendar version, and every other app plugin to one exact version, installed with `npm ci` from the committed lock file. The image's Node base is pinned by digest. The startup banner and the `openclaw.host.build.info` gauge carry the OpenClaw version and the pinned plugin versions.

Tests, all in `apps/ascend-openclaw-host`:

- Unit tests for the generator, the validator, the relay adapter, the chunk and block logic, and the outbox consumer.
- Takeover tests, one file per enabled channel. Each test starts the real OpenClaw gateway in process with the real channel plugin and the takeover plugin, feeds an inbound platform event, and asserts: the message reaches a fake agent once, the reply reaches the fake platform, and the agent run counter of D2 stays zero. Where a pinned plugin offers an injectable transport (fake Discord gateway, fake Telegram Bot API base URL, Slack Socket Mode fake), the event enters at the transport. Where it does not, the test enters at OpenClaw's shared channel turn function with that channel's finalized context, and the live checklist below covers the plugin's own preflight. Task 1.2 records which route each channel uses.
- App plugin tests (D20): for every installed app plugin, the bridge test lists its tools through the real gateway and compares the names with the plugin's `contracts.tools`, and the contract file `apps/ascend-openclaw-host/app-tools.lock.json` (tool names and a SHA-256 of each input schema) fails the test when an update changes a tool.
- A live checklist in `docs/CHANNELS.md`, run by the owner with real test bots on Discord, Telegram and Slack: direct message, group mention, thread, image, voice note, long answer, approval button, owner notification, and a stranger getting a pairing code.
- End-to-end specs in `apps/ascend-agent/e2e/` (owner request of 2026-10-04: every planned change carries end-to-end tests, deterministic Bruno tests wherever no AI model is needed), each with the next free number at implementation time. Three are deterministic: Bruno acts as the `channels` host with the host's client token (the fake channel), the real `channels` container is stopped for the run so Bruno is the only consumer of the event stream, and every chat turn uses the scripted model and e2e overlay of the shared harness of `close-agent-test-gaps`. The scripted model and the fake MCP server start only for these deterministic specs, never for the AI-run or human-gated spec, which runs against the agent with the shipped profile (owner answer 70.4 of 2026-10-04). `<N>-channel-linking-and-relay` proves the API rules, pairing, redeem and its limits, the outbox with ack and resume, conversation binding, `/new`, duplicates, attachments and voice notes, a disabled identity, unlinking and the peer bot rules with the loop guard. `<N>-channel-approvals-and-run-status` proves the approval prompt, a decision by an unlinked presser and by the linked `ADMIN` with the shown digest, a stale press, and the start and final entries of a background run, using the fake MCP server's call log as the proof that the approved action ran once. `<N>-openclaw-app-tools` proves the bridge entry connects, an app tool waits for approval and runs once after it, and the `apps` container cannot reach the agent. A fourth spec, `<N>-channel-live-platforms`, is human-gated: real test bots and test accounts on Discord, Telegram and Slack (owner facts), a real model, and a human who types every platform message and confirms what the platform shows.
- Not provable end to end, and proven by the integration tests of tasks 5.8, 5.10 and 7.4 instead: an owner notification row, because no source in the build order up to this change creates a notification on demand (approval expiry takes 24 hours), the daily cleanup task, which runs at 04:00, and the webhook routes of the edge gateway, which the development stack does not run. The owner notification on Discord stays an item of the live checklist. The Undo button is proven by `add-self-improvement`, which carries it, and the `rate_limited` and `quota_exceeded` refusals by `add-usage-metering-and-quotas` (company), which registers them later (dependency fix of 2026-10-05).

Update procedure in `docs/CHANNELS.md`: read the release notes between the two versions for hook, dispatch, access control, configuration, tool invoke and channel changes, change the pinned versions, run `npm install` to refresh the lock file, run the type check, the unit tests, the takeover tests and the app plugin tests, review every changed tool in `app-tools.lock.json`, run the live checklist, rebuild the image, and commit only when all pass. No automatic update tool is added (the owner did not ask for one).

### D6: The agent API and how the host authenticates

Two path prefixes, so that the gateway rule is one line. The host prefix keeps the name `channel-host`, because only containers of the role `channels` call it:

- `/api/v1/channel-host/` for the host only: `POST messages`, `GET events`, `POST events/{id}/ack`, `POST actions` (the one action endpoint of every button, D12, owner answer 89.6 of 2026-10-08), `GET approvals/prompts`. `add-self-improvement`, which lands later, adds no endpoint: its Undo buttons are one more action type on `POST actions`.
- `/api/v1/channels/` for signed-in users: `links` and `peer-bots`.

A `channels` container authenticates with the Keycloak confidential client `ascend-openclaw-host` through the client credentials grant (an `apps` container holds no client secret, D18), and the agent accepts the host prefix only from a token holding the scope `channel.relay` (made in `add-keycloak-login`, its D2 and D5, with this change adding its own matrix row, its D4). This holds in every profile including `dev`, because a request on this prefix names the sender as data, and anyone who could call it without a credential could act as any linked user. The development realm overlay carries the same client with a development secret. A scope and not a role is used because the two user roles stay two (`add-keycloak-login` D4), and the channel host is not a user. The gateway never forwards the host prefix (made in `harden-cloud-deployment`, its D2).

`POST /api/v1/channel-host/messages` is `multipart/form-data`: a `message` JSON part and optional `image`, `document` and `audio` parts. The JSON holds `platform`, `botAccount` (the OpenClaw account label, `default` unless the owner runs several bots on one platform), `chatId`, `chatType`, `threadId`, `sender` (`id`, `name`, `isBot`), `mentionsBot`, `messageId`, `replyToMessageId` and `text`. The answer is SSE (spec `channel-message-relay`). The host maps OpenClaw's context fields (`ChatId`, `MessageThreadId`, `SenderIsBot`, `WasMentioned`, `media`) to these fields in one function, `src/plugin/context-mapper.ts`, which is the only place that knows OpenClaw's names.

Tenant: `app.channels.accounts.<platform>.<botAccount>.tenant`, default `default` for the `default` account of every platform. A message for an account no tenant configures is refused with `channel_account_unknown`.

Duplicates: the table `channel_inbound_message` has a unique key on tenant, platform, bot account, chat id and message id. The relay inserts first and treats a conflict as `duplicate`. Rows older than `app.channels.inbound.retention` (default 24 hours) are deleted by the daily system task `channel-host-cleanup` (D22). Postgres and not Redis, because a lost Redis key would run a turn twice, and a turn can send messages and call tools.

The chat pipeline is called in process through the same service the streaming endpoint uses, with a `ChatTurnRequest` built by the relay: resolved identity, conversation id, prompt text, attachments, a channel line for the dynamic block, and for peer turns the narrowed tool list, memory extraction off and the peer bot mark (D13). No HTTP call from the agent to itself.

### D7: Tables

One Flyway migration `V<n>__create_channel_tables.sql` (`<n>` is the next free version at implementation time). Every constraint and index is named. The project is under development, so there is no data migration. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

`channel_link`: `id UUID` primary key, `tenant_id VARCHAR(64)` not null, `platform VARCHAR(32)` not null, `account_id VARCHAR(128)` not null, `account_name VARCHAR(255)`, `kind VARCHAR(16)` check in `user`, `peer_bot`, `user_id VARCHAR(255)` not null, `allowed_chat_ids JSONB` (peer bots only), `mention_in_replies BOOLEAN` not null default true, `created_by VARCHAR(255)`, `created_at`, `last_seen_at TIMESTAMPTZ`. Unique `(tenant_id, platform, account_id)`. Index `(tenant_id, user_id)`.

`channel_pairing`: `id UUID`, `tenant_id`, `platform`, `account_id`, `account_name`, `code_hash CHAR(64)` (SHA-256 of the code with a per-deployment pepper from `CHANNEL_PAIRING_PEPPER`), `created_at`, `expires_at`, `last_reply_at`, `redeemed_at`, `link_id UUID` null. Partial unique `(tenant_id, platform, account_id) WHERE redeemed_at IS NULL`. Index `(tenant_id, code_hash)`. Expired rows that were never redeemed are deleted by the daily system task `channel-host-cleanup` (D22).

`channel_conversation`: `id UUID`, `tenant_id`, `platform`, `bot_account VARCHAR(64)`, `chat_id VARCHAR(128)`, `thread_id VARCHAR(128)` not null default `''`, `user_id`, `peer_link_id UUID` null with FK to `channel_link` `ON DELETE CASCADE`, `peer_key VARCHAR(36)` not null default `''`, `conversation_id UUID` not null with FK to `conversations(id)` `ON DELETE CASCADE`, `created_at`, `last_message_at`. Unique `(tenant_id, platform, bot_account, chat_id, thread_id, user_id, peer_key)`. Index `(conversation_id)`. The cascade from `conversations` is what makes a deleted conversation drop its binding.

`channel_inbound_message`: `tenant_id`, `platform`, `bot_account`, `chat_id`, `message_id VARCHAR(128)`, `received_at`. Primary key on the first five.

`channel_outbox`: `id BIGSERIAL`, `tenant_id`, `kind VARCHAR(32)` check in `run_status`, `approval_prompt`, `approval_update`, `owner_notification`, `link_confirmation`, `loop_guard_notice`, `purge`, `platform`, `bot_account`, `chat_id`, `thread_id`, `user_id`, `payload JSONB`, `approval_id UUID` null, `notification_id UUID` null, `arguments_digest CHAR(64)` null, `prompt_entry_id BIGINT` null (an update points at its prompt), `platform_message_id VARCHAR(128)` null, `state VARCHAR(16)` check in `pending`, `sent`, `delivered`, `failed`, `dead`, `attempts INT`, `next_attempt_at`, `created_at`, `delivered_at`. Index `(state, id)`, partial `(next_attempt_at) WHERE state IN ('pending', 'sent', 'failed')`, `(approval_id)`, `(created_at)`.

Every table carries `tenant_id VARCHAR(64) NOT NULL`, written from `TenantContext.currentTenantId()` of `add-keycloak-login` (`default` in the personal deployment), and every query filters on it. A relay call, the outbox stream and the cleanup task have no user request, so they bind the tenant of the bot account or of the row with `TenantContext.runAs` of `add-keycloak-login` before any query, and with nothing bound the accessor throws (fail closed).

Foreign keys: this migration adds no foreign key to `tenants(id)`. `add-tenant-isolation` (company, build group 5) creates the `tenants` table and adds the foreign keys from the `tenant_id` column of each of the five tables (`channel_link`, `channel_pairing`, `channel_conversation`, `channel_inbound_message` and `channel_outbox`) in its own migration later (dependency fix of 2026-10-05, canon section 4). The owner decision of 2026-10-03 that put them in this migration is kept as a record (superseded by the owner build order of 2026-10-04). This migration adds the foreign keys between the channel tables and to the tables before them listed above: `channel_conversation.peer_link_id` to `channel_link(id)` `ON DELETE CASCADE` and `channel_conversation.conversation_id` to `conversations(id)` `ON DELETE CASCADE`, plus `channel_pairing.link_id` to `channel_link(id)` `ON DELETE SET NULL` and `channel_outbox.prompt_entry_id` to `channel_outbox(id)` `ON DELETE SET NULL`. `channel_outbox.approval_id` and `notification_id` stay plain values without a foreign key, because the approval and notification retention of `add-action-approvals` and `add-shared-scheduler` delete those rows on their own schedule while an outbox row may still be waiting.

### D8: Pairing is Ascend's, and a code is redeemed by a signed-in user

OpenClaw's pairing is switched off (D3), and the agent owns links. The code shape, lifetime and pending limit copy OpenClaw's (8 uppercase characters, 1 hour, 3 pending per channel), so an OpenClaw user meets the same rules. The alphabet leaves out `0`, `O`, `1`, `I` and `L`.

A code is redeemed by the user it will be linked to, while signed in to Ascend, through `POST /api/v1/channels/links`. This proves both sides: the person controls the platform account (the code was sent there) and the Ascend account (the request carries his token). OpenClaw's own model, where an operator approves a code on the command line, was not taken: it decides "allowed or not" for one owner, while Ascend must also decide which user the account belongs to, and an administrator approving codes could link a stranger's account to the wrong user.

Stranger replies are throttled (one reply per account per `app.channels.pairing.reply-interval`, default 10 minutes, no reply at all once `app.channels.pairing.max-pending` codes are pending, default 3), so the bot cannot be used to flood a person, and the stranger's text is never stored. A code expires after `app.channels.pairing.ttl` (default 1 hour). Redeem failures are counted per user in Redis with a window of `app.channels.pairing.redeem-failure-window` (default 15 minutes), so codes cannot be guessed (32 to the power of 8 codes, at most `app.channels.pairing.max-redeem-failures` tries per user per window, default 5).

### D9: A linked identity is resolved fresh from Keycloak

A channel turn needs the same identity a token gives: `sub`, tenant, roles, and the principal set once company work adds it. The message carries no user token, so the agent builds the identity from the link through Keycloak's admin API, with its own confidential client `ascend-agent-directory` that holds only `view-users` (made in `add-keycloak-login`, its D2 and D20): the user's enabled flag and realm roles, the tenant its extension point of D22 gives (`default` in the personal deployment) and the extensions of its `IdentityContributor` beans. When `add-auth-and-identity` (company) plugs in, its contributor adds the user's groups through the same principal factory and cap as a token (its D3c, D8 and D10), with no edit here. The result is cached per user for at most the realm access token lifetime, so it is never staler than with a token. When Keycloak cannot be reached or the user is disabled or deleted, the message is refused with `identity_unavailable`, never answered with an older identity (`add-keycloak-login` D20). Under the `dev` profile the link resolves to the dev identity of its D5.

Alternative considered: store a snapshot of groups at link time (rejected: a person removed from a group would keep reading its documents through the chat platform for as long as the link lives).

### D10: Conversation binding, `/new` and the channel line

The binding table maps a chat and thread per user to one conversation (spec `channel-message-relay`). The conversation is created through `ConversationService` of `add-chat-streaming-and-conversations` with the title `<Platform>: <chat name>`. `/new` alone creates a fresh conversation and moves the binding, with no model call. The channel line in the dynamic block (for example "This message came from Telegram. Use short paragraphs and no tables.") is one entry per platform in `app.channels.platform-hints`, added by `ChatContextAssembler` to the dynamic block that `add-agent-soul` D4 defines, so the static prefix and the prompt cache stay unchanged.

Default texts of `app.channels.platform-hints` (owner answer 103.5 of 2026-10-09). They are drafts, written for the owner to review later, and they ship as the defaults until the owner changes them. Each is a setting (`APP_CHANNELS_PLATFORMHINTS_<PLATFORM>`):

| Platform | Draft default text |
| --- | --- |
| `discord` | Draft: "This message came from Discord. Use short paragraphs and Discord markdown, and no tables." |
| `telegram` | Draft: "This message came from Telegram. Use short paragraphs and no tables." (the example above) |
| `slack` | Draft: "This message came from Slack. Use short paragraphs and Slack mrkdwn formatting, and no tables." |

### D11: Replies, chunking, typing and attachments

The host passes the agent's text to OpenClaw's reply dispatcher, which already applies each channel's message size limit, markdown conversion and chunking. The takeover tests check the code block rule of the spec on Discord, Telegram and Slack, and a channel that breaks it gets the split done by the host before it hands the text over. Reply mode per channel is `final` (default) or `blocks` (`OPENCLAW_HOST_REPLY_MODE_<PLATFORM>`). In `blocks` mode the host collects `delta` events and calls `sendBlockReply` for every completed paragraph, at most one call every `OPENCLAW_HOST_BLOCK_REPLY_INTERVAL_SECONDS` (default 2 seconds).

Typing uses OpenClaw's typing callbacks on the dispatcher (`createReplyDispatcherWithTyping`), started when the plugin claims the message and stopped on the last reply or on failure. Task 1.7 checks per channel that the takeover path offers them. A channel where it does not shows no typing, which the spec allows.

Attachments: the host reads each item of `ctx.media` (OpenClaw saves inbound media) and sends it as a multipart part, and the agent applies the chat endpoint's checks. A voice note goes to ascend-audio-scribe's REST transcription with the service token, through the backend in `app.channels.audio.backend` (default `local`), for a file of at most `app.channels.audio.max-bytes` (default 25 MiB), and records one `UsageEvent` of kind `transcription` through `UsageEventPort` of `add-deployment-modules`, whose default does nothing. `add-usage-metering-and-quotas` (company, build group 5) registers its implementation later, which turns the event into a ledger row. Source references are sent as titles only, because presigned links point at the private object store (`harden-cloud-deployment` D7).

Timeouts: the host waits up to `OPENCLAW_HOST_AGENT_TIMEOUT` (default 300 seconds) for the terminal event, then sends the fixed "taking too long" reply. The agent keeps running the turn and stores it in history.

### D12: Outbox, event stream and approval buttons

The outbox is the one way the agent sends without an inbound message. Rows are written by listeners of `SubagentRunChangedEvent` and `ApprovalChangedEvent` (both delivered after commit), by the `discord` owner notification channel, by the link service and by the loop guard. `GET /api/v1/channel-host/events?platforms=<list>` sends the rows of the listed platforms in id order with the id as the SSE id, so each `channels` container reads only the platforms it runs (D18), resumes after `Last-Event-ID`, wakes on a Postgres `LISTEN` notification sent by the insert, and checks every `app.channels.outbox.poll-interval` (default 5 seconds) as a fallback. The `LISTEN` is not a connection of this change's own: the outbox registers a `PostgresNotificationHandler` on the one `PostgresNotificationListener` of `add-keycloak-login` D20 with the channel `channel_outbox_inserted` (payload: the new row's id), and its `onReconnect()` wakes every open stream to re-read its rows after its last sent id, because a notification sent while the listener was disconnected is lost. The stream reads only Postgres rows and wakes on `NOTIFY` with the 5 second poll as fallback, so a row any agent instance writes reaches a `channels` container connected to any other instance (owner answer 87, rule R1). A sent row is redelivered after `app.channels.outbox.redeliver-after` (default 2 minutes) without an ack, at most `app.channels.outbox.max-attempts` times (default 10). Delivery is at least once, and the host keeps the ids of the last `OPENCLAW_HOST_DELIVERED_IDS_MAX` delivered rows (default 10,000) on its volume to skip repeats.

The host delivers through `api.runtime.channel.outbound.loadAdapter(platform)`. The exact call shape of `sendPayload` is checked in task 1.6.

Approval prompts: the payload holds the approval view fields of the spec and its two buttons, `{approval_approve, <approval id>}` and `{approval_deny, <approval id>}`. A digest does not fit in a custom id, so the agent reads the digest from the outbox row that the message was built from.

Every button of every outbox message goes through one action endpoint (owner answer 89.6 of 2026-10-08). The outbox row's `payload` holds the list of its buttons, each `{actionType, subjectId, label}`, and a button carries the custom id `ascend:<outbox id>:<button index>`, which fits Discord's 100 character limit. The host registers one interactive handler, `api.registerInteractiveHandler({ channel: "discord", namespace: "ascend" })`, and a press calls `POST /api/v1/channel-host/actions` with the outbox id, the button index, the platform and the presser's account id. The agent reads the action type and the subject id from the row, never from the host, binds the row's tenant with `TenantContext.runAs`, resolves the presser through the link, and calls the `ChannelActionHandler` bean of `add-shared-scheduler` whose `actionType()` equals the button's action type, with the tenant, the linked user's identity, the subject id, the outbox id and the channel. The action types are `approval_approve` and `approval_deny`, whose two handlers this change registers (each checks `ADMIN` of the approval's tenant and calls `ApprovalService.decide` with the digest from the row, `remember: false`, channel `discord` and the linked user, as before, made in `add-action-approvals`, its D11 and D12), and `self_improvement_undo`, whose handler `add-self-improvement` registers. A later change that adds a button adds an action type and its handler bean, never a new endpoint or a new host namespace. A press whose row or button index does not exist answers 404 `not_found`. A press whose action type has no handler bean, because its module is off, answers 409 with a problem detail and changes nothing. The endpoint keeps no state of its own, so a press that reaches any agent instance works the same (owner answer 87, rule R1). Updates edit the prompt message through the Discord message edit action where the pinned plugin offers it, else a follow-up message is sent.

Credential prompts: the fixed line on a prompt for an approval of kind `integration_credential` (owner answer 46.2) is added to the prompt payload by `add-self-built-integrations`, which lands later and owns that kind (dependency fix of 2026-10-05). A prompt never shows a credential value.

Button lifetime: callbacks are kept 24 hours, the maximum, which equals the default approval timeout. The agent's startup banner warns when `app.approvals.timeout` is longer than 24 hours. Whether OpenClaw keeps component callbacks across a host restart is checked in task 1.6. If it does not, the host reads `GET /api/v1/channel-host/approvals/prompts?state=pending` after each start and edits each pending prompt to attach fresh buttons.

Background run status: a listener of `SubagentRunChangedEvent` writes `run_status` rows for background runs whose conversation has a binding, on the first `running` and on the final state. One rule decides which runs are reported: every run kind that `add-agent-subagents` owns (`subagent`, `coding`, `scheduled`, `self_review`, `integration`) except `approval`, whose state the owner already sees through the approval prompts and their updates. A run whose conversation has no binding sends nothing.

Owner notifications: `DiscordOwnerNotificationChannel implements OwnerNotificationChannel` of `add-shared-scheduler`, named `discord`, a bean with `@ConditionalOnModule("channels")`. `canReach(tenantId, userId)` is true when the user has an active Discord link in that tenant. `deliver` is called by `OwnerNotificationService.create` inside the caller's transaction (`add-shared-scheduler` D8) and writes one `channel_outbox` row of kind `owner_notification` for the linked account's direct message, with the title, the body cut to the platform limit with a visible note, the run id when there is one, the notification id, and one button per entry of the notification's `actions` list. It makes no network call. The row commits with the notification, and its insert wakes the event stream through Postgres `NOTIFY` after the commit, so delivery stays real time. The outbox is the one retry layer for owner notifications (owner answer 89.6 of 2026-10-08): its attempts, its redelivery after 2 minutes without an ack and its `dead` state are the only retries, and `add-shared-scheduler` schedules no delivery retry. When an outbox row of kind `owner_notification` becomes `delivered` or `dead`, the outbox code calls `OwnerNotificationService.recordDeliveryOutcome(notificationId, "discord", outcome, errorCode)` once, in the same transaction as that state change, with the outcome `delivered` or `failed`, so the notification view shows the real end state of its Discord delivery. The Undo buttons of a notification of source `self_improvement` are entries of action type `self_improvement_undo` in the notification's `actions` list, written by `add-self-improvement` when it creates the report. This channel renders them like any other button, and the handler of `add-self-improvement` acts on them. No second endpoint and no second host namespace exist.

### D13: Peer bots and the loop guard

Peer bots are links of kind `peer_bot`, created by a tenant `ADMIN`. Messages from bots pass three gates in order: OpenClaw's `allowBots: "mentions"` (a bot message reaches the plugin only when it mentions our bot), Ascend's registry (only linked peer bots in their allowed channels), and Ascend's loop guard. The guard counts bot turns per chat and thread in Redis (`INCR` with an expiry of `app.channels.peer-bots.loop-guard-expiry`, default 1 hour, reset by a linked human message) and rate limits each peer with a one minute bucket. When Redis is down, peers are not answered (fail closed), and humans are answered as usual. OpenClaw's own `botLoopProtection` (20 events per 60 seconds per pair) and Hermes's own guard stay on as outer limits. Ascend's limits (`app.channels.peer-bots.max-turns-without-human`, default 6 turns without a human, and `app.channels.peer-bots.max-replies-per-minute`, default 4 replies per minute) are lower, so Ascend stops first.

Replies to a peer start with the literal mention `<@peer id>` when `mention_in_replies` is true, because Hermes with `DISCORD_BOTS_REQUIRE_INLINE_MENTION=true` (its default) needs it. `docs/CHANNELS.md` tells the owner to set `DISCORD_ALLOW_BOTS=mentions` on his Hermes.

A peer turn runs as the registering `ADMIN`, but text from another bot is untrusted. The relay passes a narrowed tool list (`app.channels.peer-bots.allowed-tools`, default empty) through step 3 of `ChatToolset` of `add-agent-skills` (its D3), which this change adds itself (task 6.6), turns memory extraction off for the turn, and wraps the peer's text as "Message from bot <name>:" so the model never reads it as the owner's words. Without tools, a peer cannot reach `Task`, `personality_propose` or `user_facts_update`. The relay also sets the peer bot mark on the `ChatTurnRequest` of a peer turn. Only this change's agent API can set that mark, and a chat request from any other caller cannot. `StreamingChatExecutor` turns the mark into the `ProvenanceSource` `peer_bot_turn` of `add-agent-soul` D15, so the turn's `RequestProvenance` is `untrusted` from its start. This change keeps no provenance marking of its own. The two tools of `add-agent-soul` read that one shared value, so nothing a peer wrote can write the personality or the user facts, and `add-self-improvement`, which lands later, reads the same value, so nothing a peer wrote can start a self change.

Ascend only answers peers. No tool, job or listener of this change sends a first message to another bot (owner decision of 2026-10-02).

### D14: Inbound webhooks through the gateway

Polling or Socket Mode is the default for Telegram and Slack, so the first three platforms need no inbound route. For webhook mode and for webhook-only platforms, the gateway site gets one route per platform under `/hooks/<platform>/`, forwarded to port 18789 of the `channels` container that runs that platform (`ascend-openclaw-host-channels` by default, D18) with the prefix rewritten to the plugin's own path (`/telegram-webhook`, Slack's events path, `/line/webhook`, `/googlechat`, `/webhooks/sms`, and the Teams path checked in its task). The gateway forwards nothing else to any container of the host, so the OpenClaw WebSocket, RPC and health endpoints stay on the private network. Each platform's own check (Telegram `webhookSecret`, Slack signing secret, LINE signature, Twilio signature) runs in the channel plugin before dispatch. Routes for the platforms the owner has not enabled answer 502 from the gateway, which leaks nothing. This change adds these routes and the refusal of `/api/v1/channel-host/` to `gateway/Caddyfile` of `harden-cloud-deployment` itself (task 7.4), because that change lands earlier (build group 3, position 4).

### D15: Deployment

Compose service `ascend-openclaw-host-channels` (D18) with `profiles: ["channels"]`, `OPENCLAW_HOST_ROLE=channels` and `OPENCLAW_HOST_CHANNELS`, built from `apps/ascend-openclaw-host` through the anchor `x-openclaw-host`, image pinned, `restart: unless-stopped`, the logging anchor, `no-new-privileges`, all capabilities dropped, read-only root with a tmpfs, the named volume `openclaw-host-channels-state` at the state directory, memory limit `mem_limit: ${OPENCLAW_HOST_CHANNELS_MEMORY_LIMIT:-<default>}` (1 GiB to start, measured in task 7.3, whose peak with headroom becomes the default), `depends_on` the agent with `condition: service_healthy`, and a healthcheck on the plugin's readiness route. Ports: `"${EXPOSE_BIND:-127.0.0.1}:18789:18789"` for local work only. Environment: `OPENCLAW_HOST_CHANNELS`, the channel tokens, `OPENCLAW_GATEWAY_TOKEN`, `OPENCLAW_HOST_CLIENT_ID`, `OPENCLAW_HOST_CLIENT_SECRET`, the agent and Keycloak addresses (`OPENCLAW_HOST_AGENT_URL` and `KEYCLOAK_ISSUER_URI`), and the OTLP endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`). Every one of them that has a default is written `${VAR:-default}` with the same default in the host's code (owner rule 98 of 2026-10-08, the list in the "Answer 98" record below). The `apps` services are D18.

The module switch is `add-deployment-modules`: `channels` in `COMPOSE_PROFILES` starts the container, and the agent reads the same list as `ASCEND_MODULES`. Every channel bean of the agent (`ChannelHostController`, `ChannelLinkController`, `PeerBotController`, the relay, the listeners, the outbox and `DiscordOwnerNotificationChannel`) carries `@ConditionalOnModule("channels")`. With the module off these beans do not exist, so the routes answer 404, no listener writes an outbox row, and the `discord` notification channel is not offered to the notification store. There is no `app.channels.enabled` flag. Voice notes check `ModuleState` for `audio` and answer the sender with a fixed text that voice notes are not available when it is off, so `channels` lists `audio` under `uses`. Run status messages need no module: the run service, the run view and `SubagentRunChangedEvent` are `core-chat` of `add-agent-subagents` (its D2), so a bound conversation gets run status messages in every deployment, for runs of every kind.

`.env.example` gains, with empty values, the secrets only: `DISCORD_BOT_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_SIGNING_SECRET`, `OPENCLAW_GATEWAY_TOKEN`, `OPENCLAW_HOST_CLIENT_SECRET` and `CHANNEL_PAIRING_PEPPER`. The per deployment values `OPENCLAW_HOST_CHANNELS`, `OPENCLAW_HOST_GROUPS_<PLATFORM>` and `OPENCLAW_HOST_APPS_REPLICAS` have defaults (empty, empty and 1), so by owner rule 98 of 2026-10-08 they get no `.env.example` line: compose writes them `${VAR:-default}`, and `docs/CONFIGURATION.md` and `docs/CHANNELS.md` describe them. The secrets of the role `apps` are listed in D18 to D20.

Platforms: Discord, Telegram and Slack first (owner decision of 2026-10-02). WhatsApp is switched on only with a spare phone number that is not the owner's own, because the Baileys plugin automates a normal WhatsApp account and that account can be banned. `docs/CHANNELS.md` states this, and the generator refuses `whatsapp` in `OPENCLAW_HOST_CHANNELS` unless `OPENCLAW_HOST_WHATSAPP_SPARE_NUMBER=true` is set, so the choice is written down once.

### D16: Data the host keeps

OpenClaw's state directory may hold session records, transcripts of user turns and cached inbound media even after a takeover. Task 1.5 measures exactly what one message leaves on the volume, and what one `/tools/invoke` call leaves in an `apps` container, whose state directory is a tmpfs (D18). The host then sets the shortest session pruning and media retention the pinned version accepts, and the outbox kind `purge` asks the host to delete OpenClaw's session data of a platform account. The agent writes a `purge` row when a link is removed. `add-audit-and-gdpr-compliance` (company, build group 5) adds user erasure later, which removes the user's links through the same path, so each removed link queues its `purge` row. `docs/CHANNELS.md` lists what each volume and tmpfs holds and for how long.

### D17: Metrics, logs and traces

Host: OpenTelemetry through the OTLP endpoint of the platform collector. Metric names are domain first, dotted and lower case, under `openclaw.host.`: `openclaw.host.messages{platform,outcome}`, `openclaw.host.agent.duration{platform,outcome}`, `openclaw.host.replies{platform,outcome}`, `openclaw.host.outbound.events{kind,outcome}`, `openclaw.host.channels.connected{platform}`, `openclaw.host.openclaw.agent.runs`, `openclaw.host.build.info{openclaw_version}`, and in `apps` containers `openclaw.host.app.tool.calls{tool,outcome}`, `openclaw.host.app.tool.duration{tool,outcome}` and `openclaw.host.app.tools.listed`. The `tool` tag is bounded by the tools of the pinned app plugins. If the pinned OpenClaw sets up a global meter provider through its `diagnostics-otel` plugin, the host registers its instruments there, otherwise it starts the OpenTelemetry Node SDK itself (task 7.5). The correlation id is the `x-request-id` the host sends with every agent call and writes into every log line of that message. In an `apps` container the bridge logs its own call id and the MCP request id instead. Every metric and log line carries the role and the container's host name as resource attributes, never as metric tags.

Agent: names under `channel.` following `add-observability` D2 and D5, tagged only with `platform`, `outcome`, `kind` or `state`. The AI Pipeline dashboard gains one row: messages by outcome, turn duration, outbox backlog and pairing redeems. The calls of app tools are measured by the MCP metrics of `add-mcp-tool-servers` with `server=openclaw-apps` (or the id of a plugin group entry).

### D18: One service, a role and a plugin list per container

`ascend-openclaw-host` is one program, one image, one codebase and one update procedure for every OpenClaw plugin, chat platform connections (channels) and app plugins alike (owner answer 48 of 2026-10-02). It runs as several containers when the load or the number of plugins grows. The two former modes are now the two roles a container can have. Every container reads at startup:

- `OPENCLAW_HOST_ROLE`: `channels` or `apps`. Any other value, or none, is refused.
- Its plugin list: `OPENCLAW_HOST_CHANNELS` (channel ids, comma separated) for the role `channels`, `OPENCLAW_HOST_APP_PLUGINS` (app plugin ids, comma separated) for the role `apps`. Both are empty by default.

Rules, checked by the validator of D3 before the gateway starts, each refusal one ERROR line that names the setting and never a value:

1. A `channels` container loads the takeover plugin and only the channel plugins of its list, with `config/openclaw.channels.template.json5` (D3). It refuses a non-empty `OPENCLAW_HOST_APP_PLUGINS`, any `OPENCLAW_HOST_APP_CONFIG_<ID>` and any bridge token, so a container that holds chat platform tokens never runs third party app plugins.
2. An `apps` container loads only the app plugins of its list and the MCP bridge of D19, with `config/openclaw.apps.template.json5` (below). It refuses a non-empty `OPENCLAW_HOST_CHANNELS`, every channel token variable, `OPENCLAW_HOST_CLIENT_SECRET` and `CHANNEL_PAIRING_PEPPER`, all listed once in `src/config/forbidden-env.ts`.

One container cannot see the others, so the rule that a chat platform connection runs in exactly one container (each bot token allows one active connection) is checked where the whole layout is visible: `OpenClawHostComposeTest` in the host module reads `docker compose config --format json` and fails when one channel id is in the lists of two containers, when a `channels` service asks for more than one replica, or when one service sets both lists. The unique inbound key of D6 is the last guard: a message that still arrives twice runs one turn.

Compose layout, decided: several compose services built from the one image through one YAML anchor `x-openclaw-host` (build context, image tag, hardening of D15, logging, healthcheck), and replicas only for the role `apps`:

| Compose service | Role | Profile | Replicas | State | Networks |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ascend-openclaw-host-channels` | `channels` | `channels` | one, no `deploy.replicas` | named volume `openclaw-host-channels-state` | `default` |
| `ascend-openclaw-host-apps` | `apps` | `openclaw-apps` | `deploy.replicas: ${OPENCLAW_HOST_APPS_REPLICAS:-1}` | tmpfs only | `mcp-openclaw-apps-net` |
| `ascend-openclaw-host-apps-<group>`, added by the owner when needed | `apps` | `openclaw-apps` | `deploy.replicas` of its own | tmpfs, or a named volume with one replica | `mcp-openclaw-apps-<group>-net` |

- The `channels` service holds every enabled channel by default. To split channels, for example Discord into a container of its own, the owner adds a second `channels` service from the anchor with its own list and its own volume, takes those ids out of the first list, and points the platform's webhook route at the new service when the platform has one (D14). The compose test refuses any overlap.
- The `apps` service runs every app plugin of its list in each replica. Replicas share nothing: no `container_name`, the state directory on a tmpfs, the configuration generated at start, and the plugins in the image. More load means a higher `OPENCLAW_HOST_APPS_REPLICAS` in `.env` and `docker compose up -d`.
- A plugin group is a further `apps` service with its own `OPENCLAW_HOST_APP_PLUGINS`, its own secrets, its own network and its own MCP entry (D19). It is used when one plugin needs its own memory limit, secrets that the other plugins must not hold, or a persistent volume. A plugin group with a named volume keeps one replica, because two gateways must not share one state directory.

Why several services from one image and not one scaled service: replicas of one compose service are identical, so they can only spread the load of one plugin list. A role and a plugin list are environment values, and different environments are different compose services. Why replicas only for `apps`: an app tool call is one independent request that any identical replica can answer (D19), while a chat platform connection must be held by one container. Why `deploy.replicas` from `.env` and not `docker compose up --scale` on the command line: the count stays in the files the owner keeps, and every command runs against the main compose file with no extra flag.

Configuration of an `apps` container, `config/openclaw.apps.template.json5`:

- No channel and no channel plugin enabled, so no inbound message exists and the takeover plugin is not loaded.
- `gateway.mode: "local"`, the gateway bound to loopback inside the container, the gateway auth token from `OPENCLAW_GATEWAY_TOKEN_APPS` (its own value, never the one of a `channels` container), the Control UI off.
- No model, provider, auth profile, memory plugin, heartbeat, cron, hook or skill, as in D3. Skills are switched off with an empty skill allowlist, so the bundled skills never load.
- `plugins.allow` lists exactly the app plugin ids in `OPENCLAW_HOST_APP_PLUGINS`, each of which must be pinned in `package.json`.
- `tools.allow` lists exactly the tools those plugins declare in their manifests' `contracts.tools`, and nothing else. `gateway.tools.deny` keeps OpenClaw's hard deny list and adds every core tool group, so no core tool (browser, web fetch, file, exec, sessions, messaging) can be invoked even if a later version adds one.
- The plugin config of each app plugin (`plugins.entries.<id>.config`) is generated from `OPENCLAW_HOST_APP_CONFIG_<ID>` (non-secret JSON) and environment variable references for its secrets, never values.

The validator refuses to start, naming the setting, when any model, provider, skill, channel, cron, heartbeat or memory is enabled, when `plugins.allow` names an id that is not pinned in `package.json`, when `tools.allow` names a tool no allowed plugin declares, or when a known provider key variable is set. The agent run observer of D2 stays on: any agent run start is an ERROR line, a counter and a failed readiness, as in a `channels` container.

Why app plugins never share a container with channels: an app plugin is third party code that runs in the gateway process. In the same process it could read the channel tokens, the agent client secret and the pairing pepper, and its crash would take the channels down. OpenClaw's own docs advise separate gateways across trust boundaries (Context). An `apps` container holds only its app plugins' own secrets, its gateway token and its bridge token. It is still the same service, image, codebase and update procedure.

Alternatives considered: app plugins inside a `channels` container (rejected: shared secrets and a shared crash domain), one compose service per plugin by default (rejected: each OpenClaw gateway costs its own memory, and the owner asked for more containers only when the load or the number of plugins grows), and connecting each app's own MCP server instead of OpenClaw plugins (rejected by the owner's decision of 2026-10-02 for the apps he named, and still possible for any other app as one entry of `add-mcp-tool-servers`).

### D19: The MCP bridge over `tools.catalog` and `/tools/invoke`, and one entry per `apps` service

`src/apps/` runs a Streamable HTTP MCP server with `@modelcontextprotocol/sdk` on port `OPENCLAW_HOST_APPS_MCP_PORT` (default 18790), path `/mcp`, next to the gateway in every `apps` container. It runs in the SDK's stateless mode (no `Mcp-Session-Id`, no stream from server to client), so every replica can answer every request:

- Authentication: every request must carry `Authorization: Bearer <OPENCLAW_APPS_MCP_TOKEN>`, compared in constant time. Anything else answers 401. The agent sends the header through the generic headers of its server entry. A plugin group uses its own variable `OPENCLAW_APPS_MCP_TOKEN_<GROUP>`.
- `tools/list`: the bridge reads the gateway's `tools.catalog` over the loopback WebSocket with the apps gateway token, keeps only entries with `source: "plugin"` whose `pluginId` is in `OPENCLAW_HOST_APP_PLUGINS`, and maps each to an MCP tool with its name, description and input schema. Task 1.8 proves which fields `tools.catalog` returns on the pinned version. If it carries no input schema, the bridge reads the TypeBox `parameters` of each tool, which are JSON Schema objects, from the plugin's registered tool definitions through the plugin SDK at startup. The listing is built on start. It changes only with a new image, and every replica of one service runs the same image and the same list, so the list is the same on every replica. No `notifications/tools/list_changed` is sent: the agent lists again when its tool listing cache expires.
- `tools/call`: the bridge sends `POST http://127.0.0.1:18789/tools/invoke` with `{ "tool": <name>, "args": <arguments>, "idempotencyKey": <a new random UUID per call> }` and the apps gateway token. A fresh UUID is used and not the MCP request id, because without a session the request ids of different agent connections can repeat. `{ ok: true, result }` becomes the tool result: text content as it is, and a structured `details` object as JSON text. `{ ok: false }` and the statuses 400, 403, 404 and 500 become a result with `isError: true` and the gateway's error type and sanitized message. 401 and a timeout become `isError: true` with a fixed text and an ERROR line. The call timeout is `OPENCLAW_HOST_APP_TOOL_TIMEOUT` (default 60 seconds), below the agent entry's `request-timeout`.
- No OpenClaw approval prompt runs on this path (Context), which is why every approval is Ascend's (D20).

The MCP entry across several containers, decided: one entry per `apps` compose service, with all of its replicas behind that one entry. The entry's URL is the compose service name. Docker's internal DNS answers that name with the address of every running replica, so the agent's HTTP client spreads new connections over the replicas, and the stateless bridge lets any replica answer any call. The spread is per connection, not per call, which is enough for tool calls that each take seconds. Task 1.10 proves on the pinned versions that the agent's MCP client works against the stateless bridge and that the calls of one agent reach more than one replica.

Alternatives considered: one entry per container (rejected: replicas have no stable names, and the same tools under two entries need two prefixes, so the model would see every tool twice), and one entry with a load balancer in the agent (rejected: Spring AI's MCP client has one URL per connection and no balancer, and writing one adds code for what Docker's DNS already does).

The agent's entry, in `application.yaml` of ascend-agent:

```yaml
app:
  mcp:
    servers:
      openclaw-apps:
        module: openclaw-apps
        url: ${APP_MCP_SERVERS_OPENCLAWAPPS_URL:http://ascend-openclaw-host-apps:18790}
        trust: external
        tool-prefix: openclaw
        discovery: search
        default-mode: requires_approval
        max-result-chars: ${APP_MCP_SERVERS_OPENCLAWAPPS_MAXRESULTCHARS:20000}
        request-timeout: ${APP_MCP_SERVERS_OPENCLAWAPPS_REQUESTTIMEOUT:75s}
        headers:
          Authorization: "Bearer ${OPENCLAW_APPS_MCP_TOKEN:}"
        tools:
          overrides: {}
```

A plugin group adds one more entry written the same way: id `openclaw-apps-<group>`, module `openclaw-apps`, URL `http://ascend-openclaw-host-apps-<group>:18790`, tool prefix `openclaw_<group>` (prefixes must be unique, `add-mcp-tool-servers` D4), and its own token variable. Moving a plugin from one service to another therefore changes the names of its tools, and its overrides move with it to the other entry. `docs/OPENCLAW_APPS.md` says so.

Trust is `external`, decided here: the code that answers is third party plugin code, so the entry must never receive the service token or the tenant and request ids in `_meta`, its calls are metered, and its tools ask first. `internal` would hand all three to code Ascend does not own.

Network: every `apps` service sits on its own internal network (`mcp-openclaw-apps-net`, or `mcp-openclaw-apps-<group>-net` for a plugin group), shared only with the agent and the `mcp-egress-proxy` of `add-mcp-tool-servers`, which is always on with no profile (owner answer 76.5 of 2026-10-08). This change adds its own use of it: the proxy joins each `apps` network and the containers set the proxy variables (task 8.4). Its replicas share that network, and two plugin groups share none. The containers set `HTTPS_PROXY`, `HTTP_PROXY` and `NODE_USE_ENV_PROXY=1` so Node's built-in `fetch` uses the proxy. A plugin request that bypasses the proxy has no route, because the network is internal. The proxy refuses private and internal addresses, so a plugin cannot reach the agent, the database or another container through it. Task 1.9 proves both on the pinned Node and OpenClaw versions.

### D20: Installing and reviewing an app plugin

Installing is the owner's step, never the agent's and never at run time:

1. Choose the plugin on npm or ClawHub and read its source and its `contracts.tools`.
2. Add it to `apps/ascend-openclaw-host/package.json` with an exact version. A plugin published only on ClawHub is downloaded once as a tarball, checked in under `apps/ascend-openclaw-host/vendor-plugins/` and referenced as a `file:` dependency, so the lock file records its integrity hash.
3. Run the update procedure of D5, which refreshes `app-tools.lock.json` with the plugin's tool names and input schema digests.
4. Add the plugin id to the `OPENCLAW_HOST_APP_PLUGINS` of the `apps` service that should run it (`ascend-openclaw-host-apps`, or a plugin group service of D18), its non-secret config to `OPENCLAW_HOST_APP_CONFIG_<ID>` and its secrets to the root `.env`, add the secret variable names to that service only, and rebuild and restart with `openclaw-apps` in `COMPOSE_PROFILES`.

`openclaw plugins install` is never run inside the container, the generator writes `plugins.allow` from the pinned list only, and the validator refuses any other plugin, so nothing reaches the gateway that the lock file does not hold.

Reviewing: every tool of the entry is `requires_approval` by the `trust: external` default of `add-mcp-tool-servers`. After reading a tool's description and schema in `app-tools.lock.json`, the owner reviews it by adding `<tool>: { mode: allowed }` to the entry's overrides, or a `category`, `rememberable` and `scope-arguments` for a tool that should keep asking with a better preview. A tool whose input schema digest changes in an update fails the app plugin test of D5, so the owner sees it before the new version is accepted, and a new tool without an override keeps asking.

### D21: Skills that wrap a command line tool are not run here

The research in Context shows that many OpenClaw app integrations are skills, not plugins: `gog` for Google Workspace, `gh` for GitHub, `himalaya` for mail and others. A skill is instructions for OpenClaw's agent, which runs the tool with its `exec` shell tool. Both are excluded here: OpenClaw's agent never runs (D2), and `exec` is on the hard deny list of `/tools/invoke`. So no `apps` container runs skills.

How such a tool would run in Ascend, if the owner names an app that exists only as a command line skill:

- The skill's instructions become an Ascend skill of `add-agent-skills`, which tells Ascend's model to run the tool with the shell tool of a sandbox workspace of `add-agent-sandbox`.
- The command line tool is installed at a pinned version in a sandbox image profile of `add-agent-sandbox`, so nothing is downloaded at run time.
- The workspace holds no secret. Its requests leave through the per-workspace egress proxy, and a credential is added outside the workspace by the credential gateway pattern of `add-coding-agent-delegation` (one fixed upstream host, allowed path prefixes, one header, secret files on a tmpfs). That works only for a tool that can send its requests to a configured base URL where the gateway adds the header. A tool that must keep its own OAuth refresh token or key ring in the workspace (`gog` stores its Google tokens locally after `gog auth add`, `skills/gog/SKILL.md`) cannot meet the rule that no secret is in the workspace, and is not used this way.

Route chosen: OpenClaw tool plugins in containers of the role `apps`, now. They run without OpenClaw's agent through a documented endpoint, keep their secrets in their own containers, and give the model typed tools that the approval gate sees one by one. The command line skill route is described here and not built now, because the owner asked for no app list and it needs a sandbox image and a gateway route per tool. When the owner names such an app, it becomes a change of its own, or the app is reached through a tool plugin, a configured MCP server of `add-mcp-tool-servers` or a self-built integration of `add-self-built-integrations`.

### D22: Periodic work: one shared system task, the rest stays local

The rule of `add-shared-scheduler` D2 applies: work that writes shared state runs once per deployment on the shared scheduler, and work that only serves one instance stays local.

Shared: the system task `channel-host-cleanup` of `add-shared-scheduler`, a value of its `SchedulerTaskName` enum that this change adds, registered by a bean with `@ConditionalOnModule("channels")` under that change's registration contract. Its schedule is daily, the five field cron `app.scheduler.system-tasks.channel-host-cleanup.cron` (default `0 4 * * *`) with `.time-zone` (default `Europe/Warsaw`). Each firing runs on exactly one agent instance and deletes, for every tenant:

- `channel_inbound_message` rows older than `app.channels.inbound.retention` (default 24 hours, D6),
- `channel_pairing` rows that expired and were never redeemed (D7, D8),
- `channel_outbox` rows that are `delivered` or `dead` and older than `app.channels.outbox.retention` (default 7 days, D12).

A firing that runs twice deletes nothing more, and a failed firing is retried at the next one, so nothing is lost while it waits.

Local, and said so in the code and in `docs/CHANNELS.md`:

- The event stream of D12 belongs to the one agent instance that serves the open connection of one `channels` container. Its fallback check every `app.channels.outbox.poll-interval` (default 5 seconds) and its redelivery of rows sent `app.channels.outbox.redeliver-after` ago (default 2 minutes) without an ack run inside that stream. Marking a row `sent` is a conditional update, so two instances can never send the same row twice.
- The loop guard counters of D13 expire through their Redis time to live, with no job.
- In the host, the reconnect with backoff of the event stream and the agent token refresh run inside each container.

## Required edits to other changes

This change does not edit any other change. Each edit below was asked of the named change by its owner. Every one of them is now made there, checked on 2026-10-03 and noted under its heading, and the tasks say which part of the target they use. A task that uses an edit of an earlier change uses it as applied. An edit that a later change or a company change carries is that change's own work, and no task here waits for it (owner rule of 2026-10-04, dependency fix of 2026-10-05).

### `add-deployment-modules`

1. Design D3, modules that later changes add: a catalog entry `openclaw-apps` from this change, whose compose services are the `apps` containers of `ascend-openclaw-host` (`ascend-openclaw-host-apps` and any plugin group service of D18), `requires` none, `uses` none, and the agent secret `OPENCLAW_APPS_MCP_TOKEN`. `mcp-egress-proxy` is not part of the entry: it is always on with no profile (owner answer 76.5 of 2026-10-08), and the `apps` containers only use it. The entry is added to `personal`.
2. Design D3, the `channels` row: its compose services are the `channels` containers of `ascend-openclaw-host` (`ascend-openclaw-host-channels` by default), and `uses` is `audio` only. `subagents` is dropped: the run status messages read `SubagentRunChangedEvent` and the run view, which are `core-chat` of `add-agent-subagents` (its D2), and the peer bot narrowing that keeps `Task` away from a peer works on the tool list, so no class of the module `subagents` is used. `scheduler` is dropped too, because the `OwnerNotificationChannel` port this change implements comes from `add-shared-scheduler`, not from the `scheduler` module of `add-scheduled-tasks`.
3. Design D3 and its compose text: `ascend-openclaw-host` is one service, one program and one image, run as several containers, each with a role and a plugin list (D18). A chat platform connection runs in exactly one container, app plugins may be spread over many containers, and a container that holds chat platform tokens never runs app plugins.
4. Its edits 1 to 5 to this change are applied here: no `app.channels.enabled`, every channel bean carries `@ConditionalOnModule("channels")`, both changes read `ASCEND_MODULES`, the catalog entries `channels` and `openclaw-apps` are added to `personal` (D15), voice notes check `audio` (D15), and the containers follow the roles of D18. Its statement that `uses` of `channels` holds `subagents` is replaced by edit 2 above.

Edits 1 to 3 are made in that change (checked 2026-10-03, its D3).

### `add-shared-scheduler`

1. Design D2, the inventory: a row for the system task `channel-host-cleanup` of this change (owner `add-openclaw-plugin-host`, home shared, daily, default `0 4 * * *` in `Europe/Warsaw`, module `channels`), and a row for the event stream checks and the loop guard of this change as local work (D22). `SchedulerTaskName` gains the value `channel-host-cleanup`, added by this change when it lands.

Made in that change (checked 2026-10-03, its D2 inventory and its section for this change).

### `add-keycloak-login`

These edits were made in `add-auth-and-identity` and moved to `add-keycloak-login` with the split of 2026-10-04 (owner rule of 2026-10-04), except the groups of edit 3, which stay in `add-auth-and-identity` and plug in through `IdentityContributor`. `add-keycloak-login` lands before this change, so the matrix rows of edit 2 are added by this change itself (task 3.7), the rule of its D4.

1. Realm export (design D2 and the `identity-provider` spec): a confidential client `ascend-openclaw-host` with only the client credentials grant, whose secret only `channels` containers hold, a client scope `channel.relay` assigned to it, and no other client holding that scope. The development overlay carries the same client with a development secret. A confidential client `ascend-agent-directory` with the service account role `view-users` of `realm-management` and nothing else.
2. Design D4 authorization matrix and the `agent-authentication` spec: `/api/v1/channel-host/**` requires the scope `channel.relay` in every profile, including `dev`. `/api/v1/channels/links` (`POST`, `GET`, `DELETE`) needs an authenticated user. `/api/v1/channels/peer-bots/**` needs `ADMIN`. The two user roles stay two.
3. Design D3 and the `user-identity` spec: an identity can also be resolved from a chat platform link for a request on the channel host path. It is built from Keycloak's admin API for the linked user (enabled flag, realm roles, and the groups `add-auth-and-identity` adds later through the same principal factory and cap), is cached for at most the access token lifetime, and fails closed when it cannot be resolved. The cross-provider identity link, deferred as D11 and D12 of `add-auth-and-identity` (company, build group 5, its section "Deferred D11 and D12"), is a different thing (a link between identity providers) and stays deferred there. This change does not wait for it. The offline identity resolution that `add-scheduled-tasks` asks for serves the same need, so one resolver serves both.
4. `docs/SECURITY.md` runbook: rotating the two client secrets.

Edits 1, 3 and 4 are made in `add-keycloak-login` (checked 2026-10-04, its D2 realm export, its D4 table of later changes, its D5 dev rule for the host prefix, its D20, its tasks 1.12, 2.5, 3.7 and 9.1, and its `identity-provider`, `agent-authentication` and `user-identity` specs). Edit 2 is this change's task 3.7.

### `harden-cloud-deployment`

1. Design D2 and the `production-deployment` spec "The edge gateway is the only publicly bound service": the gateway also routes `/hooks/<platform>/*` to port 18789 of the `channels` container that runs that platform (`ascend-openclaw-host-channels` by default, D18), rewritten to the platform's webhook path, for Telegram and Slack now and for every webhook platform the owner enables later by the same pattern, and it answers 404 for `/api/v1/channel-host/*` without forwarding it. Nothing else reaches a `channels` container, and nothing reaches an `apps` container.
2. Its D1 port list: `ascend-openclaw-host-channels` publishes `18789` only through `${EXPOSE_BIND:-127.0.0.1}`, on the host port `${OPENCLAW_CHANNELS_HOST_PORT:-18789}` (owner answer 100.6 of 2026-10-09). A second `channels` service publishes no port, and no `apps` service publishes a port.
3. The external port scan scenario stays true: no new public port.

`harden-cloud-deployment` lands earlier (build group 3, position 4), so edits 1 and 2 moved here by the dependency fix of 2026-10-05 and are this change's own work: tasks 7.4, 7.9 and 9.13, and the MODIFIED requirements of `specs/production-deployment/spec.md` of this change. Edit 3 holds as written.

### `add-action-approvals`

1. Design D11, the Discord paragraph: replace the description by role with this change's D12 (outbox prompt, buttons with the outbox id, decision through the one action endpoint `/api/v1/channel-host/actions` with the action types `approval_approve` and `approval_deny` as the linked owner, owner answer 89.6 of 2026-10-08). Its Context and D11 sentences that this change does not exist yet are removed.
2. Design D12 and the `action-approval-decisions` spec "Only the owner decides": `ApprovalService.decide` takes the deciding identity as an argument, so a decision through the channel relay acts as the linked user with channel `discord` after the same `ADMIN` and digest checks. Add a scenario: a Discord press by the linked owner approves with `decisionChannel` `discord`, and a press by an account linked to a non-admin user is refused.

Edits 1 and 2 are made in that change (checked 2026-10-03, its D11 and D12 and its `action-approval-decisions` spec).

### `add-chat-streaming-and-conversations`

1. Design D4: a conversation can be bound to a chat platform chat and thread through `channel_conversation`, whose foreign key to `conversations(id)` has `ON DELETE CASCADE`, so deleting a conversation removes its binding.
2. The conversation list and messages endpoints show channel conversations like any other. No field is added.
3. The streaming pipeline's turn service is callable in process with a prepared identity and attachments, which the relay uses (no new endpoint).

Edits 1 to 3 are made in that change (checked 2026-10-03, its context, its conversation delete steps and `specs/chat-streaming/spec.md`). Edit 2 asks for no new text there. That change lands earlier (build group 3), so the use of its turn service and the cascade of edit 1 are this change's task 4.2 (moved here from its task 9.6 by the dependency fix of 2026-10-05).

### `add-usage-metering-and-quotas`

Company, build group 5. It registers its `UsageEventPort` implementation and its rate limits later, and this change does not wait for it: this change records the `transcription` usage event of a voice note through `UsageEventPort` of `add-deployment-modules` (D11). The task that proves the two refusals and the ledger row moved there (dependency fix of 2026-10-05).

1. `specs/rate-limiting/spec.md` first requirement: `POST /api/v1/channel-host/messages` consumes the chat buckets of the linked user and tenant. A rejection is answered to the platform as `refused` with reason `rate_limited`, not as an HTTP 429 to the host.
2. `specs/usage-metering/spec.md`: a voice note transcription writes a `transcription` ledger row with `audio_seconds`, attributed to the linked user.
3. `specs/quota-enforcement/spec.md`: a quota refusal of a channel turn is answered as `refused` with reason `quota_exceeded` and the retry time in the text.

Edits 1 to 3 are made in that change (checked 2026-10-03, its rate limiting and quota design and its `rate-limiting`, `usage-metering` and `quota-enforcement` specs).

### `add-audit-and-gdpr-compliance`

Company, build group 5. It registers its `AuditEventPort` implementation later, and this change does not wait for it: this change records the link, pairing and refusal events through `AuditEventPort` of `add-deployment-modules` (task 7.8). The erasure and export task moved there (dependency fix of 2026-10-05).

1. Design line 42 and `specs/audit-logging/spec.md`: add `CHANNEL_PAIRING_CREATED`, `CHANNEL_LINK_CREATED`, `CHANNEL_LINK_REMOVED`, `CHANNEL_PAIRING_REDEEM_FAILED` and `CHANNEL_MESSAGE_REFUSED` (details: platform, link id or a hash of the account id, reason, never text or code).
2. `specs/data-erasure/spec.md`: user erasure deletes the user's `channel_link`, `channel_pairing` and `channel_outbox` rows (the bindings go with the conversations) and queues a `purge` row per removed link, so the host deletes OpenClaw's session data of those accounts. Tenant erasure deletes every channel row of the tenant and purges every account.
3. `specs/data-portability/spec.md`: user export includes the user's links and conversation bindings.
4. `specs/log-redaction/spec.md` "Platform-wide redaction convention covers all six services": seven services, adding `ascend-openclaw-host`, whose containers of both roles share one log format.

Edits 1 to 4 are made in that change (checked 2026-10-03, its D3 action table, its erasure table and its `audit-logging`, `data-erasure`, `data-portability` and `log-redaction` specs).

### `add-tenant-isolation`

Company, build group 5, lands after this change. It plugs in later and this change does not wait for it (owner rule of 2026-10-04).

1. `specs/tenant-isolation/spec.md`: `channel_link`, `channel_pairing`, `channel_conversation`, `channel_inbound_message` and `channel_outbox` carry `tenant_id VARCHAR(64) NOT NULL`, and every query filters on it. `add-tenant-isolation` adds the FK of each to `tenants(id)` in its own migration (D7, dependency fix of 2026-10-05).
2. Fail-closed resolution: an identity resolved from a link (D9) is held to the same rule as a token identity, and a bot account with no configured tenant is refused. The bot account rule and the fail closed `TenantContext` are already in this change (D6, D7, task 3.8), and the cross tenant checks move to `add-tenant-isolation`.

Edits 1 and 2 were made in that change (checked 2026-10-03, its decision 14 and `specs/tenant-isolation/spec.md`). Its decision 14 stated the rule of the owner decision of 2026-10-03 that a change landing after it adds its own foreign keys (superseded by the owner build order of 2026-10-04): this change now lands first, so the foreign keys of the five tables are in the migration of `add-tenant-isolation`, listed in its inbox file of the dependency fix of 2026-10-05.

### `add-agent-skills`

1. Design D3: `ChatToolset` accepts an optional per-request allow list that narrows the tool list after the policy filter and before the approval wrapping, so a peer bot turn gets only `app.channels.peer-bots.allowed-tools`. Without the list, nothing changes.

`add-agent-skills` lands earlier (build group 4, position 1), so this step moved here by the dependency fix of 2026-10-05 and is this change's task 6.6. That change keeps the step's place in its D3.

### `add-self-improvement`

Made in that change (checked 2026-10-03, its D11 and D13 and its required edits table).

1. Design D11 and its required edit to this change: the undo of a change is callable in process with a deciding identity (`SelfImprovementService.undo(changeId, identity, channel)`), so a Discord Undo press decides as the linked owner after the `ADMIN` check, with channel `discord`. `add-self-improvement` lands later (build group 4, position 13), so the Undo buttons (the action type `self_improvement_undo` and its `ChannelActionHandler` bean on the one action endpoint `POST /api/v1/channel-host/actions` of D12, owner answer 89.6 of 2026-10-08), and the check that no self change starts from a peer turn, are tasks of that change (dependency fix of 2026-10-05). This change keeps the peer bot mark that gives the `ProvenanceSource` `peer_bot_turn` of `add-agent-soul` D15 (D13).

### Applied here from other changes

- `add-scheduled-tasks` (its required edit to this change, with the port now in `add-shared-scheduler`): the `discord` `OwnerNotificationChannel`, `canReach` on an active Discord link, delivery as one outbox row (D12). Its edit 2 (the compose profile switches the channel on) is met by `@ConditionalOnModule("channels")` (D15).
- `add-self-improvement`: the peer bot mark on a peer bot turn, which `StreamingChatExecutor` turns into the `ProvenanceSource` `peer_bot_turn` of `add-agent-soul` D15 (D13). The Undo buttons are carried by `add-self-improvement` itself (dependency fix of 2026-10-05).
- `add-agent-soul` (its required edit to this change, D15): a peer bot turn reaches the chat with the peer bot mark that only this change's agent API can set, and `StreamingChatExecutor` turns it into `peer_bot_turn`, so the request is `untrusted` (D13, `channel-peer-bots` spec, tasks 6.5 and 6.7). The `StreamingChatExecutor` step moved here from `add-agent-soul` task 8.5 by the dependency fix of 2026-10-05, and that change keeps the source value and its rule.
- `add-self-built-integrations`: the fixed line on an `integration_credential` approval prompt is carried by `add-self-built-integrations` itself, which lands later (dependency fix of 2026-10-05, D12).
- `add-deployment-modules`: its edits 1 to 4 (D15, and edit 3 above).

### Checked, no edit needed

- `upgrade-spring-boot-4`: this change adds its codes to `ApiErrorCode` itself and uses its problem body and Flyway.
- `add-agent-subagents`: the run view, the run kinds and `SubagentRunChangedEvent` are used as published. Its D17 already names a Discord bot as a consumer.
- `add-agent-soul`: the channel line is one more entry of the dynamic block, which its D4 already allows.
- `add-shared-scheduler`: the `OwnerNotificationChannel` port is implemented as published, with no change to the port. Its inventory gains the rows of the edit above.
- `add-mcp-tool-servers`: the `openclaw-apps` entry uses its generic mechanism as written (one entry, `trust: external` defaults, tool search, overrides as reviews, the shared egress proxy), and both changes read `ASCEND_MODULES`.

## Risks / Trade-offs

- [An OpenClaw release moves or renames the takeover seam or stops calling it for one channel] → the pin means nothing changes until the owner updates, the takeover tests fail on that channel, and the agent run observer turns readiness red if it slips through.
- [OpenClaw's own agent runs anyway on some path] → no provider is configured, so it cannot reach a model, the observer makes it visible, and a test covers each channel.
- [OpenClaw writes message text into its own state] → measured in task 1.5, pruned to the shortest value, purged on unlink and erasure, and listed in `docs/CHANNELS.md`.
- [A large dependency (389 MB) with a wide attack surface runs next to the agent] → its own containers, each with no secrets but those of its role and plugin list, no model keys (refused at startup), non-root, read-only root, no public port, and only the agent's host prefix reachable from the `channels` container with a scope that grants nothing else.
- [An app plugin is malicious or careless] → the owner installs it by exact version and reads it first, it runs in its own container without the channel tokens, it reaches the internet only through the egress proxy that refuses internal addresses, every one of its tools asks first until the owner reviews it, a changed tool fails the update test, and the agent never sends it the service token or the tenant.
- [The gateway token of an `apps` container is a full operator credential] → it is its own value, the gateway listens on loopback inside the container, and only the bridge in the same container uses it.
- [A chat platform token is put into two containers by mistake] → `OpenClawHostComposeTest` refuses the layout, the event stream of each container carries only its own platforms, and the unique inbound key runs a twice delivered message once.
- [Docker's DNS spreads load per connection, not per call] → enough for tool calls that take seconds, and more replicas or a plugin group are the next step, measured in task 7.3.
- [A tool result of an app plugin carries injected instructions] → tool results are data to the model, and every unreviewed tool asks first with its exact arguments.
- [A stranger floods the bot] → no model call for strangers, one throttled reply, a pending limit, and OpenClaw's own per-channel limits.
- [Prompt injection from other bots] → peers are registered by an `ADMIN`, run with no tools by default, cannot write memory or user facts, carry the request provenance source `peer_bot_turn`, so the request is `untrusted` for self-improvement and for the soul tools, and are rate limited with a loop guard.
- [WhatsApp through Baileys is not an official API] → only with a spare number, written down once with `OPENCLAW_HOST_WHATSAPP_SPARE_NUMBER=true`, and `docs/CHANNELS.md` states the account risk.
- [Approval button callbacks end after 24 hours] → equal to the default approval timeout, a banner warning for longer timeouts, and the app and REST stay available.
- [Keycloak is down] → linked users get the "cannot be used now" reply, nothing runs with a guessed identity.
- [Two languages in the repository] → the host is kept small, holds no business rules, and every rule (identity, conversations, limits, approvals) lives in the agent.

## Migration Plan

1. Land as build group 4, position 10 of the owner build order of 2026-10-04, after the changes it needs (proposal). No step waits for a company change. The required edits are all made in their target changes (checked on 2026-10-03). Group 1 tasks (proofs against the pinned OpenClaw) may start earlier, because they touch only the new module.
2. Flyway applies the new migration. There is no data to move.
3. With `channels` and `openclaw-apps` not in `COMPOSE_PROFILES`, nothing changes for any client.
4. Channels: the owner creates the Discord application and bot, sets the token, adds `channels` to `COMPOSE_PROFILES`, runs `docker compose up -d`, sends a direct message to the bot, and redeems the code in the app or with the documented `curl` command.
5. Apps: the owner installs an app plugin by the steps of D20, adds `openclaw-apps` to `COMPOSE_PROFILES`, and runs `docker compose up -d`. More load means a higher `OPENCLAW_HOST_APPS_REPLICAS`, and a plugin that needs its own secrets or limits gets a plugin group service (D18).
6. Rollback: remove the module from `COMPOSE_PROFILES` and run `docker compose up -d`, which recreates the agent. The tables stay and are ignored. Flyway runs forward only, so removing them is a new migration, written only if the owner asks for it.

## Decision record numbering

The monorepo decision record "OpenClaw as a channel and app plugin library" (D1, D2, D18, D19 and D21) takes the next free number in `docs/architecture/decisions/` at implementation time.

## Owner decisions of 2026-10-02

These were open questions and are now decided. The design and tasks follow them.

1. Node.js 24 for the host, and Node 26 later through the update procedure (D4).
2. A TypeScript and Node.js coding standards skill is imported from the owner's agent-standards repository before implementation (task 0.2). Until it is imported, no host code is written.
3. Approval buttons on Telegram and Slack come later, through the same outbox kind and an interactive handler per channel. Until then those platforms get a text notice that points to the app.
4. The assistant never starts a conversation with another bot on its own (D13).
5. Discord, Telegram and Slack first. WhatsApp only with a spare number (D15). Every other platform is enabled by the owner when he needs it, with its takeover test, its live checklist entry and, for webhook platforms, its gateway route.
6. Apps come through OpenClaw plugins, with no app list now (D18 to D21).
7. Owner answer 46.3: this change is renamed from `add-openclaw-channel-host` to `add-openclaw-plugin-host`, and its service from `ascend-channel-host` and `ascend-openclaw-apps` to `ascend-openclaw-host`. The module names stay `channels` and `openclaw-apps`, and the agent's API prefix stays `/api/v1/channel-host/` (D6).
8. Owner answer 48: one service `ascend-openclaw-host`, one program and one image that runs every OpenClaw plugin as several containers, each told its role and plugin list. A chat platform connection runs in exactly one container, app plugins may be spread over as many containers as needed, and a container holding chat platform tokens never runs third party app plugins (D18, D19).
9. Owner answer 46.2: integration passwords of `add-self-built-integrations` go into the separate file `integration-secrets.env`, which only its sandbox runner reads. The fixed line on a credential prompt says so (D12).

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. Its channel tables start empty, and it needs none of today's data.

## Owner decisions of 2026-10-07

Answer 75.1 (review of the group 3, 4 and 5 changes of 2026-10-07, fix of all 75 items approved): item 67 is fixed here. The deferred identity link D11 and D12 is named as a decision of `add-auth-and-identity`, where it exists, not of `add-keycloak-login`. Follow-up of item 5: the network text of D19 now says this change adds the profile `openclaw-apps` to `mcp-egress-proxy` (task 8.4), because `add-mcp-tool-servers` names no module profile on it.

## Owner decisions of 2026-10-08

Answer 76.5: `mcp-egress-proxy` is always on from `add-mcp-tool-servers` onward, because our own tool servers are always on, so it carries no profile. This change still adds its own use of it: the proxy joins each `apps` network and the `apps` containers set the proxy variables (D19, task 8.4). It no longer adds the profile `openclaw-apps` to the proxy, which replaces the follow-up of item 5 of 2026-10-07 recorded above.

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/channels/` (task 9.4).

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (tasks 9.5, 9.6 and 9.7). Superseded by answer 91.1 below.

Answer 89.6: `channel_outbox` is the one retry layer of owner notifications, `owner_notification_delivery` of `add-shared-scheduler` only records the end state that the outbox reports, the Discord channel writes its outbox row inside the notification's transaction, and every button goes through `POST /api/v1/channel-host/actions` with an action type and the one host namespace `ascend` (D6, D12, the required edits to `add-action-approvals` and `add-self-improvement`, the `channel-approvals` and `channel-message-relay` specs, tasks 1.6, 5.1, 5.5, 5.6 and 5.8). Because the notification owner chose `channel_outbox`, this change keeps it with its attempts, its redelivery and its `dead` state. The request `notification-action-unknown-event.yml` that `add-self-improvement` once added to spec 9.6 is gone with its endpoint (note under task section 9).

Answer 87 (rule R1, several agent instances): the event stream and the action endpoint keep no in-process state, so they work with several agent instances. The stream reads only Postgres rows, and its wake-up is a `PostgresNotificationHandler` on the channel `channel_outbox_inserted` of the one `PostgresNotificationListener` of `add-keycloak-login` D20, whose `onReconnect()` makes every stream re-read its rows, with the 5 second poll as fallback (D12, task 5.1). Checked and kept: duplicates through the unique key of `channel_inbound_message`, pairing, redeem and binding through conditional Postgres updates, the redeem failure count and the loop guard in Redis, the daily `channel-host-cleanup` on db-scheduler, and the identity cache of D9, bounded by the realm access token lifetime and so never staler than a token, with the link itself read from Postgres on every message.

Answer 88 (rule R2): the OpenClaw `apps` role with its MCP bridge (finding A7) and the pairing and identity linking (finding A8) stay as written.

Answer 89.1: `StreamingChatExecutor` of `add-chat-streaming-and-conversations` is the one chat executor, and this change adds its peer bot mark step to it once (D13, the applied lists, tasks 6.5 and 6.7).

Answer 91.1: in the deterministic phase AscendMemory is faked in the one Mockoon container `e2e-scripted-model` under the route prefix `/ascend-memory/`, the agent's `app.memory.semantic.base-url` points there in the deterministic overlay, and only the agent is recreated. The deterministic specs of tasks 9.5, 9.6 and 9.7 therefore wipe no memory and need no dummy key. The human-gated spec runs against the real AscendMemory.

Answer 91.2: the fake MCP server that spec 9.6 uses is the one fake MCP server class of the agent's test sources, packaged as `ascend-e2e-fake-mcp:local` by `close-agent-test-gaps` task 4.2, so this change writes no fake MCP server program (task 9.4).

Answer 91.3: checked every spec of this change. The three deterministic specs stay, one per capability (relay and linking, approvals and run status, app tools), because each proves the live wiring of the host prefix with the client credentials token, the outbox stream and the MCP bridge, which no lower test reaches. The human-gated spec stays, because it runs with a real model, and the live checklist of task 9.11 already covers only the items that spec does not.

Answer 93: not applied, because each would remove a behaviour: one reply mode per platform instead of `final` and `blocks` (D11), and dropping `OPENCLAW_HOST_WHATSAPP_SPARE_NUMBER`, the written guard against switching WhatsApp on with the owner's own number (D15). The tenant header unification does not touch this change. Answer 86.1: no Testcontainers test of this change needs an HTTP fake. Answer 85.1: the channel tokens and the host client secret live only in the repository `.env`, and the Bruno step reads the client secret from a secret variable of the Bruno environment, never from a shell export (task 9.4).

Answer 98 (owner rule 98, every value with a default is a setting): made external.

On the `ascend-agent` service, each as `${ENV:default}` in `application.yaml`, the same default in `ChannelProperties` (or in the scheduler or MCP entry properties it belongs to) and `- ENV=${ENV:-default}` in `compose.yaml` (tasks 3.1, 5.10 and 8.5): `app.channels.accounts.<platform>.default.tenant` for the shipped `default` accounts of `discord`, `telegram` and `slack` (`APP_CHANNELS_ACCOUNTS_DISCORD_DEFAULT_TENANT`, `APP_CHANNELS_ACCOUNTS_TELEGRAM_DEFAULT_TENANT` and `APP_CHANNELS_ACCOUNTS_SLACK_DEFAULT_TENANT`, each `default`), `app.channels.pairing.ttl` (`APP_CHANNELS_PAIRING_TTL`, `1h`), `app.channels.pairing.reply-interval` (`APP_CHANNELS_PAIRING_REPLYINTERVAL`, `10m`), `app.channels.pairing.max-pending` (`APP_CHANNELS_PAIRING_MAXPENDING`, `3`), `app.channels.pairing.max-redeem-failures` (`APP_CHANNELS_PAIRING_MAXREDEEMFAILURES`, `5`), `app.channels.pairing.redeem-failure-window` (`APP_CHANNELS_PAIRING_REDEEMFAILUREWINDOW`, `15m`), `app.channels.inbound.retention` (`APP_CHANNELS_INBOUND_RETENTION`, `24h`), `app.channels.audio.backend` (`APP_CHANNELS_AUDIO_BACKEND`, `local`), `app.channels.audio.max-bytes` (`APP_CHANNELS_AUDIO_MAXBYTES`, `25MB`), `app.channels.outbox.poll-interval` (`APP_CHANNELS_OUTBOX_POLLINTERVAL`, `5s`), `app.channels.outbox.redeliver-after` (`APP_CHANNELS_OUTBOX_REDELIVERAFTER`, `2m`), `app.channels.outbox.max-attempts` (`APP_CHANNELS_OUTBOX_MAXATTEMPTS`, `10`), `app.channels.outbox.retention` (`APP_CHANNELS_OUTBOX_RETENTION`, `7d`), `app.channels.peer-bots.allowed-tools` (`APP_CHANNELS_PEERBOTS_ALLOWEDTOOLS`, empty), `app.channels.peer-bots.max-turns-without-human` (`APP_CHANNELS_PEERBOTS_MAXTURNSWITHOUTHUMAN`, `6`), `app.channels.peer-bots.max-replies-per-minute` (`APP_CHANNELS_PEERBOTS_MAXREPLIESPERMINUTE`, `4`), `app.channels.peer-bots.loop-guard-expiry` (`APP_CHANNELS_PEERBOTS_LOOPGUARDEXPIRY`, `1h`), `app.channels.platform-hints.<platform>` for `discord`, `telegram` and `slack` (`APP_CHANNELS_PLATFORMHINTS_DISCORD`, `APP_CHANNELS_PLATFORMHINTS_TELEGRAM` and `APP_CHANNELS_PLATFORMHINTS_SLACK`, texts not decided beyond the Telegram example of D10), the cleanup task's `app.scheduler.system-tasks.channel-host-cleanup.cron` (`APP_SCHEDULER_SYSTEMTASKS_CHANNELHOSTCLEANUP_CRON`, `0 4 * * *`) and `.time-zone` (`APP_SCHEDULER_SYSTEMTASKS_CHANNELHOSTCLEANUP_TIMEZONE`, `Europe/Warsaw`), and three values of the `openclaw-apps` MCP entry of D19: `url` (`APP_MCP_SERVERS_OPENCLAWAPPS_URL`, `http://ascend-openclaw-host-apps:18790`), `max-result-chars` (`APP_MCP_SERVERS_OPENCLAWAPPS_MAXRESULTCHARS`, `20000`) and `request-timeout` (`APP_MCP_SERVERS_OPENCLAWAPPS_REQUESTTIMEOUT`, `75s`). `CHANNEL_PAIRING_PEPPER` and `OPENCLAW_APPS_MCP_TOKEN` are secrets with no default.

On the `ascend-openclaw-host` containers, each read by the host's settings module with the same default and written `${VAR:-default}` on the compose services, through the anchor `x-openclaw-host` or on the one service it belongs to (tasks 2.8, 7.1 and 8.4): `OPENCLAW_HOST_CHANNELS` (empty), `OPENCLAW_HOST_APP_PLUGINS` (empty), `OPENCLAW_HOST_GROUPS_DISCORD`, `OPENCLAW_HOST_GROUPS_TELEGRAM` and `OPENCLAW_HOST_GROUPS_SLACK` (each empty), `OPENCLAW_HOST_REPLY_MODE_DISCORD`, `OPENCLAW_HOST_REPLY_MODE_TELEGRAM` and `OPENCLAW_HOST_REPLY_MODE_SLACK` (each `final`), `OPENCLAW_HOST_WHATSAPP_SPARE_NUMBER` (`false`), `OPENCLAW_HOST_AGENT_TIMEOUT` (`300` seconds), `OPENCLAW_HOST_BLOCK_REPLY_INTERVAL_SECONDS` (`2`), `OPENCLAW_HOST_DELIVERED_IDS_MAX` (`10000`), `OPENCLAW_HOST_AGENT_URL` (`http://ascend-agent:9917`), `KEYCLOAK_ISSUER_URI` (`http://keycloak:8080/realms/ascend-ai`, the one name and default of owner answer 98.3), `OPENCLAW_HOST_CLIENT_ID` (`ascend-openclaw-host`), `OTEL_EXPORTER_OTLP_ENDPOINT` (`http://otel-collector:4317`, the value the other services have in `compose.yaml`, read on 2026-10-08), `OPENCLAW_HOST_APP_TOOL_TIMEOUT` (`60` seconds), `OPENCLAW_HOST_APPS_MCP_PORT` (`18790`), `OPENCLAW_HOST_APPS_REPLICAS` (`1`), `OPENCLAW_HOST_CHANNELS_MEMORY_LIMIT` (1 GiB to start, then the peak of task 7.3 with headroom), `OPENCLAW_HOST_APPS_MEMORY_LIMIT` (the peak of task 7.3 with headroom), `OPENCLAW_HOST_SESSION_PRUNE_AFTER` and `OPENCLAW_HOST_MEDIA_RETENTION` (the shortest values the pinned version accepts, read in task 1.5), `OPENCLAW_HOST_EVENTS_RECONNECT_INITIAL_SECONDS` and `OPENCLAW_HOST_EVENTS_RECONNECT_MAX_SECONDS` (the backoff of the event stream reconnect, defaults not decided) and `OPENCLAW_HOST_HEALTHCHECK_INTERVAL` (the compose health check interval of the anchor, default not decided). `EXPOSE_BIND` keeps its existing default `127.0.0.1`. `OPENCLAW_HOST_ROLE` has no default on purpose: each compose service sets its role, and a missing role is refused (D18). The channel tokens, `OPENCLAW_GATEWAY_TOKEN`, `OPENCLAW_GATEWAY_TOKEN_APPS`, `OPENCLAW_HOST_CLIENT_SECRET`, `OPENCLAW_APPS_MCP_TOKEN` and the secrets of app plugins are secrets with no default, `.env` only, and only secrets get `.env.example` lines (D15, task 7.2).

The rows of the agent settings go into `apps/ascend-agent/docs/CONFIGURATION.md`, each description ending with "Added by `add-openclaw-plugin-host`.", and the rows of the host settings into `docs/CONFIGURATION.md` with the services `ascend-openclaw-host-channels` and `ascend-openclaw-host-apps` (task 9.14).

Kept as constants, because they are not operational: the OpenClaw gateway port 18789 inside the container (OpenClaw's own default, which the gateway routes of task 7.4, the loopback publication of task 7.9 and the port scan of task 9.13 name), the pairing code length 8 and its alphabet (a format copied from OpenClaw), the button custom id `ascend:<outbox id>:<button index>` and Discord's 100 character limit, `channels.discord.agentComponents.ttlMs` 86400000 (the platform maximum, chosen to equal the default approval timeout, so the 24 hour banner threshold of task 5.7 follows it), the access settings of D3 (`dmPolicy`, `allowFrom`, `groupPolicy`, `allowBots` and the `commands` switches), which the validator enforces, OpenClaw's `botLoopProtection` and Hermes's own guard (outer limits of other programs, not set by this change), the file mode `0600`, the one minute bucket of the peer rate (the unit in the property's name), the MCP path `/mcp`, the entry's `trust`, `tool-prefix`, `discovery` and `default-mode` (security posture and names), the SSE event names, refusal reasons, outbox kinds and states, action types, the namespace `ascend`, the table, metric and audit event names, and the Node and OpenClaw version pins (dependencies raised only through the update procedure of D5). No test or measurement of this change uses LM Studio: the deterministic specs use the scripted model, and the human-gated spec of task 9.8 uses a real chat model that the plan does not name. Changed: D6, D8, D11, D12, D13, D15, D19, D22, the `channel-identity-linking` and `channel-message-relay` specs, the proposal's `.env.example` line, and tasks 2.8 (new), 3.1, 5.10, 7.1, 7.2, 8.4, 8.5, 9.4 and 9.14 (new).

Answer 98.1: the test settings reach the running agent by copy in the deterministic phase: `close-agent-test-gaps` D7 copies the overlay into `/app/config/application.yaml` of the running agent and restarts it, and at the end recreates it and checks that the file is gone. There is no `e2e` profile and no test line in `compose.yaml`. The deterministic specs of tasks 9.5, 9.6 and 9.7 and the overlay entries of task 9.4 use that step as it is, and task 9.4 now says that the agent is restarted with the copied overlay instead of recreated.

Answer 98.6: the replicas of an `apps` service (D18) publish no port, so they need no host port range, and callers inside Docker reach every replica by the compose service name (D19). Running several copies of the platform across machines for a company is not planned here: company plans it later in `plan-scaled-deployment` (build group 5), this change does not wait for it.

## Owner decisions of 2026-10-09

Answer 100.6: every published host port is a setting `${<SERVICE>_HOST_PORT:-<today's port>}:<container port>`. `ascend-openclaw-host-channels` publishes `"${EXPOSE_BIND:-127.0.0.1}:${OPENCLAW_CHANNELS_HOST_PORT:-18789}:18789"` (task 7.9), and the container port 18789 stays fixed. The copied `production-deployment` requirements name the host port settings of `harden-cloud-deployment` (the loopback form and the gateway host ports `GATEWAY_HTTP_HOST_PORT` and `GATEWAY_HTTPS_HOST_PORT`). The rows task that the Answer 98 record names, task 9.14, did not exist in tasks.md and is added now, with `OPENCLAW_CHANNELS_HOST_PORT` among its rows.

Answer 103.5: the host settings that the Answer 98 record left without a default now have one, under the names that record gave them: `OPENCLAW_HOST_EVENTS_RECONNECT_INITIAL_SECONDS` `1` and `OPENCLAW_HOST_EVENTS_RECONNECT_MAX_SECONDS` `30` (the event stream reconnect starts after 1 second and doubles each time up to 30 seconds, task 5.2), and `OPENCLAW_HOST_HEALTHCHECK_INTERVAL` `30s` (the compose health check interval of the anchor `x-openclaw-host`, task 7.1). The three platform hint texts of `app.channels.platform-hints` are drafted in D10 for the owner to review later and are marked as drafts there (task 3.1). Each value is a setting with the same default in code and in its compose line `${VAR:-default}`, with its row in the configuration reference (task 9.14). The host settings task 2.8, which the Answer 98 record names as new, was missing from tasks.md and is added now, the same as task 9.14 was added for answer 100.6.

## Open Questions

None. The rename question is decided by owner answer 46.3 above.
