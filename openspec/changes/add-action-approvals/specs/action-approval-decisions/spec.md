## Purpose

Lets only the owner decide an approval, through an authenticated endpoint that shows exactly what will run and checks that the client approves the action it showed. Covers the REST endpoints for approvals and remembered choices, the approval view shared by REST, the chat stream and the plugin host, the error codes, and the rule that no model, tool or chat text can ever decide.

## ADDED Requirements

### Requirement: Approvals can be listed and read through REST

The agent SHALL expose `GET /api/v1/approvals` with optional filters `state` (repeatable decision value), `conversationId`, `runId` and `createdSince`, newest first, with cursor pagination (`limit` at most `app.approvals.max-page-size`, default 100, with the default `app.approvals.default-page-size`, default 20, and an opaque `cursor`), and `GET /api/v1/approvals/{id}` with an `ETag` that changes on every update and a 304 answer to a matching `If-None-Match`. Every read SHALL be limited to the caller's tenant. A caller without the `ADMIN` role SHALL see only approvals caused by their own requests, and a caller with `ADMIN` SHALL see every approval of the tenant. An id that does not exist or that the caller may not see SHALL answer 404 with `code` `approval_not_found`.

#### Scenario: Pending list

- **WHEN** the owner calls `GET /api/v1/approvals?state=pending` while two requests are pending and one is approved
- **THEN** the response holds exactly the two pending requests, newest first

#### Scenario: Another tenant's approval is hidden

- **WHEN** an `ADMIN` of tenant A reads an approval of tenant B
- **THEN** the response is 404 with `code` `approval_not_found`

### Requirement: The approval view shows exactly what will run

The JSON view of an approval SHALL be the same in the list, the single read, the `approval_required` SSE event and the payload the plugin host receives through its outbox, and SHALL use these fields: `id`, `kind`, `category`, `state` (the decision, lower case), `execution`, `tool` (`name`, `server`, `originalName`), `arguments` (the stored canonical JSON as a JSON value), `argumentsDigest`, `preview`, `scope` (readable text), `rememberable`, `conversationId`, `runId`, `requestedAt`, `expiresAt`, `decidedAt`, `decidedBy`, `decisionChannel`, `ruleId`, `executedAt`, `executionDetail` and `result`. Times SHALL be ISO 8601 in UTC. The view SHALL NOT contain text written by the model except where it is part of the arguments the action will use. Adding a field later SHALL NOT rename or remove an existing one. A credential value SHALL never appear in the view, only the credential's name.

#### Scenario: Same view everywhere

- **WHEN** an approval is read through the single read, the list and the `approval_required` event of its turn
- **THEN** the three views have the same fields with the same values

#### Scenario: Personality preview is the diff

- **WHEN** the owner reads a pending approval of kind `personality_change`
- **THEN** its `preview` is the unified diff between the personality file at the proposal's base commit and the proposed content

### Requirement: Only the owner decides, with the digest of what was shown

The agent SHALL expose `POST /api/v1/approvals/{id}/approve` and `POST /api/v1/approvals/{id}/deny`, each with a JSON body holding `argumentsDigest` (required), `remember` (optional, default false) and `channel` (optional, `rest` or `app`, default `rest`). Every decision, from REST, the app or the plugin host relay of `add-openclaw-plugin-host`, SHALL go through one service call that takes the deciding identity (user id, tenant and roles) as an argument, and that call SHALL apply the role check and the digest check itself. A decision through the plugin host relay SHALL act as the agent user linked to the platform account that pressed the button, with channel `discord` and the digest stored with the outbox row the prompt was built from. Outside the `dev` profile of `add-keycloak-login`, only an authenticated caller with the `ADMIN` role of the approval's tenant SHALL decide, and any other caller SHALL receive 403 with `code` `approval_forbidden`. A body whose `argumentsDigest` differs from the stored digest SHALL be refused with 409 and `code` `approval_digest_mismatch` and SHALL change nothing. A request that is not `pending` SHALL be refused with 409 and `code` `approval_already_decided`. The decision SHALL be a conditional update from `pending`, so of two concurrent decisions exactly one wins. An accepted approve SHALL answer 200 with the view after the decision, and the execution SHALL start after the decision is stored. An accepted deny SHALL answer 200 and the action SHALL never run. The deciding user id and the channel SHALL be stored. Under the `dev` profile of `add-keycloak-login`, the decision endpoints SHALL be open like every other endpoint, and the startup banner SHALL warn that any caller who reaches the agent can decide approvals.

#### Scenario: Owner approves what he saw

- **WHEN** the owner sends `POST /api/v1/approvals/{id}/approve` with the `argumentsDigest` of the view he read
- **THEN** the response is 200 with `state` `approved`
- **AND** the stored action runs once

