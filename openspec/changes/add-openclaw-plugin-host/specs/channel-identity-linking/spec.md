## Purpose

Makes sure the agent answers a chat platform account only after that account is linked to an Ascend user, through a pairing code the user redeems while signed in to Ascend, and refuses every stranger.

## ADDED Requirements

### Requirement: A platform account is answered only when it is linked

The agent SHALL keep one link per tenant, platform and platform account id, naming exactly one Ascend user. A channel message from a sender with no active link SHALL NOT start a chat turn, SHALL NOT call a model or a tool, and SHALL NOT write chat history. The link SHALL be looked up for every message, so a removed link stops the next message. A link SHALL be refused for a platform account id that belongs to a bot, unless the link is a peer bot link of the `channel-peer-bots` capability.

#### Scenario: Linked owner is answered

- **WHEN** the owner's linked Discord account sends a direct message to the bot
- **THEN** the agent runs a chat turn as the owner's user and the reply is sent to that direct message

#### Scenario: Removed link stops the next message

- **WHEN** the owner removes the link of his Telegram account and then writes to the bot from that account
- **THEN** no chat turn runs and the sender gets the pairing reply

### Requirement: A stranger in a direct message gets a pairing code and nothing else

When an unlinked sender writes in a direct message, the agent SHALL answer with one fixed text that contains a pairing code and says the account is not linked, and SHALL do nothing else with the message. The code SHALL be 8 characters from an alphabet without easily confused characters, SHALL expire after `app.channels.pairing.ttl` (default 1 hour), SHALL be stored only as a hash, and SHALL be bound to the tenant, platform and platform account id that asked for it. A sender that already has a pending code SHALL get the same code again until it expires, and SHALL get no answer at all for further messages within `app.channels.pairing.reply-interval` (default 10 minutes). At most `app.channels.pairing.max-pending` codes (default 3) SHALL be pending per tenant and platform, and when that number is reached a new stranger SHALL get no answer. The message text of a stranger SHALL NOT be stored or logged.

#### Scenario: First message from a stranger

- **WHEN** an unlinked Telegram account sends "hello" to the bot in a direct message
- **THEN** it receives one reply with a pairing code and the text that the account is not linked
- **AND** no model is called and the word "hello" is not stored or logged

#### Scenario: Stranger keeps writing

- **WHEN** the same stranger sends five more messages within ten minutes
- **THEN** none of them gets an answer

#### Scenario: Pending limit reached

- **WHEN** three codes are pending for Discord in the tenant and a fourth unlinked account writes
- **THEN** the fourth account gets no answer and no code is created

### Requirement: An unlinked sender in a group is ignored

In a group chat, a guild channel or a thread that is not a direct message, a message from an unlinked sender SHALL get no answer and SHALL NOT create a pairing code, whether or not it mentions the bot.

#### Scenario: Stranger mentions the bot in a guild channel

- **WHEN** an unlinked Discord user mentions the bot in a guild channel
- **THEN** the bot does not answer and no pairing code is created

### Requirement: A signed-in user links an account by redeeming its code

The agent SHALL expose `POST /api/v1/channels/links` with a JSON body holding `code`. Only an authenticated user SHALL redeem a code, and the new link SHALL name that user and the user's tenant. A code SHALL be redeemed at most once. A code of another tenant, an expired code, a used code and an unknown code SHALL all answer 404 with `code` `channel_pairing_not_found`, so a caller cannot tell them apart. After `app.channels.pairing.max-redeem-failures` (default 5) failed redeems by one user within `app.channels.pairing.redeem-failure-window` (default 15 minutes), further redeems by that user SHALL answer 429 with `code` `channel_pairing_rate_limited` until the window ends. A successful redeem SHALL answer 201 with the link view and SHALL send one confirmation message to the linked account. A platform account that is already linked SHALL answer 409 with `code` `channel_link_exists`.

#### Scenario: Owner links his Discord account

- **WHEN** the owner, signed in, sends `POST /api/v1/channels/links` with the code his Discord account received
- **THEN** the response is 201 with the link view naming Discord, the account id and his user
- **AND** his Discord direct message receives a confirmation, and his next message there runs a chat turn

#### Scenario: Guessing codes is limited

- **WHEN** a signed-in user sends six wrong codes within 15 minutes
- **THEN** the sixth answer is 429 with `code` `channel_pairing_rate_limited`

### Requirement: Links can be listed and removed

The agent SHALL expose `GET /api/v1/channels/links` and `DELETE /api/v1/channels/links/{id}`. A user SHALL see and remove only his own links. A caller with `ADMIN` of the tenant SHALL see and remove every link of the tenant. A removed link SHALL stop the next message of that account, SHALL leave the conversations of the user in place, and SHALL send no message to the account. An unknown or foreign id SHALL answer 404 with `code` `channel_link_not_found`. The link view SHALL carry `id`, `platform`, `accountId`, `accountName`, `kind` (`user` or `peer_bot`), `userId`, `createdAt` and `lastSeenAt`, and SHALL never carry a token.

#### Scenario: Admin removes a link of another user

- **WHEN** a tenant `ADMIN` removes the Slack link of another user of the tenant
- **THEN** the response is 204 and that Slack account gets the pairing reply on its next direct message

### Requirement: A linked identity is the caller of the chat turn

A chat turn started by a channel message SHALL run as the linked user, with the user's tenant, roles and principal set resolved for that user at the time of the message, never with the host's own service identity and never with a wider principal set than the user has when signed in. When the user's identity cannot be resolved (the user is disabled, deleted or the identity provider cannot be reached), the message SHALL be refused with a fixed reply and no chat turn SHALL run. Only a user who holds `ADMIN` of the tenant SHALL be offered the tools and decisions that need `ADMIN`.

#### Scenario: Disabled user

- **WHEN** an administrator disables the owner's Keycloak account and the owner's linked Discord account writes to the bot
- **THEN** no chat turn runs and the reply says the account cannot be used now

#### Scenario: Same documents as in the app

- **WHEN** a linked user asks the same question through Discord and through the app
- **THEN** the retrieval of both turns uses the same principal set

### Requirement: Linking is measured, logged and audited

The agent SHALL count pairing codes created, redeems by outcome and refused messages by reason (`unlinked`, `group_unlinked`, `pending_limit`, `identity_unavailable`), with the `platform` tag only, never an account id or a code. It SHALL log one INFO line per link created or removed, with platform, link id and user id, and never the code. It SHALL record an audit event through the `AuditEventPort` of `add-deployment-modules` for every pairing code created, every redeem by outcome and every link removed, never with the code or message text. Where the events are stored is decided by the port's implementation, which `add-audit-and-gdpr-compliance` registers later.

#### Scenario: Redeem is counted without the code

- **WHEN** a code is redeemed successfully
- **THEN** the redeem counter with `platform` and `outcome` `ok` grows by one
- **AND** no log line contains the code

#### Scenario: Link removal reaches the audit port

- **WHEN** a link is removed while a test `AuditEventPort` bean replaces the default
- **THEN** that bean receives one event naming the platform and the link id, with no code and no message text
