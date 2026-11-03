## Purpose

On Windows, macOS and Linux the app lives in the system tray (the menu bar on macOS). Closing the window hides the app to the tray instead of quitting, and the tray menu opens or quits it. Owner decision 65.18 of 2026-10-04.

## ADDED Requirements

### Requirement: Desktop app shows a tray icon
On Windows, macOS and Linux the app SHALL show a tray icon with the tooltip "Ascend is running" and a menu with the entries "Open Ascend" and "Quit". On Android, iOS and web the app SHALL show no tray icon.

#### Scenario: Tray icon on desktop
- **WHEN** the app starts on Windows, macOS or Linux
- **THEN** a tray icon with the menu "Open Ascend" and "Quit" is shown

#### Scenario: No tray on a phone or web
- **WHEN** the app starts on Android, iOS or web
- **THEN** no tray code runs

### Requirement: Closing the window hides the app to the tray
On desktop, closing the window SHALL hide it and SHALL NOT end the app. The polling of owner screens and a running stream SHALL go on while the window is hidden.

#### Scenario: Close hides instead of quitting
- **WHEN** the user closes the window on desktop
- **THEN** the window is hidden, the process keeps running and the tray icon stays

#### Scenario: Stream continues while hidden
- **WHEN** a reply is streaming and the user closes the window
- **THEN** the stream is not cancelled and the reply is complete when the window is opened again

### Requirement: The tray menu opens and quits the app
"Open Ascend" SHALL show and focus the window. "Quit" SHALL cancel open streams, stop the polling timer and end the process. On Windows and macOS a click on the tray icon SHALL also show and focus the window.

#### Scenario: Open from the tray
- **WHEN** the window is hidden and the user picks "Open Ascend"
- **THEN** the window is shown and focused

#### Scenario: Quit from the tray
- **WHEN** the user picks "Quit"
- **THEN** open streams are cancelled and the process ends
