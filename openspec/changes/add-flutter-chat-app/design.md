## Context

AscendAI is a multi-module monorepo with Java and Python backend services but no user-facing frontend. The ascend-ai-agent exposes a REST API on port 9917 for AI prompts (with multipart file support), a specced server-sent events streaming endpoint, and a conversation management REST API. See proposal.md for the full motivation. The `flutter_chat_ui` library provides the chat widget, `flutter_chat_core` provides message models and the `ChatController` interface.

## Goals / Non-Goals

**Goals:**
- Deliver a cross-platform chat client (Android, iOS, web, Windows, macOS, Linux) from a single Flutter codebase.
- Use `flutter_chat_ui` as the presentation layer, with a custom `ChatController` that bridges the ascend-ai-agent conversation API.
- Support real-time token streaming via server-sent events for assistant responses.
- Let the user manage conversations (list, create, rename, delete) and attach files to prompts.
- Provide a dark-mode-first theme with light-mode toggle.
- Let the user sign in with a Keycloak account through the authorization code flow with PKCE, and send a bearer token on every request (decision 14, owner decision 65.2 and owner answer 70.2 of 2026-10-04). `add-keycloak-login` lands earlier, so the app never sends `X-User-Id`.
- On Windows, macOS and Linux, keep the app in the system tray (the menu bar on macOS): closing the window hides the app to the tray, and the tray menu opens or quits it (decision 15, owner decision 65.18 of 2026-10-04).
- Let the user dictate a prompt on Android and iOS. Speech becomes text on the phone, the text fills the input box for review, and the agent only ever receives text.
- Give the owner the screens the other agent changes (all landing earlier) ask of this app: approval cards and a pending approvals screen (`add-action-approvals`), a notification list (`add-shared-scheduler`), a background runs screen (`add-agent-subagents`), a scheduled jobs screen (`add-scheduled-tasks`) and a "What I learned" screen (`add-self-improvement`). See decisions 10 to 13.

**Non-Goals:**
- Push notifications and background sync. The app reads notifications, pending approvals and runs only while it is open (decision 10). A push channel is a later change: it is one more implementation of the owner notification port of `add-shared-scheduler`, and needs no change to the screens planned here.
- Offline-first or local database persistence of messages (messages are fetched from the API; the `ChatController` is API-backed, not Hive-backed).
- Knowledge base document management UI (specced separately in `add-document-management-api`).
- Server-side audio transcription through ascend-audio-scribe, or any upload of audio to the agent (voice input is transcribed on the phone, see decision 9).
- Text-to-speech for assistant replies. Replies stay text for now.
- Voice input on web, Windows, macOS and Linux. The owner asked for it on the phone, so the microphone button is shown on Android and iOS only.
- MCP tool invocation UI.
- Files a sandbox produced, for now. `add-agent-sandbox` offers `GET /api/v1/conversations/{id}/sandbox-outputs`, `GET /api/v1/conversations/{id}/sandbox-outputs/{workspaceId}` and `GET /api/v1/runs/{id}/sandbox-output`, and this change shows no files list in the chat or on the run detail and calls none of them. Owner decision 51.5 of 2026-10-03: a later feature lets the owner download a file a sandbox produced from the mobile app, through a download link the agent creates for that file, the same way a download of `add-file-download` reaches him as a link that lasts at most 24 hours. The app then opens that link like any other link, so it needs no save-file step and no header of its own for the download, and the later change that adds the link adds the button.

## Decisions

### 1. Module placement and naming

The Flutter module lives at `apps/ascend-chat/`, beside the other modules under `apps/`. The `pubspec.yaml` project name is `ascend_chat`. It is a standalone client: it is not served by the agent and not placed behind a reverse proxy. It calls the agent directly at `ASCEND_API_URL`, set with `--dart-define` at build time (default `http://localhost:9917`).

**Alternatives considered:**
- Nested under `apps/ascend-agent/frontend/`: rejected because ascend-ai-agent is a Gradle project and mixing Flutter build artifacts into it creates tooling conflicts.
- Separate repository: rejected because the OpenSpec workflow and agent instructions rely on monorepo-local changes.

### 2. State management with Riverpod

The app uses `flutter_riverpod` with the current API only: `Provider` for the config and API client, `Notifier`/`NotifierProvider` for synchronous state (theme, prompt settings) and `AsyncNotifier`/`AsyncNotifierProvider` for loaded state (conversation list). The legacy `StateNotifierProvider` and `ChangeNotifierProvider` are not used.

**Alternatives considered:**
- `provider` (already a dependency of `flutter_chat_ui`): simpler but lacks async state primitives and compile-time safety.
- `bloc`: heavier ceremony for an app with relatively simple state transitions.

### 3. HTTP and server-sent events client

The app uses the `http` package for REST calls. The streaming endpoint is a multipart `POST`, so `EventSource` (GET only, no body) cannot be used. One platform-independent SSE parser turns a `Stream<List<int>>` into typed events (`delta`, `citations`, `sources`, `done`, `error`, and the non-terminal `run_started`, `subagent_status` and `approval_required`) by reading `event:` and `data:` lines. `run_started` and `subagent_status` carry `{"run": <run view>}` of `add-agent-subagents`, and `approval_required` carries `{"approval": <approval view>}` of `add-action-approvals`. Both changes add these events to the stream of `add-chat-streaming-and-conversations` through their required edits there. An event name the parser does not know is skipped and logged at debug level, never treated as an error, so a later agent change can add an event without breaking an app that is already installed. The same parser reads `GET /api/v1/runs/{id}/events`, which sends `subagent_status` events with the run's update counter as the SSE `id`, and it exposes that `id` so a dropped run stream is resumed with `Last-Event-ID`. The reconnect waits `ASCEND_RUN_STREAM_RECONNECT_INITIAL_SECONDS` (1 second) before its first attempt, doubles the wait after each failed attempt up to `ASCEND_RUN_STREAM_RECONNECT_MAX_SECONDS` (30 seconds), goes back to the first wait after an event arrives, and has no attempt limit: it stops only when the run is final or the screen is left (owner answer 106 of 2026-10-09, decision 16). Every REST call and the wait for the response headers of a stream have the time limit `ASCEND_HTTP_TIMEOUT_SECONDS` (30 seconds), never an open stream body, and a call past it is reported to the user as a failed call (owner answer 106 of 2026-10-09). Two byte sources feed it behind a conditional import: on native platforms `http.Client.send` with a `MultipartRequest` and its `StreamedResponse.stream`, and on web `fetch` from `package:web` reading `response.body` through a `ReadableStreamDefaultReader`. `dart:html` is not used.

