## Purpose

Makes sure a self-built integration gets a password or token, or sends anything outside the system, only after the owner said yes once for that integration, and that the secret itself lives only in the sandbox runner's environment and is never visible to the agent, the model, the coding agent or the integration.

## ADDED Requirements

### Requirement: A credential is granted only through an owner approval

The tool `integration_request_credential` SHALL take an integration id and a credential name declared in the integration's active or candidate manifest, and SHALL submit one approval of kind `integration_credential` through the approval service. The approval's preview SHALL be built by the server from the stored manifest and SHALL show the integration title and version, the credential name, its kind, its header name, its destination host, its allowed path prefixes, its purpose and the tools that use it. Approving it SHALL always remember an allow rule of kind `integration_credential` scoped to the integration, the credential name and the digest of the credential's binding (its kind, header, host and path prefixes), and that rule SHALL be the grant. No column of the integration's tables SHALL copy the decision, and the credential state the integration view shows SHALL be read from the approval and rule records. A credential SHALL be usable only while such a rule covers its current binding. A denied or expired approval SHALL leave the credential unusable, and the model MAY ask again with a new call.

#### Scenario: Credential requested

- **WHEN** the model calls `integration_request_credential` for credential `api_key` of the integration `quotes`
- **THEN** one pending approval of kind `integration_credential` exists, its preview names `api.quotes.example` and the header, and the tool result names the approval id

#### Scenario: Approval leaves one grant rule

- **WHEN** the owner approves that `integration_credential` approval
- **THEN** exactly one allow rule of kind `integration_credential` with the integration, the credential name and the binding digest exists, and the integration view shows the credential as `granted`

#### Scenario: Binding unchanged keeps the grant

- **WHEN** a new version keeps the credential's name, kind, header, host and path prefixes
- **THEN** no new approval is created and the credential reads `granted`

### Requirement: The secret value never passes through a chat

The value of a granted credential SHALL be given only by the owner, as a line in the integration secrets file `integration-secrets.env` that docker compose passes to the sandbox runner alone, under the variable name the runner derives from the integration id and the credential name (`INTEGRATION_SECRET_<first 12 hex characters of the integration id, upper case>_<credential name, upper case>`, with `_USERNAME` and `_PASSWORD` for kind `basic`). The approval preview, the tool result of `integration_request_credential` and the integration view SHALL show that variable name. The tool result SHALL tell the model that the value is set by the owner outside the chat and that it must never ask the user to type a secret into the chat. No tool and no endpoint SHALL read, set or return a credential value, and no database table SHALL hold one.

#### Scenario: Variable name shown

- **WHEN** the owner reads the pending approval of credential `api_key` of the integration `quotes`
- **THEN** its preview names the variable `INTEGRATION_SECRET_<id12>_API_KEY` and says the value goes into `integration-secrets.env`

#### Scenario: Value never returned

- **WHEN** the owner reads `GET /api/v1/integrations/{id}`
- **THEN** each credential shows its state, its variable name and whether the runner reports a value, and no part of the value

### Requirement: A credential prompt says the secret never goes into a chat

A prompt for an approval of kind `integration_credential` that `add-openclaw-plugin-host` posts on Discord SHALL carry one fixed line, added by the agent, saying that the owner adds the secret to the integration secrets file `integration-secrets.env`, which only the sandbox runner reads, and never types it into any chat. The prompt SHALL show the variable name that the approval names and SHALL never show a value.

#### Scenario: Credential prompt on Discord

- **WHEN** an `integration_credential` approval becomes pending and the owner has a linked Discord account
- **THEN** the prompt holds the fixed line and the variable name, and no secret value

### Requirement: Secret values live only in the runner's environment and reach only the gateway

The sandbox runner SHALL read a credential value from its own environment, only by the variable name it derives for a service whose tenant label it checked, and SHALL write it only into the gateway's memory-backed folder. It SHALL never accept a value or another variable name from the agent, and SHALL never put a value into an environment variable of another container, a label, a command, a log, a metric, a trace attribute, an error body or an answer. The agent SHALL never hold a value. A granted credential whose variable is missing or empty SHALL leave the integration waiting with the reason `credential_value_missing`. A new or changed value SHALL take effect after the owner recreates the runner, without recreating the integration container. Revoking a credential, removing the integration or erasing the tenant SHALL remove the credential route from the gateway at once, and the owner removes the line from the file.

#### Scenario: Value absent from logs and context

- **WHEN** an integration with a set credential runs and is called while every log of the agent and the runner is at DEBUG
- **THEN** no log line, trace attribute, stored chat message, tool result, approval preview or agent memory holds the value

#### Scenario: Missing value

- **WHEN** a credential is granted and `integration-secrets.env` has no line for its variable
- **THEN** the integration stays `awaiting_owner` with the reason `credential_value_missing`, and its tools return the waiting result

#### Scenario: Value added later

- **WHEN** the owner adds the line and recreates the runner
- **THEN** by the next firing of `integration-reconcile` the gateway adds the header, the integration container was not recreated, and the integration becomes `active` when nothing else is pending

#### Scenario: Revoke

- **WHEN** the owner calls `DELETE /api/v1/integrations/{id}/credentials/{name}`
- **THEN** the grant rule is removed and the credential reads `revoked`, the gateway no longer adds the value from the moment the revocation has reconciled the integration, and the integration view lists the variable as still present in the runner until the owner removes the line

### Requirement: The first send to each destination needs the owner's yes

When an integration is registered, and when a new version declares a destination the integration has no decided approval for, the agent SHALL submit one approval of kind `integration_egress` per such destination, with the integration id and the host as its scope and a preview showing the integration title, the host, its purpose and the tools of the manifest. Approving it SHALL remember an allow for that integration and host, which then adds the host to the integration's egress proxy. A denial with remember SHALL keep that host refused for that integration. Removing the remembered rule through `/api/v1/approvals/rules/{id}` SHALL remove the host from the egress proxy at once through the rule change event, and at the latest by the next firing of `integration-reconcile`. An integration SHALL send nothing to a host before its approval is approved.

#### Scenario: Approved once

- **WHEN** the owner approves the egress approval for `api.quotes.example`
- **THEN** a remembered allow exists for that integration and host, and the integration's proxy allows the host by the next firing of `integration-reconcile`
- **AND** a later version that keeps the same host needs no new approval

#### Scenario: Rule removed

- **WHEN** the owner removes the remembered allow for `api.quotes.example`
- **THEN** by the next firing of `integration-reconcile` the proxy refuses that host and the integration's tools return the waiting result

### Requirement: Approval decisions follow the approval service

Every decision on `integration_credential` and `integration_egress` SHALL be taken only through the decision endpoints of the approval service, with its digest check and its rule that no model, tool or chat text can decide. An expiry SHALL count as a denial. Each grant, denial, expiry and revocation SHALL be visible on the integration's view, read from the approval and rule records of the approval service. On Discord the Approve and Deny buttons of these approvals SHALL go through the one channel action endpoint of the plugin host.

#### Scenario: Expired egress approval

- **WHEN** an egress approval is not decided within the approval timeout
- **THEN** it ends `expired`, the host stays refused, and the integration view shows the destination as `expired`
