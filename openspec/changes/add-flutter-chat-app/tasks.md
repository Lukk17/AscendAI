## 1. Project Scaffold

- [ ] 1.1 Create `apps/ascend-chat/` with `flutter create --project-name ascend_chat --platforms android,ios,web,windows,macos,linux apps/ascend-chat`. Verify: `flutter analyze` in `apps/ascend-chat` reports no issues on the generated project.
- [ ] 1.2 Add `flutter_chat_ui`, `flutter_chat_core`, `flutter_riverpod`, `go_router`, `http`, `web`, `file_picker`, `shared_preferences` and `url_launcher` to `apps/ascend-chat/pubspec.yaml`. Look up each package on pub.dev at implementation time and pin a caret on its current stable version. Do not copy versions from this plan. Verify: `flutter pub outdated` shows every direct dependency at its latest resolvable version, and `flutter pub get` succeeds.
- [ ] 1.3 Create `apps/ascend-chat/AGENTS.md` (build, test and run commands, `--dart-define` keys, the Flutter skills to load) and `apps/ascend-chat/README.md` (how to run on desktop, web and a phone). Verify: both files name `ASCEND_API_URL` and `ASCEND_USER_ID`.
- [ ] 1.4 Create `lib/src/api/`, `lib/src/chat/`, `lib/src/conversations/`, `lib/src/config/`, `lib/src/theme/`, `lib/src/widgets/`. Verify: `flutter build web` succeeds.

## 2. Configuration and API Client

- [ ] 2.1 Create `lib/src/config/app_config.dart` reading `ASCEND_API_URL` (default `http://localhost:9917`) and `ASCEND_USER_ID` (default `user1`) with `String.fromEnvironment`. Verify: a unit test asserts the defaults, and `flutter run --dart-define=ASCEND_API_URL=http://10.0.0.5:9917` makes the client call that host (checked in task 2.6 with a fake).
- [ ] 2.2 Implement `lib/src/api/ascend_api_client.dart` with `sendPromptStream()` returning `Stream<SseEvent>`, `listConversations()`, `createConversation()`, `getConversationMessages()`, `renameConversation()`, `deleteConversation()`. Every request sends `X-User-Id`. Verify: task 2.6 passes.
- [ ] 2.3 Implement `lib/src/api/sse_parser.dart`: a pure function from `Stream<List<int>>` to typed `SseEvent` (`DeltaEvent`, `CitationsEvent`, `SourcesEvent`, `DoneEvent`, `ErrorEvent`), handling multi-line `data:` and events split across chunks. `SourcesEvent` entries carry `downloadUrl`, `expiresAt`, `documentId`, `contentPath`, `name`, `mimeType`. Verify: task 10.4 passes.
- [ ] 2.4 Implement the byte source behind a conditional import: `lib/src/api/stream_source_io.dart` sends a `MultipartRequest` with `http.Client.send` and returns `StreamedResponse.stream`, and `lib/src/api/stream_source_web.dart` uses `fetch` from `package:web` with a `FormData` body and reads `response.body` with a `ReadableStreamDefaultReader`. No `EventSource`, no `dart:html`. Verify: `grep -rn "dart:html\|EventSource" apps/ascend-chat/lib` returns nothing, and the web build streams deltas in task 11.2.
- [ ] 2.5 Create Riverpod providers for `AppConfig` and `AscendApiClient` in `lib/src/config/providers.dart` using plain `Provider`. Verify: `grep -rn "StateNotifierProvider\|ChangeNotifierProvider" apps/ascend-chat/lib` returns nothing.
- [ ] 2.6 Unit tests `test/api/ascend_api_client_test.dart` with `MockClient` from `package:http/testing.dart`: correct URLs under the configured base, `X-User-Id` sent, 4xx mapped to typed errors. Verify: `flutter test test/api` is green.

## 3. Theme and App Shell

