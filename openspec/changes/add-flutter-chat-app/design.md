## Context

AscendAI is a multi-module monorepo with Java and Python backend services but no user-facing frontend. The ascend-ai-agent exposes a REST API on port 9917 for AI prompts (with multipart file support), a specced server-sent events streaming endpoint, and a conversation management REST API. See proposal.md for the full motivation. The `flutter_chat_ui` library provides the chat widget, `flutter_chat_core` provides message models and the `ChatController` interface.

## Goals / Non-Goals

**Goals:**
- Deliver a cross-platform chat client (Android, iOS, web, Windows, macOS, Linux) from a single Flutter codebase.
- Use `flutter_chat_ui` as the presentation layer, with a custom `ChatController` that bridges the ascend-ai-agent conversation API.
- Support real-time token streaming via server-sent events for assistant responses.
- Let the user manage conversations (list, create, rename, delete) and attach files to prompts.
- Provide a dark-mode-first theme with light-mode toggle.

**Non-Goals:**
- Push notifications or background sync (requires backend WebSocket or Firebase, out of scope for the first iteration).
- User authentication and login (the backend currently uses a simple `X-User-Id` header, and this change keeps that pattern).
- Offline-first or local database persistence of messages (messages are fetched from the API; the `ChatController` is API-backed, not Hive-backed).
- Knowledge base document management UI (specced separately in `add-document-management-api`).
- Audio transcription integration or MCP tool invocation UI.

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

The app uses the `http` package for REST calls. The streaming endpoint is a multipart `POST`, so `EventSource` (GET only, no body) cannot be used. One platform-independent SSE parser turns a `Stream<List<int>>` into typed events (`delta`, `citations`, `sources`, `done`, `error`) by reading `event:` and `data:` lines. Two byte sources feed it behind a conditional import: on native platforms `http.Client.send` with a `MultipartRequest` and its `StreamedResponse.stream`, and on web `fetch` from `package:web` reading `response.body` through a `ReadableStreamDefaultReader`. `dart:html` is not used.

**Alternatives considered:**
- `dio`: feature-rich but adds a large dependency tree; the `http` package covers all needed functionality.
- `eventsource` pub package: abandoned/unmaintained; manual SSE parsing is straightforward (under 100 lines) and avoids a dependency risk.

### 4. ChatController implementation

A custom `AscendChatController` implements the `flutter_chat_core` `ChatController` interface. It holds an in-memory list of messages loaded from the API and emits `ChatOperation` events. On `insertMessage`, it sends the prompt to the streaming endpoint and handles the response. The controller does not write directly to a local database; all persistence is via the ascend-ai-agent conversation API.

**Alternatives considered:**
- `InMemoryChatController` with external API calls: the library's built-in controller does not emit the right events when messages arrive asynchronously from server-sent events, so a custom implementation is necessary.
- Hive-backed `PersistedChatController` from the Flyer Chat examples: adds local persistence complexity without benefit since the backend is the source of truth.

### 5. Navigation

The app uses `go_router` for declarative, URL-based navigation. Two routes: `/conversations` (list) and `/conversations/:id` (chat). Deep linking is supported on web and mobile.

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

The web build runs on a different origin than the agent, so the agent gains a CORS configuration (`config/CorsConfig.java`) whose allowed origins come from `app.cors.allowed-origins` (empty by default, so nothing changes until an operator sets it). It allows `GET`, `POST`, `PATCH`, `DELETE`, the `Content-Type` and `X-User-Id` headers, and exposes `Location`. Native apps do not need CORS.

A phone reaches the agent at `http://<host LAN address>:9917`. The agent's compose service `ascend-agent` must publish 9917 on all interfaces (not only 127.0.0.1) for that, and the host firewall must allow it. Android blocks clear-text HTTP by default, so the Android debug build allows clear-text traffic through a debug-only network security config, and iOS gets an `NSAllowsLocalNetworking` entry. Both are documented in `apps/ascend-chat/README.md`.

**Alternatives considered:**
- Serve the web build from nginx with an `/api` proxy: rejected by the owner, it ties the app to one deployment and does not help a phone.
- Serve it from the agent: rejected by the owner, the app must be separate.

## Risks / Trade-offs

- **[Backend dependency]** The Flutter app depends on the streaming and conversation endpoints from the `add-chat-streaming-and-conversations` change, which may not be implemented yet. Mitigation: the API client layer is behind an interface, and mock implementations can be used during frontend development.
- **[SSE on web]** `EventSource` cannot send a POST body. Mitigation: fetch-based streaming through `package:web` on web, `http` streaming on native, one shared parser.
- **[Open CORS]** A wide allowed-origins list lets any site call the agent from a browser. Mitigation: empty by default, explicit origins only, never `*` together with credentials.
- **[No offline mode]** If the backend is unreachable, the app shows errors instead of cached content. This is acceptable for a first iteration since the app is designed for use on the same network as the backend.
- **[Stale pins]** Versions in this plan go stale. Mitigation: task 1.2 re-checks every dependency on pub.dev at implementation time and pins the current stable release.

## Open Questions

- Should the app support system tray or menu bar integration on desktop platforms? Deferred to a later change.
