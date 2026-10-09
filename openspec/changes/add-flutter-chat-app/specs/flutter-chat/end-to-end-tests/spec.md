## Purpose

Proves the whole app works against a running stack. Flutter integration tests run the real app against the agent, Keycloak and their stores, and human-gated checks cover what automation cannot reach on a real device. Owner request of 2026-10-04.

## ADDED Requirements

### Requirement: The app has an end-to-end suite of integration tests against a running stack
The project SHALL ship an e2e suite at `apps/ascend-chat/e2e/` that follows the spec, tasks-template and run record contract of the other e2e suites, numbered with the next free number when each spec is written. Each automated spec SHALL run one Flutter integration test (`integration_test` package) of the real app against a running agent, and SHALL pass only when the test exits 0 and the persisted state it names is right when read back through the agent's API. No spec SHALL pass or fail on a log line or on the wording of a model answer. A spec SHALL be marked AI-run only when a real model is needed to reach the state under test. A state reached by a tool call, such as an approval card or a started background run, SHALL be reached through the scripted model of the shared e2e harness of `close-agent-test-gaps` (its design D5 and task group 4), so no AI model decides the result. A spec that sends a prompt but judges no wording, such as the streamed prompt, attachments, sources and citations, web build and tray specs, SHALL send it to the provider `scripted` of that harness and SHALL need no hosted provider key. The scripted model and the fake MCP server of that harness SHALL start only for deterministic specs, never for an AI-run spec (owner answer 70.4 of 2026-10-04). A deterministic spec SHALL NOT wipe memories, because AscendMemory is faked in that phase. A behaviour that a widget, unit or integration test already proves SHALL NOT be repeated by an e2e spec: the owner screens SHALL be checked end to end by the live approval card spec only, and the real JSON shapes of the agent's views SHALL be proved by API client tests that parse fixtures recorded from the running agent.

#### Scenario: Sign-in and chat
- **WHEN** the login and streamed prompt specs run on the Windows desktop target
- **THEN** sign-in through a random loopback port reaches the agent with a bearer token, and a streamed reply grows before `done`
- **AND** the agent stores the conversation, the user prompt and one assistant message

#### Scenario: Conversations, attachments and provider choice
- **WHEN** the conversation management and attachments specs run
- **THEN** rename and delete in the app are reflected in the agent's conversation list
- **AND** the recorded prompt request carries the attachment part and the chosen provider and model

#### Scenario: Sources and citations
- **WHEN** the sources and citations spec asks about a seeded canary document with attach sources on
- **THEN** the citation chip shows the canary's name and position, and the source tile opens a `downloadUrl` that returns the canary's bytes

#### Scenario: Web build streams across origins
- **WHEN** the web build spec runs the streamed prompt test on Chrome from an origin listed in `app.cors.allowed-origins`
- **THEN** the stream reaches `done` and the agent stores the conversation

#### Scenario: Voice input with a fake recogniser
- **WHEN** the voice spec runs on an Android emulator with a scripted fake recogniser
- **THEN** the transcript fills the input box, nothing is sent before the send button, and the agent stores the edited text as the user message with no audio part in the request
- **AND** a denied permission, a missing recogniser and a missing language model each show their message and leave the input box unchanged

#### Scenario: Owner screen views parse the agent's real JSON
- **WHEN** the API client tests of the owner screens run on fixtures recorded from the running agent
- **THEN** every view model parses its recorded view, and a fixture that loses a field the view model reads fails its test

#### Scenario: Desktop window hides to the tray
- **WHEN** the tray spec closes the window during a streamed reply and opens it again
- **THEN** the app kept running, and the reply reached `done` while the window was hidden

#### Scenario: Live approval card
- **WHEN** the approval card spec sends a prompt whose scripted model calls a gated tool
- **THEN** the approval card appears in the conversation, and an approve made in the app is visible in the agent

### Requirement: Real-device behaviour is checked by human-gated specs
What automation cannot reach SHALL be covered by human-gated specs with their own tasks-template and run record: dictation with the real microphone and the platform recogniser on an Android phone and an iPhone, online and offline and with the permission denied, sign-in and the owner screens on a phone on the same network, on Windows and on the web build, and the operating system tray on Windows, Linux and macOS. These specs SHALL run only in the run scenarios that already need a human at the keyboard.

#### Scenario: Dictation on real phones
- **WHEN** a person runs the dictation spec on an Android phone and an iPhone
- **THEN** the transcript is reviewed before sending, works offline with the language model installed, and the denied permission shows its message
- **AND** the agent stores the edited text as the user message

#### Scenario: Tray on real desktops
- **WHEN** a person closes the window during a reply, opens it from the tray and quits from the tray on Windows, Linux and macOS
- **THEN** the reply is complete after opening and no app process remains after Quit
