## Purpose

Runs every OpenClaw plugin, chat platform connections (channels) and app plugins, in one service of its own, `ascend-openclaw-host`, as a library only, as several containers that each have a role and a plugin list, so the assistant is reachable on the messaging platforms OpenClaw supports while Ascend's agent, never OpenClaw's agent, answers every message.

## ADDED Requirements

### Requirement: One service runs every OpenClaw plugin, with a role and a plugin list per container

`ascend-openclaw-host` SHALL be one program built into one image that runs every OpenClaw plugin, and SHALL run as one or more containers. Each container SHALL be told its role, `channels` or `apps`, through `OPENCLAW_HOST_ROLE`, and its plugin list, `OPENCLAW_HOST_CHANNELS` for the role `channels` and `OPENCLAW_HOST_APP_PLUGINS` for the role `apps`, and SHALL load only the plugins of its list. A container SHALL refuse to start, with one ERROR line naming the setting, when its role is missing or unknown, when a `channels` container is given an app plugin list, an app plugin configuration or a bridge token, or when an `apps` container is given a channel list, a channel token, the host's agent client secret or the pairing pepper. A chat platform connection SHALL run in exactly one container, and the repository's compose layout test SHALL fail when one channel id is in the lists of two containers, when a `channels` service has more than one replica, or when one service sets both lists. App plugins MAY be spread over any number of `apps` containers.

#### Scenario: Channels container given an app plugin

- **WHEN** a container starts with `OPENCLAW_HOST_ROLE=channels` and a non-empty `OPENCLAW_HOST_APP_PLUGINS`
- **THEN** it exits before the gateway starts and the log names `OPENCLAW_HOST_APP_PLUGINS`

#### Scenario: One channel in two containers

- **WHEN** the compose files give `discord` to two `channels` services
- **THEN** the compose layout test fails and names `discord` and both services

#### Scenario: Apps containers scaled

- **WHEN** `OPENCLAW_HOST_APPS_REPLICAS=3` and `openclaw-apps` is in `COMPOSE_PROFILES`
- **THEN** three `apps` containers run with the same plugin list, and the `channels` container still runs once

### Requirement: Every inbound message is handed to Ascend and OpenClaw's agent never runs

Every `channels` container of `ascend-openclaw-host` SHALL run the `openclaw` package as a gateway with the channel plugins of its list and one takeover plugin of this repository. The takeover plugin SHALL claim every inbound message that reaches dispatch, on every enabled channel, before OpenClaw's own agent dispatch, forward it to the agent's channel message API and deliver the agent's answer. No inbound message SHALL start an OpenClaw agent run, call a model provider, run an OpenClaw tool, load an OpenClaw skill, read or write OpenClaw memory, or build an OpenClaw prompt. OpenClaw's chat commands (slash commands and text commands such as `/new`, `/model` and `/status`) SHALL be switched off, so their text reaches the takeover plugin like any other message. When the takeover plugin cannot reach the agent, it SHALL still claim the message and send a fixed short reply that the assistant is not available, never fall back to OpenClaw's agent.

#### Scenario: Message on each enabled channel is taken over

- **WHEN** a linked account sends a message on each enabled channel
- **THEN** the agent's channel message API receives each one once
- **AND** the host records no OpenClaw agent run start and no model provider call for any of them

#### Scenario: Agent is down

- **WHEN** ascend-agent cannot be reached and a linked account writes on Discord
- **THEN** the sender receives the fixed "not available" reply
- **AND** no OpenClaw agent run starts

#### Scenario: OpenClaw command text is not run by OpenClaw

- **WHEN** a linked account sends `/model gpt-5` in a direct message
- **THEN** OpenClaw does not change any model setting and the text reaches the agent's channel message API

### Requirement: OpenClaw runs with no model provider

The OpenClaw configuration of every container SHALL be generated at startup from the template of its role checked into the repository, and SHALL configure no model provider, no provider key, no agent tools, no skills, no memory plugin, no heartbeat, no cron jobs and no hooks except the takeover plugin's. The host SHALL refuse to start, with one ERROR line naming the setting, when the generated configuration enables any of them or when an environment variable of a known model provider key is set in the container. OpenClaw's own pairing and allow lists SHALL NOT decide who is answered: direct messages SHALL be open to the takeover plugin, and the agent's link check SHALL decide. Group chats SHALL be reachable only in the groups, guilds and channels listed in the host configuration, and a group message SHALL reach the takeover plugin only when it mentions the bot.

