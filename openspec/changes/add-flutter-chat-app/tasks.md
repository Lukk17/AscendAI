## 1. Project Scaffold

- [ ] 1.1 Create the `AscendChat/` directory at the repo root and run `flutter create` with project name `ascend_chat`, targeting Android, iOS, web, Windows, macOS, and Linux
- [ ] 1.2 Add `flutter_chat_ui: ^2.11.1`, `flutter_chat_core: ^2.9.0`, `flutter_riverpod: ^2.6.1`, `go_router: ^14.8.1`, `http: ^1.3.0`, `file_picker: ^8.3.7`, `shared_preferences: ^2.5.3`, and `url_launcher: ^6.3.1` to `pubspec.yaml` with pinned caret versions
- [ ] 1.3 Create the `AscendChat/AGENTS.md` file with module-level agent instructions referencing Flutter skills and the ascend-ai-agent API
- [ ] 1.4 Set up the source directory structure: `lib/src/api/`, `lib/src/chat/`, `lib/src/conversations/`, `lib/src/config/`, `lib/src/theme/`, `lib/src/widgets/`
- [ ] 1.5 Verify the project compiles with `flutter build web` and `flutter analyze` passes with zero issues

## 2. Configuration and API Client

- [ ] 2.1 Create `AppConfig` class in `lib/src/config/` that reads the ascend-ai-agent base URL from environment variable `ASCEND_API_URL` (default `http://localhost:9917`) and the default user ID from `ASCEND_USER_ID` (default `user1`)
- [ ] 2.2 Implement `AscendApiClient` in `lib/src/api/` with methods for: `sendPromptStream()` returning a `Stream` of typed SSE events, `listConversations()`, `createConversation()`, `getConversationMessages()`, `renameConversation()`, `deleteConversation()`
- [ ] 2.3 Implement the platform-conditional SSE parser that reads the chunked HTTP response body line-by-line and emits typed `SseEvent` objects (`DeltaEvent`, `SourcesEvent`, `DoneEvent`, `ErrorEvent`)
- [ ] 2.4 Implement the web-specific SSE client using `dart:html` `EventSource` behind a conditional import
- [ ] 2.5 Create Riverpod providers for `AppConfig` and `AscendApiClient` in `lib/src/config/providers.dart`

## 3. Theme and App Shell

- [ ] 3.1 Create `AscendDarkTheme` and `AscendLightTheme` Material `ThemeData` objects in `lib/src/theme/` with brand colors
- [ ] 3.2 Create `AscendChatTheme` extending `flutter_chat_core` `ChatTheme` for dark and light modes, setting bubble colors, text styles, composer background, and surface colors
- [ ] 3.3 Implement `ThemeNotifier` with Riverpod that reads/writes the theme preference (dark/light/auto) using `shared_preferences`
- [ ] 3.4 Create the `AscendChatApp` root widget in `lib/main.dart` using `ProviderScope` and `MaterialApp.router` with `go_router` configuration and dynamic theme switching
- [ ] 3.5 Configure `go_router` with two routes: `/conversations` (conversation list) and `/conversations/:id` (chat screen), with `/conversations` as the initial route

## 4. Conversation Management Screen

- [ ] 4.1 Create `ConversationListScreen` widget in `lib/src/conversations/` that fetches and displays conversations in a `ListView` sorted by `updatedAt` descending
- [ ] 4.2 Implement paginated loading: fetch next page when the user scrolls to the bottom of the list
- [ ] 4.3 Implement empty state UI with a message and a prominent new-conversation button
- [ ] 4.4 Implement the new-conversation button in the app bar that navigates to an empty chat screen (no `conversationId`)
- [ ] 4.5 Implement long-press context menu on each conversation item with rename and delete actions
- [ ] 4.6 Implement the rename flow: inline text field, validation (non-blank, 255-char max), `PATCH` request, and optimistic UI update
- [ ] 4.7 Implement the delete flow: confirmation dialog, `DELETE` request, animated removal from the list
- [ ] 4.8 Create a Riverpod `StateNotifierProvider` for conversation list state (loading, data, error, pagination)

## 5. Core Chat Screen and ChatController

