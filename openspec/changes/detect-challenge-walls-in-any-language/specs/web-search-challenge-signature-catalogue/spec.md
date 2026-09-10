## Purpose

Defines what the catalogue of vendor markers and phrases contains, where each entry's provenance is recorded, how the
runtime file is produced from the maintained source, which languages the phrase supplement covers, and what evidence
a marker needs before it is admitted, so that the catalogue can be trusted, extended and corrected by reading it.

## ADDED Requirements

### Requirement: The runtime catalogue is generated from a maintained source

The catalogue the service loads SHALL be generated from a maintained source file by a generator that is part of the
repository. The generated file SHALL be committed and SHALL be byte-identical to what the generator produces from the
committed source. The test suite SHALL fail when the two differ.

#### Scenario: A hand edit to the generated file

- **WHEN** the generated catalogue is edited directly and the generator is run in check mode
- **THEN** the check fails and names the file

#### Scenario: Regeneration is deterministic

- **WHEN** the generator is run twice on the same source
- **THEN** the two outputs are byte-identical

### Requirement: Every vendor marker carries a source and a verification date

Each vendor marker in the source SHALL record the signal it feeds, the URL of the source it was verified against and
the date of that verification. A marker without a source SHALL be rejected by the test suite. Markers that could not
be verified against a vendor page or a maintained detector SHALL NOT be in the catalogue and SHALL be listed in the
design as excluded.

#### Scenario: A marker without a source

- **WHEN** a marker is added to the source file with no source URL
- **THEN** the test suite fails and names the marker

#### Scenario: The excluded list is honoured

- **WHEN** the catalogue is loaded
- **THEN** none of the markers the design lists as unverified is present

### Requirement: The catalogue covers the named vendors

The catalogue SHALL carry markers for Cloudflare managed and JavaScript challenges and the explicit Turnstile script,
DataDome, GeeTest, Akamai Bot Manager, Imperva Incapsula, Kasada, MTCaptcha, Friendly Captcha, Arkose Labs,
hCaptcha, Google reCAPTCHA, PerimeterX and HUMAN, DDoS-Guard, Amazon's own captcha page and AWS WAF. For each vendor
it SHALL record at least one marker in the vendor signature family.

#### Scenario: Every named vendor is present

- **WHEN** the catalogue is loaded
- **THEN** each named vendor has at least one marker

#### Scenario: Definitive markers are documented as such

- **WHEN** a marker is recorded as definitive
- **THEN** its source is the vendor's own documentation of that header

### Requirement: Every marker is admitted with a fixture that fires it

Every vendor script, interstitial structure and definitive header marker SHALL be fired by at least one fixture in
the corpus. Every vendor SHALL have at least one wall fixture. A marker with no fixture SHALL fail the test suite.

#### Scenario: A marker with no fixture

- **WHEN** a marker is added to the source and no fixture fires it
- **THEN** the corpus test fails and names the marker

#### Scenario: A fixture removed from under a marker

- **WHEN** the only fixture firing a marker is removed
- **THEN** the corpus test fails and names the marker

### Requirement: Phrases are a supplement with stable ids, captured per language, never typed

The phrase table SHALL hold sixteen phrase ids, each with a canonical English text and a translation per language
only where one has been captured. Each translation SHALL record the URL it was captured from, the tier or the browser
locale it was captured through, and the date. A translation with no capture record SHALL be rejected by the test
suite. The language set SHALL be thirty BCP 47 codes: the official languages of the European Union except Irish and
Maltese, plus Ukrainian, Russian, Turkish, Japanese, Korean, Simplified Chinese, Traditional Chinese and Arabic.

#### Scenario: A translation without provenance

- **WHEN** a translation is added to the source with no capture record
- **THEN** the test suite fails and names the phrase and the language

#### Scenario: Coverage is visible

- **WHEN** the generator is run in coverage mode
- **THEN** it prints a table with one column per language code and one row per phrase id, marking each captured
  translation

#### Scenario: Every phrase the old dictionary carried is present

- **WHEN** the catalogue is loaded
- **THEN** every phrase the previous dictionary carried, in English and in Polish, is present under its id

### Requirement: Phrases are normalised once, by one function

Phrases SHALL be normalised at generation and at match time by the same function: Unicode compatibility
normalisation, case folding, punctuation removal and whitespace collapsing. The generator SHALL import that function
from the matcher rather than defining its own.

#### Scenario: Ellipsis variants match

- **WHEN** a page title is `Just a moment…` with a single ellipsis character
- **THEN** the phrase `Just a moment...` matches

#### Scenario: One implementation

- **WHEN** the generator module is inspected
- **THEN** it defines no normalisation function of its own

### Requirement: The corpus holds real captures, marked synthetic only when no public page exists

Each fixture SHALL record its source URL, capture date, capture method, status, the allowlisted headers, the cookie
names, and its expected verdict, intervention type, vendor and the signals that must and must not fire. A fixture
SHALL be marked synthetic only when no public page served that vendor's wall at capture time, SHALL then be built
from cited markers alone, and SHALL be replaced by a real capture when one is observed. No fixture SHALL exceed 200
kilobytes, and no fixture SHALL contain a cookie value, a session token or personal data.

#### Scenario: A fixture over the size bound

- **WHEN** a fixture larger than 200 kilobytes is added
- **THEN** the corpus test fails and names it

#### Scenario: A fixture carrying a cookie value

- **WHEN** a fixture contains a catalogued cookie name followed by a value
- **THEN** the corpus test fails and names it

#### Scenario: A synthetic fixture beside a real one

- **WHEN** a real capture is added for a vendor that has a synthetic fixture
- **THEN** the synthetic fixture is removed in the same change
- **AND** the corpus test rejects a manifest that carries both

### Requirement: The corpus pins both sides of the threshold

The corpus SHALL contain, beside the wall fixtures, a counterexample set including a blog post with a captcha under
its comment form, a page hosting a challenge widget beside its own short text, a vendor's own page hosting its
widget beside real content, a login page with a captcha, articles in at least five languages including two in
non-Latin scripts, a 404 page, a 403 with a large real body, and a script-only application shell. The corpus test
SHALL run every fixture through the scoring function and assert its expected verdict.

#### Scenario: Every fixture has the expected verdict

- **WHEN** the corpus test runs
- **THEN** every wall fixture is judged a wall with its expected type and vendor
- **AND** every counterexample is judged as its manifest states

#### Scenario: Near misses are visible

- **WHEN** the corpus test runs
- **THEN** it prints each fixture's score and margin to the threshold
- **AND** fixtures within twenty points of the threshold are listed under their own heading
