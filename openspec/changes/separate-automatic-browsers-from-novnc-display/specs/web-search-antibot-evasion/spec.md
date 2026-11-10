## ADDED Requirements

### Requirement: Automatic browser tiers keep their posture on their own screen

Automatic browser tiers SHALL follow the same headed or headless setting on their own screen as before, and SHALL NOT become headless because of the move. At the default settings the automatic browser screen SHALL have the same size, colour depth and rendering extensions as the screen the automatic browser tiers used before, and a window manager. A tier that measures its screen to shape its fingerprint SHALL measure the automatic browser screen.

#### Scenario: Headed by default

- **WHEN** an automatic browser tier reads a page at the default settings
- **THEN** its browser runs headed on the automatic browser screen

#### Scenario: The headless setting is still honoured

- **WHEN** `PLAYWRIGHT_HEADLESS` is true and an automatic browser tier reads a page
- **THEN** its browser runs headless and opens a window on neither screen

#### Scenario: The screen has the same shape at the default settings

- **WHEN** the service runs at the default settings
- **THEN** the automatic browser screen has the same size, colour depth and rendering extensions as the screen the human sees

#### Scenario: A browser that measures its screen

- **WHEN** a browser tier that bounds its fingerprint by the size of its screen launches at a custom `AUTOMATIC_BROWSER_DISPLAY_SIZE`
- **THEN** the bound it applies is that custom size and not the size of the screen the human sees
