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
- **THEN** the app SHALL open the presigned `downloadUrl` of that source in the device's default handler (browser or file viewer)

### Requirement: Attach sources toggle
The app SHALL provide a toggle to control whether source references are requested from the backend.

#### Scenario: Enabling attach sources
- **WHEN** the user enables the attach-sources toggle in settings or the chat toolbar
- **THEN** subsequent prompt requests SHALL include `attachSources=true` in the form fields

#### Scenario: Disabling attach sources
- **WHEN** the user disables the attach-sources toggle
- **THEN** subsequent prompt requests SHALL omit the `attachSources` field or set it to `false`

### Requirement: Citations are shown as tappable labels
When an assistant message has a `citations` event, the app SHALL render each citation label (for example `[S1]`) as a tappable label under the message. Tapping a label SHALL show the citation's document name and its page or chunk position when present, and SHALL offer to open the matching source's `downloadUrl` when the source list carries that document.

#### Scenario: Tapping a citation label
- **WHEN** an assistant message carries a citation `[S1]` for page 4 of `handbook.pdf` and the user taps `[S1]`
- **THEN** the app SHALL show `handbook.pdf` and page 4
- **AND** the app SHALL offer to open the source's `downloadUrl`