Error parsing: every error body of the agent is the RFC 7807 problem detail that `upgrade-spring-boot-4` defines (its D19, owner decision of 2026-10-02), sent as `application/problem+json` with `type` (`https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`), `title`, `status`, `detail`, `instance` and a top-level snake case `code`. The terminal `error` event of the stream carries the same object (`add-chat-streaming-and-conversations` design D2). One parser in `lib/src/api/` turns either source into one sealed `ApiProblem` value with `status`, `code` and `detail`, so a REST error and a stream error are handled the same way. The app branches on `status` and `code` (for example `conversation_not_found` sends the user back to the list, `vision_unsupported` explains that the model cannot read images) and shows `detail` to the user. A body that is not a problem detail, for example an HTML page from a proxy, becomes an `ApiProblem` with the HTTP status, no code and a generic text, so the app never fails on an unexpected body.

**Alternatives considered:**
- `dio`: feature-rich but adds a large dependency tree; the `http` package covers all needed functionality.
- `eventsource` pub package: abandoned/unmaintained; manual SSE parsing is straightforward (under 100 lines) and avoids a dependency risk.

### 4. ChatController implementation

A custom `AscendChatController` implements the `flutter_chat_core` `ChatController` interface. It holds an in-memory list of messages loaded from the API and emits `ChatOperation` events. On `insertMessage`, it sends the prompt to the streaming endpoint and handles the response. The controller does not write directly to a local database; all persistence is via the ascend-ai-agent conversation API.

**Alternatives considered:**
- `InMemoryChatController` with external API calls: the library's built-in controller does not emit the right events when messages arrive asynchronously from server-sent events, so a custom implementation is necessary.
- Hive-backed `PersistedChatController` from the Flyer Chat examples: adds local persistence complexity without benefit since the backend is the source of truth.

### 5. Navigation

The app uses `go_router` for declarative, URL-based navigation. Two routes for chat: `/conversations` (list) and `/conversations/:id` (chat). The owner screens of decision 11 add `/approvals`, `/notifications`, `/runs`, `/runs/:id`, `/scheduled-jobs`, `/scheduled-jobs/:id` and `/learned`. The conversation list app bar reaches each of them, with a badge on the approvals, notifications and "What I learned" entries. Deep linking is supported on web and mobile.

**Alternatives considered:**
- Navigator 2.0 directly: verbose; `go_router` is the recommended Flutter routing package.
- `auto_route`: code-generation-heavy; `go_router` is simpler for two routes.

### 6. File picker for attachments

The app uses the `file_picker` package for cross-platform file selection (images and documents). Selected files are held in memory until the prompt is sent, then attached as multipart parts.

**Alternatives considered:**
- `image_picker`: only handles images, not documents.
- Platform-specific file access: `file_picker` already abstracts this.

### 7. Theme persistence

Theme preference (dark, light, auto) is stored using `shared_preferences`. On startup, the app reads the stored preference and applies it before the first frame renders.

### 8. Direct connection, CORS and phone access

There is no container, no nginx and no compose service for the app. The owner wants a separate client that can connect from a phone, so the address of the agent is a build-time setting and the app talks to it directly.

The web build runs on a different origin than the agent, so the agent gains a CORS configuration (`config/CorsConfig.java`) whose allowed origins come from `app.cors.allowed-origins` (empty by default, so nothing changes until an operator sets it). Under owner rule 98 it is read from the environment variable `APP_CORS_ALLOWEDORIGINS` (a comma separated list): `application.yaml` writes `${APP_CORS_ALLOWEDORIGINS:}`, the `@ConfigurationProperties` record defaults to an empty list, and the `ascend-agent` service of `compose.yaml` writes `- APP_CORS_ALLOWEDORIGINS=${APP_CORS_ALLOWEDORIGINS:-}`. It allows `GET`, `POST`, `PATCH`, `DELETE`, the `Content-Type` and `Authorization` headers, and exposes `Location`. `X-User-Id` is never allowed, because the app sends only the bearer token (decision 14). Native apps do not need CORS.

A phone reaches the agent at `http://<host LAN address>:9917` on a development host. The compose service `ascend-agent` publishes 9917 on `${EXPOSE_BIND:-127.0.0.1}`, loopback by default (the `production-deployment` rule of `harden-cloud-deployment`), so the developer sets `EXPOSE_BIND` to the host LAN address or `0.0.0.0` in `.env` on that development host only, and the host firewall must allow port 9917. The compose file is not changed. In a deployment the phone reaches the agent through the edge gateway at its public HTTPS address, never through port 9917. Android blocks clear-text HTTP by default, so the Android debug build allows clear-text traffic through a debug-only network security config, and iOS gets an `NSAllowsLocalNetworking` entry. Both are documented in `apps/ascend-chat/README.md`.

**Alternatives considered:**
- Serve the web build from nginx with an `/api` proxy: rejected by the owner, it ties the app to one deployment and does not help a phone.
- Serve it from the agent: rejected by the owner, the app must be separate.

### 9. Voice input through the platform speech recogniser

The owner's decision: the phone turns his voice into text, the server receives text and never audio, and recognition must not need a server or a GPU. So the app uses the speech recogniser that ships with the phone: `SpeechRecognizer` on Android and the Speech framework (`SFSpeechRecognizer`) on iOS. Flutter reaches both through the `speech_to_text` package.

Package check, done on pub.dev on 2026-10-02: the latest stable version is 7.5.0, published about 17 days before the check by the verified publisher `csdcorp.com`, with 150 pub points and steady releases (7.4.0 four months earlier, 7.3.0 thirteen months earlier). It is licensed BSD-3-Clause and needs Dart 3.12 or newer. It supports Android, iOS, macOS, web and Windows, and not Linux. A 7.6.0 beta exists and is not used. Task 1.2 checks the version again at implementation time, like every other dependency.

