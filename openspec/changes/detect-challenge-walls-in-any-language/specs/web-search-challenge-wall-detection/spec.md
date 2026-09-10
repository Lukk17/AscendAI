## Purpose

Defines how the service decides that a fetched page is a challenge wall rather than content, so that a wall from any
vendor and in any language is escalated instead of being returned as the page, and so that a page carrying a real
article beside a captcha widget is returned as the page instead of being escalated.

## ADDED Requirements

### Requirement: A page is judged by a score over independent signals, not by a phrase list

The service SHALL decide whether a page is a challenge wall by summing the weights of every signal that fires on the
page and comparing the sum with a single configured threshold. The signals SHALL be drawn from five families in this
order of precedence: vendor signatures, HTTP evidence, page structure, content shape, and phrases. The first four
families SHALL depend on no natural-language text. A wall verdict SHALL NOT require a phrase match.

#### Scenario: A wall from a vendor with no phrase in any list

- **WHEN** a page carries a catalogued vendor's challenge script and a captcha input inside a form that dominates
  its visible text, and none of its text matches any phrase
- **THEN** the page is judged a wall

#### Scenario: A site's own captcha in a language with no phrase captured

- **WHEN** a page carries no catalogued vendor marker, a form input whose name contains `captcha`, an image whose
  source contains `captcha`, and a form that dominates its visible text, written in a language for which no phrase
  has been captured
- **THEN** the page is judged a wall

#### Scenario: A phrase alone is not a wall

- **WHEN** a page carries a catalogued phrase in its body and no other signal fires
- **THEN** the page is not judged a wall

### Requirement: No single non-definitive signal decides a wall

Every signal that is not definitive SHALL carry a weight below the threshold, so that a wall verdict without a
definitive signal rests on at least two signals. A definitive signal SHALL be one that a vendor documents as present
only while a challenge is being served, and it SHALL carry a weight that no combination of negative signals can
cancel.

#### Scenario: A vendor script on a thin page

- **WHEN** a page carries a catalogued vendor's challenge script and few words, few links and no article element
- **THEN** the page is judged a wall because the script and the content shape both fired

#### Scenario: A definitive header beside a rich body

- **WHEN** a response carries a header the vendor documents as meaning a challenge is being served, and the body
  carries more words and more links than the rich-content guard requires
- **THEN** the page is judged a wall

#### Scenario: A status code alone with a body

- **WHEN** a response is a 403, 429 or 503 with a body that carries no other signal and enough words to be content
- **THEN** the page is not judged a wall by the status alone

### Requirement: A page with a real article is content, even beside a captcha widget

A page whose extracted main text reaches the configured rich-content word count SHALL receive a negative signal
large enough that a vendor script, a captcha element and a captcha input together cannot make it a wall. A page with
at least the configured rich link count SHALL receive a further negative signal. These guards SHALL NOT override a
definitive signal.

#### Scenario: A blog post with a captcha under its comment form

- **WHEN** a page carries a catalogued vendor's widget script, a widget element and a widget response field, and its
  extracted text is a full article with many links
- **THEN** the page is judged content and returned to the caller

#### Scenario: A page that hosts a widget beside a short text

- **WHEN** a page carries a catalogued vendor's widget script and widget element and its extracted text is below the
  rich-content word count
- **THEN** the page is judged a wall

#### Scenario: An article in a non-Latin script

- **WHEN** a page is an article in Japanese or Arabic with no vendor marker
- **THEN** the page is judged content

### Requirement: The word floor is kept as a separate condition

A page whose extracted text is below the configured minimum word count SHALL NOT be accepted as content, whatever
its score. This floor SHALL be reported separately from the wall verdict, so that a page that is neither a wall nor
content is distinguishable from both.

#### Scenario: A script-only application shell

- **WHEN** a page's body is script and a `noscript` element with fewer words than the minimum
- **THEN** the page is not accepted as content
- **AND** it is reported as having no content rather than as a wall

### Requirement: Structure signals are read from markup, never from words

The page structure family SHALL fire on element names and attribute values only: a form input or text area whose
name, id or autocomplete attribute contains `captcha`, an element whose class or id contains `captcha` or carries the
GeeTest prefix, an image, canvas or frame whose source or id contains `captcha`, a form whose visible text is at
least the configured share of the page's visible text, a meta refresh, and a body that is script and `noscript` with
fewer than the minimum words.

#### Scenario: The same wall in two languages

- **WHEN** a site's own captcha page is fetched with the interface language set to Polish and again set to Korean
- **THEN** the same structure signals fire on both
- **AND** both are judged a wall

#### Scenario: A word in prose does not fire a structure signal

- **WHEN** a page's prose contains the word `captcha` but no attribute value does
- **THEN** no structure signal fires

### Requirement: A wall's intervention type is classified from markup

When a page is judged a wall and the form that dominates its visible text contains a password input, the
intervention type SHALL be `login`. Otherwise it SHALL be `captcha`. This classification SHALL NOT depend on the
page's language.

#### Scenario: A login page with a captcha in Turkish

- **WHEN** a Turkish page is judged a wall and its dominant form carries a password input and a captcha input
- **THEN** the intervention type is `login`

#### Scenario: A captcha page with no password input

- **WHEN** a page is judged a wall and no dominant form carries a password input
- **THEN** the intervention type is `captcha`

### Requirement: A markup parse failure does not accept the page

When the page cannot be parsed for structure signals, the structure family SHALL contribute nothing, the failure
SHALL be recorded on the verdict, and every other family SHALL still be evaluated. The page SHALL NOT be accepted
because parsing failed.

#### Scenario: Unparseable bytes with a definitive header

- **WHEN** a response body cannot be parsed and the response carries a definitive challenge header
- **THEN** the page is judged a wall
- **AND** the parse failure is recorded on the verdict

### Requirement: Every tier and the monitor use the same verdict

Every fetch tier and the human-intervention monitor SHALL obtain their decision about a page from the same scoring
function, passing the response status, the response headers and the cookie names each has available. A tier that
has headers SHALL pass them. The orchestrator's second look at a tier's output SHALL use the same function with the
markup alone.

#### Scenario: A header-only wall at the first tier

- **WHEN** the first tier receives a 403 whose only wall evidence is a definitive challenge header
- **THEN** that tier escalates rather than returning the body

#### Scenario: The monitor and the reader agree

- **WHEN** the human-intervention monitor judges a rendered page cleared
- **THEN** the orchestrator, given the same markup, judges it content

### Requirement: The verdict carries its evidence

The verdict SHALL carry the score, the threshold, every signal that fired with its weight, the vendor the signals
point at when they point at one, the wall decision, the content-floor decision and the intervention type. A signal
SHALL fire at most once per verdict however many markers matched it. The evidence recorded for a signal SHALL be the
marker that matched and never an excerpt of the page.

#### Scenario: Two scripts, one signal

- **WHEN** a page carries two copies of a catalogued vendor's script
- **THEN** the vendor script signal appears once on the verdict

#### Scenario: Evidence is the marker

- **WHEN** a phrase signal fires
- **THEN** the verdict records the phrase id and not the surrounding text