- [ ] 3.1 Create dark and light Material `ThemeData` in `lib/src/theme/app_theme.dart`. Verify: a widget test pumps the app in each mode without errors.
- [ ] 3.2 Create the dark and light `ChatTheme` for `flutter_chat_ui` in `lib/src/theme/chat_theme.dart` (bubble colors, text styles, composer). Verify: a golden or widget test renders one message in each mode.
- [ ] 3.3 Implement `ThemeModeNotifier extends Notifier<ThemeMode>` with a `NotifierProvider`, reading and writing the choice (dark, light, auto) through `shared_preferences`. Verify: a unit test with `SharedPreferences.setMockInitialValues` restores the stored mode.
- [ ] 3.4 Create the root widget in `lib/main.dart` with `ProviderScope` and `MaterialApp.router`. Verify: `flutter run -d chrome` opens the conversation list.
- [ ] 3.5 Configure `go_router` in `lib/src/router.dart` with `/conversations` (initial) and `/conversations/:id`. Verify: a widget test navigates to `/conversations/abc` and finds the chat screen.

## 4. Conversation Management Screen

- [ ] 4.1 Create `ConversationListScreen` in `lib/src/conversations/` listing conversations by `updatedAt` descending. Verify: task 10.1 covers list rendering.
- [ ] 4.2 Load the next page when the user scrolls to the end. Verify: a widget test with a fake client of 25 items loads the second page after a scroll.
- [ ] 4.3 Empty state with a message and a new-conversation button. Verify: task 10.1 covers the empty state.
- [ ] 4.4 New-conversation button in the app bar opens an empty chat screen without a `conversationId`. Verify: a widget test taps it and finds the chat screen.
- [ ] 4.5 Long-press menu on each item with rename and delete. Verify: task 10.1.
- [ ] 4.6 Rename: text field, validation (non-blank, at most 255 characters), `PATCH`, optimistic update rolled back on error. Verify: task 10.1 covers success and a failed `PATCH`.
- [ ] 4.7 Delete: confirmation dialog, `DELETE`, removal from the list. Verify: task 10.1.
- [ ] 4.8 Hold the list state in `ConversationListNotifier extends AsyncNotifier` with an `AsyncNotifierProvider` (loading, data, error, next page). Verify: a unit test with `ProviderContainer` covers load, error and next page.

## 5. Core Chat Screen and ChatController

- [ ] 5.1 Create `AscendChatController` implementing the `flutter_chat_core` `ChatController` interface with an in-memory list. Verify: task 10.3.
- [ ] 5.2 `loadInitialMessages()` fetches the latest page from `GET /api/v1/conversations/{id}/messages`. Verify: task 10.3.
- [ ] 5.3 Older pages load when the list reaches its end and are prepended. Verify: task 10.3.
- [ ] 5.4 Create `ChatScreen` in `lib/src/chat/` wiring the `Chat` widget with the controller, `currentUserId`, `resolveUser` and `onMessageSend`. Verify: task 10.2.
- [ ] 5.5 Use the reversed animated list so the newest messages are at the bottom. Verify: task 10.2 asserts the last message is nearest the composer.
- [ ] 5.6 `onMessageSend`: insert the user message, call `sendPromptStream()`, grow the assistant message on each `delta`, attach `citations` and `sources`, finish on `done`, show `error` as a system message. Verify: task 10.2 with a fake stream.
- [ ] 5.7 Without a `conversationId`, take it from the `done` event and use it for later messages. Verify: a controller test asserts the second send carries the id from the first `done`.
- [ ] 5.8 Pre-stream 4xx (400, 404, 415) shows a dismissible snackbar. Verify: task 10.2.
- [ ] 5.9 Cancel the active stream when the screen is disposed. Verify: task 10.3 asserts the stream subscription is cancelled.

## 6. Attachments

- [ ] 6.1 Attachment button in the composer. Verify: a widget test finds it.
- [ ] 6.2 `file_picker` for images (JPEG, PNG, GIF, WEBP) and documents (PDF, DOCX, PPTX, HTML, TXT, MD), reading bytes so it works on web. Verify: a unit test of the extension filter.
- [ ] 6.3 Preview in the composer: thumbnail for an image, name and size for a document. Verify: a widget test for each kind.
- [ ] 6.4 One attachment at a time, a new pick replaces the old one. Verify: a unit test of the composer state.
- [ ] 6.5 `sendPromptStream()` adds the file as the `image` or `document` multipart part. Verify: task 2.6 asserts the part name for each kind.
- [ ] 6.6 Progress indicator from send until the first event. Verify: a widget test with a delayed fake stream.
- [ ] 6.7 415 shows a message that the model has no vision support. Verify: a widget test.

## 7. Provider and Model Selection

