## MODIFIED Requirements

### Requirement: Optional proxy egress, disabled by default

The service SHALL support routing fetches through a configurable proxy for all tiers (curl_cffi, Playwright, Patchright, Camoufox, Crawlee) via a single proxy abstraction. Proxy support SHALL be disabled by default and enabled only by configuration.

#### Scenario: Proxy not configured

- **WHEN** no proxy is configured
- **THEN** all tiers fetch over the host's direct egress exactly as today

#### Scenario: Proxy configured

- **WHEN** a proxy is configured
- **THEN** each tier routes its outbound fetch through that proxy
