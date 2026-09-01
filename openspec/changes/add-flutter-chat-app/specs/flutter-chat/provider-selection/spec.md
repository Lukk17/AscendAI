## Purpose

Allows users to select which AI provider and model to use for each prompt, exposing the multi-provider routing capability of the AscendAgent backend.

## ADDED Requirements

### Requirement: User can select an AI provider
The app SHALL provide a UI control for choosing the AI provider before sending a prompt.

#### Scenario: Default provider pre-selected
- **WHEN** the user opens the chat screen
- **THEN** the provider selector SHALL show the backend's default provider (determined by `app.ai.default-provider` configuration) as the active selection

#### Scenario: Changing provider
- **WHEN** the user selects a different provider from the list (LM Studio, OpenAI, Gemini, Anthropic, MiniMax)
- **THEN** subsequent prompts SHALL include the selected provider value in the `provider` form field

### Requirement: User can override the model
The app SHALL allow the user to specify a model name that overrides the provider's default model.

#### Scenario: Specifying a model override
- **WHEN** the user enters a model name in the model override field
- **THEN** the prompt request SHALL include the model value in the `model` form field

#### Scenario: Clearing the model override
- **WHEN** the user clears the model override field
- **THEN** the prompt request SHALL omit the `model` field, letting the backend use its configured default for the selected provider

### Requirement: Provider selection persists within a session
The app SHALL remember the selected provider and model override for the duration of the app session.

#### Scenario: Switching conversations
- **WHEN** the user switches to a different conversation within the same session
- **THEN** the previously selected provider and model override SHALL remain active

### Requirement: Embedding provider selection
The app SHALL allow the user to optionally select an embedding provider for RAG-enhanced prompts.

#### Scenario: Setting embedding provider
- **WHEN** the user selects an embedding provider from the advanced settings
- **THEN** the prompt request SHALL include the `embeddingProvider` form field with the selected value
