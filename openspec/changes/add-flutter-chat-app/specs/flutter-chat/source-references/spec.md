## Purpose

Displays the source documents that grounded a RAG-enhanced assistant response, giving users transparency into which knowledge base documents informed the answer.

## ADDED Requirements

### Requirement: Source references are displayed when present
The app SHALL display source document references below the assistant message when the response includes source data.

#### Scenario: Response with sources
- **WHEN** the streaming response includes a `sources` server-sent event with one or more source documents
- **THEN** the app SHALL render a collapsible section below the assistant message bubble showing each source with its document name and MIME type badge

#### Scenario: Response without sources
- **WHEN** the streaming response completes without a `sources` event
- **THEN** no source reference section SHALL be displayed for that message

### Requirement: Source documents are downloadable
The app SHALL allow users to download or open source documents referenced in a response.

#### Scenario: Tapping a source reference
- **WHEN** the user taps on a source document reference
- **THEN** the app SHALL open the presigned download URL from the `downloadUrl` or `contentPath` field in the device's default handler (browser or file viewer)

### Requirement: Attach sources toggle
The app SHALL provide a toggle to control whether source references are requested from the backend.

#### Scenario: Enabling attach sources
- **WHEN** the user enables the attach-sources toggle in settings or the chat toolbar
- **THEN** subsequent prompt requests SHALL include `attachSources=true` in the form fields

#### Scenario: Disabling attach sources
- **WHEN** the user disables the attach-sources toggle
- **THEN** subsequent prompt requests SHALL omit the `attachSources` field or set it to `false`
