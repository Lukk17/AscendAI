## Purpose

Defines the visual identity of the chat app, including a dark-mode-first Material theme and a custom Flyer Chat theme that aligns with the AscendAI brand, with light mode support.

## ADDED Requirements

### Requirement: Dark mode is the default theme
The app SHALL launch in dark mode by default.

#### Scenario: First launch
- **WHEN** the user opens the app for the first time
- **THEN** the app SHALL render with a dark color scheme

### Requirement: Light mode is available
The app SHALL support a light color scheme that the user can switch to.

#### Scenario: Switching to light mode
- **WHEN** the user toggles the theme setting to light mode
- **THEN** the entire app, including the chat bubbles, composer, and conversation list, SHALL re-render with the light color scheme

### Requirement: Theme preference persists across sessions
The app SHALL remember the user's theme preference.

#### Scenario: Restarting the app
- **WHEN** the user restarts the app after selecting light mode
- **THEN** the app SHALL launch in light mode

### Requirement: Chat theme customizes bubble and composer appearance
The app SHALL apply a custom `ChatTheme` to the `flutter_chat_ui` `Chat` widget that sets bubble colors, text styles, composer styling, and background color.

#### Scenario: User message bubble styling
- **WHEN** a user message is displayed
- **THEN** the bubble SHALL use the primary brand color as background with contrasting text

#### Scenario: Assistant message bubble styling
- **WHEN** an assistant message is displayed
- **THEN** the bubble SHALL use a neutral surface color distinct from user bubbles

### Requirement: System-level theme follows platform when set to auto
The app SHALL support an automatic theme mode that follows the device's system-level light or dark setting.

#### Scenario: Auto mode responds to system change
- **WHEN** the user sets theme to auto and the device switches from light to dark mode
- **THEN** the app SHALL switch to dark mode without requiring a restart
