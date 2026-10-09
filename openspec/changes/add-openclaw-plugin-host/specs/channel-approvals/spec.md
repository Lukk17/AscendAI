## Purpose

Lets the owner approve or deny a pending action of the approval service from Discord, with buttons on a message that shows exactly what will run, deciding as his linked identity and never as the bot.

## ADDED Requirements

### Requirement: A pending approval is posted to the owner on Discord

When an approval of `add-action-approvals` becomes `pending` and the `discord` channel is on, the agent SHALL queue one outbound approval prompt for every user who holds `ADMIN` of the approval's tenant and has an active Discord link. The channel host SHALL send it as a direct message to that linked account. The message SHALL show the approval's kind, category, tool name and server, scope text, expiry time and preview, and SHALL carry an Approve button and a Deny button. The preview SHALL be cut to fit the platform's message limit with a visible note that it was cut, and the full view SHALL stay readable through `GET /api/v1/approvals/{id}`. The message SHALL NOT show a credential value. When no tenant `ADMIN` has a Discord link, no prompt SHALL be queued and the approval SHALL stay decidable through REST and the app.

#### Scenario: Gated tool call reaches the owner's Discord

- **WHEN** a chat turn calls a tool that requires approval and the owner has a linked Discord account
- **THEN** the owner's Discord direct message receives one message with the tool, the arguments preview, the expiry time and the two buttons

#### Scenario: No linked admin

- **WHEN** an approval becomes pending and no `ADMIN` of the tenant has a Discord link
- **THEN** no Discord message is sent and the approval stays `pending`

### Requirement: A button press decides as the linked owner, with the shown digest

A button press SHALL be sent by the `channels` container that runs Discord to the one action endpoint `POST /api/v1/channel-host/actions` of the agent with the platform, the presser's platform account id, the outbox id of the message and the index of the pressed button. The agent SHALL read the action type (`approval_approve` or `approval_deny`), the approval id and the arguments digest from the outbox row the message was built from, never from the host. The agent SHALL resolve the presser through the link, SHALL refuse the press when the presser has no active link or the linked user does not hold `ADMIN` of the approval's tenant, and SHALL otherwise decide through the approval service with channel `discord`, the linked user as the deciding user and the digest from the message. A digest that no longer matches SHALL change nothing. The button press SHALL never decide as the bot or as the channel host's service identity. A "remember this choice" option SHALL NOT be offered on Discord.

#### Scenario: Owner presses Approve

- **WHEN** the owner presses Approve on the prompt of a pending approval
- **THEN** the approval is `approved` with `decisionChannel` `discord` and the owner's user as the deciding user
- **AND** the stored action runs once

#### Scenario: Someone else presses a button

- **WHEN** the prompt was forwarded and another Discord account presses Deny
- **THEN** the approval stays `pending` and that account receives an ephemeral or direct reply that it may not decide

#### Scenario: Unknown button

- **WHEN** the host sends a press whose outbox id or button index does not exist
- **THEN** the agent answers 404 with the code `not_found` and no approval changes

#### Scenario: Stale prompt

- **WHEN** the owner presses Approve on a prompt whose approval was already denied in the app
- **THEN** nothing runs and the message is updated to show the approval as already decided

### Requirement: The prompt message follows the approval's state

After every change of a prompted approval (decided by anyone, expired, cancelled, executed), the host SHALL edit the prompt message to show the new state, who decided and through which channel, and SHALL remove the buttons once the approval is not `pending`. When the edit fails, the host SHALL send a short follow-up message with the new state instead.

#### Scenario: Approval expires

- **WHEN** a prompted approval expires after 24 hours
- **THEN** the Discord message shows it as expired and has no buttons

### Requirement: Approval prompts are measured and logged

The agent and the host SHALL count approval prompts sent and button presses by outcome (`approved`, `denied`, `forbidden`, `stale`, `error`), with the `platform` tag only. Log lines SHALL carry the approval id and the link id and SHALL NOT carry the preview or the arguments at INFO level.

#### Scenario: Forbidden press is counted

- **WHEN** an unlinked account presses a button
- **THEN** the press counter with `outcome` `forbidden` grows by one