- [ ] 5.1 Create `AscendChatController` implementing the `flutter_chat_core` `ChatController` interface, holding an in-memory message list and emitting `ChatOperation` events
- [ ] 5.2 Implement `AscendChatController.loadInitialMessages()` that fetches the most recent page of messages from `GET /api/v1/conversations/{id}/messages` and populates the list
- [ ] 5.3 Implement pagination in the controller: expose an `onEndReached` callback that fetches the next page of older messages and prepends them
- [ ] 5.4 Create `ChatScreen` widget in `lib/src/chat/` that wires the `Chat` widget from `flutter_chat_ui` with the `AscendChatController`, `currentUserId`, `resolveUser`, and `onMessageSend`
- [ ] 5.5 Use `ChatAnimatedListReversed` via the `builders` parameter so newest messages appear at the bottom
- [ ] 5.6 Implement the `onMessageSend` handler: insert user message into controller, call `sendPromptStream()`, consume the SSE stream, progressively insert/update the assistant message with each delta, finalize on `done`, handle `error`
- [ ] 5.7 Implement auto-conversation-creation: when `conversationId` is null and the first prompt is sent, capture the `conversationId` from the `done` event and persist it for subsequent messages
- [ ] 5.8 Implement pre-stream 4xx error handling: catch non-SSE responses (400, 404, 415) and display them as dismissible snackbar notifications
- [ ] 5.9 Implement controller disposal: cancel active SSE connections and release resources when navigating away

## 6. Attachments

- [ ] 6.1 Add an attachment button to the chat composer area (via the `flutter_chat_ui` `Builders.composerBuilder` or a custom wrapper)
- [ ] 6.2 Implement file picker integration using `file_picker` for both images (JPEG, PNG, GIF, WEBP) and documents (PDF, DOCX, PPTX, HTML, TXT, MD)
- [ ] 6.3 Display a preview widget in the composer: image thumbnail for images, file name and size chip for documents
- [ ] 6.4 Enforce single-attachment constraint: selecting a new file replaces the existing attachment
- [ ] 6.5 Update `sendPromptStream()` to include the attachment as a multipart `image` or `document` part based on file type
- [ ] 6.6 Display an indeterminate progress indicator in the composer after sending until the first SSE event arrives
- [ ] 6.7 Handle `415 Unsupported Media Type` error with a notification explaining the model lacks vision support

## 7. Provider and Model Selection

- [ ] 7.1 Create a `PromptSettingsNotifier` with Riverpod that holds the selected provider, model override, embedding provider, and attach-sources toggle
- [ ] 7.2 Add a settings panel accessible from the chat screen app bar (bottom sheet or dropdown) with provider selector, model text field, embedding provider selector, and attach-sources toggle
- [ ] 7.3 Wire the selected values into the `sendPromptStream()` call as additional form fields
- [ ] 7.4 Persist provider and model selection within the Riverpod scope (session-only, not across app restarts)

## 8. Source References

- [ ] 8.1 Create a `SourceReferencesWidget` that renders a collapsible list of source documents below an assistant message bubble
- [ ] 8.2 Display each source with document name and a MIME type badge (PDF, DOCX, MD, etc.)
- [ ] 8.3 Implement tap-to-open using `url_launcher` to open the presigned `downloadUrl` or `contentPath`
- [ ] 8.4 Wire the `sources` SSE event data into the assistant message metadata so the widget has access to it
- [ ] 8.5 Conditionally render the widget only when sources are present in the message

## 9. Containerization and Compose Integration

- [ ] 9.1 Create a multi-stage `AscendChat/Dockerfile`: first stage uses the pinned Flutter SDK image to run `flutter build web --release`, second stage uses a pinned `nginx:alpine` image to serve the build output
- [ ] 9.2 Create `AscendChat/nginx.conf` with a single-page-app fallback (try_files to `index.html`) and API reverse proxy from `/api/` to the ascend-ai-agent container
- [ ] 9.3 Add the `ascend-chat` service to `docker-compose.yaml` with port mapping (default 3000), dependency on ascend-ai-agent, and a health check
- [ ] 9.4 Verify the containerized build runs end-to-end: `docker compose build ascend-chat` succeeds and the web app loads at `http://localhost:3000`

## 10. Testing and Verification

- [ ] 10.1 Write widget tests for `ConversationListScreen`: empty state, list rendering, rename flow, delete flow
- [ ] 10.2 Write widget tests for `ChatScreen`: message sending, streaming response display, error handling
- [ ] 10.3 Write unit tests for `AscendChatController`: initial load, insert message, pagination, disposal
- [ ] 10.4 Write unit tests for the SSE parser: well-formed events, multi-line data, error events, connection drops
- [ ] 10.5 Write unit tests for `AscendApiClient` with mocked HTTP responses
- [ ] 10.6 Run `flutter test` and verify all tests pass
- [ ] 10.7 Run `flutter analyze` and verify zero issues
- [ ] 10.8 Update the root `README.md` monorepo structure table and `docker-compose.yaml` services table with the new `AscendChat` module
