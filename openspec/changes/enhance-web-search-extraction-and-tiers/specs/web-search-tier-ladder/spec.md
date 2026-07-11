## ADDED Requirements

### Requirement: Tier ladder is curl_cffi → Patchright → Camoufox → NoVNC with FlareSolverr retired

AscendWebSearch SHALL escalate reads through curl_cffi, then Patchright (patched Chromium, the default browser tier), then Camoufox (hardened Firefox, tried automatically when Patchright is detected/blocked or fails), then NoVNC human intervention. FlareSolverr SHALL be removed from the ladder and the codebase; its Cloudflare-challenge and cookie-persistence role SHALL be covered by the patched-browser tiers replaying the stored session. All browser tiers SHALL be free and self-hosted; no paid external service SHALL be required.

#### Scenario: Patchright block escalates to Camoufox

- **WHEN** a read at the Patchright tier is detected or fails on a hardened anti-bot page
- **THEN** the read escalates to the Camoufox tier automatically
- **AND** if Camoufox succeeds the page content is returned

#### Scenario: FlareSolverr is gone

- **WHEN** the codebase is inspected after this change
- **THEN** no FlareSolverr strategy or dependency remains
- **AND** the escalation ladder contains curl_cffi, Patchright, Camoufox, and NoVNC only

### Requirement: Per-domain tier memory with decay

AscendWebSearch SHALL record, per registrable domain in Redis, the cheapest tier that last succeeded, and SHALL start subsequent reads for that domain at the remembered tier. The remembered tier SHALL decay back toward curl_cffi on a configurable schedule, so a transient block does not pin a domain to an expensive tier indefinitely.

#### Scenario: Remembered tier is the start point

- **WHEN** a domain previously succeeded only at the Camoufox tier and a new read for it begins
- **THEN** the read starts at the Camoufox tier rather than re-climbing from curl_cffi

#### Scenario: Decay lowers the start tier over time

- **WHEN** the decay window elapses for a domain remembered at Camoufox
- **THEN** the next read for that domain starts at a cheaper tier and re-establishes the minimum needed

### Requirement: Local CAPTCHA solver before human escalation

A free, self-hosted open-source CAPTCHA solver SHALL be attempted for common CAPTCHA types before escalating to the NoVNC human tier. No paid CAPTCHA-solving API SHALL be used, so no page content leaves the deployment to a third-party solving service.

#### Scenario: Solvable CAPTCHA handled locally

- **WHEN** a page presents a common CAPTCHA type the local solver handles
- **THEN** the solver resolves it without human intervention and the read proceeds

#### Scenario: Unsolvable CAPTCHA escalates to NoVNC

- **WHEN** the local solver cannot resolve the challenge
- **THEN** the read escalates to the existing NoVNC human tier
- **AND** no external paid solver is called
