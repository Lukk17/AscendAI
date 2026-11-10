## Why

AscendAI has no user-facing frontend. Every interaction with the platform goes through raw HTTP requests or API clients. A cross-platform chat application built with Flutter gives users one interface on Android, iOS, Windows, macOS, Linux and web from a single codebase. The `flutter_chat_ui` library (Apache 2.0, published by flyer.chat) provides a backend-agnostic chat widget with an animated message list, theming, and text, image, file and system messages, which maps directly onto the ascend-ai-agent prompt and conversation API.

The owner's requirement (2026-10-01): the app must be separate and must be able to connect even from a phone. So it is a standalone client that talks to the agent's API directly at a configurable address. It is not served by the agent and not placed behind nginx.

The owner's decision on voice (2026-10-02): the mobile app transcribes his voice into prompts on the phone, so the server receives text, not audio. Replies stay text for now, with no text-to-speech. On-device recognition must not need a server or a GPU.

## What Changes

- Add a standalone Flutter client at `apps/ascend-chat/` (pubspec name `ascend_chat`).
- The agent base URL is set at build time with `--dart-define=ASCEND_API_URL=<url>` (default `http://localhost:9917` for local development). A phone on the same network uses the agent host's LAN address, for example `http://192.168.1.20:9917`, and a remote deployment uses its public address. Every other value with a default is a build-time setting too, listed in design decision 16, among them the HTTP call time limit `ASCEND_HTTP_TIMEOUT_SECONDS` (30), the run event stream reconnect waits `ASCEND_RUN_STREAM_RECONNECT_INITIAL_SECONDS` (1) doubling to `ASCEND_RUN_STREAM_RECONNECT_MAX_SECONDS` (30) with no attempt limit, and the speech pause timeout `ASCEND_SPEECH_PAUSE_SECONDS` (2) (owner answer 106 of 2026-10-09).
- Use `flutter_chat_ui` and `flutter_chat_core` for the chat interface. Every dependency version is re-checked against pub.dev at implementation time and pinned to the current stable release then.
- An API client for `POST /api/v1/ai/prompt/stream` (server-sent events), the `/api/v1/conversations` family, and multipart attachments. On native platforms streaming reads the chunked response with `package:http`. On web it uses fetch-based streaming of the POST response body through `package:web` (not `EventSource`, which cannot send a POST body, and not `dart:html`, which is deprecated).
- A custom `ChatController` backed by the conversation API.
- A conversation list screen (create, rename, delete) and a chat screen per conversation.
- Per-prompt AI provider and model selection.
- RAG sources open their presigned `downloadUrl`. Citations from add-passage-level-citations show as tappable labels.
- A dark-mode-first theme.
- Voice input on Android and iOS: a microphone button in the composer turns speech into text on the phone through the platform speech recogniser (Android `SpeechRecognizer`, iOS Speech framework), reached through the `speech_to_text` package. The transcript fills the input box for review and is never sent on its own. The agent receives the prompt as text and never receives audio. The user picks the recognition language. The microphone permission, a denied permission, offline use and a device with no recogniser are all handled.
- Not in scope for now: text-to-speech. Assistant replies stay text and are not read aloud.
- Not in scope for now: files a sandbox produced. Owner decision 51.5 of 2026-10-03: a later feature lets the owner download them from the mobile app through a download link the agent creates, the same way downloads of `add-file-download` reach him (design, Non-Goals).
- Owner screens that other agent changes, all landing earlier, ask of this app in their required edits. From `add-action-approvals`: an approval card in the conversation for the `approval_required` event with Approve, Deny and a "remember this choice" switch, and a pending approvals screen. From `add-shared-scheduler`: a notification list on `GET /api/v1/notifications` with an unread badge and mark as read. From `add-agent-subagents`: a background runs screen on `/api/v1/runs` with status, live events and cancel. From `add-scheduled-tasks`: a scheduled jobs screen on `/api/v1/scheduled-jobs` with pause, resume, run now and cancel. From `add-self-improvement`: a "What I learned" screen with undo and an unseen badge.
- The stream parser reads the new non-terminal events `run_started`, `subagent_status` and `approval_required`, and skips any event name it does not know instead of failing.
- The app reads `GET /api/v1/modules` (`add-deployment-modules`) and hides the scheduled jobs and "What I learned" screens when their module is off.
- Sign-in with Keycloak (owner decision 65.2 of 2026-10-04): the app signs the user in through the public client `ascend-flutter` of `add-keycloak-login` with the authorization code flow and PKCE, and sends `Authorization: Bearer` on every call and stream. Redirect addresses: `http://127.0.0.1/callback` on desktop (loopback, any port, RFC 8252), `com.lukk.ascend:/callback` on Android and iOS, and the exact hosting address of a web build. The mobile app logs in to Keycloak and gets OAuth tokens, and the backend authenticates every request with those tokens (owner answer 70.2 of 2026-10-04). `add-keycloak-login` (build group 3, position 3) lands earlier and removes `X-User-Id` from the agent, so the app never sends `X-User-Id` and has no built-in password login of its own.
- A desktop tray icon (owner decision 65.18 of 2026-10-04): on Windows, macOS and Linux closing the window hides the app to the tray (the menu bar on macOS), and the tray menu opens or quits it, with `tray_manager` and `window_manager`.
- No push notifications for now. The app refreshes notifications, pending approvals and unseen changes while it is open: on start, on return to the foreground, on pull to refresh, after a stream event that names a run or an approval, and every `ASCEND_OWNER_REFRESH_SECONDS` seconds (a build-time setting, default 60) while in front. Push is recommended as a later change that adds one channel to the notification port of `add-shared-scheduler` (design decision 10).
- State management uses the current Riverpod API (`Notifier`, `AsyncNotifier` and their providers). The legacy `StateNotifierProvider` is not used.
- Backend work this needs, in the agent: a CORS configuration for the Flutter web build with configurable allowed origins, and documentation of how a phone reaches the agent (host address, port 9917 binding).
- A module-level `apps/ascend-chat/AGENTS.md`.