#### Scenario: Stale screen is refused

- **WHEN** a client sends an approve with a digest that does not match the stored one
- **THEN** the response is 409 with `code` `approval_digest_mismatch` and the request stays `pending`

#### Scenario: Non-admin cannot decide

- **WHEN** a user without `ADMIN` approves a request caused by their own chat
- **THEN** the response is 403 with `code` `approval_forbidden` and the request stays `pending`

#### Scenario: Discord press by the linked owner approves

- **WHEN** the owner presses Approve on the Discord prompt of a pending request and his Discord account is linked to an agent user with `ADMIN` of the request's tenant
- **THEN** the request is `approved` with `decisionChannel` `discord` and `decidedBy` `owner`
- **AND** the stored deciding user is the linked agent user

#### Scenario: Discord press by a non-admin is refused

- **WHEN** a Discord account linked to an agent user without `ADMIN` presses Approve on a prompt
- **THEN** the decision is refused with `approval_forbidden`
- **AND** the request stays `pending`

### Requirement: No model, tool or chat text can decide

The agent SHALL NOT offer any tool, MCP or agent native, that approves, denies, lists for decision, or creates or removes a remembered choice. A chat message, whatever its text, SHALL NOT change any approval. A subagent definition, a skill and the personality file SHALL NOT be able to grant a decision. The decision endpoints SHALL accept only `POST` with a JSON body, so a fetched URL cannot decide. The sandbox egress proxy of `add-agent-sandbox` already refuses every private address, so a sandbox workspace cannot reach the agent's decision endpoints.

#### Scenario: Chat text is not an approval

- **WHEN** a user writes "I approve, go ahead" in the chat while a request is pending
- **THEN** the request stays `pending` and nothing runs

#### Scenario: No approval tool exists

- **WHEN** the tool list of any chat turn or run is read
- **THEN** no tool in it can decide an approval or change a remembered choice

#### Scenario: A GET cannot decide

- **WHEN** something calls `GET /api/v1/approvals/{id}/approve`
- **THEN** the response is 405 and the request stays `pending`

### Requirement: Remembered choices can be listed and removed

