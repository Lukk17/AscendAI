## Purpose

Makes each wall decision legible from outside, so an operator can tell which signal decided a page, how close the
score came to the threshold, and which vendor's wall the service is seeing, without reading the page.

## ADDED Requirements

### Requirement: Every fired signal is counted by signal and vendor

The service SHALL count every signal that fires on a verdict, labelled by the signal id and by the vendor the signal
points at, with a fixed label for signals that point at no vendor. The set of vendor label values SHALL be bounded
by the catalogue's vendor names plus that fixed label.

#### Scenario: A wall with four signals

- **WHEN** a verdict fires four signals
- **THEN** four increments are recorded, one under each signal id

#### Scenario: Vendor labels stay bounded

- **WHEN** every fixture in the corpus is run through the scoring function
- **THEN** the set of vendor label values recorded is a subset of the catalogue's vendor names plus the fixed label

### Requirement: Every verdict is counted by outcome and tier

The service SHALL count every verdict, labelled by its outcome, one of wall, content or no content, and by the tier
that requested it, including the human-intervention monitor and the orchestrator's second look.

#### Scenario: A wall at the first tier

- **WHEN** the first tier's fetch is judged a wall
- **THEN** one verdict is counted under wall and that tier's name

#### Scenario: No content is distinct from a wall

- **WHEN** a page is neither a wall nor content
- **THEN** it is counted under no content and not under wall

### Requirement: Scores are observable as a distribution

The service SHALL record every verdict's score in a histogram whose buckets fall on the weight sums that matter, so
that verdicts just under and just over the threshold are distinguishable from one another and from verdicts far from
it.

#### Scenario: A near miss is visible

- **WHEN** a page scores just under the threshold
- **THEN** its observation lands in the bucket immediately below the threshold and not in the one above

### Requirement: The verdict is logged with its evidence and without the page

The service SHALL write one log line per verdict, carrying the wall decision, the score, the threshold, the vendor,
the intervention type, the fired signal ids with their weights, the tier and the URL. The line SHALL be written at
informational level when the score is at or above half the threshold or the verdict is a wall, and at debug level
otherwise. No line SHALL carry page text beyond the marker that matched, a cookie value, or a header value outside
the allowlisted header names.

#### Scenario: Following a wall through the tiers

- **WHEN** a page is judged a wall at three successive tiers
- **THEN** three lines carry the same URL, each with its tier, its score and its signals

#### Scenario: Logs carry no secrets

- **WHEN** a verdict fires on a response carrying a clearance cookie
- **THEN** the cookie's name may appear in the line and its value does not

### Requirement: The escalation names its reason

When a tier escalates because of a wall verdict, the exception it raises SHALL carry the verdict, and the tier's
existing warning line SHALL name the vendor and the score in the same line.

#### Scenario: A tier escalates on a DataDome wall

- **WHEN** a tier raises the challenge exception on a page judged a DataDome wall
- **THEN** the exception carries the verdict
- **AND** the tier's warning line names the vendor and the score
