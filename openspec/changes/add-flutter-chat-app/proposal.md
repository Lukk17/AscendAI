## Why

AscendAI has no user-facing frontend. Every interaction with the platform goes through raw HTTP requests or API clients. A cross-platform chat application built with Flutter gives users one interface on Android, iOS, Windows, macOS, Linux and web from a single codebase. The `flutter_chat_ui` library (Apache 2.0, published by flyer.chat) provides a backend-agnostic chat widget with an animated message list, theming, and text, image, file and system messages, which maps directly onto the ascend-ai-agent prompt and conversation API.

The owner's requirement (2026-10-01): the app must be separate and must be able to connect even from a phone. So it is a standalone client that talks to the agent's API directly at a configurable address. It is not served by the agent and not placed behind nginx.

## What Changes

- Add a standalone Flutter client at `apps/ascend-chat/` (pubspec name `ascend_chat`).
- The agent base URL is set at build time with `--dart-define=ASCEND_API_URL=<url>` (default `http://localhost:9917` for local development). A phone on the same network uses the agent host's LAN address, for example `http://192.168.1.20:9917`, and a remote deployment uses its public address.
- Use `flutter_chat_ui` and `flutter_chat_core` for the chat interface. Every dependency version is re-checked against pub.dev at implementation time and pinned to the current stable release then.
- An API client for `POST /api/v1/ai/prompt/stream` (server-sent events), the `/api/v1/conversations` family, and multipart attachments. On native platforms streaming reads the chunked response with `package:http`. On web it uses fetch-based streaming of the POST response body through `package:web` (not `EventSource`, which cannot send a POST body, and not `dart:html`, which is deprecated).
- A custom `ChatController` backed by the conversation API.
- A conversation list screen (create, rename, delete) and a chat screen per conversation.
- Per-prompt AI provider and model selection.
- RAG sources open their presigned `downloadUrl`. Citations from add-passage-level-citations show as tappable labels.
- A dark-mode-first theme.
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

### Modified Capabilities
(none)

## Impact

- New module `apps/ascend-chat/` with its own `pubspec.yaml`, `AGENTS.md`, `README.md` and source tree. No Dockerfile, no nginx and no compose service: the web build is static files any host can serve, and the app is not served by the agent.
- Agent changes (small): a CORS configuration class in `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/` with allowed origins from a property, and documentation in `apps/ascend-agent/AGENTS.md` on reaching the agent from a phone. The agent's compose service is `ascend-agent`, port 9917.
- Depends on `POST /api/v1/ai/prompt/stream` and `/api/v1/conversations` from add-chat-streaming-and-conversations, on `downloadUrl` in sources (add-document-management-api), and on the `citations` event (add-passage-level-citations).
- Identity stays the `X-User-Id` header until group C adds authentication. The app sends a configurable user id (`--dart-define=ASCEND_USER_ID`).
- Requires a current stable Flutter SDK and Dart 3 on the build machine.

## Build order

Last in group D: add-document-management-api, then add-chat-streaming-and-conversations, then add-passage-level-citations, then this change.

## Relevant Skills

- `/flutter-architecture`
- `/flutter-http-and-json`
- `/flutter-routing-and-navigation`
- `/flutter-layout`
- `/flutter-forms`
- `/flutter-testing-apps`
- `/flutter-accessibility`
- `/flutter-environment-setup-windows`, `/flutter-environment-setup-linux`, `/flutter-environment-setup-macos`
- `/design-system`
- `/springboot-patterns` (CORS configuration in the agent)
- `/security-review` (CORS origins)
- `/tdd-workflow`