Offline support, as the package source shows it: `SpeechListenOptions.onDevice` asks for recognition that never leaves the device, and the listen attempt fails if the device cannot do that. On Android the package then sets `RecognizerIntent.EXTRA_PREFER_OFFLINE` and, on API 31 or newer when `SpeechRecognizer.isOnDeviceRecognitionAvailable` is true, creates the recogniser with `SpeechRecognizer.createOnDeviceSpeechRecognizer`. On iOS the same option sets `requiresOnDeviceRecognition` on the Speech framework request, and the package refuses the listen call with `onDeviceError` when the recogniser for that language reports no `supportsOnDeviceRecognition` (no downloaded model for it). On Android below API 31 the system decides whether an offline model is used.

The app code talks to a small `VoiceRecognizer` interface in `lib/src/voice/`, and `SpeechToTextRecognizer` is its one adapter over the package. Widgets and notifiers depend on the interface, so tests use a fake recogniser and the package can be replaced without touching the screens. A `VoiceInputNotifier extends Notifier<VoiceInputState>` holds the state: `idle`, `listening`, `permissionDenied`, `unavailable` and the last error.

How it behaves:

- On-device only. Every listen call passes `onDevice: true`, so speech stays on the phone and nothing reaches a cloud recogniser, the agent or ascend-audio-scribe. The prompt request is the same text-only request a typed prompt sends.
- Microphone permission. The first tap on the microphone button calls `initialize`, which shows the system permission dialog (microphone, and on iOS also speech recognition). If the user denies it, `initialize` returns false or reports `error_permission`, the app stays out of the listening state, leaves the input box unchanged, and shows a snackbar that says voice input needs the microphone permission and where to turn it on in the system settings. The button stays enabled, and a later tap checks `hasPermission` and calls `initialize` again, so a permission granted in the settings works without a restart. On iOS the system dialog appears only once, so after a denial the snackbar is the only way back.
- Review before sending. The transcript goes into the composer's text field, never into a sent message. Partial results replace the dictated part of the text live while the user speaks. Text that was already in the box stays in front of it, joined with one space. When recognition ends (the user taps the button again, or no speech is heard for `ASCEND_SPEECH_PAUSE_SECONDS` seconds, default 2, passed as `pauseFor` on every listen call, owner answer 106 of 2026-10-09) the final text stays in the box with the cursor at its end, and the user edits it and presses send as for a typed prompt. Pressing send while listening stops the listening first and sends the text currently in the box.
- Language selection. The language list comes from the recogniser's `locales()`, and the default is `systemLocale()`. The chosen locale id is passed as `localeId` on every listen call and is stored with `shared_preferences` by a `VoiceLanguageNotifier`, the same way the theme choice is stored, because it is a device preference and not a per-session prompt setting. The picker sits in the chat settings bottom sheet. A stored locale that the recogniser no longer lists falls back to `systemLocale()`.
- Offline. Recognition works with no network when the device has an on-device model for the chosen language, and the agent does not need to be reachable to dictate. When the model is missing, the recogniser reports `error_language_unavailable` on Android or `onDeviceError` on iOS, and the app shows a message that the offline speech model for that language is not installed and names where to download it (Android: the speech recognition languages in the system settings, iOS: the dictation languages in the keyboard settings). It does not fall back to a cloud recogniser.
- No recogniser. When `initialize` fails because the device has no recogniser (the package reports `recognizerNotAvailable` on Android, for example a phone without Google speech services), the state becomes `unavailable`, the microphone button is shown disabled with the tooltip "Voice input is not available on this device", and typing works as before.
- Leaving the screen. Listening is cancelled when the chat screen is disposed and when the app goes to the background, so the microphone is never held open.

Platform entries: the Android manifest gets `android.permission.RECORD_AUDIO` and a `<queries>` entry for the `android.speech.RecognitionService` intent, which Android 11 (API 30) and newer need to find the recogniser. The iOS `Info.plist` gets `NSMicrophoneUsageDescription` and `NSSpeechRecognitionUsageDescription`. The Bluetooth permissions the package README also lists are only needed for Bluetooth headsets and are not added.

**Alternatives considered:**
- Send audio to ascend-audio-scribe and transcribe on the server: rejected by the owner. The server must receive text, and the local Whisper backend needs a GPU.
- Run a Whisper model inside the app (for example through `whisper.cpp` bindings): works offline on every platform, but adds a model of tens to hundreds of megabytes to the app and is slow on phones without strong hardware. The platform recogniser costs nothing in app size.
- Call the platform recognisers through our own platform channels: `speech_to_text` already does this, is maintained and has a verified publisher, so writing our own would repeat it.
- Auto-send the transcript when speech ends: rejected, because a recognition mistake would go straight to the model. The user reviews the text first.
- Add `permission_handler` to open the app settings page from the snackbar: one more dependency for one button. The snackbar names the settings path instead.

### 10. Polling while the app is open, push later

The sources agree that the app reads, it is not woken. `add-shared-scheduler` asks for a notification list read "when the app opens, when it returns to the foreground and on pull to refresh", and says push stays out of scope and a push channel later is one more implementation of its notification port. `add-action-approvals` asks the app to read `GET /api/v1/approvals?state=pending` when it opens, when it returns to the foreground and after every `approval_required` or `subagent_status` event, and puts push in a later notification change. While the app is closed the owner is still reached through the `discord` channel of that port, which `add-openclaw-plugin-host` implements with Approve, Deny and Undo buttons.

