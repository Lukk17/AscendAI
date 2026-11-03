## MODIFIED Requirements

### Requirement: Challenge and login detection regardless of page size

Challenge, block and login detection SHALL NOT be skipped based on response size. A page larger than the size threshold SHALL still be scanned: detection reads a bounded prefix of the response rather than abandoning the scan, so a large page can never fail open into being treated as clean content. The prefix length SHALL be a named configuration setting. The wall decision SHALL be the scored verdict of `ChallengeDetector.assess`, which reads the status code, the response headers and the cookie names when the tier has them, plus the bounded prefix, so a wall whose text is in a language the phrase list does not know is still detected through its language-independent signals.

#### Scenario: Large challenge page

- **WHEN** a Cloudflare interstitial or login page larger than the configured prefix is returned
- **THEN** detection scans the bounded prefix and still identifies it as a challenge or login page
- **AND** the orchestrator escalates or signals login rather than accepting it as content

#### Scenario: Wall in a language with no captured phrase

- **WHEN** a tier receives Amazon's captcha page from `amazon.co.jp` and no Japanese phrase is in the catalogue
- **THEN** the verdict is a wall from the structure and shape signals alone
- **AND** the read answers HTTP 428 with a `vnc_url` rather than HTTP 200 with the interstitial as content