#### Scenario: Provider key in the environment

- **WHEN** a container of either role starts with `OPENAI_API_KEY` set
- **THEN** the host exits before connecting any channel and the log names the variable, not its value

#### Scenario: Group not listed

- **WHEN** the bot is added to a Discord guild that is not in the host configuration and a linked user mentions it there
- **THEN** no message reaches the agent

### Requirement: The OpenClaw version is pinned and updated through one procedure

The `openclaw` package and every OpenClaw channel plugin package SHALL be pinned to an exact version in `package.json`, installed from the committed lock file with a clean install, and the base image SHALL be pinned by version and digest. The host SHALL log the OpenClaw version in its startup banner and expose it as a metric label. The repository SHALL document one update procedure: change the pinned versions, refresh the lock file, run the type check, the unit tests and the per-channel takeover tests, read OpenClaw's release notes for hook, dispatch, access control and channel changes, and accept the new version only when every test passes. A new OpenClaw version SHALL never be picked up by a build without a change to the repository.

#### Scenario: Build is repeatable

- **WHEN** the host image is built twice from the same commit
- **THEN** both images contain the same `openclaw` version and the same dependency tree

#### Scenario: Update that breaks the takeover is caught

- **WHEN** a new `openclaw` version stops calling the takeover hook on one channel
- **THEN** that channel's takeover test fails and the update is not accepted

### Requirement: Channels are switched on by configuration and their secrets come from the environment only

Each channel SHALL be switched on by naming it in the `OPENCLAW_HOST_CHANNELS` of exactly one `channels` container (comma separated, empty by default), and Discord, Telegram and Slack SHALL be supported first. WhatsApp SHALL start only when `OPENCLAW_HOST_WHATSAPP_SPARE_NUMBER` is `true`, which records that a spare phone number and not the owner's own is used. Every secret a channel needs (bot tokens, app tokens, signing secrets, webhook secrets) and the host's own agent credentials SHALL be read only from environment variables set in the root `.env`, and SHALL NOT be written into the configuration template, the generated configuration on disk, an image, a log line, a metric or an error reply. A channel named in `OPENCLAW_HOST_CHANNELS` whose required secret is empty SHALL NOT start, SHALL be reported as failed by readiness, and SHALL be named in one ERROR line. Other channels SHALL keep working.

#### Scenario: Missing Telegram token

- **WHEN** `OPENCLAW_HOST_CHANNELS=discord,telegram` and `TELEGRAM_BOT_TOKEN` is empty
- **THEN** Discord works, Telegram does not start, readiness lists Telegram as failed, and the log names `TELEGRAM_BOT_TOKEN`

#### Scenario: WhatsApp without the spare number setting

- **WHEN** `OPENCLAW_HOST_CHANNELS=whatsapp` and `OPENCLAW_HOST_WHATSAPP_SPARE_NUMBER` is not `true`
- **THEN** WhatsApp does not start and one ERROR line names the setting

#### Scenario: Generated configuration holds no secret

- **WHEN** the generated OpenClaw configuration file is read inside the running container
- **THEN** it contains no token value, only references to environment variables

### Requirement: The channels role is one deployment module, off by default

The `channels` containers of the host SHALL be the deployment module `channels` of `add-deployment-modules`: their compose services SHALL be under the compose profile `channels`, and the agent SHALL read the same list from `ASCEND_MODULES`, so one entry in `COMPOSE_PROFILES` starts them and turns on the agent's channel API. Every channel bean of the agent SHALL carry the module condition `channels`, and no other flag SHALL switch the channel API on or off. With the module off, the agent's channel endpoints SHALL not exist and SHALL answer 404, no outbound event SHALL be queued, the `discord` owner notification channel SHALL not be offered, and no channel tables SHALL be written. The default `channels` container SHALL publish no host port except, for local work, its own HTTP port on `127.0.0.1` through `EXPOSE_BIND`. The state directory of a `channels` container SHALL be a named volume mounted only by that container.

#### Scenario: Default stack