Decision: polling while the app is open is enough now. One `OwnerRefreshNotifier` refreshes the three badge sources (unread notifications, pending approvals, and unseen "What I learned" changes, counted as the number of ids in `subjectIds` of the caller's unread notifications of source `self_improvement` from `GET /api/v1/notifications?unread=true&source=self_improvement`, owner answer 89.6 of 2026-10-08) at these moments: app start, the app lifecycle moving to `resumed`, pull to refresh on each screen, every `approval_required`, `run_started` or `subagent_status` event of a chat stream, and a timer of `ASCEND_OWNER_REFRESH_SECONDS` seconds (default 60, a build-time setting of decision 16 read in `lib/src/config/app_config.dart`) that runs only while the lifecycle is `resumed` and is stopped on `paused` and `hidden`. Each refresh is three small `GET` calls, so the cost is low, and the longest delay for a change made elsewhere is one interval while the app is in front.

Push is the recommendation for later, in its own change: a push channel (Firebase Cloud Messaging on Android, Apple Push Notification service on iOS) is one more `OwnerNotificationChannel` of `add-shared-scheduler`, plus a device token endpoint in the agent and a token registration call in the app. The screens and notifiers planned here stay as they are, because a push only tells the app to run the same refresh.

**Alternatives considered:**
- Push now: needs a Firebase project and Apple push credentials, a device token store in the agent and a new channel, none of which any active change plans. Rejected for now, recorded above as the next step.
- A long-lived server-sent events stream of owner events: no agent change offers one, and it would hold a connection the phone drops in the background anyway.
- Reading only on open and on resume, with no timer: what the sources list as the minimum. The timer is added because an approval that arrives from a background run while the owner looks at another screen would otherwise wait until he leaves and comes back.

### 11. Owner screens and their data layer

Each agent change that asks for a screen gets one feature folder under `lib/src/`, following the layers of `/flutter-architecture`: a stateless API client per feature (one class per group of agent endpoints), immutable view models parsed from the JSON views those changes define, a Riverpod notifier that holds the screen state, and the screen. Every client reuses one `AgentHttp` helper in `lib/src/api/agent_http.dart` that builds the URL under `ASCEND_API_URL`, sends the `Authorization` header of the `AuthSession` (decision 14) and turns every non-2xx body into an `ApiProblem` (decision 3), so no client repeats that work. `AscendApiClient` (task 2.2) keeps the prompt and conversation calls and moves onto the same helper.

| Feature folder | Asked by | API client and endpoints | State | Route |
| :--- | :--- | :--- | :--- | :--- |
| `lib/src/approvals/` | `add-action-approvals` | `ApprovalsApi`: `GET /api/v1/approvals?state=pending`, `GET /api/v1/approvals/{id}`, `POST /api/v1/approvals/{id}/approve`, `POST /api/v1/approvals/{id}/deny` | `PendingApprovalsNotifier extends AsyncNotifier<List<ApprovalView>>`, `ApprovalDecisionNotifier` per card | `/approvals` |
| `lib/src/notifications/` | `add-shared-scheduler` | `NotificationsApi`: `GET /api/v1/notifications` (filters `unread`, `source`, `kind`, cursor), `GET /api/v1/notifications/{id}`, `POST /api/v1/notifications/{id}/read` | `NotificationListNotifier extends AsyncNotifier` with paging | `/notifications` |
| `lib/src/runs/` | `add-agent-subagents` | `RunsApi`: `GET /api/v1/runs` (filter `kind`, cursor), `GET /api/v1/runs/{id}`, `GET /api/v1/runs/{id}/events`, `POST /api/v1/runs/{id}/cancel` | `RunListNotifier extends AsyncNotifier`, `RunDetailNotifier` (family by id) following the event stream | `/runs`, `/runs/:id` |
| `lib/src/scheduled_jobs/` | `add-scheduled-tasks` | `ScheduledJobsApi`: `GET /api/v1/scheduled-jobs`, `GET /api/v1/scheduled-jobs/{id}`, `GET /api/v1/scheduled-jobs/{id}/firings`, `POST /api/v1/scheduled-jobs/{id}/pause`, `/resume`, `/trigger`, `DELETE /api/v1/scheduled-jobs/{id}` | `ScheduledJobListNotifier extends AsyncNotifier`, `ScheduledJobDetailNotifier` (family by id) | `/scheduled-jobs`, `/scheduled-jobs/:id` |
| `lib/src/learned/` | `add-self-improvement` | `SelfImprovementApi`: `GET /api/v1/self-improvement/changes` (filters `since`, `type`, `status`, `unseen`, cursor), `GET /api/v1/self-improvement/changes/{id}`, `POST /api/v1/self-improvement/changes/{id}/undo`, and the unread `self_improvement` notifications through `NotificationsApi` | `LearnedChangesNotifier extends AsyncNotifier` with paging | `/learned` |
| `lib/src/modules/` | `add-deployment-modules` | `ModulesApi`: `GET /api/v1/modules` | `ActiveModulesNotifier extends AsyncNotifier<Set<String>>` | none |

How the screens behave:

- Approval card. An `approval_required` event inserts one custom message into the conversation, rendered by `ApprovalCard`: the kind, the preview, the exact arguments as formatted JSON, the expiry time in local time, an Approve button, a Deny button, and a "Remember this choice" switch shown only when `rememberable` is true. A button sends `POST /api/v1/approvals/{id}/approve` or `/deny` with `argumentsDigest` taken from the view on screen, `remember` from the switch and `channel` `app`, so the owner approves exactly what he read. The card then shows the outcome. A refusal shows the `detail` of its `ApiProblem`. `approval_already_decided` (409) shows "Already decided" and reloads the view with `GET /api/v1/approvals/{id}`, and `approval_digest_mismatch` (409) reloads the view and asks the owner to read it again. The same card is used on the pending approvals screen, so staged self-improvement changes (kind `self_change`), coding publish and cleanup approvals and the credential approvals of `add-self-built-integrations` all show through the preview text the agent writes, with no kind-specific code in the app.
- Notification list. Newest first, unread items marked, a detail view, and `POST /api/v1/notifications/{id}/read` when a notification is opened. Opening one also goes to the screen of its subject: source `approval` and `coding_area` kind `cleanup` open `/approvals`, source `self_improvement` opens `/learned`, and source `scheduled_job` opens `/runs/:runId` when `runId` is set, else `/scheduled-jobs/:jobId`.
- Background runs. The list shows each run's kind, description, state, cost so far and last step, filtered by kind. The detail view shows the whole run view (state, tokens, limits, cost, last step, failure with reason and `cancelledBy`, and the result when done). While the run is not final the detail view follows `GET /api/v1/runs/{id}/events` and resumes it with `Last-Event-ID` after a drop. A Cancel button, shown while the run is not final, sends `POST /api/v1/runs/{id}/cancel` after a confirmation. In a conversation, `run_started` inserts a compact run status line that `subagent_status` updates and that opens `/runs/:id` when tapped.
- Scheduled jobs. The list shows each job's name, kind (`reminder` or `task`), state and next firing in local time. The detail view shows the job and its firing history from `/firings`, with Pause, Resume, Run now (`POST /trigger`) and Cancel (`DELETE`, after a confirmation). The app does not create or edit jobs: `add-scheduled-tasks` asks only for these actions, and the owner creates a job by asking the agent in chat.
- "What I learned". A list of change records with what changed, why, the trigger, the check outcome, the untrusted source mark and an Undo button. Tapping a record shows its detail with the diff from `GET /changes/{id}`. Undo sends `POST /changes/{id}/undo` after a confirmation and shows the refusal `detail` when the agent refuses it (for example when the caller is not an `ADMIN`). The badge counts the ids in `subjectIds` of the unread notifications of source `self_improvement`, and opening the screen sends `POST /api/v1/notifications/{id}/read` for each of those notifications, so the notification list and the badge agree (owner answer 89.6 of 2026-10-08). The list may still use the filter `unseen=true` of `GET /changes`, which the agent now derives from the same notifications.

**Alternatives considered:**
- Add every endpoint to `AscendApiClient`: one class with six reasons to change. Rejected for small clients over one shared helper.
- A repository layer between the clients and the notifiers: the agent is the single source of truth and the app caches nothing (Non-Goals), so a repository would only pass calls through. Notifiers call the clients directly, as the existing conversation list does.

### 12. Hiding screens of modules that are off

`add-deployment-modules` lets a deployment switch modules off, and says the app may read `GET /api/v1/modules` to hide screens. The app does so at start and on resume. The scheduled jobs screen is shown only when `scheduler` is active and the "What I learned" screen only when `self-improvement` is active. Approvals, notifications and runs belong to `core-chat` and are always shown. When the modules call fails, every screen is shown and each screen shows its own error, so a failed call never hides a screen that works.

### 13. Badges

Each badge shows the number of items on the first page of its list (`unread=true` for notifications, `state=pending` for approvals, and for "What I learned" the change ids in `subjectIds` of the first page of unread notifications of source `self_improvement`), and a plus sign when the page says more exist, so a badge never needs a count endpoint the agent does not offer. The badges refresh at the moments of decision 10.

### 14. Sign-in with Keycloak, authorization code with PKCE

Owner decision 65.2 of 2026-10-04. `add-keycloak-login` (the personal login change split out of `add-auth-and-identity` on 2026-10-04, build group 3, position 3, owner answer 70.2 of 2026-10-04: the mobile app logs in to Keycloak and gets OAuth tokens, and the backend authenticates every request with those tokens) makes every agent endpoint require a bearer token from the realm `ascend-ai` and removes `X-User-Id` from the agent (its task 3.4). It lands before this change, so the app sends only the bearer token from its first build. The app therefore signs the user in through the public client `ascend-flutter` of that realm: authorization code flow with PKCE `S256`, no client secret and never a password grant (`add-keycloak-login` D2a). The user types the password only on Keycloak's own login page, never in the app.

The app reads two more build-time settings with `--dart-define`: `ASCEND_AUTH_ISSUER` (the realm issuer, for example `https://auth.example.com/realms/ascend-ai`, read through its discovery document) and `ASCEND_AUTH_CLIENT_ID` (default `ascend-flutter`). The redirect address depends on the platform:

| Platform | Redirect address | How the app receives the code |
|---|---|---|
| Windows, macOS, Linux | `http://127.0.0.1:<port>/callback` | A one-time HTTP listener bound to `127.0.0.1` on a random free port (port 0), opened in the system browser with `url_launcher`. Keycloak accepts any port for the registered loopback address `http://127.0.0.1/callback`, as RFC 8252 section 7.3 asks. The listener answers one request with a short "You can close this window" page and closes |
| Android, iOS | `com.lukk.ascend:/callback` | The private-use URI scheme of RFC 8252 section 7.1, received through the platform browser session (Custom Tabs on Android, `ASWebAuthenticationSession` on iOS) by a package checked on pub.dev at implementation time (task 19.1) |
| Web | The exact hosting address of the web build followed by `/callback`, for example `https://chat.example.com/callback` | The page itself is redirected, and the `/callback` route of `go_router` finishes the exchange. The PKCE verifier and the `state` are kept in `sessionStorage` for that one round trip only |

The `state` parameter is random per sign-in and checked on return, and a mismatch is refused. The code is exchanged for tokens at the token endpoint with the verifier. The access token is sent as `Authorization: Bearer <token>` by `AgentHttp` and by both stream byte sources, so every REST call and every stream carries it. Before a request the app refreshes an access token that expires within `ASCEND_TOKEN_REFRESH_MARGIN_SECONDS` seconds (default 30, a build-time setting of decision 16). A 401 triggers one refresh and one retry, and a second 401 or a failed refresh sends the user to the sign-in screen. On Android, iOS and desktop the refresh token is kept in `flutter_secure_storage`. On web no token is written to storage: tokens live in memory, and a reload signs in again through Keycloak's single sign-on session without a password while that session lasts. Sign out calls the realm's end session endpoint and clears the stored tokens.

Order: this change is build group 4, position 17 of the owner build order of 2026-10-04, and `add-keycloak-login` is build group 3, position 3, so it is applied before any task of this change starts. The app therefore never has `X-User-Id` or `ASCEND_USER_ID`, and never has two ways to say who the user is, and it has no built-in password login of its own (owner answer 70.2 of 2026-10-04). Task group 19 builds the sign-in on that change. The login flow lives behind one `AuthSession` interface in `lib/src/auth/`, so the rest of the app only asks for the current header, and the tasks before group 19 use a fake `AuthSession` in their tests. Keycloak is a core prerequisite of the stack. Several tenants, brokered corporate sign-in and organizations are company work of `add-auth-and-identity` (build group 5) and need nothing from this app.

**Alternatives considered:**
- Password grant in the app: refused, it is prohibited by the security standard of `add-keycloak-login` (D2a) and the realm export turns it off.
- A fixed loopback port: refused, a fixed port can be taken by another program, and RFC 8252 asks the server to accept any port for a loopback redirect.
- `localhost` instead of `127.0.0.1`: refused, RFC 8252 section 8.3 recommends the loopback IP literal, because `localhost` can resolve to another interface.

### 15. Desktop tray icon, close hides to the tray

Owner decision 65.18 of 2026-10-04. On Windows, macOS and Linux the app shows an icon in the system tray (the menu bar on macOS). Closing the window does not quit the app: it hides the window and the app keeps running in the tray, so polling (decision 10) and a running stream go on. The tray icon has a menu with two entries, "Open Ascend" (shows and focuses the window) and "Quit" (stops the polling timer, cancels open streams and ends the process). Quit is the only way the app ends from the window side. On Windows and macOS a click on the tray icon also opens the window. Android, iOS and web are not affected.

Packages, both from the verified publisher leanflutter.dev under the MIT license, checked on pub.dev on 2026-10-04:

- `tray_manager` 0.7.0 (published about 2026-09-20, needs Dart 3.13 or newer, Linux, macOS and Windows): the tray icon, its tooltip and its context menu. From 0.7.0 the icon on Linux is a StatusNotifierItem over D-Bus, so the build needs only GTK 3, X11 and Xi development files and no longer `libayatana-appindicator3-dev`. On Linux the panel keeps clicks on the icon and opens the menu itself, so the menu is the way to open the window there, which is why "Open Ascend" is a menu entry and not only a click.
- `window_manager` 0.5.2 (published about 2026-07, Linux, macOS and Windows): `setPreventClose(true)` at start, the close event of its window listener, `hide()`, `show()`, `focus()` and `destroy()` for Quit.

Task 1.2 still re-checks both on pub.dev at implementation time and pins the current stable release then. The tray code lives in `lib/src/desktop/` behind a `DesktopShell` interface, created only when the platform is Windows, macOS or Linux and the build is not web, so tests use a fake shell.

**Alternatives considered:**
- `system_tray`: an older package with the same purpose. Not chosen, because `tray_manager` and `window_manager` come from one verified publisher, are released together and cover both the icon and the window close.
- Quit on close: refused by the owner, he wants the app to stay in the tray.

### 16. Build-time settings of the app

Owner rule 98 of 2026-10-08: no hidden constant an operator might need to change. The app has no server environment, so every value with a default is a build-time setting passed with `--dart-define=<NAME>=<value>` (the mechanism decision 1 already uses for `ASCEND_API_URL`) and read in one place, `lib/src/config/app_config.dart`, with `String.fromEnvironment` or `int.fromEnvironment` and the default below as `defaultValue`. No other file holds one of these values.

| Setting | Default | What it does |
| :-- | :-- | :-- |
| `ASCEND_API_URL` | `http://localhost:9917` | Base address of the agent (decision 1) |
| `ASCEND_AUTH_ISSUER` | `http://localhost:8180/realms/ascend-ai` (owner answer 103.5 of 2026-10-09) | Issuer of the Keycloak realm `ascend-ai`, read through its discovery document (decision 14) |
| `ASCEND_AUTH_CLIENT_ID` | `ascend-flutter` | Keycloak public client of the app (decision 14) |
| `ASCEND_OWNER_REFRESH_SECONDS` | 60 | Interval of the owner refresh timer while the app is in front (decision 10) |
| `ASCEND_TOKEN_REFRESH_MARGIN_SECONDS` | 30 | An access token that expires within this many seconds is refreshed before a request (decision 14) |
| `ASCEND_HTTP_TIMEOUT_SECONDS` | 30 (owner answer 106 of 2026-10-09) | Time limit of every REST call and of the wait for the response headers of a stream, never of an open stream body (decision 3) |
| `ASCEND_RUN_STREAM_RECONNECT_INITIAL_SECONDS` | 1 (owner answer 106 of 2026-10-09) | Wait before the first reconnect of a dropped run event stream, doubled after each failed attempt (decision 3) |
| `ASCEND_RUN_STREAM_RECONNECT_MAX_SECONDS` | 30 (owner answer 106 of 2026-10-09) | Largest wait between reconnect attempts of a run event stream, with no attempt limit (decision 3) |
| `ASCEND_SPEECH_PAUSE_SECONDS` | 2 (owner answer 106 of 2026-10-09) | Listening ends after this many seconds without speech, passed as `pauseFor` (decision 9) |

The rows go into the section "Flutter chat app" of the repository configuration reference `docs/CONFIGURATION.md` (columns Service, Variable, Default, What it does, Added by), and the agent setting `app.cors.allowed-origins` of decision 8 gets its row in `apps/ascend-agent/docs/CONFIGURATION.md` (task 12.6). Kept as constants, because they are not operational: the single refresh and single retry after a 401 (a second 401 with a fresh token means the session is gone, so more retries cannot succeed), the PKCE verifier length of 64 characters and the method `S256` (RFC 7636), the loopback port 0 and the redirect addresses (RFC 8252 and the realm export of `add-keycloak-login`), the conversation name limit of 255 characters (the agent's own limit), the route paths, the stream event names, the `shared_preferences` keys, and the tray texts.

## Risks / Trade-offs

- **[Sign-in on every device]** Every use of the app needs a Keycloak account, because `add-keycloak-login` lands earlier and the agent accepts no `X-User-Id`. Mitigation: the stored refresh token and the Keycloak single sign-on session keep sign-ins rare, and the development overlay of `add-keycloak-login` seeds the users a local stack needs.
- **[Web build tokens]** A browser page cannot keep a secret. Mitigation: no token in browser storage, only in memory, and the Keycloak single sign-on session makes a reload cheap.
- **[Hidden window keeps running]** A user may not notice the app still runs after closing the window. Mitigation: the tray icon stays visible with the tooltip "Ascend is running" and the menu has Quit.
- **[Backend dependency]** The Flutter app depends on the streaming and conversation endpoints of `add-chat-streaming-and-conversations` (build group 3, position 9), which lands earlier, so the endpoints exist when this change is built. Mitigation for a contract change: the API client layer is behind an interface, and the widget tests use fake implementations of it.
- **[SSE on web]** `EventSource` cannot send a POST body. Mitigation: fetch-based streaming through `package:web` on web, `http` streaming on native, one shared parser.
- **[Open CORS]** A wide allowed-origins list lets any site call the agent from a browser. Mitigation: empty by default, explicit origins only, never `*` together with credentials.
- **[No offline mode]** If the backend is unreachable, the app shows errors instead of cached content. This is acceptable for a first iteration since the app is designed for use on the same network as the backend.
- **[Stale pins]** Versions in this plan go stale. Mitigation: task 1.2 re-checks every dependency on pub.dev at implementation time and pins the current stable release.
- **[No on-device model]** On-device recognition needs a downloaded model per language, and some Android phones below API 31 or without Google speech services have none. Mitigation: the app names the missing model and where to install it, the button is disabled with a reason when there is no recogniser at all, and typing always works.
- **[Recognition quality]** Platform recognisers differ in accuracy between phones and languages. Mitigation: the transcript is always reviewed in the input box before it is sent.
- **[Dart SDK floor]** `speech_to_text` 7.5.0 needs Dart 3.12 or newer. Mitigation: task 1.2 resolves it against the current stable Flutter SDK, which is already a requirement.
- **[No push]** An approval expires after 24 hours (`add-action-approvals`), and the app sees it only while it is open. Mitigation: the `discord` channel of `add-openclaw-plugin-host` reaches the owner while the app is closed, and push is the planned next step (decision 10).
- **[Polling delay]** A change made elsewhere shows up to 60 seconds late while the app is in front. Mitigation: every chat stream event that names a run or an approval refreshes at once, and pull to refresh is on every owner screen.
- **[New stream events]** A later agent change may add stream events. Mitigation: the parser skips an event it does not know (decision 3), and task 11.4 tests that.

## Open Questions

- Closed (owner decision 65.18 of 2026-10-04): the desktop app gets a tray (menu bar) icon, closing the window minimizes it to the tray instead of quitting, and the tray menu opens or quits it (decision 15).
- Closed (owner decision 65.2 of 2026-10-04): the app signs in with Keycloak through the authorization code flow with PKCE and sends a bearer token, with the redirect addresses `http://127.0.0.1/callback` (desktop, any port), `com.lukk.ascend:/callback` (Android and iOS) and the exact hosting address of a web build (decision 14).
- Resolved by the owner on 2026-10-02: there is no cloud recogniser fallback. When the phone has no on-device model for a language, the app shows the error described under Offline and does nothing else.

## Owner decisions of 2026-10-07

Answer 75.1 (review of the group 3, 4 and 5 changes of 2026-10-07, fix of all 75 items approved): items 9, 38 and 68 are fixed here. Item 9: phone access on a development host sets `EXPOSE_BIND` in `.env` and never edits the compose file, and a deployment reaches the agent through the gateway (Risks and task 10.3). Item 38: every spec that sends a prompt (21.3, 21.5, 21.6, 21.7, 21.10, 21.14 and 21.16) runs on the scripted model of `close-agent-test-gaps`, no spec of the suite is AI-run, and the count of AI-run specs is gone (task group 21, `end-to-end-tests` spec). Item 68: the backend dependency risk no longer says the streaming endpoints may not exist, because `add-chat-streaming-and-conversations` lands earlier.

## Owner decisions of 2026-10-08

Answer 76.3 (partly): the marker name `chat-sources-and-citations` of spec 21.6 stays as it is. The answer keeps only the name, not its folders.

Answer 76.2: the scripted model of the shared harness of `close-agent-test-gaps` is Mockoon (the `mockoon/cli` image, pinned by version and digest). This change adds its script rules to the shared environment file `apps/ascend-agent/e2e/fixtures/scripted-model/scripted-model.json`, which holds every rule of every change, and keeps its reply files in `apps/ascend-agent/e2e/fixtures/scripted-model/responses/flutter-chat/`, its vector file in `apps/ascend-agent/e2e/fixtures/scripted-model/embeddings/flutter-chat/` (tasks 21.3, 21.5, 21.6 and 21.10).

Answer 76.4: the backend refuses an image for a model without image support (415 `vision_unsupported`). For the test, the test configuration of `close-agent-test-gaps` (its D5 and task 4.4) only adds the scripted model `scripted-text-only`, marked as having no image support, and spec 21.5 picks it for the refusal check (task 21.5).

Answer 78.1: the provider `scripted` uses `default-embedding: openai`, and the deterministic phase overlay points the agent's own embedding entry `openai` at Mockoon. There is no separate scripted embedding entry, and every vector file of this change is 1536 long (`ascendai-1536` and `ascend_memory_1536`).

Approved fix of 2026-10-08: every deterministic spec of this change that runs a scripted chat turn wipes in AscendMemory the memories of its users in its Reset state and Post-run cleanup (`POST /api/v1/memory/wipe` with the provider `openai` and the service token), because the memory extraction of a scripted turn embeds through the scripted model into `ascend_memory_1536` (tasks 21.3, 21.5, 21.6, 21.7, 21.8, 21.10, 21.14 and 21.16).

Answer 79.3: spec 21.8 (voice input) sends its transcribed message to the provider `scripted`, so the scripted model of `close-agent-test-gaps` answers it with a fixed text and no AI model runs, and it keeps the memory wipe of its Reset state and Post-run cleanup (task 21.8).

Answer 85.1: no plan text of this change exports a key or a secret in a shell. The app's build-time settings (`ASCEND_API_URL`, `ASCEND_AUTH_ISSUER`, `ASCEND_AUTH_CLIENT_ID`) are not secrets, the public client `ascend-flutter` has no secret, and the e2e suite signs in through the sign-in helper with the users of the development overlay of `add-keycloak-login`. Nothing changes here.

Answer 87 (rule R1, several agent instances): confirmed. The app is a client and keeps no server state. It reads every list from the agent, resumes a run stream with `Last-Event-ID` from the run events that `add-agent-subagents` feeds from the shared store, so a stream that reconnects to another agent instance continues, and the agent side of this change (`CorsConfig`) is configuration that every instance reads the same way.

Answer 89.6: the notification `read_at` is the only seen marker. The "What I learned" badge counts the changes of unread `self_improvement` notifications, and opening the screen marks those notifications read. The app sends no `POST /changes/seen` (decisions 10, 11 and 13, tasks 18.1 to 18.4, the `self-improvement-report` spec). Every button the app shows calls the agent's REST endpoints directly, so the one channel action endpoint of the plug-in host changes nothing in the app.

Answer 91.1: the deterministic specs of task group 21 that send a scripted prompt run in the deterministic phase of `close-agent-test-gaps` D7: only the agent changes (its test settings arrive by a copy and a restart, answer 98.1 below), AscendMemory is faked under `/ascend-memory/` of `e2e-scripted-model` and never restarted, and no deterministic spec wipes memories. The memory wipes of specs 21.3, 21.5, 21.6, 21.7, 21.8, 21.10, 21.14 and 21.16 are removed, so the approved fix above and the wipe of answer 79.3 no longer apply. Answer 91.2: the fake MCP server that spec 21.10 calls is the one fake MCP server class of `close-agent-test-gaps` task 4.2.

Answer 91.3: the live owner screen specs 21.9 (approvals), 21.11 (notifications), 21.12 (scheduled jobs), 21.13 (background runs), 21.14 (live background run) and 21.15 ("What I learned") are removed, because each repeats the widget and API tests of task groups 14 to 18, and the spec 21.17 that recreated the agent to hide two screens is removed, because the widget test of task 13.4 proves it. The live approval card spec 21.10 stays as the one deterministic owner screen spec, because it alone proves the path from a gated tool call through the stream event to a decision in the agent. What the removed specs proved about the agent's real JSON is kept by the new task 13.7: the fixtures of the API client tests of the owner screens are recorded from the real agent views. The login integration test of task 19.9 uses the realm `ascend-ai` of the running stack, so the second Keycloak test realm is removed. No spec of this suite runs with real AI answers, so none of that kind is touched.

Answer 93: not applied, because it would cut a capability (rule R3): the web build stays. It is the only way to chat from a browser with no app installed, and it brings the CORS setting, the second stream byte source and the web sign-in route.

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 98 (owner rule 98, every value with a default is a setting): the app's values are build-time settings passed with `--dart-define` and read only in `lib/src/config/app_config.dart` (decision 16): `ASCEND_API_URL` (`http://localhost:9917`), `ASCEND_AUTH_ISSUER` (default not decided, listed for the owner), `ASCEND_AUTH_CLIENT_ID` (`ascend-flutter`), `ASCEND_OWNER_REFRESH_SECONDS` (60, formerly the constant `ownerRefreshInterval`) and `ASCEND_TOKEN_REFRESH_MARGIN_SECONDS` (30). The agent setting `app.cors.allowed-origins` is read from `APP_CORS_ALLOWEDORIGINS` (default empty) with the compose line `- APP_CORS_ALLOWEDORIGINS=${APP_CORS_ALLOWEDORIGINS:-}` on the `ascend-agent` service (decision 8, task 10.2), and gets no `.env.example` line, because rule 98 adds none for a setting with a default. New task 12.6 adds the rows to the section "Flutter chat app" of `docs/CONFIGURATION.md` and the agent row to `apps/ascend-agent/docs/CONFIGURATION.md` in the same commit as the settings. The constants kept and why are in decision 16. The plan names no timeout of the app's HTTP calls, no delay or attempt limit for the reconnect of a run event stream (task 16.2) and no pause timeout of the speech recogniser (the package default applies), so none is added here, and all three are listed for the owner (decided by answer 106 of 2026-10-09 below). No test or measurement of this change uses LM Studio: every spec that sends a prompt uses the provider `scripted`, and no spec is AI-run. The provider selector shows the agent's default provider (`app.ai.default-provider`, `lmstudio` in today's `application.yaml`) as product behaviour, not as a test default.

Answer 98.1: there is no `e2e` profile any more. The deterministic specs of task group 21 run in the deterministic phase of `close-agent-test-gaps` D7, in which the test settings reach the running agent by a copy of `apps/ascend-agent/e2e/overlay/application-e2e.yaml` into `/app/config/application.yaml` and a restart, and the phase ends with a recreate of the agent. The text of answer 91.1 above and of task group 21 says so and cites D7 for the steps. Spec 21.7 needs its second web origin in `app.cors.allowed-origins`, so task 21.7 adds that origin to the overlay file, which is test configuration and never a line of `compose.yaml`.

## Owner decisions of 2026-10-09

Answer 103.5: the build define `ASCEND_AUTH_ISSUER` has the default `http://localhost:8180/realms/ascend-ai`, the realm `ascend-ai` of the development Keycloak on its host port 8180 (`KEYCLOAK_HOST_PORT` of `add-keycloak-login`), read with `String.fromEnvironment` in `lib/src/config/app_config.dart` and listed in the section "Flutter chat app" of `docs/CONFIGURATION.md` (decision 16, tasks 12.6 and 19.2). A build for another machine or for production passes its own issuer with `--dart-define`. Still not decided by anybody: the timeout of the app's HTTP calls, the delay and attempt limit of the reconnect of a run event stream (task 16.2) and the pause timeout of the speech recogniser (the Answer 98 record above). Answer 106 below decides them.

Answer 106: the remaining app values are decided, each a build-time setting of decision 16 passed with `--dart-define`, read only in `lib/src/config/app_config.dart` with `int.fromEnvironment`, named after the app's existing `ASCEND_` settings, and listed with its row in the section "Flutter chat app" of `docs/CONFIGURATION.md` (task 12.6). `ASCEND_HTTP_TIMEOUT_SECONDS` (30) is the time limit of every REST call of `AgentHttp` and of the wait for the response headers of both stream byte sources, never of an open stream body, and a call past it is reported as a failed call (decision 3, task 13.1). `ASCEND_RUN_STREAM_RECONNECT_INITIAL_SECONDS` (1) and `ASCEND_RUN_STREAM_RECONNECT_MAX_SECONDS` (30) set the reconnect of a run event stream: the first attempt after a drop waits 1 second, each further failed attempt doubles the wait up to 30 seconds, a received event resets it to 1 second, and there is no attempt limit, so the app keeps trying until the run is final or the screen is left (decision 3, task 16.2, spec `background-runs`). `ASCEND_SPEECH_PAUSE_SECONDS` (2) is the pause timeout of the speech recogniser, passed as `pauseFor` on every listen call, so listening ends after 2 seconds without speech (decision 9, task 9.3, spec `voice-input`). The attempt limit is behaviour, not a value, so it has no setting.
