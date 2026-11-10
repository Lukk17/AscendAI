## Purpose

Defines the agent side of the channels: the API that turns one chat platform message into one chat turn of an Ascend conversation and returns the answer, and the durable outbound event stream through which the agent sends background run status messages, approval prompts and notices to chat platforms.

## ADDED Requirements

### Requirement: A channel message becomes one chat turn

The agent SHALL expose `POST /api/v1/channel-host/messages` for the `channels` containers of the host. The request SHALL carry the platform, the bot account id, the chat id, the chat type (`direct` or `group`), the thread id when there is one, the sender's platform account id and display name, whether the sender is a bot, whether the message mentions the bot, the platform message id, the text, and optional attachments. The agent SHALL resolve the tenant from the bot account, the caller from the sender's link (`channel-identity-linking`) and the conversation from the binding below, then run the message through the same chat pipeline as `POST /api/v1/ai/prompt/stream`, with the same retrieval, tools, approvals, personality file, user facts, history, compaction, memory extraction and usage events, and with the limits that pipeline applies. The dynamic system block of the turn SHALL carry one short line naming the platform and its formatting rules (for example, no tables on platforms that do not render them). A message whose platform message id was already handled for the same platform, bot account and chat SHALL NOT run a second turn.

#### Scenario: Telegram message is answered through the normal pipeline

- **WHEN** the owner's linked Telegram account asks "what did I upload yesterday?"
- **THEN** one chat turn runs as the owner with retrieval over the owner's documents
- **AND** the turn's history row is in the conversation bound to that Telegram chat

#### Scenario: Retried delivery

- **WHEN** the host sends the same platform message id twice after a restart
- **THEN** only one chat turn runs and the second call answers with the outcome `duplicate`

### Requirement: Each platform chat and thread maps to one conversation per user

The agent SHALL bind each combination of tenant, platform, bot account, chat id, thread id and user to exactly one conversation of `add-chat-streaming-and-conversations`, created on the first message with a title naming the platform and chat. A new thread SHALL get a new conversation. Two linked users in one group chat SHALL each have their own conversation there. The text `/new` alone SHALL bind the chat and thread to a new conversation for that user and answer with a short confirmation, without a model call. Deleting a conversation through the conversation API SHALL remove its binding, so the next message starts a new conversation. Conversations started from a channel SHALL be listed and readable through `/api/v1/conversations` like any other.

#### Scenario: Thread gets its own conversation

- **WHEN** the owner writes in a Discord DM and then in a thread of a guild channel
- **THEN** the two messages are in two different conversations

#### Scenario: Deleting a conversation removes its chat platform binding

- **WHEN** the owner deletes a conversation that is bound to a chat platform thread
- **THEN** the binding is gone, so the next message from that thread starts a new conversation

#### Scenario: Start over

- **WHEN** the owner sends `/new` in a Telegram chat and then a question
- **THEN** the question is the first turn of a new conversation and the earlier conversation is unchanged

### Requirement: Attachments and voice notes are accepted within the chat limits

The channel message API SHALL accept images and documents with the same types and size limits as the chat endpoint, and voice notes and audio files up to `app.channels.audio.max-bytes` (default 25 MiB). Images and documents SHALL reach the turn exactly as they do through the chat endpoint. A voice note SHALL be transcribed through ascend-audio-scribe, and the transcript SHALL be the prompt text, or SHALL be added after the typed text when there is both. When the `audio` module is not active, a voice note SHALL NOT start a turn and SHALL get a short reply that voice notes are not available. An attachment of another type or over its limit SHALL NOT start a turn and SHALL get a short reply naming what is accepted. Attachment bytes SHALL NOT be stored by the relay beyond what the chat pipeline already stores.

#### Scenario: Photo with a question

- **WHEN** the owner sends a photo with the caption "what plant is this?" on WhatsApp
- **THEN** the turn receives the image and the caption as the prompt

#### Scenario: Voice note

- **WHEN** the owner sends a 20 second voice note on Telegram
- **THEN** the voice note is transcribed and the transcript is answered as the prompt

#### Scenario: Unsupported file

- **WHEN** the owner sends a 300 MB video
- **THEN** no turn runs and the reply says which files are accepted

### Requirement: The answer is returned as a stream the host delivers in platform sized parts