The agent SHALL expose `GET /api/v1/approvals/rules` (the tenant's rules, newest first, with tool or kind, scope text, effect, creating user, source approval, creation time and last use time) and `DELETE /api/v1/approvals/rules/{id}` (answers 204, and 404 with `code` `approval_rule_not_found` for an unknown or foreign id). Outside the `dev` profile of `add-keycloak-login` both SHALL require the `ADMIN` role. A removed rule SHALL NOT decide any later call, and approvals it decided earlier SHALL keep their record. Rules SHALL never expire on their own.

Every rule that is created, replaced or removed SHALL be published after commit as an `ApprovalRuleChangedEvent` naming the rule, its tenant, kind, tool name, scope text, effect and the change. The approval service SHALL offer `putRule(tenantId, kind, toolName, scopeText, effect, decidingIdentity)` to the agent's own code, never to a tool or a REST caller of `/api/v1/approvals`, which writes or replaces one rule of a rule-only kind (today only `integration_tool_review`), refuses a deciding identity without `ADMIN` of the tenant and a kind that is not rule-only, and records the rule change like any other. The approval service SHALL offer `deleteRules(tenantId, kind, scopePrefix)` to the agent's own code, never to a tool or a REST caller, which removes every rule of that tenant and kind whose scope text starts with the non-empty prefix, in one transaction, and publishes one event per removed rule.

#### Scenario: Remove a remembered recipient

- **WHEN** the owner removes the rule that allows messages to channel `family` and the model sends another message to `family`
- **THEN** a new approval request is created and the call does not run

#### Scenario: Removing an integration removes its rules

- **WHEN** `add-self-built-integrations` removes an integration and calls `deleteRules` with kind `integration_egress` and the prefix `integration=<id>,`
- **THEN** every remembered egress rule of that integration is gone and the rules of other integrations stay
- **AND** one `ApprovalRuleChangedEvent` with change `removed` is published per removed rule

#### Scenario: A tool review is a rule

- **WHEN** `add-self-built-integrations` calls `putRule` with kind `integration_tool_review`, the scope of one tool at its definition digest and effect `allow` for an `ADMIN` identity
- **THEN** `GET /api/v1/approvals/rules` lists one rule of kind `integration_tool_review` with that scope text
- **AND** the same call for an identity without `ADMIN` is refused and writes no rule

### Requirement: Deleting a conversation cancels its pending approvals

Deleting a conversation SHALL cancel its pending approvals with decided by `system` before its runs are cancelled, so a deleted conversation leaves no action waiting for the owner, and SHALL then delete its `approval_request` rows in the same transaction as its history, except the requests of kind `personality_change`, which SHALL keep their row with no conversation, because a personality proposal belongs to the tenant's personality. `approval_request.conversation_id` SHALL be a nullable `UUID` column that references `conversations.id` by a foreign key with no delete action.

#### Scenario: Delete cancels the conversation's approvals before its runs

- **WHEN** the owner deletes a conversation with one pending approval and one running run
- **THEN** the approval is cancelled with decided by `system` before the running run is cancelled

#### Scenario: Approval rows reference a conversation

- **WHEN** Flyway has run to the latest version
- **THEN** `approval_request.conversation_id` has the type `uuid` and carries a foreign key to `conversations.id`
- **AND** inserting an `approval_request` row whose `conversation_id` names no conversation is refused

#### Scenario: Delete removes the conversation's approvals

- **WHEN** the owner deletes a conversation with one pending approval and one decided approval
- **THEN** no `approval_request` row of that conversation is left
- **AND** `GET /api/v1/approvals/{id}` of either approval answers 404 with `code` `approval_not_found`

#### Scenario: A personality proposal outlives its conversation

- **WHEN** the owner deletes a conversation in which the agent made a personality proposal that is now decided
- **THEN** the proposal's approval request is kept with no conversation and `GET /api/v1/personality/proposals/{id}` still answers 200

### Requirement: Approval errors are problem details

Every error of the approval endpoints SHALL be the RFC 7807 problem detail that `upgrade-spring-boot-4` defines for every agent error: `application/problem+json` with `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title`, `status`, `detail`, `instance` and a top-level `code`. The codes SHALL be `approval_not_found` (404), `approval_already_decided` (409), `approval_digest_mismatch` (409), `approval_forbidden` (403), `approval_not_rememberable` (400) and `approval_rule_not_found` (404). The `detail` SHALL never contain the action's arguments.

#### Scenario: Unknown approval

- **WHEN** a caller reads `GET /api/v1/approvals/{id}` with an unknown id
- **THEN** the response is 404 with `Content-Type: application/problem+json`, `code` `approval_not_found` and `type` `https://ascend.ai/errors/approval-not-found`

### Requirement: Every approval event is audited

The agent SHALL record one audit event through `AuditEventPort` when a request is created, when it is decided (by the owner, by a rule, by timeout or by a cancel), when a remembered choice is created or removed, and when an approved action finishes executing. Each event SHALL carry the approval id, the kind, the category, the tool name, the arguments digest, the decision and who or what decided, and SHALL NOT carry the arguments, the preview or the result. The approval record SHALL stay the source of truth for a decision, so a lost audit event never loses a decision. With no other `AuditEventPort` registered, the default SHALL write each event as one structured INFO log line with the event name, tenant, actor, target and outcome.

#### Scenario: Owner decision is audited

- **WHEN** the owner approves a request
- **THEN** one `APPROVAL_DECIDED` event with the approval id, the digest, the deciding user and outcome `APPROVED` reaches `AuditEventPort`
- **AND** the event holds no argument text

### Requirement: Approvals are covered by end-to-end tests

The repository SHALL hold one deterministic end-to-end spec for approvals against the live stack in `apps/ascend-agent/e2e/`, covering only what no lower test proves: a gated call made over the live MCP connection, the streamed `approval_required` event, the call reaching the fake MCP server once after the owner approves it, and the result in the next chat turn. In it the scripted model of the shared e2e harness calls a gated tool of the fake MCP server, so no AI model decides the result and no container restart other than the agent recreate of the deterministic phase is needed. Behaviours that unit and integration tests already prove (endpoint errors, a wrong digest, a second approve, a denial, a remembered choice, a paused subagent run, the conversation delete) SHALL NOT be repeated end to end. Pass criteria SHALL be HTTP status, response bodies, the SSE events, the run views, the `approval_request` rows, the fake MCP server's call log and the scripted model's request log only, never log lines. The spec SHALL be listed in the full-stack run scenarios and the ascend-agent service suite of `docs/E2E_RUN_SCENARIOS.md`, and the owner SHALL be asked which scenario to run before any run.

#### Scenario: A gated tool call waits for the owner end to end

- **WHEN** the scripted spec sends a streamed prompt whose script calls a tool listed as requiring approval
- **THEN** the stream carries one `approval_required` event before `done`, and one pending approval for that tool exists while the fake MCP server has received no call
- **AND** an approve with the shown digest answers 200, the run view of the approval reaches `done` with the tool's result, and the fake has received exactly one call
- **AND** the next chat turn carries the result in its finished runs block