## Capabilities

### New Capabilities
- `flutter-chat/core-chat`: the chat screen powered by `flutter_chat_ui`, the custom `ChatController`, streaming responses, system messages, and the configurable direct connection to the agent.
- `flutter-chat/conversation-management`: conversation list with create, rename, delete, switching, and auto-creation on first prompt.
- `flutter-chat/attachments`: image and document attachments through the multipart fields on the prompt endpoint.
- `flutter-chat/provider-selection`: per-prompt provider and model selection (LM Studio, OpenAI, Gemini, Anthropic, MiniMax).
- `flutter-chat/source-references`: RAG source references with name, type badge and presigned download link, plus tappable citation labels.
- `flutter-chat/theming`: dark-mode-first `ChatTheme` and app-wide Material theme with a light mode.
- `flutter-chat/voice-input`: on-device speech to text on Android and iOS that fills the composer for review, with language selection, microphone permission handling, offline behaviour and a clear state for a device with no recogniser.
- `flutter-chat/action-approvals`: the approval card in the conversation and the pending approvals screen, deciding with the digest of the view on screen and channel `app`.
- `flutter-chat/notifications`: the notification list with unread badge, detail, mark as read and navigation to the notification's subject, refreshed while the app is open.
- `flutter-chat/background-runs`: the background runs list and detail with live status, cancel, and the run status line in the conversation.
- `flutter-chat/scheduled-jobs`: the scheduled jobs list and detail with firing history, pause, resume, run now and cancel.
- `flutter-chat/self-improvement-report`: the "What I learned" screen with the change records, the diff, undo and the unseen badge.
- `flutter-chat/authentication`: sign-in with Keycloak through the authorization code flow with PKCE on every platform, the bearer token on every request, refresh, sign out, and the redirect address of each platform.
- `flutter-chat/desktop-tray`: the tray (menu bar) icon on Windows, macOS and Linux, close hides to the tray, and the tray menu with Open and Quit.
- `flutter-chat/end-to-end-tests`: an e2e suite at `apps/ascend-chat/e2e/` of Flutter integration tests against a running stack for sign-in, chat, attachments, sources and citations, the web build, voice input with a fake recogniser, every owner screen and the desktop tray, plus human-gated specs on real devices for the microphone, phone sign-in and the operating system tray (owner request of 2026-10-04).

### Modified Capabilities
(none)

## Impact