The channel message API SHALL answer as `text/event-stream` with the events `delta`, `done`, `refused` and `error`. `done` SHALL carry the full reply text and the conversation id. `refused` SHALL carry a reason (`unlinked`, `group_unlinked`, `pending_limit`, `identity_unavailable`, `peer_ignored`, `loop_guard`, `duplicate`, `unsupported_attachment`, and `rate_limited` and `quota_exceeded`, which occur only once `add-usage-metering-and-quotas` registers its limits) and the reply text to send, which is empty when the sender must get no answer. `error` SHALL carry the RFC 7807 problem detail. The host SHALL send the reply in the platform's message size limit, split at paragraph, line or sentence ends and never inside a code block, and SHALL send it as a reply in the same chat and thread. By default the host SHALL send only the final reply. When a channel's reply mode is `blocks`, the host SHALL send each completed paragraph block as it arrives. While the agent works, the host SHALL show the platform's typing indicator where the platform has one, and SHALL stop it when the reply is sent or the turn fails. Source references of a retrieval answer SHALL be sent as titles, never as presigned links.

#### Scenario: Long answer on Discord

- **WHEN** the agent answers with 5000 characters including a code block on Discord
- **THEN** the host sends three or more messages of at most 2000 characters each, and no code block is split

#### Scenario: Typing while the agent works

- **WHEN** a Discord turn takes 20 seconds
- **THEN** the typing indicator shows in that chat until the reply is sent

### Requirement: Outbound events reach the platform at least once and in order per chat

The agent SHALL write every message it sends without an inbound message (run status, approval prompts and their updates, owner notifications, link confirmations, loop guard notices) to a durable outbox in the same transaction as the change that causes it, or after commit for events that come from another change's after-commit event. The agent SHALL expose `GET /api/v1/channel-host/events?platforms=<list>`, a `text/event-stream` that sends every undelivered outbox entry of the listed platforms in order with its sequence number as the SSE id, so each `channels` container receives only the entries of the platforms it runs, resumes after `Last-Event-ID`, and sends new entries as they are written. The host SHALL deliver each entry and acknowledge it with `POST /api/v1/channel-host/events/{id}/ack`, carrying `delivered` and the platform message id, or `failed` and a reason. An entry not acknowledged within `app.channels.outbox.redeliver-after` (default 2 minutes) SHALL be sent again, at most `app.channels.outbox.max-attempts` times (default 10), and then marked `dead` with a WARN line. The host SHALL skip an entry id it already delivered. The fallback check and the redelivery SHALL run inside the stream on the agent instance that serves it, as local work, and marking an entry sent SHALL be a conditional update, so no two instances send the same entry.

#### Scenario: Host restarts while an event waits

- **WHEN** a run finishes while the host is down
- **THEN** after the host reconnects it receives the run status entry and posts it once

#### Scenario: Platform keeps refusing

- **WHEN** Discord refuses an entry ten times
- **THEN** the entry is `dead`, a WARN line names its id and kind, and later entries keep flowing

### Requirement: Old relay rows are removed by one daily system task

The agent SHALL register the system task `channel-host-cleanup` of `add-shared-scheduler` while the `channels` module is active, scheduled daily by `app.scheduler.system-tasks.channel-host-cleanup.cron` (default `0 4 * * *`) in `.time-zone` (default `Europe/Warsaw`), so that each firing runs on exactly one agent instance. Each firing SHALL delete inbound message keys older than `app.channels.inbound.retention` (default 24 hours), pairing codes that expired and were never redeemed, and outbox entries that are delivered or dead and older than `app.channels.outbox.retention` (default 7 days). A second run of the same firing SHALL delete nothing more. No other periodic job SHALL delete these rows.

#### Scenario: Cleanup runs once with two agent instances

- **WHEN** two agent instances run and the cleanup firing is due, with one expired pairing code and one inbound key 25 hours old
- **THEN** exactly one instance runs the firing, and afterwards neither row exists

### Requirement: Background runs started from a channel report their status in the same chat

When a background run of `add-agent-subagents` belongs to a conversation bound to a chat, the agent SHALL queue one message when the run starts and one message when it reaches a final state, addressed to that chat and thread. One rule SHALL decide which runs are reported: every run kind (`subagent`, `coding`, `scheduled`, `self_review`, `integration` and any kind added later) except `approval`, whose state is shown through the approval prompts of `channel-approvals` instead. The start message SHALL name the run's kind and description. The final message SHALL name the state, the cost and the first 1500 characters of the result or the failure reason, and SHALL point to the run id. Last step changes SHALL NOT send messages. A run of a conversation that is not bound to a chat SHALL send nothing.

#### Scenario: Research run finishes after the chat ended

- **WHEN** the owner asks on Telegram for a background comparison and the run finishes ten minutes later
- **THEN** the Telegram chat receives a start message and then a final message with the start of the result

#### Scenario: Coding run is reported

