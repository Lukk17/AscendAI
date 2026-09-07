## Purpose

Enables users to attach image and document files to their chat prompts, which are uploaded as multipart form data to the ascend-ai-agent prompt endpoint.

## ADDED Requirements

### Requirement: User can attach an image to a prompt
The app SHALL allow the user to select an image file and include it in the prompt request.

#### Scenario: Attaching an image from device
- **WHEN** the user taps the attachment button and selects an image file
- **THEN** the app SHALL display a thumbnail preview of the selected image in the composer area and include it as the `image` multipart part when sending

#### Scenario: Image sent with prompt
- **WHEN** the user sends a prompt with an attached image
- **THEN** the request to `POST /api/v1/ai/prompt/stream` SHALL include both the `prompt` text field and the `image` file part

#### Scenario: Vision-unsupported model rejection
- **WHEN** the backend returns `415 Unsupported Media Type` because the selected model lacks vision capabilities
- **THEN** the app SHALL display an error notification explaining that the current model does not support image input

### Requirement: User can attach a document to a prompt
The app SHALL allow the user to select a document file and include it in the prompt request.

#### Scenario: Attaching a document
- **WHEN** the user taps the attachment button and selects a document file (PDF, DOCX, PPTX, HTML, TXT, MD)
- **THEN** the app SHALL display the file name and size in the composer area and include it as the `document` multipart part when sending

#### Scenario: Document sent with prompt
- **WHEN** the user sends a prompt with an attached document
- **THEN** the request to the streaming prompt endpoint SHALL include both the `prompt` text field and the `document` file part

### Requirement: Upload progress indication
The app SHALL indicate upload progress for attached files.

#### Scenario: Large file upload
- **WHEN** the user sends a prompt with a large attachment
- **THEN** the app SHALL display an indeterminate or determinate progress indicator until the server begins streaming the response

### Requirement: Only one attachment per prompt
The app SHALL allow at most one image or one document per prompt, not both simultaneously.

#### Scenario: Switching attachment type
- **WHEN** the user has an image attached and then selects a document
- **THEN** the app SHALL replace the image attachment with the document attachment and update the preview accordingly