- New module `apps/ascend-chat/` with its own `pubspec.yaml`, `AGENTS.md`, `README.md` and source tree. No Dockerfile, no nginx and no compose service: the web build is static files any host can serve, and the app is not served by the agent.
- Agent changes (small): a CORS configuration class in `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/` with allowed origins from a property, and documentation in `apps/ascend-agent/AGENTS.md` on reaching the agent from a phone. The agent's compose service is `ascend-agent`, port 9917.
- Depends on `POST /api/v1/ai/prompt/stream` and `/api/v1/conversations` from add-chat-streaming-and-conversations, on `downloadUrl` in sources (add-document-management-api), and on the `citations` event (add-passage-level-citations).
- Depends on upgrade-spring-boot-4, which makes every agent error body an RFC 7807 problem detail (`application/problem+json` with `type`, `title`, `status`, `detail`, `instance` and a top-level `code`, owner decision of 2026-10-02). The app parses that body, and the same object in the stream's `error` event, into one typed error (design section 3).
- Identity is the bearer token from Keycloak on every request (owner decision 65.2 and owner answer 70.2 of 2026-10-04). Task group 19 depends on `add-keycloak-login` (build group 3, position 3), which lands earlier, and adds `ASCEND_AUTH_ISSUER` and `ASCEND_AUTH_CLIENT_ID`. The app has no `X-User-Id` header and no `ASCEND_USER_ID` setting. `add-keycloak-login` registers the redirect addresses on the `ascend-flutter` client in its realm export (its task 1.1). Keycloak is a core prerequisite of the stack. Several tenants, brokered corporate sign-in and organizations are company work of `add-auth-and-identity` (build group 5), which this change does not need.
- Desktop builds add `tray_manager` and `window_manager` (task group 20). A Linux build machine needs the GTK 3, X11 and Xi development files.
- Requires a current stable Flutter SDK and Dart 3 on the build machine. `speech_to_text` 7.5.0, the version checked on 2026-10-02, needs Dart 3.12 or newer.
- Voice input adds platform permission entries in the app only: `RECORD_AUDIO` and a `<queries>` entry for `android.speech.RecognitionService` in the Android manifest, and `NSMicrophoneUsageDescription` and `NSSpeechRecognitionUsageDescription` in the iOS `Info.plist`. No agent change, no new endpoint, and no use of ascend-audio-scribe.

- The owner screens depend on agent changes that all land earlier, named here with their place in the owner build order of 2026-10-04: `add-deployment-modules` (group 3, position 6, `GET /api/v1/modules`), `add-shared-scheduler` (group 3, position 7, `/api/v1/notifications`), `add-agent-subagents` (group 4, position 2, `/api/v1/runs` and the `run_started` and `subagent_status` events), `add-action-approvals` (group 4, position 5, `/api/v1/approvals` and the `approval_required` event), `add-scheduled-tasks` (group 4, position 12, `/api/v1/scheduled-jobs`) and `add-self-improvement` (group 4, position 13, `/api/v1/self-improvement/changes`). The staged changes, coding approvals and credential approvals of `add-self-improvement`, `add-coding-agent-delegation` (group 4, position 11) and `add-self-built-integrations` (group 4, position 14) need no app code of their own, because the approval card shows any kind through its preview.
- The seven e2e specs that send a prompt (21.3, 21.5, 21.6, 21.7, 21.8, 21.10 and 21.16) use the scripted model and the fake MCP server of the shared e2e harness of `close-agent-test-gaps` (its design D5 and task group 4) (group 3, position 1). The scripted model and the fake MCP server of that harness start only for deterministic tests, never for AI-run e2e specs (owner answer 70.4 of 2026-10-04).

## Build order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders): build group 4 (personal), position 17, the last personal change. It needs `close-agent-test-gaps` (the shared e2e harness of its design D5 and task group 4, for the scripted specs), `upgrade-spring-boot-4` (the problem detail error body it parses), `add-keycloak-login` (the client `ascend-flutter`, the realm and the bearer token check of the agent), `add-deployment-modules`, `add-shared-scheduler`, `add-document-management-api` and `add-chat-streaming-and-conversations` of build group 3, and `add-agent-subagents`, `add-action-approvals`, `add-scheduled-tasks`, `add-self-improvement` and `add-passage-level-citations` of build group 4. All of them land earlier, so no task group of this change waits for a later change. It depends on no company change of build group 5 (owner rule of 2026-10-04).

## Relevant Skills

- `/flutter-architecture`
- `/flutter-http-and-json`
- `/flutter-routing-and-navigation`
- `/flutter-layout`
- `/flutter-forms`
- `/flutter-testing-apps`
- `/keycloak-auth-services` (authorization code flow with PKCE, redirect addresses)
- `/flutter-native-interop` (tray icon and window close on desktop)
- `/flutter-accessibility`
- `/flutter-environment-setup-windows`, `/flutter-environment-setup-linux`, `/flutter-environment-setup-macos`
- `/design-system`
- `/springboot-patterns` (CORS configuration in the agent)
- `/security-review` (CORS origins)
- `/tdd-workflow`