- **WHEN** a run of kind `coding` started from a bound Discord conversation ends `succeeded`
- **THEN** the Discord chat receives a start message and a final message for it

#### Scenario: Approval run is not reported as a run

- **WHEN** a run of kind `approval` starts and ends in a bound conversation
- **THEN** no run status message is queued for it

### Requirement: Owner notifications reach the owner's Discord direct message

When the `channels` module is active, the agent SHALL offer a channel named `discord` to the owner notification store of `add-shared-scheduler`, through its `OwnerNotificationChannel` port. The channel SHALL report that it can reach a user only when the user has an active Discord link in the notification's tenant. Delivering a notification SHALL write one outbox entry for that linked account's direct message, with the title, the body cut to the platform's message limit with a visible note that it was cut, and the run id when the notification has one, and SHALL report the notification delivered once the entry is committed.

#### Scenario: Notification delivered

- **WHEN** a notification for the owner is created and the owner has a linked Discord account
- **THEN** one outbox entry for his direct message is written and the notification is recorded as delivered on the `discord` channel

#### Scenario: Owner without a Discord link

- **WHEN** a notification is created for a user with no Discord link
- **THEN** the `discord` channel reports that it cannot reach the user and no outbox entry is written

### Requirement: Channel API errors are problem details

Every error of the channel endpoints SHALL be the RFC 7807 problem detail of `upgrade-spring-boot-4`, with these new codes: `channel_forbidden` (403), `channel_account_unknown` (404, a bot account id that is not configured for any tenant), `channel_pairing_not_found` (404), `channel_pairing_rate_limited` (429), `channel_link_exists` (409), `channel_link_not_found` (404), `channel_peer_platform_unsupported` (400), `channel_peer_not_found` (404), `channel_event_not_found` (404, also for an unknown outbox id of an approval button) and `channel_attachment_rejected` (400). A button press by an unlinked account or by a user without `ADMIN` SHALL answer 403 with `channel_forbidden`, and the host SHALL tell the presser that he may not decide. A refusal that the host must turn into a platform reply SHALL be a `refused` event, not an HTTP error.

#### Scenario: Unknown bot account

- **WHEN** the host sends a message for a bot account id that no tenant configures
- **THEN** the response is 404 with `code` `channel_account_unknown` and no turn runs

### Requirement: The relay is measured and logged

The agent SHALL count channel messages by `platform` and `outcome` (`answered`, each `refused` reason, `error`), time the channel turn by `platform`, count outbox entries by `kind` and `state`, and gauge undelivered outbox entries. It SHALL log one INFO line per channel turn with the platform, the link id, the conversation id, the outcome and the duration, and never the text. The startup banner SHALL show whether the channel module is on, the configured bot accounts by platform and tenant, and the outbox settings.

#### Scenario: Outbox backlog is visible

- **WHEN** the host is down and five events are queued
- **THEN** the undelivered outbox gauge reads five

### Requirement: The relay is proven end to end with a fake channel and with real platforms

The repository SHALL hold deterministic end-to-end specs in `apps/ascend-agent/e2e/testing/`, with Bruno requests in `docs/api/request/AscendAI/ascend-agent/testing/channels/` and `docs/api/request/AscendAI/ascend-agent/testing/openclaw-apps/`, in which Bruno acts as the `channels` host with the host's client token and every chat turn uses the scripted model of the shared harness of `close-agent-test-gaps`, so that no AI model runs. The scripted model and the fake MCP server SHALL start only for these deterministic specs, never for the human-gated spec, which runs against the agent with the shipped profile. They SHALL prove the channel API rules, pairing and linking, the outbox with acknowledgement and resume, conversation binding, duplicates, attachments, peer bots with the loop guard, approval decisions through the one action endpoint of the host prefix, background run status entries and the app tool bridge. A human-gated spec SHALL prove the real takeover on Discord, Telegram and Slack with dedicated test bots and test accounts named as owner facts and a real model. Every spec SHALL pass only on SSE events, HTTP answers, persisted rows, Prometheus samples and call logs, never on a log line.

#### Scenario: Fake channel needs no model

- **WHEN** the deterministic relay spec runs with the e2e overlay on and the `channels` container stopped
- **THEN** every step passes without a call to any hosted or local chat model

#### Scenario: Outbox resume proven

- **WHEN** the spec reads the link confirmation from `GET /api/v1/channel-host/events?platforms=discord`, acknowledges it as delivered, and opens the stream again with its `Last-Event-ID`
- **THEN** the second stream does not send that entry again
- **AND** a stream for `telegram` never sent it