- **WHEN** the stack starts with `COMPOSE_PROFILES` empty
- **THEN** no `ascend-openclaw-host` container runs and `POST /api/v1/channel-host/messages` answers 404

#### Scenario: Module on

- **WHEN** `COMPOSE_PROFILES=channels` and the Discord token is set
- **THEN** the `channels` container connects to Discord and the agent's channel API accepts its calls

### Requirement: Platforms that need inbound webhooks are reached only through the gateway

A channel that receives platform events over HTTP (Telegram in webhook mode, Slack with request URLs, LINE, Google Chat, Microsoft Teams, Twilio SMS and the like) SHALL be reached from the internet only through the edge gateway, on a path reserved for that channel that the gateway forwards to the `channels` container that runs the channel. Every such route SHALL be verified by the platform's own check (secret token, signing secret or signature) before the message reaches the takeover plugin, and a request that fails the check SHALL be refused without reaching the agent. Channels that keep an outbound connection (Discord, Telegram in polling mode, Slack in Socket Mode, WhatsApp, Signal, Matrix) SHALL need no inbound route, and polling or Socket Mode SHALL be the default where a platform offers both.

#### Scenario: Forged Telegram webhook

- **WHEN** Telegram runs in webhook mode and a request arrives at the Telegram path without the configured secret token header
- **THEN** the request is refused and the agent receives nothing

#### Scenario: Discord needs no route

- **WHEN** only Discord is enabled
- **THEN** the gateway has no route to the host and Discord works

### Requirement: The host authenticates to the agent with its own service credentials

A `channels` container SHALL call the agent only with the host's own service credentials, never with a user's token, and SHALL send the platform identity of each sender as data for the agent to check. The agent SHALL accept the endpoints under `/api/v1/channel-host/` only from a caller holding the channel scope, in every Spring profile including `dev`, and SHALL refuse every other caller with 403 and `code` `channel_forbidden`. The edge gateway SHALL NOT forward any path under `/api/v1/channel-host/` from the internet. A `channels` container SHALL refuse to start when the credentials are missing, and no `apps` container SHALL hold them.

#### Scenario: User token on the channel API

- **WHEN** a signed-in user calls `POST /api/v1/channel-host/messages` with his own token
- **THEN** the response is 403 with `code` `channel_forbidden`

#### Scenario: Host endpoints are not public

- **WHEN** a client on the internet sends `POST https://<ASCEND_DOMAIN>/api/v1/channel-host/messages`
- **THEN** the gateway answers 404 and the agent receives nothing

### Requirement: The host reports health, readiness, metrics and logs

Every container SHALL answer liveness and readiness on its HTTP port: liveness while the process runs. A `channels` container SHALL be ready only while the agent is reachable and every channel of its list is connected, listing each channel's state. An `apps` container SHALL be ready only while its gateway answers and its bridge has listed the tools. It SHALL emit OpenTelemetry metrics and traces to the platform collector with service name `ascend-openclaw-host` and the role as a resource attribute, with metric names that are domain first, dotted and lower case: `openclaw.host.messages` (received, claimed and refused, by `platform` and `outcome`), `openclaw.host.agent.duration` (by `platform` and `outcome`), `openclaw.host.replies` (by `platform` and `outcome`), `openclaw.host.outbound.events` (by `kind` and `outcome`), the gauge `openclaw.host.channels.connected` (by `platform`), the counter `openclaw.host.openclaw.agent.runs`, and `openclaw.host.build.info` with the OpenClaw version. No metric SHALL carry an account id, chat id, user id or message text as a label. Logs SHALL be JSON lines with a correlation id that is also sent to the agent as `x-request-id`, and SHALL NOT contain message text, attachment content, tokens or pairing codes at INFO level. The startup banner SHALL list the role, the OpenClaw version, the plugins of the container's list and their state, the agent address for the role `channels`, and the webhook paths in use, and no secret.

#### Scenario: Readiness after a Discord disconnect

- **WHEN** the Discord connection drops and has not come back
- **THEN** readiness answers not ready with Discord marked disconnected, and liveness stays ok

#### Scenario: One message is traceable

- **WHEN** a message flows from Telegram through the host to the agent and back
- **THEN** the host log line and the agent log line of that message carry the same correlation id
- **AND** neither line contains the message text
