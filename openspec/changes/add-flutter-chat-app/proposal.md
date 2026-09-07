## Why

AscendAI has no user-facing frontend. Every interaction with the platform goes through raw HTTP requests or API clients. A cross-platform chat application built with Flutter would give users a native, polished interface on Android, iOS, Windows, macOS, Linux, and web, all from a single codebase. The [`flutter_chat_ui` library](https://github.com/flyerhq/flutter_chat_ui) (version 2.11.1, Apache 2.0, 1600+ pub likes, published by flyer.chat) provides a production-grade, backend-agnostic chat widget with animated message lists, customizable theming, and support for text, image, file, and system messages, which maps directly onto the ascend-ai-agent prompt and conversation API.

## What Changes

- Add a new `AscendChat` Flutter module at the repository root, alongside the existing backend modules.
- Integrate `flutter_chat_ui` (^2.11.1) and `flutter_chat_core` (^2.9.0) as the chat interface foundation.
- Implement an API client layer that connects to the ascend-ai-agent REST endpoints (`POST /api/v1/ai/prompt`, `POST /api/v1/ai/prompt/stream` via server-sent events, and the `/api/v1/conversations` family).
- Build a custom `ChatController` backed by the conversation API for persistent message history across sessions.
- Support server-sent events streaming so assistant responses appear token-by-token in real time.
- Provide a conversation list screen (create, rename, delete conversations) and a chat screen per conversation.
- Support AI provider and model selection per prompt.
- Support image and document attachment uploads via multipart form data.
- Display RAG source document references returned by the assistant.
- Apply a dark-mode-first custom theme consistent with the AscendAI brand.
- Wire the module into `docker-compose.yaml` for optional containerized deployment behind nginx.
- Add a module-level `AGENTS.md` to the new module for agent instructions.

## Capabilities

### New Capabilities
- `flutter-chat/core-chat`: The primary chat screen powered by `flutter_chat_ui`, including the `Chat` widget integration, custom `ChatController` backed by ascend-ai-agent conversations API, real-time server-sent events streaming for assistant responses, message sending with text, and display of system messages.
- `flutter-chat/conversation-management`: Conversation list screen with create, rename, delete operations, conversation switching, and auto-creation on first prompt.
- `flutter-chat/attachments`: Image and document file attachment support via the multipart upload fields on the prompt endpoint, including file picker integration and upload progress indication.
- `flutter-chat/provider-selection`: Per-prompt AI provider and model selection UI, allowing the user to pick from configured providers (LM Studio, OpenAI, Gemini, Anthropic, MiniMax) and override the model.
- `flutter-chat/source-references`: Display of RAG source document references returned in prompt responses, with document name, type badge, and presigned download link.
- `flutter-chat/theming`: Dark-mode-first custom `ChatTheme` and app-wide Material theme aligned with the AscendAI brand, with light-mode support via dynamic theming.

### Modified Capabilities
(none)

## Impact

- New top-level module `AscendChat/` with its own `pubspec.yaml`, `AGENTS.md`, `Dockerfile`, and source tree.
- Depends on the ascend-ai-agent HTTP API (port 9917), specifically the existing `POST /api/v1/ai/prompt` and the specced streaming and conversation endpoints from the `add-chat-streaming-and-conversations` change.
- Requires Flutter SDK 3.x and Dart 3.x on the build machine.
- Adds a new service entry to `docker-compose.yaml` for the containerized web build.
- No changes to any existing backend module code.
