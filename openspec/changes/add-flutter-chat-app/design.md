## Context

AscendAI is a multi-module monorepo with Java and Python backend services but no user-facing frontend. The ascend-ai-agent exposes a REST API on port 9917 for AI prompts (with multipart file support), a specced server-sent events streaming endpoint, and a conversation management REST API. See proposal.md for the full motivation. The `flutter_chat_ui` library (v2.11.1) provides the chat widget, `flutter_chat_core` provides message models and the `ChatController` interface.

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

The Flutter module lives at `AscendChat/` in the monorepo root, following the existing flat layout (`apps/ascend-agent/`, `apps/ascend-audio-scribe/`, `apps/ascend-web-hunter/`, etc.). The `pubspec.yaml` project name is `ascend_chat`.

**Alternatives considered:**
- Nested under `apps/ascend-agent/frontend/`: rejected because ascend-ai-agent is a Gradle project and mixing Flutter build artifacts into it creates tooling conflicts.
- Separate repository: rejected because the OpenSpec workflow and agent instructions rely on monorepo-local changes.

### 2. State management with Riverpod

The app uses `flutter_riverpod` for dependency injection and state management. Providers expose the API client, the current conversation state, the theme mode, and provider/model selection. Riverpod was chosen because it supports code generation for compile-time safety, handles async state natively, and integrates cleanly with the `ChatController` lifecycle.

**Alternatives considered:**
- `provider` (already a dependency of `flutter_chat_ui`): simpler but lacks async state primitives and compile-time safety.
- `bloc`: heavier ceremony for an app with relatively simple state transitions.

### 3. HTTP and server-sent events client

The app uses the `http` package for REST calls and `dart:io`/`dart:html` `HttpClient` (via a platform-conditional wrapper) for server-sent events consumption. The server-sent events stream is consumed by reading the chunked response body line-by-line, parsing `event:` and `data:` fields, and dispatching typed events to the `ChatController`.

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

### 8. Containerization

The web build is containerized with a multi-stage Dockerfile: Flutter SDK stage builds the web app, then an nginx stage serves the static assets. The container is added to `compose.yaml` as `ascend-chat` on a configurable port (default 3000).

**Alternatives considered:**
- No containerization: inconsistent with the rest of the monorepo where every module has a Dockerfile.

## Risks / Trade-offs

- **[Backend dependency]** The Flutter app depends on the streaming and conversation endpoints from the `add-chat-streaming-and-conversations` change, which may not be implemented yet. Mitigation: the API client layer is behind an interface, and mock implementations can be used during frontend development.
- **[SSE on web]** Server-sent events consumption via `dart:html` `EventSource` has different semantics than the `dart:io` `HttpClient` approach. Mitigation: a platform-conditional SSE client that uses `EventSource` on web and raw HTTP streaming on native platforms.
- **[No offline mode]** If the backend is unreachable, the app shows errors instead of cached content. This is acceptable for a first iteration since the app is designed for use on the same network as the backend.
- **[flutter_chat_ui version lock]** Pinning to `^2.11.1` means the app inherits any breaking changes in the 2.x line. Mitigation: version is declared in `pubspec.yaml` with a caret constraint, allowing patch updates but not major bumps.

## Open Questions

- What port should the containerized web build be exposed on? Defaulting to 3000 until confirmed.
- Should the app support system tray or menu bar integration on desktop platforms? Deferring to a follow-up change.