- [ ] 7.1 `PromptSettingsNotifier extends Notifier<PromptSettings>` with a `NotifierProvider` holding provider, model override, embedding provider and attach-sources toggle. Verify: a unit test with `ProviderContainer`.
- [ ] 7.2 Settings bottom sheet from the chat app bar. Verify: a widget test opens it and changes the provider.
- [ ] 7.3 Send the chosen values as form fields. Verify: task 2.6 asserts the fields.
- [ ] 7.4 Settings live for the session only. Verify: a unit test shows a new `ProviderContainer` starts with defaults.

## 8. Source References and Citations

- [ ] 8.1 `SourceReferencesWidget` renders a collapsible source list under an assistant message. Verify: a widget test.
- [ ] 8.2 Each source shows its name and a MIME type badge. Verify: a widget test with PDF and MD sources.
- [ ] 8.3 Tapping a source opens its presigned `downloadUrl` with `url_launcher` (`launchUrl`). Verify: a widget test with a fake `UrlLauncherPlatform` asserts the URL.
- [ ] 8.4 `CitationLabels` renders each citation label (for example `[S1]`) as a tappable chip. Tapping shows the document name and the page or chunk position, and offers the matching source's `downloadUrl`. Verify: a widget test taps `[S1]` and finds the name and page.
- [ ] 8.5 Render either widget only when its data is present. Verify: a widget test with no sources and no citations finds neither.

## 9. Agent support for a separate client

- [ ] 9.1 Add `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/CorsConfig.java` with allowed origins bound from `app.cors.allowed-origins` (list, empty default) through a `@ConfigurationProperties` class, allowing `GET`, `POST`, `PATCH`, `DELETE`, `OPTIONS`, the headers `Content-Type` and `X-User-Id`, exposing `Location`, and wired into `SecurityConfig` with `http.cors(...)`. Verify: a `@WebMvcTest` sends a preflight from an allowed origin (200 with `Access-Control-Allow-Origin`) and from another origin (no allow header).
- [ ] 9.2 Add `app.cors.allowed-origins` to `apps/ascend-agent/src/main/resources/application.yaml` and to the root `.env.example` as a commented example. Verify: the agent starts with the property empty and with one origin set.
- [ ] 9.3 Document phone access in `apps/ascend-agent/AGENTS.md` and `apps/ascend-chat/README.md`: the agent must be published on `0.0.0.0:9917` by the `ascend-agent` compose service, find the host LAN address, allow port 9917 in the host firewall, build with `--dart-define=ASCEND_API_URL=http://<host>:9917`, Android debug clear-text config, iOS `NSAllowsLocalNetworking`. Verify: the docs name each step and the compose port mapping of `ascend-agent` is checked against `compose.yaml`.
- [ ] 9.4 Add the Android debug-only network security config in `apps/ascend-chat/android/app/src/debug/` and the iOS local networking key in `apps/ascend-chat/ios/Runner/Info.plist`. Verify: a debug build on an Android phone reaches `http://<host>:9917`.

## 10. Testing

- [ ] 10.1 Widget tests for `ConversationListScreen`: empty state, list, rename, delete. Verify: green.
- [ ] 10.2 Widget tests for `ChatScreen`: sending, streamed display, citations, errors. Verify: green.
- [ ] 10.3 Unit tests for `AscendChatController`: initial load, insert, paging, disposal. Verify: green.
- [ ] 10.4 Unit tests for the SSE parser: each event type, multi-line data, an event split across chunks, a dropped connection. Verify: green.
- [ ] 10.5 Run `flutter test` in `apps/ascend-chat`. Verify: all green.
- [ ] 10.6 Run `flutter analyze` in `apps/ascend-chat`. Verify: no issues.

## 11. End-to-end and documentation

- [ ] 11.1 Run the app on Windows (or Linux or macOS) against a local agent and send a streamed prompt with `attachSources=true`. Verify: tokens appear one by one, citations and sources render, a source opens.
- [ ] 11.2 Build the web app with `flutter build web --dart-define=ASCEND_API_URL=http://localhost:9917`, serve it from another port, and set that origin in `app.cors.allowed-origins`. Verify: the browser network panel shows one streamed `POST` to `/api/v1/ai/prompt/stream` and no CORS error.
- [ ] 11.3 Install the debug build on a phone on the same network. Verify: listing conversations and a streamed prompt work against `http://<host LAN address>:9917`.
- [ ] 11.4 Update the root `README.md` module table with `apps/ascend-chat`. Verify: the table lists the module and links its README.
