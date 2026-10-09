## Purpose

Lets the user dictate a prompt on Android and iOS. Speech is turned into text on the phone by the platform speech recogniser, the text fills the composer for review, and the ascend-ai-agent only ever receives text.

## ADDED Requirements

### Requirement: Speech is transcribed on the device
The app SHALL turn speech into text with the platform speech recogniser (Android `SpeechRecognizer`, iOS Speech framework) through the `speech_to_text` package, and SHALL request on-device recognition on every listen call. The app SHALL NOT send audio to the ascend-ai-agent, to ascend-audio-scribe or to any other server, and SHALL NOT need a GPU.

#### Scenario: Dictating a prompt
- **WHEN** the user taps the microphone button and speaks
- **THEN** the app SHALL show the recognised words in the composer input box as they are recognised

#### Scenario: Request carries text only
- **WHEN** the user sends a prompt that was dictated
- **THEN** the request to `POST /api/v1/ai/prompt/stream` SHALL carry the text in the `prompt` field and SHALL NOT carry any audio part

### Requirement: The transcript is reviewed before sending
The app SHALL place the transcript in the composer input box and SHALL NOT send it on its own. The user sends it with the send button, as for a typed prompt.

#### Scenario: Speech ends
- **WHEN** recognition ends because the user taps the microphone button again or no speech is heard for `ASCEND_SPEECH_PAUSE_SECONDS` seconds (a build-time setting, default 2)
- **THEN** the final transcript SHALL stay in the input box, editable, and no prompt request SHALL be sent

#### Scenario: Text already in the input box
- **WHEN** the input box already holds text and the user dictates more
- **THEN** the app SHALL keep the existing text and add the transcript after it, separated by one space

#### Scenario: Sending while listening
- **WHEN** the user presses send while the app is still listening
- **THEN** the app SHALL stop listening and send the text that is in the input box at that moment

### Requirement: Microphone permission is requested and a denial is handled
The app SHALL ask for the microphone permission (and on iOS the speech recognition permission) the first time the user taps the microphone button, and SHALL handle a denied permission without listening and without changing the input box.

#### Scenario: First use
- **WHEN** the user taps the microphone button for the first time
- **THEN** the app SHALL show the system permission dialog before it starts listening

#### Scenario: Permission denied
- **WHEN** the user denies the permission
- **THEN** the app SHALL NOT start listening, SHALL leave the input box unchanged, and SHALL show a message that voice input needs the microphone permission and where to turn it on in the system settings

#### Scenario: Permission granted later in the system settings
- **WHEN** the user turns the permission on in the system settings and taps the microphone button again
- **THEN** the app SHALL start listening without a restart

### Requirement: The user selects the recognition language
The app SHALL offer the languages the device recogniser lists, SHALL default to the recogniser's system language, SHALL use the chosen language on every listen call, and SHALL remember the choice across app restarts.

#### Scenario: Default language
- **WHEN** the user has never chosen a recognition language
- **THEN** the app SHALL listen in the recogniser's system language

#### Scenario: Choosing a language
- **WHEN** the user picks a language in the chat settings
- **THEN** the next listen call SHALL use that language, and the app SHALL use it again after a restart

#### Scenario: Stored language no longer offered
- **WHEN** the stored language is no longer in the recogniser's list
- **THEN** the app SHALL fall back to the recogniser's system language

### Requirement: Voice input works offline
The app SHALL transcribe speech without a network connection when the device has an on-device model for the chosen language, and SHALL NOT fall back to a cloud recogniser when it does not.

#### Scenario: No network connection
- **WHEN** the device has no network connection and has an on-device model for the chosen language
- **THEN** dictation SHALL fill the input box as it does online

#### Scenario: No on-device model for the language
- **WHEN** the recogniser reports that the chosen language has no on-device model
- **THEN** the app SHALL show a message that the offline speech model for that language is not installed and where to install it, SHALL leave the input box unchanged, and SHALL NOT fall back to a cloud recogniser or any other recogniser

### Requirement: A device without a recogniser keeps working
The app SHALL detect when the device has no speech recogniser and SHALL keep text input working.

#### Scenario: No recogniser on the device
- **WHEN** the speech recogniser cannot be initialised because the device has none
- **THEN** the microphone button SHALL be shown disabled with the explanation "Voice input is not available on this device", and typing and sending SHALL work as before

### Requirement: Voice input is offered on phones only
The app SHALL show the microphone button on Android and iOS only.

#### Scenario: Desktop or web build
- **WHEN** the app runs on web, Windows, macOS or Linux
- **THEN** the composer SHALL NOT show a microphone button

### Requirement: The microphone is released when it is not needed
The app SHALL stop listening when the user leaves the chat screen or the app goes to the background.

#### Scenario: Leaving the chat screen while listening
- **WHEN** the user navigates away from the chat screen while the app is listening
- **THEN** the app SHALL cancel the listening session and release the microphone

#### Scenario: App goes to the background while listening
- **WHEN** the app goes to the background while it is listening
- **THEN** the app SHALL cancel the listening session and release the microphone
