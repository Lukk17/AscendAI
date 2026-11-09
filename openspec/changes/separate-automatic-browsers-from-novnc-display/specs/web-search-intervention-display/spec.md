## ADDED Requirements

### Requirement: Automatic browsers stay off the screen the human sees

The service SHALL draw every browser that no human is waiting on, on a screen separate from the one the human sees. This SHALL hold for every automatic browser tier and for every path that uses one, which are the read ladder, a page screenshot and a crawl job. A browser opened by an automatic read SHALL NOT create a window on the screen the human sees and SHALL NOT take input focus there.

#### Scenario: An automatic read while a window is open

- **WHEN** an intervention window is open and an automatic browser tier reads a page
- **THEN** the set of windows on the screen the human sees is the same before, during and after the read

#### Scenario: Every automatic tier stays off the human screen

- **WHEN** each of `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` and `5-crawlee_adaptive` reads a page in turn
- **THEN** no read creates a window on the screen the human sees

#### Scenario: The human keeps the focus

- **WHEN** the human is typing in an intervention window and an automatic browser tier starts a read
- **THEN** the intervention window keeps the input focus
- **AND** every key the human types reaches that window

#### Scenario: A screenshot and a crawl job stay off the human screen

- **WHEN** a page screenshot or a crawl job runs an automatic browser tier while an intervention window is open
- **THEN** the set of windows on the screen the human sees does not change

### Requirement: Intervention windows appear on the screen the human sees

An intervention window, whether opened by an escalation to `6-novnc` or by a session establish request, SHALL appear on the screen the human sees, at the position of its slot.

#### Scenario: An escalation still reaches the human

- **WHEN** a read escalates to `6-novnc`
- **THEN** its window appears on the screen the human sees at the position of its slot

#### Scenario: A session establish request still reaches the human

- **WHEN** a session establish request opens a login window
- **THEN** its window appears on the screen the human sees at the position of its slot

### Requirement: No remote viewer can reach the automatic browser screen

The remote viewer SHALL be attached only to the screen the human sees. The service SHALL NOT open any listener or port for the automatic browser screen. A person connected over NoVNC SHALL NOT be able to see or control a page that an automatic browser tier has open.

#### Scenario: The viewer shows only intervention windows

- **WHEN** an automatic browser tier has a page open and a human connects over NoVNC
- **THEN** the human sees no window of that page

#### Scenario: The container gains no port

- **WHEN** the container runs with both screens
- **THEN** the ports it listens on from outside the container are the same as before this requirement

### Requirement: Each screen has its own settings

The screen the human sees and the automatic browser screen SHALL each be named by a setting. The size of the automatic browser screen SHALL be its own setting with a default, with one source that the display server and the service both read. Changing the size of the screen the human sees SHALL NOT change the size of the automatic browser screen.

#### Scenario: The human screen is resized

- **WHEN** `NOVNC_DISPLAY_SIZE` is changed and `AUTOMATIC_BROWSER_DISPLAY_SIZE` is not
- **THEN** the automatic browser screen keeps its size

### Requirement: A wrong pair of screen settings is refused at startup

The service SHALL refuse to start, naming the setting, when the two settings name the same screen, when only one of them is set, or when a screen name or the size is malformed.

#### Scenario: The same screen named twice

- **WHEN** the service starts with `NOVNC_DISPLAY` and `AUTOMATIC_BROWSER_DISPLAY` set to the same value
- **THEN** the service refuses to start and the error names both settings

#### Scenario: Only one screen named

- **WHEN** the service starts with exactly one of `NOVNC_DISPLAY` and `AUTOMATIC_BROWSER_DISPLAY` set
- **THEN** the service refuses to start and the error names the missing setting

#### Scenario: A malformed value

- **WHEN** the service starts with a screen name that does not read as a colon and a number, or a size that does not read as `<width>x<height>`
- **THEN** the service refuses to start and the error names the setting

### Requirement: A run outside the container keeps its own display

With neither screen setting set, which is a run outside the container, every browser SHALL use the display of the service process, as it did before this change.

#### Scenario: A run outside the container

- **WHEN** the service runs with neither `NOVNC_DISPLAY` nor `AUTOMATIC_BROWSER_DISPLAY` set
- **THEN** the service starts
- **AND** an intervention window opens on the display of the service process

### Requirement: The startup banner names both screens

The startup banner SHALL name the automatic browser screen and its size. The existing line that names the size of the screen the human sees SHALL keep its format.

#### Scenario: The banner names both screens

- **WHEN** the service starts in the container
- **THEN** the startup banner carries the unchanged line for the size of the screen the human sees
- **AND** it carries a line with the automatic browser screen and its size
