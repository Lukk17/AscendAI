## Purpose

Provides the conversation list screen where users browse, create, rename, and delete conversations, and switch between them to continue chatting.

## ADDED Requirements

### Requirement: Conversation list displays all user conversations
The app SHALL display a scrollable list of the current user's conversations, sorted by most recently updated first.

#### Scenario: User opens the app
- **WHEN** the user launches the app or navigates to the conversation list
- **THEN** the app SHALL fetch conversations from `GET /api/v1/conversations` and display each with its title and last-updated timestamp

#### Scenario: Empty state
- **WHEN** the user has no conversations
- **THEN** the app SHALL display an empty state with a prompt to start a new conversation

#### Scenario: Paginated loading
- **WHEN** the user scrolls to the end of the conversation list
- **THEN** the app SHALL load the next page of conversations and append them

### Requirement: User can create a new conversation
The app SHALL allow the user to start a new conversation.

#### Scenario: Explicit creation
- **WHEN** the user taps the new conversation button
- **THEN** the app SHALL navigate to an empty chat screen where the first prompt auto-creates the conversation via the API

#### Scenario: Auto-creation on first prompt
- **WHEN** the user sends a prompt without an existing `conversationId`
- **THEN** the backend auto-creates a conversation and the app SHALL capture the returned `conversationId` from the `done` event for subsequent messages

### Requirement: User can rename a conversation
The app SHALL allow the user to change a conversation title.

#### Scenario: Rename via context menu
- **WHEN** the user long-presses or opens the context menu on a conversation and selects rename
- **THEN** the app SHALL display an inline edit field, and on confirmation send `PATCH /api/v1/conversations/{id}` with the new title

#### Scenario: Rename validation
- **WHEN** the user submits a blank title or a title exceeding 255 characters
- **THEN** the app SHALL display a validation error and not send the request

### Requirement: User can delete a conversation
The app SHALL allow the user to delete a conversation.

#### Scenario: Delete via context menu
- **WHEN** the user selects delete from the conversation context menu
- **THEN** the app SHALL display a confirmation dialog before sending `DELETE /api/v1/conversations/{id}`

#### Scenario: Successful deletion
- **WHEN** the backend returns `204 No Content`
- **THEN** the app SHALL remove the conversation from the list with an animation

### Requirement: User can switch between conversations
The app SHALL allow navigating from the conversation list into a specific conversation's chat screen.

#### Scenario: Tapping a conversation
- **WHEN** the user taps a conversation in the list
- **THEN** the app SHALL navigate to the chat screen for that conversation, loading its message history
